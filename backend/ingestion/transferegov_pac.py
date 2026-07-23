"""Ingestao Selecao PAC / Novo PAC via DADOS ABERTOS (HTTP puro, sem navegador).

===========================================================================
POR QUE ESTA VERSAO SUBSTITUIU O SCRAPER DE NAVEGADOR (2026-07-23)
===========================================================================
A versao anterior abria o Chromium, entrava em
`discricionarias.transferegov.../voluntarias/propostapac/listarPropostaPac.jsf`
como convidado, filtrava por CNPJ, paginava a grid JSF e abria o detalhe de
cada proposta -- POR MUNICIPIO. Numa VPS de 2 vCPU compartilhada isso custava
horas e era o segundo maior consumidor de CPU do sistema.

Os mesmos dados estao publicados como CSV no portal oficial, com carga DIARIA:
  api-publica.transferegov.gestao.gov.br/downloads/dadosgov/

Nao e so mais barato -- e mais FIEL. O precedente interno esta no
`fns_scraper.py`, que saiu do Playwright para httpx e registrou no proprio
codigo "cobertura Piracema 49% -> 99%": o navegador estava PERDENDO metade dos
registros por falha de paginacao e timeout. Aqui vale o mesmo raciocinio: um
CSV completo nao tem paginacao para falhar, e um campo ausente falha alto (o
KeyError aparece) em vez de virar `None` silencioso, como acontecia com o
parser por regex sobre innerText.

ATENCAO AO PRAZO: o ambiente antigo de dados abertos do TransfereGov sera
DESLIGADO em 31/08/2026. Esta implementacao ja usa o endereco novo.

===========================================================================
DE ONDE VEM CADA CAMPO
===========================================================================
  siconv_proposta_selecao_pac  -> numero_proposta, objeto, situacao,
                                  valor_total, justificativa
  siconv_proponentes           -> proponente, cnpj  (e o casamento com o
                                  municipio, por CNPJ ou por nome+UF)
  siconv_programa              -> programa, programa_codigo
  siconv_pergunta/resposta_*   -> valor_contrapartida e valor_repasse
                                  (sao perguntas do formulario do programa)
  siconv_proposta_formalizacao_pac + siconv_emenda -> emenda_parlamentar
                                  (a proposta PAC formalizada vira proposta
                                  SICONV, e dela sai o parlamentar)

`qualificacao` e `detalhe_url` nao existem no dado aberto -- o UPSERT usa
COALESCE nesses campos, entao o que ja foi coletado antes e preservado.

Uso: python -m ingestion.transferegov_pac [municipio_id]   (sem id = todos ativos)
Requer DATABASE_URL_SYNC. NAO requer Chromium.
"""
import csv
import io
import json
import logging
import os
import sys
import time
import unicodedata
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tg_pac")

BASE = os.getenv(
    "TRANSFEREGOV_DADOS_URL",
    "https://api-publica.transferegov.gestao.gov.br/downloads/dadosgov",
).rstrip("/")

_CACHE_DIR = os.getenv("SICONV_CACHE_DIR") or os.path.join(
    os.getenv("TEMP") or os.getenv("TMPDIR") or "/tmp", "siconv_opendata"
)
# Os arquivos sao regerados 1x/dia; reaproveitar dentro da janela evita baixar
# ~85 MB a cada execucao quando o cron roda mais de uma vez.
_CACHE_HORAS = int(os.getenv("TRANSFEREGOV_CACHE_HORAS", "20") or "20")

# csv de 350 MB numa linha so estoura o limite padrao do modulo csv
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def _db_url() -> str:
    return (os.getenv("DATABASE_URL_SYNC", "")
            .replace("&channel_binding=require", "").replace("?channel_binding=require", ""))


def _norm(s: str) -> str:
    """Minusculo, sem acento e sem pontuacao -- para casar nome de municipio."""
    s = unicodedata.normalize("NFD", (s or "").strip())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().replace("-", " ").replace("'", " ").split())


def _so_digitos(s: str) -> str:
    return "".join(c for c in (s or "") if c.isdigit())


