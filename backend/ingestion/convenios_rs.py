"""
Convenios estaduais do RIO GRANDE DO SUL (CAGE/SEFAZ-RS) -> convenios_estadual.

O equivalente gaucho do SIGCON-MG, e — ao contrario do que `docs/MAPA_RS.md` §13
supunha — **NAO precisa de login**. A propria Contadoria e Auditoria-Geral do
Estado publica a carteira inteira como dado aberto no CKAN estadual:

    https://dados.rs.gov.br  ->  dataset `convenios-do-estado`
    recurso "Convenios de Despesa"  ->  ZIP com ConveniosDespesa-RS.csv

53.636 convenios historicos, com valores pactuados, valor JA PAGO, vigencia,
situacao e CNPJ do convenente. Para Santa Maria/RS sao 412 registros, 17 deles
de 2026.

O Portal de Convenios e Parcerias (logado, perfil PCPRS) continua necessario —
mas so para PROPOSTA, MONITORAMENTO MENSAL e PRESTACAO DE CONTAS. A carteira em
si vem daqui, de graca.

⚠️ CASAMENTO POR CNPJ, NUNCA POR `MunicipioConvenente`. Dos 412 registros com
"SANTA MARIA" nessa coluna, so 108 sao da prefeitura; o resto e fundo, autarquia,
a CAMARA MUNICIPAL (que nao e o cliente) e entidades homonimas. Mesma disciplina
do `gconv_es.py`.

⚠️⚠️ O CSV NAO TEM NUMERO DE CONVENIO. Nenhuma das 24 colunas identifica o
instrumento — conferido tambem no recurso "Layout Convenios", que apesar do nome
e outra copia do MESMO csv. E `convenios_estadual.nr_sigcon` tem UNIQUE GLOBAL
(`fix_unique_nrsigcon_full.sql`): sem id estavel, N convenios colapsariam num
registro so no ON CONFLICT, em silencio.

A saida e uma CHAVE SINTETICA sobre os campos que nao mudam com o tempo. Medido
contra o arquivo inteiro (53.636 linhas):

    exercicio+orgao+cnpj+assinatura+valor .................. 332 colisoes
    + Objeto ...............................................  28 colisoes
    + vigencias + publicacao (a escolhida) .................  24 colisoes

Das 19 chaves repetidas na escolhida, **14 sao linhas byte a byte IDENTICAS** —
duplicata do proprio dump, onde colapsar e o comportamento CERTO. As outras 5
diferem apenas em `DataSituacao` e `Justificativa`.

⚠️ E esses dois campos NAO PODEM entrar na chave, por mais tentador que seja:
eles MUDAM ao longo da vida do convenio. Um convenio que troca de situacao
ganharia chave nova na coleta seguinte e viraria DOIS registros na tela — trocar
uma colisao rara por duplicacao sistematica e um pessimo negocio.

Entao a ambiguidade residual e tratada onde ela e visivel: dentro do conjunto que
este coletor de fato importa (os CNPJs do municipio), linhas identicas sao
deduplicadas em silencio e chaves com conteudo divergente sao gravadas pela
situacao mais recente **com aviso no log**. Em Santa Maria a medicao deu
**108 chaves para 108 linhas** — zero ambiguidade no caso real.

Rodavel por Scheduled Task (worker de tenant com municipio do RS) ou a mao:
    python -u ingestion/convenios_rs.py            # coleta de verdade
    python -u ingestion/convenios_rs.py --dry      # so parseia e mostra
"""
import csv
import io
import json
import logging
import os
import re
import sys
import tempfile
import zipfile
from datetime import date, datetime

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("convenios_rs")

CKAN_PKG = ("https://dados.rs.gov.br/api/3/action/package_show"
            "?id=convenios-do-estado")