# O dado aberto traz a situacao como ENUM em caixa alta (ENVIADA,
# NAO_HABILITADA...), enquanto a tela .jsf -- e portanto tudo o que o scraper
# antigo gravou, e o que os filtros do painel esperam -- usa o rotulo humano.
# Este mapa foi DERIVADO das 570 propostas ja coletadas, comparando o enum do
# CSV com o rotulo no banco: bateu 1:1, sem ambiguidade. Traduzir aqui evita
# quebrar filtros e relatorios existentes.
_SITUACAO = {
    "HABILITADA": "Habilitada",
    "SELECIONADA": "Selecionada",
    "ENVIADA": "Enviada para Análise",
    "NAO_HABILITADA": "Não Habilitada",
    "CADASTRADA": "Cadastrada",
    "COMPLEMENTADA_ENVIADA": "Complementada Enviada para Análise",
}
_situacoes_desconhecidas: set[str] = set()


def _situacao(bruta: str | None) -> str | None:
    """Traduz o enum para o rotulo da tela. Enum novo NAO passa em silencio."""
    s = (bruta or "").strip()
    if not s:
        return None
    if s in _SITUACAO:
        return _SITUACAO[s]
    if s not in _situacoes_desconhecidas:
        _situacoes_desconhecidas.add(s)
        logger.warning(f"  situacao PAC desconhecida no dado aberto: '{s}' "
                       f"-- gravando com formatacao generica; adicione ao mapa _SITUACAO")
    return s.replace("_", " ").capitalize()


def _money(v) -> float | None:
    """'1.234.567,89' -> 1234567.89. Devolve None para vazio/invalido."""
    s = (str(v) if v is not None else "").strip()
    if not s:
        return None
    s = s.replace("R$", "").replace(" ", "")
    if "," in s:                      # formato brasileiro
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------- download --

def _baixa(nome: str) -> str:
    """Baixa <nome>.zip para o cache e devolve o caminho local.

    Grava em disco (e nao em memoria) de proposito: o siconv_programa.csv tem
    350 MB descomprimido e o zipfile precisa de um arquivo posicionavel para
    conseguir descomprimir em STREAM, sem carregar tudo na RAM -- o que
    importa numa maquina de 7,6 GB compartilhada por 43 containers.
    """
    import httpx
    os.makedirs(_CACHE_DIR, exist_ok=True)
    destino = os.path.join(_CACHE_DIR, nome)
    if os.path.exists(destino) and os.path.getsize(destino) > 1000:
        idade_h = (time.time() - os.path.getmtime(destino)) / 3600
        if idade_h < _CACHE_HORAS:
            logger.info(f"  {nome}: cache de {idade_h:.1f}h")
            return destino

    url = f"{BASE}/{nome}"
    logger.info(f"  baixando {url} ...")
    parcial = destino + ".part"
    with httpx.stream("GET", url, timeout=900, follow_redirects=True) as r:
        r.raise_for_status()
        with open(parcial, "wb") as fh:
            for bloco in r.iter_bytes(1024 * 256):
                fh.write(bloco)
    os.replace(parcial, destino)
    logger.info(f"  {nome}: {os.path.getsize(destino):,} bytes")
    return destino


def _linhas(nome: str):
    """Itera o CSV de dentro do zip como dicts, em stream.

    ENCODING: os arquivos sao UTF-8 COM BOM (comecam com EF BB BF). Ler como
    latin-1 -- erro cometido na primeira versao deste modulo -- causa DOIS
    estragos: os acentos viram mojibake ("SÃO PAULO") e, pior, o nome da
    primeira coluna vira `ï»¿ID_PROPONENTE`, entao todo `linha.get("ID_...")`
    devolve None e o resultado e zero silencioso. `utf-8-sig` resolve os dois.
    `errors="replace"` evita que um byte solto derrube uma carga inteira.
    """
    caminho = _baixa(nome)
    with zipfile.ZipFile(caminho) as z:
        interno = z.namelist()[0]
        with z.open(interno) as bruto:
            texto = io.TextIOWrapper(bruto, encoding="utf-8-sig", errors="replace", newline="")
            leitor = csv.DictReader(texto, delimiter=";")
            if leitor.fieldnames:
                leitor.fieldnames = [c.strip().lstrip("﻿") for c in leitor.fieldnames]
            for linha in leitor:
                yield linha


# ------------------------------------------------------------- municipios ---

def _municipios(municipio_id=None) -> list[dict]:
    """Municipios ativos + o CNPJ da prefeitura, quando ja conhecido."""
    import psycopg2
    conn = psycopg2.connect(_db_url())
    cur = conn.cursor()
    if municipio_id:
        cur.execute("SELECT id, nome, uf FROM municipios WHERE id=%s", (int(municipio_id),))
    else:
        cur.execute("SELECT id, nome, uf FROM municipios WHERE active=true ORDER BY nome")
    muns = [{"id": r[0], "nome": r[1], "uf": r[2]} for r in cur.fetchall()]
    for m in muns:
        cur.execute("""SELECT identificacao FROM transferegov_propostas
                       WHERE municipio_id=%s AND identificacao ~ '^[0-9]'
                       GROUP BY identificacao ORDER BY count(*) DESC LIMIT 1""", (m["id"],))
        row = cur.fetchone()
        m["cnpj"] = _so_digitos(row[0]) if row and row[0] else None
    cur.close()
    conn.close()
    return muns


def _mapa_proponentes(muns: list[dict]) -> tuple[dict, dict]:
    """ID_PROPONENTE -> municipio_id, e ID_PROPONENTE -> dados do proponente.

    REGRA DE CASAMENTO (a precisao aqui importa mais que a cobertura):

    1. Por CNPJ, quando o municipio ja tem um conhecido das voluntarias. E o
       criterio exato, o mesmo que o scraper de navegador usava.
    2. Por municipio+UF, MAS somente quando o proponente e a propria
       prefeitura. Esse filtro nao e preciosismo: o cadastro de proponentes
       inclui entidades privadas com sede na cidade (ha uma confederacao de
       hapkido cadastrada em Sao Paulo). Casar so por municipio+UF atribuiria
       propostas de terceiros ao municipio -- dado errado no painel do
       prefeito, que e pior do que dado faltando.

    O passo 2 e um ganho real sobre a versao anterior, que simplesmente PULAVA
    municipios sem CNPJ conhecido.
    """
    por_cnpj = {m["cnpj"]: m["id"] for m in muns if m.get("cnpj")}
    por_nome = {(_norm(m["nome"]), (m["uf"] or "").upper()): m["id"] for m in muns}

    # Prefixos que identificam o ente municipal (e nao uma entidade qualquer
    # sediada na cidade). Ajustavel por env sem precisar de deploy.
    prefixos = tuple(
        _norm(p) for p in (os.getenv(
            "TRANSFEREGOV_PREFIXOS_ENTE",
            "MUNICIPIO DE|MUNICIPIO DO|PREFEITURA MUNICIPAL DE|PREFEITURA DE|PREFEITURA MUNICIPAL DO",
        ) or "").split("|") if p.strip()
    )

    prop_para_mun: dict[str, int] = {}
    dados: dict[str, dict] = {}
    casados_cnpj = casados_nome = 0

    for linha in _linhas("siconv_proponentes.zip"):
        pid = (linha.get("ID_PROPONENTE") or "").strip()
        if not pid:
            continue
        cnpj = _so_digitos(linha.get("IDENTIF_PROPONENTE"))
        mun_id = por_cnpj.get(cnpj) if cnpj else None
        if mun_id:
            casados_cnpj += 1
        else:
            nome_prop = _norm(linha.get("NM_PROPONENTE"))
            if not nome_prop.startswith(prefixos):
                continue
            chave = (_norm(linha.get("MUNICIPIO_PROPONENTE")),
                     (linha.get("UF_PROPONENTE") or "").strip().upper())
            mun_id = por_nome.get(chave)
            if mun_id:
                casados_nome += 1
        if mun_id:
            prop_para_mun[pid] = mun_id
            dados[pid] = {
                "cnpj": linha.get("IDENTIF_PROPONENTE"),
                "nome": linha.get("NM_PROPONENTE"),
            }

    logger.info(f"  proponentes casados: {len(prop_para_mun)} "
                f"({casados_cnpj} por CNPJ, {casados_nome} por nome+UF)")
    return prop_para_mun, dados


# ------------------------------------------------------------- montagem -----