# ⚠️ O recurso e resolvido pelo NOME, nunca pelo uuid medido hoje: o CKAN troca
# o uuid quando o publicador substitui o arquivo. Mesma razao do `_ckan_urls` do
# gconv_es.
#
# ⚠️ E a comparacao IGNORA ACENTO. O nome publicado e "Convênios de Despesa";
# um `.lower()` cru contra "convenios de despesa" nao casa, e o coletor morre
# com "recurso nao encontrado" — parecendo que a fonte saiu do ar quando o
# problema e a cedilha do outro lado. Custou uma rodada para descobrir.
RECURSO = "convenios de despesa"
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0 coleta de dados abertos RS)"}
FONTE = "CAGE-RS"
UF = "RS"
PREFIXO = "CAGE-RS-"

# Campos ESTAVEIS que compoem a chave. Ver o cabecalho para o porque de
# DataSituacao e Justificativa ficarem de fora.
CAMPOS_CHAVE = ["ExercicioConvenio", "Cod_Orgao", "cnpj_convenente",
                "DataAssinatura", "ValorConcedente", "Objeto",
                "DataInicioVigencia", "DataFimVigencia", "DataPublicacao"]
# Guarda de esquema: se a fonte publicar outro arquivo no lugar (ja aconteceu em
# GO), o coletor para antes de processar 53 mil linhas que nao casam com nada.
COLUNAS_MINIMAS = {"ExercicioConvenio", "Orgao", "SituacaoConvenio",
                   "NomeConvenente", "cnpj_convenente", "ValorConcedente"}