def _coleta(muns: list[dict]) -> dict[int, list[dict]]:
    """Devolve {municipio_id: [proposta, ...]} lendo os CSVs oficiais."""
    prop_para_mun, prop_dados = _mapa_proponentes(muns)
    if not prop_para_mun:
        logger.warning("  nenhum proponente casou com os municipios - nada a fazer")
        return {}

    # 1) Propostas PAC dos nossos proponentes
    propostas: dict[str, dict] = {}          # id_selecao -> registro
    ids_programa: set[str] = set()
    for linha in _linhas("siconv_proposta_selecao_pac.zip"):
        pid = (linha.get("ID_PROPONENTE") or "").strip()
        mun_id = prop_para_mun.get(pid)
        if not mun_id:
            continue
        id_sel = (linha.get("ID_PROPOSTA_SELECAO_PAC") or "").strip()
        numero = (linha.get("NR_PROPOSTA_SELECAO_PAC") or "").strip()
        if not id_sel or not numero:
            continue
        id_prog = (linha.get("ID_PROGRAMA") or "").strip()
        ids_programa.add(id_prog)
        propostas[id_sel] = {
            "municipio_id": mun_id,
            "numero_proposta": numero,
            "programa": None,
            "programa_codigo": None,
            "proponente": (prop_dados.get(pid) or {}).get("nome"),
            "cnpj": (prop_dados.get(pid) or {}).get("cnpj"),
            "situacao": _situacao(linha.get("SITUACAO_PROPOSTA_SELECAO_PAC")),
            "valor_repasse": None,
            "valor_contrapartida": None,
            "valor_total": _money(linha.get("VALOR_TOTAL_PROPOSTA_SELECAO_PAC")),
            "emenda_parlamentar": None,
            "qualificacao": None,
            "objeto": (linha.get("OBJETO_PROPOSTA_SELECAO_PAC") or "").strip() or None,
            "justificativa": (linha.get("JUSTIFICATIVA_PROPOSTA_SELECAO_PAC") or "").strip() or None,
            "detalhe_url": None,
            "_id_programa": id_prog,
            "_data_envio": (linha.get("DATA_ENVIO_PROPOSTA_SELECAO_PAC") or "").strip() or None,
        }
    logger.info(f"  propostas PAC encontradas: {len(propostas)}")
    if not propostas:
        return {}

    # 2) Nome e codigo do programa (arquivo grande: le em stream e so guarda o que interessa)
    programas: dict[str, dict] = {}
    for linha in _linhas("siconv_programa.zip"):
        pid = (linha.get("ID_PROGRAMA") or "").strip()
        if pid in ids_programa and pid not in programas:
            programas[pid] = {
                "nome": (linha.get("NOME_PROGRAMA") or "").strip() or None,
                "codigo": (linha.get("COD_PROGRAMA") or "").strip() or None,
            }
            if len(programas) == len(ids_programa):
                break
    for p in propostas.values():
        prog = programas.get(p.pop("_id_programa"), {})
        p["programa"] = prog.get("nome")
        p["programa_codigo"] = prog.get("codigo")
    logger.info(f"  programas resolvidos: {len(programas)}/{len(ids_programa)}")

    # 3) Valores de repasse/contrapartida -- sao RESPOSTAS do formulario do programa
    perguntas_valor: dict[str, str] = {}     # id_pergunta -> 'repasse' | 'contrapartida'
    for linha in _linhas("siconv_pergunta_selecao_pac.zip"):
        texto = _norm(linha.get("PERGUNTA_SELECAO_PAC"))
        qid = (linha.get("ID_PERGUNTA_SELECAO_PAC") or "").strip()
        if not qid or "valor" not in texto:
            continue
        if "contrapartida" in texto:
            perguntas_valor[qid] = "contrapartida"
        elif "repasse" in texto:
            perguntas_valor[qid] = "repasse"
    if perguntas_valor:
        achados = 0
        for linha in _linhas("siconv_resposta_selecao_pac.zip"):
            qid = (linha.get("ID_PERGUNTA_SELECAO_PAC") or "").strip()
            tipo = perguntas_valor.get(qid)
            if not tipo:
                continue
            alvo = propostas.get((linha.get("ID_PROPOSTA_SELECAO_PAC") or "").strip())
            if alvo is None:
                continue
            valor = _money(linha.get("RESPOSTA_SELECAO_PAC"))
            if valor is not None:
                alvo["valor_contrapartida" if tipo == "contrapartida" else "valor_repasse"] = valor
                achados += 1
        logger.info(f"  valores por resposta: {achados} "
                    f"(de {len(perguntas_valor)} perguntas financeiras)")

    # Repasse implicito quando so veio a contrapartida
    for p in propostas.values():
        if p["valor_repasse"] is None and p["valor_total"] and p["valor_contrapartida"] is not None:
            p["valor_repasse"] = round(p["valor_total"] - p["valor_contrapartida"], 2)

    # 4) Emenda parlamentar: proposta PAC formalizada -> proposta SICONV -> emenda
    sel_para_proposta: dict[str, str] = {}
    for linha in _linhas("siconv_proposta_formalizacao_pac.zip"):
        id_sel = (linha.get("ID_PROPOSTA_SELECAO_PAC") or "").strip()
        if id_sel in propostas:
            id_prop = (linha.get("ID_PROPOSTA") or "").strip()
            if id_prop:
                sel_para_proposta[id_sel] = id_prop
    if sel_para_proposta:
        alvo_props = set(sel_para_proposta.values())
        parlamentar: dict[str, str] = {}
        for linha in _linhas("siconv_emenda.zip"):
            id_prop = (linha.get("ID_PROPOSTA") or "").strip()
            if id_prop in alvo_props:
                nome = (linha.get("NOME_PARLAMENTAR") or "").strip()
                if nome and id_prop not in parlamentar:
                    parlamentar[id_prop] = nome
        for id_sel, id_prop in sel_para_proposta.items():
            nome = parlamentar.get(id_prop)
            if nome:
                propostas[id_sel]["emenda_parlamentar"] = nome
        logger.info(f"  formalizadas: {len(sel_para_proposta)} | "
                    f"com parlamentar: {len(parlamentar)}")

    por_municipio: dict[int, list[dict]] = {}
    for p in propostas.values():
        por_municipio.setdefault(p.pop("municipio_id"), []).append(p)
    return por_municipio


# ----------------------------------------------------------------- upsert ---

def _upsert(mun_id: int, propostas: list[dict]) -> int:
    """UPSERT idempotente por (municipio_id, numero_proposta).

    COALESCE nos campos que o dado aberto NAO tem (qualificacao, detalhe_url) e
    tambem em emenda_parlamentar: nunca apagar o que uma coleta anterior ja
    tinha so porque esta fonte nao traz aquele campo.
    """
    import psycopg2
    conn = psycopg2.connect(_db_url())
    cur = conn.cursor()
    n = 0
    for p in propostas:
        try:
            cur.execute("""
                INSERT INTO transferegov_pac
                  (municipio_id, numero_proposta, programa, programa_codigo, proponente, cnpj,
                   situacao, valor_repasse, valor_contrapartida, valor_total, emenda_parlamentar,
                   qualificacao, objeto, justificativa, detalhe_url, raw_data, updated_at)
                VALUES (%(m)s,%(numero_proposta)s,%(programa)s,%(programa_codigo)s,%(proponente)s,%(cnpj)s,
                   %(situacao)s,%(valor_repasse)s,%(valor_contrapartida)s,%(valor_total)s,%(emenda_parlamentar)s,
                   %(qualificacao)s,%(objeto)s,%(justificativa)s,%(detalhe_url)s,%(raw)s::jsonb, NOW())
                ON CONFLICT (municipio_id, numero_proposta) DO UPDATE SET
                   programa=COALESCE(EXCLUDED.programa, transferegov_pac.programa),
                   programa_codigo=COALESCE(EXCLUDED.programa_codigo, transferegov_pac.programa_codigo),
                   proponente=COALESCE(EXCLUDED.proponente, transferegov_pac.proponente),
                   cnpj=COALESCE(EXCLUDED.cnpj, transferegov_pac.cnpj),
                   situacao=COALESCE(EXCLUDED.situacao, transferegov_pac.situacao),
                   valor_repasse=COALESCE(EXCLUDED.valor_repasse, transferegov_pac.valor_repasse),
                   valor_contrapartida=COALESCE(EXCLUDED.valor_contrapartida, transferegov_pac.valor_contrapartida),
                   valor_total=COALESCE(EXCLUDED.valor_total, transferegov_pac.valor_total),
                   emenda_parlamentar=COALESCE(EXCLUDED.emenda_parlamentar, transferegov_pac.emenda_parlamentar),
                   qualificacao=COALESCE(EXCLUDED.qualificacao, transferegov_pac.qualificacao),
                   objeto=COALESCE(EXCLUDED.objeto, transferegov_pac.objeto),
                   justificativa=COALESCE(EXCLUDED.justificativa, transferegov_pac.justificativa),
                   detalhe_url=COALESCE(EXCLUDED.detalhe_url, transferegov_pac.detalhe_url),
                   raw_data=EXCLUDED.raw_data, updated_at=NOW()
            """, {**{k: p.get(k) for k in ("numero_proposta", "programa", "programa_codigo", "proponente",
                     "cnpj", "situacao", "valor_repasse", "valor_contrapartida", "valor_total",
                     "emenda_parlamentar", "qualificacao", "objeto", "justificativa", "detalhe_url")},
                  "m": mun_id, "raw": json.dumps(p, ensure_ascii=False)})
            n += 1
        except Exception as e:
            logger.warning(f"upsert {p.get('numero_proposta')}: {str(e)[:80]}")
            conn.rollback()
            continue
    conn.commit()
    cur.close()
    conn.close()
    return n