def _so_digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _sem_acento(s: str) -> str:
    """Minusculas e sem acento — para casar rotulo publicado com rotulo esperado."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "").lower())
                   if unicodedata.category(c) != "Mn").strip()


def _valor(s) -> float | None:
    """'30000,00' / '1.321.259,80' -> float. Vazio -> None."""
    t = str(s or "").strip()
    if not t:
        return None
    try:
        return float(t.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _data(s) -> date | None:
    t = str(s or "").strip()
    if not t:
        return None
    try:
        return datetime.strptime(t, "%d/%m/%Y").date()
    except ValueError:
        return None


def _decodificar(bruto: bytes) -> str:
    """utf-8 ANTES de latin-1, e a ordem importa: latin-1 nunca falha, entao
    tenta-lo primeiro esconderia um arquivo UTF-8 atras de mojibake permanente.
    Copiado do `transfvol_go._decodificar` pela mesma razao."""
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return bruto.decode(enc)
        except UnicodeDecodeError:
            continue
    return bruto.decode("latin-1", errors="replace")


def _com_retry(fn, tentativas: int = 4, espera: float = 3.0):
    """Repete em falha de transporte. ⚠️ A infraestrutura web do RS tem JANELAS
    de instabilidade: em 16/08/2026 tanto o CKAN estadual quanto o portal do
    Diario Oficial passaram minutos devolvendo `Connection reset by peer` no
    handshake, sem resposta HTTP — e voltaram sozinhos (o cliente padrao
    respondeu 12/12 depois). Nao e anti-bot: durante a janela, o `curl_cffi` com
    `impersonate` falhou junto, enquanto o curl do host respondia 200.

    Aqui a espera pode ser generosa (ao contrario da busca interativa do
    `services/diario_rs.py`): isto roda em cron, e uma rodada que demora 30s a
    mais vale muito mais que uma rodada perdida."""
    import time
    ultimo = None
    for i in range(1, tentativas + 1):
        try:
            return fn()
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            ultimo = e
            if i < tentativas:
                log.info("  tentativa %d/%d falhou (%s) — repetindo em %.0fs",
                         i, tentativas, type(e).__name__, espera * i)
                time.sleep(espera * i)
    raise ultimo


def _url_do_recurso(client: httpx.Client) -> str:
    r = _com_retry(lambda: client.get(CKAN_PKG, headers=UA, timeout=60))
    r.raise_for_status()
    for rec in (r.json().get("result") or {}).get("resources") or []:
        if RECURSO in _sem_acento(rec.get("name")):
            url = rec.get("url")
            if url:
                log.info("recurso '%s' (modificado em %s)", rec.get("name"),
                         (rec.get("last_modified") or rec.get("created") or "?")[:10])
                return url
    raise RuntimeError(f"recurso '{RECURSO}' nao encontrado no dataset do CKAN-RS")


def _baixar_csv(client: httpx.Client, url: str):
    """Devolve um iterador de dicts. ⚠️ STREAMING PARA DISCO, nao para memoria:
    sao 7,8 MB de zip que viram 49 MB de CSV, e num worker burstable de 0,6 vCPU
    um `list(DictReader(resp.text))` custa ~150 MB de RSS por rodada."""
    def _baixa(destino: str) -> None:
        with open(destino, "wb") as fh, client.stream(
                "GET", url, headers=UA, timeout=300, follow_redirects=True) as resp:
            resp.raise_for_status()
            for bloco in resp.iter_bytes(chunk_size=1 << 20):
                fh.write(bloco)

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        caminho = tmp.name
    # O retry envolve o download INTEIRO (e nao cada bloco): um reset no meio do
    # stream deixa o zip truncado, e zip truncado nao e erro de rede — e
    # `BadZipFile` trinta linhas adiante, com a causa ja perdida.
    _com_retry(lambda: _baixa(caminho))
    try:
        with zipfile.ZipFile(caminho) as z:
            nome = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
            if not nome:
                raise RuntimeError("zip do CKAN-RS sem .csv dentro")
            texto = _decodificar(z.read(nome))
        leitor = csv.DictReader(io.StringIO(texto), delimiter=";")
        faltando = COLUNAS_MINIMAS - set(leitor.fieldnames or [])
        if faltando:
            raise RuntimeError(
                f"CSV do CKAN-RS sem as colunas {sorted(faltando)} — "
                "a fonte publicou outro arquivo neste recurso")
        return list(leitor)
    finally:
        try:
            os.unlink(caminho)
        except OSError:
            pass


def chave_natural(r: dict) -> str:
    """`nr_sigcon` do registro. Ver o cabecalho para o desenho e a medicao."""
    import hashlib
    base = "|".join((r.get(c) or "").strip() for c in CAMPOS_CHAVE)
    return PREFIXO + hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]


def _mapa_cnpj_municipio(cur) -> dict[str, int]:
    """{cnpj(14 digitos): municipio_id} dos municipios ATIVOS do RS.

    A prefeitura vem de `municipios.cnpj` (coluna propria desde
    add_municipio_identificadores.sql); as demais entidades, das fontes federais
    ja coletadas. ⚠️ CNPJ ligado a dois municipios NAO entra: e consorcio ou erro
    de origem, e escolher um gravaria o convenio na cidade errada, calado."""
    cur.execute("""
        SELECT cnpj_digitos, min(municipio_id) FROM (
            SELECT regexp_replace(coalesce(m.cnpj,''), '\\D', '', 'g') AS cnpj_digitos,
                   m.id AS municipio_id
              FROM municipios m
             WHERE m.active AND upper(coalesce(m.uf,'')) = %s
            UNION ALL
            SELECT regexp_replace(coalesce(p.cnpj,''), '\\D', '', 'g'), p.municipio_id
              FROM transferegov_pac p JOIN municipios m ON m.id = p.municipio_id
             WHERE m.active AND upper(coalesce(m.uf,'')) = %s
            UNION ALL
            SELECT regexp_replace(coalesce(s.nu_cnpj,''), '\\D', '', 'g'), s.municipio_id
              FROM sismob_obras s JOIN municipios m ON m.id = s.municipio_id
             WHERE m.active AND upper(coalesce(m.uf,'')) = %s
        ) t
        WHERE length(cnpj_digitos) = 14
        GROUP BY cnpj_digitos
        HAVING count(DISTINCT municipio_id) = 1
    """, (UF, UF, UF))
    return {r[0]: r[1] for r in cur.fetchall()}


_SQL = """
INSERT INTO convenios_estadual (
    nr_sigcon, municipio_id, convenente_nome, orgao_concedente, objeto, objetivo,
    situacao, tp_instrumento, valor_concedente, valor_contrapartida, valor_total,
    valor_repassado, dt_publicacao, dt_vigencia_inicial, dt_vigencia_final,
    dt_vigencia_atual, ano, fonte, raw_data, created_at, updated_at)
VALUES (
    %(nr)s, %(mid)s, %(convenente)s, %(orgao)s, %(objeto)s, %(objetivo)s,
    %(situacao)s, %(tipo)s, %(v_conc)s, %(v_contra)s, %(v_total)s,
    %(v_pago)s, %(dt_pub)s, %(dt_ini)s, %(dt_fim)s,
    %(dt_fim)s, %(ano)s, %(fonte)s, %(raw)s::jsonb, NOW(), NOW())
ON CONFLICT (nr_sigcon) DO UPDATE SET
    municipio_id = EXCLUDED.municipio_id,
    convenente_nome = EXCLUDED.convenente_nome,
    orgao_concedente = EXCLUDED.orgao_concedente,
    objeto = EXCLUDED.objeto, objetivo = EXCLUDED.objetivo,
    situacao = EXCLUDED.situacao, tp_instrumento = EXCLUDED.tp_instrumento,
    valor_concedente = EXCLUDED.valor_concedente,
    valor_contrapartida = EXCLUDED.valor_contrapartida,
    valor_total = EXCLUDED.valor_total,
    valor_repassado = EXCLUDED.valor_repassado,
    dt_publicacao = EXCLUDED.dt_publicacao,
    dt_vigencia_inicial = EXCLUDED.dt_vigencia_inicial,
    dt_vigencia_final = EXCLUDED.dt_vigencia_final,
    dt_vigencia_atual = EXCLUDED.dt_vigencia_atual,
    ano = EXCLUDED.ano,
    -- ⚠️ `fonte` NAO entra no UPDATE, de proposito: se um dia a chave sintetica
    -- colidir com um nr_sigcon mineiro, o convenio do SIGCON seria reetiquetado
    -- como gaucho e sumiria da tela de MG. So o INSERT define a procedencia.
    raw_data = EXCLUDED.raw_data,
    updated_at = NOW()