def _registra_ingestao(total: int, ok: bool, erro: str | None = None) -> None:
    import psycopg2
    try:
        conn = psycopg2.connect(_db_url())
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ingestion_log (source, status, records_inserted, error_message, "
                "started_at, finished_at) VALUES ('transferegov_pac', %s, %s, %s, NOW(), NOW())",
                ("success" if ok else "failed", total, (erro or "")[:500] or None),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"  (ingestion_log nao registrado: {e})")


async def run(municipio_id=None) -> int:
    """Mantem a assinatura async da versao com navegador (chamada de
    transferegov_voluntarias), embora agora o trabalho seja HTTP sincrono."""
    t0 = time.monotonic()
    muns = _municipios(municipio_id)
    if not muns:
        logger.warning("Nenhum municipio ativo")
        return 0
    logger.info(f"=== PAC (dados abertos): {len(muns)} municipios ===")

    # TG_PAC_DRY_RUN=1 coleta e relata SEM gravar. Serve para validar a
    # extracao contra producao antes de deixar o cron escrever.
    dry = (os.getenv("TG_PAC_DRY_RUN", "") or "").strip() in ("1", "true", "yes")
    if dry:
        logger.warning("  MODO SIMULACAO (TG_PAC_DRY_RUN=1): nada sera gravado")

    total = 0
    try:
        por_municipio = _coleta(muns)
        nomes = {m["id"]: m["nome"] for m in muns}
        for mun_id, props in sorted(por_municipio.items(), key=lambda kv: nomes.get(kv[0], "")):
            if dry:
                com_valor = sum(1 for p in props if p.get("valor_total"))
                com_parl = sum(1 for p in props if p.get("emenda_parlamentar"))
                logger.info(f"  [simulacao] {nomes.get(mun_id, mun_id)}: {len(props)} propostas "
                            f"({com_valor} com valor, {com_parl} com parlamentar)")
                for p in props[:2]:
                    logger.info(f"      {p['numero_proposta']} | {(p.get('situacao') or '-')[:22]} | "
                                f"R$ {p.get('valor_total')} | {(p.get('programa') or '-')[:48]}")
                total += len(props)
                continue
            ins = _upsert(mun_id, props)
            logger.info(f"  {nomes.get(mun_id, mun_id)}: {ins} PAC upsert")
            total += ins
        sem_dados = [nomes[m] for m in nomes if m not in por_municipio]
        if sem_dados:
            logger.info(f"  sem proposta PAC: {len(sem_dados)} municipio(s)")
        if not dry:
            _registra_ingestao(total, ok=True)
    except Exception as e:
        logger.error(f"PAC falhou: {e}")
        _registra_ingestao(total, ok=False, erro=str(e))
        raise
    logger.info(f"=== PAC concluido: {total} propostas em {time.monotonic()-t0:.0f}s ===")
    return total


if __name__ == "__main__":
    import asyncio
    mid = int(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(run(mid))