"""


def _registro(r: dict, municipio_id: int) -> dict:
    v_conc, v_contra = _valor(r.get("ValorConcedente")), _valor(r.get("ValorConvenente"))
    total = None
    if v_conc is not None or v_contra is not None:
        total = (v_conc or 0) + (v_contra or 0)
    return {
        "nr": chave_natural(r),
        "mid": municipio_id,
        "convenente": (r.get("NomeConvenente") or "").strip()[:500] or None,
        "orgao": (r.get("Orgao") or r.get("NomeConcedente") or "").strip()[:500] or None,
        "objeto": (r.get("Objeto") or "").strip() or None,
        "objetivo": (r.get("Justificativa") or "").strip() or None,
        # Rotulo CRU do Estado ("Assinado", "Liberado para Assembleia
        # Legislativa"...). ⚠️ NAO sobrescrever com `SituacaoVigencia`: as duas
        # respondem perguntas diferentes, e a tela ja calcula "vence em N dias"
        # a partir da data. `SituacaoVigencia` fica no raw_data.
        "situacao": (r.get("SituacaoConvenio") or "").strip()[:200] or None,
        "tipo": (r.get("TipoTransferencia") or "").strip()[:100] or None,
        "v_conc": v_conc, "v_contra": v_contra, "v_total": total,
        "v_pago": _valor(r.get("ValorPago")),
        "dt_pub": _data(r.get("DataPublicacao")),
        "dt_ini": _data(r.get("DataInicioVigencia")),
        "dt_fim": _data(r.get("DataFimVigencia")),
        "ano": int(r["ExercicioConvenio"]) if (r.get("ExercicioConvenio") or "").strip().isdigit() else None,
        "fonte": FONTE,
        "raw": json.dumps(r, ensure_ascii=False),
    }


def _resolver_ambiguidade(linhas: list[dict]) -> tuple[list[dict], int]:
    """Uma linha por chave. Devolve `(linhas, ambiguas)`.

    Linhas byte a byte iguais sao a MESMA coisa publicada duas vezes — colapsar
    e correto e silencioso. Chave repetida com conteudo diferente e ambiguidade
    real: fica a de `DataSituacao` mais recente, e o chamador AVISA. Silenciar
    aqui seria repetir o defeito que esta funcao existe para evitar."""
    import collections
    grupos = collections.defaultdict(list)
    for r in linhas:
        grupos[chave_natural(r)].append(r)
    saida, ambiguas = [], 0
    for _, v in grupos.items():
        if len(v) == 1:
            saida.append(v[0])
            continue
        distintas = {tuple(sorted(x.items())) for x in v}
        if len(distintas) > 1:
            ambiguas += 1
            v = sorted(v, key=lambda x: _data(x.get("DataSituacao")) or date.min)
        saida.append(v[-1])
    return saida, ambiguas


def _log_ingest(cur, conn, status: str, inseridos: int, erro: str | None = None):
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES ('convenios_rs', %s, %s, %s, NOW())",
            (status, inseridos, erro))
        conn.commit()
    except Exception as e:
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def ingest(dry: bool = False) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            mapa = _mapa_cnpj_municipio(cur)
            if not mapa:
                # Nenhum municipio do RS com CNPJ conhecido: a fonte NAO SE
                # APLICA a este tenant. `success`, nao falha — mesmo criterio do
                # CAGEC fora de MG e do GConv fora do ES.
                log.info("nenhum municipio do RS com CNPJ conhecido — "
                         "convenios do RS nao se aplicam a este tenant")
                if not dry:
                    _log_ingest(cur, conn, "success", 0)
                return 0
            log.info("Convenios-RS: %d CNPJ(s) de municipio gaucho no mapa", len(mapa))

            with httpx.Client(follow_redirects=True) as client:
                linhas = _baixar_csv(client, _url_do_recurso(client))
            log.info("  %d convenios no dump do Estado", len(linhas))

            minhas = [r for r in linhas
                      if _so_digitos(r.get("cnpj_convenente")) in mapa]
            # O que tem o NOME do municipio mas CNPJ desconhecido: camara,
            # consorcio, entidade homonima. Contado e logado — a lacuna precisa
            # ser visivel, senao parece que a fonte simplesmente nao tem o dado.
            nomes = {r.get("MunicipioConvenente", "").strip().upper() for r in minhas}
            de_fora = sum(1 for r in linhas
                          if r.get("MunicipioConvenente", "").strip().upper() in nomes
                          and _so_digitos(r.get("cnpj_convenente")) not in mapa)
            minhas, ambiguas = _resolver_ambiguidade(minhas)
            log.info("  %d convenio(s) dos CNPJs conhecidos%s", len(minhas),
                     f" | {de_fora} com o nome do municipio mas CNPJ desconhecido "
                     "(camara/consorcio/homonimo) — nao importados" if de_fora else "")
            if ambiguas:
                log.warning("  %d chave(s) ambigua(s): mesma identidade com conteudo "
                            "diferente — gravada a situacao mais recente", ambiguas)

            if dry:
                for r in minhas[:5]:
                    reg = _registro(r, mapa[_so_digitos(r["cnpj_convenente"])])
                    log.info("    %s | %s | %s | R$ %s", reg["nr"], reg["ano"],
                             (reg["orgao"] or "")[:40], reg["v_conc"])
                return 0

            gravados = 0
            for r in minhas:
                reg = _registro(r, mapa[_so_digitos(r["cnpj_convenente"])])
                try:
                    cur.execute("SAVEPOINT sp_conv_rs")
                    cur.execute(_SQL, reg)
                    cur.execute("RELEASE SAVEPOINT sp_conv_rs")
                    gravados += 1
                except Exception as e:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_conv_rs")
                    log.warning("  upsert falhou %s: %s", reg["nr"], str(e)[:110])
            conn.commit()
            log.info("=== Convenios-RS: %d de %d gravado(s) ===", gravados, len(minhas))
            _log_ingest(cur, conn, "success" if gravados == len(minhas) else "partial",
                        gravados)
            return gravados
        except Exception as e:
            conn.rollback()
            log.error("Convenios-RS falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ingest(dry="--dry" in sys.argv)
