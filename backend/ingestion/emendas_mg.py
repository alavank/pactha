"""
Emendas estaduais de MG pelos DADOS ABERTOS do Estado (dados.mg.gov.br, pacote
`portal_emendas_estaduais`) — a EXECUÇÃO que o SIGCON não mostra, sem senha de
ninguém. É a mesma base do portal emendas.mg.gov.br (SEGOV).

    https://dados.mg.gov.br/api/3/action/package_show?id=portal_emendas_estaduais
    recurso vw_sg_v2_ep_indic_recursos_tw.csv (indicação × beneficiário × valores)

Uma linha por INDICAÇÃO (37 mil em 24/09/2026, 2023-2026): autor, tipo
(Transferência Especial, Resolução SES, Convênio, Execução Direta...), situação,
beneficiário com CNPJ e — o que o SIGCON não tem — valor EMPENHADO, LIQUIDADO e
PAGO. O número da indicação é o MESMO do SIGCON ("INDICACAO: 78139"), e é por ele
que as duas fontes se completam em `emendas_estaduais`.

O QUE ESTA FONTE ACRESCENTA (medido em Monte Sião: 57 indicações 2023-2026):
- a execução de cada indicação;
- a RESOLUÇÃO SES (fundo a fundo da saúde por emenda), ~3 mil/ano no Estado, que
  o "Pesquisar Emendas por Convenente" do SIGCON não lista à prefeitura;
- o município sem senha do SIGCON no Cofre (20 de 42 na Freitas em 29/08).

AS ARMADILHAS, medidas em 24/09/2026:

1. ⚠️ **O emendas.mg.gov.br BARRA IP DE DATACENTER.** A 1ª versão lia as duas
   planilhas .xlsx do site: 200 do IP residencial, 403 da VPS (até a página
   inicial) e 403 do runner do GitHub. Nunca gravou nada nos três tenants de MG.
   O pacote do dados.mg.gov.br responde à VPS (`segov_pagamentos` e
   `sigcon_ckan_backfill` leem dele com `success` toda noite) e é MAIS NOVO:
   atualizado em 23/09/2026, contra a planilha do site
   parada em 12/05/2026. UA de navegador, como nos outros coletores do dados.mg.

2. ⚠️ **SÓ 2023 EM DIANTE.** O CSV aberto começa em 2023 (a planilha do site ia a
   2019, sem IBGE). Indicação anterior continua só com o que o SIGCON raspou.

3. ⚠️ **NÚMERO EXPORTADO COMO FLOAT.** IBGE "3143401,0", CNPJ "41774639000101,0"
   — e CNPJ que perdeu o zero à esquerda (13 dígitos). Tirar a casa decimal ANTES
   de pegar os dígitos, senão o IBGE vira 8 dígitos e nada casa.

4. **A DATA É A DO RECURSO NO CKAN** (`last_modified`), e vai em `execucao_em`:
   "pago R$ 0" só vale até essa data. Com mais de `IDADE_MAX_DIAS` a rodada sai
   `partial` — a fonte parou, e o vigia diz. Colunas lidas por NOME; faltando
   uma, o arquivo é recusado (`partial`, e nada é apagado).

5. ⚠️ **O MUNICÍPIO DA LINHA É O DO BENEFICIÁRIO, E NEM TODO BENEFICIÁRIO É A
   PREFEITURA.** Entra em `emendas_estaduais` (as contas) só o ente municipal —
   tipo MUNICÍPIO / FUNDO MUNICIPAL, ou o CNPJ de `municipios.cnpj`. OSC, caixa
   escolar (escola ESTADUAL), órgão estadual e consórcio vão para
   `emendas_estaduais_outros`, fora das somas. Sem o tipo, vale o CNPJ ou o nome
   começando por PREFEITURA/MUNICÍPIO/FUNDO MUNICIPAL.

6. ⚠️ **O SIGCON GANHA NOS CAMPOS DELE.** Ele é raspado todo dia. Numa indicação
   que o SIGCON já gravou, esta fonte só PREENCHE o que está vazio e grava as
   colunas de execução — `raw_data` e situação continuam do SIGCON. Numa
   indicação que só ela tem, ela é dona da linha.

7. Linha sem IBGE (caixa escolar: ~3.600) casa pelo NOME normalizado, por
   IGUALDADE, entre os municípios de MG do tenant — nunca por "contém" (a lição
   da Santa Maria do Herval). Em MG o nome é único dentro do estado.

8. ⚠️ **A TE-MG NÃO VIRA CONVÊNIO — O OBJETO VEM DAQUI** (25/09/2026). A tela só
   mostrava o objeto do convênio ligado, e a TE aparecia sem dizer para que é o
   dinheiro. `objeto` = título do plano de trabalho, da proposta ou a descrição
   da indicação (Resolução SES e doação de bens só têm esta); `fase_plano` = a
   situação do instrumento (ANÁLISE TÉCNICA, ADEQUAÇÃO, VIGENTE...). Em 2026, das
   3.834 TE: 3.327 vigentes, 22 em ADEQUAÇÃO — a prefeitura precisa corrigir o
   plano. O SIGCON não tem nenhum dos dois, então aqui a fonte manda sempre.

Rodável por Scheduled Task (worker de tenant com município de MG) ou à mão:
    python -u ingestion/emendas_mg.py            # coleta de verdade
    python -u ingestion/emendas_mg.py --dry      # baixa, lê, casa e mostra
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import sys
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("emendas_mg")

PACOTE = "https://dados.mg.gov.br/api/3/action/package_show?id=portal_emendas_estaduais"
RECURSO = "vw_sg_v2_ep_indic_recursos_tw.csv"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131 Safari/537.36"}
UF = "MG"
SOURCE = "emendas_mg"
# raw_data->>'_source' das linhas que esta fonte criou. O nome é da 1ª versão (a
# planilha do site) e fica: é ele que diz ao upsert quem é dono da linha.
FONTE_RAW = "emendas_mg_planilha"
TIMEOUT = 300
MIN_LINHAS = 10000                  # 37 mil em 24/09/2026; menos = cortado
IDADE_MAX_DIAS = int(os.getenv("EMENDAS_MG_IDADE_MAX_DIAS") or "90")

# Nome no NOSSO registro -> coluna do CSV (armadilha 4: faltando uma, recusa).
COLUNAS = {
    "ano": "ano_exercicio", "nr": "numero_indicacao",
    "tipo": "tipo_indicacao", "status": "status_indicacao", "autor": "responsavel",
    "tipo_atendimento": "tipo_aplicacao_descricao", "uo_codigo": "uo",
    "uo_sigla": "uo_sigla", "grupo": "grupo_despesa_nome",
    "ibge": "municipio_ibge", "municipio": "municipio",
    "tipo_beneficiario": "beneficiario_tipo",
    "beneficiario": "beneficiario_nome", "cnpj": "beneficiario_cnpj",
    "valor_indicacao": "valor_indicacao", "valor_empenhado": "valor_empenhado",
    "valor_liquidado": "valor_liquidado", "valor_pago": "valor_pago",
    "instrumento": "instrumento_numero",
}
# O OBJETO (armadilha 8): o primeiro preenchido. TE e convênio têm plano de
# trabalho; Resolução SES, doação de bens e execução direta, só a descrição.
OBJETO = ("plano_titulo", "proposta_titulo", "descricao_indicacao")
FASE = "status_instrumento"         # ANÁLISE TÉCNICA, ADEQUAÇÃO, VIGENTE...
# Vão só para o raw_data: o caminho da indicação até o dinheiro.
EXTRAS = ("proposta_numero", "plano_numero", "status_instrumento", "numero_siafi",
          "data_publicacao", "data_validade", "descricao_indicacao", "acao_nome")


def _norm(s) -> str:
    t = unicodedata.normalize("NFD", str(s or "").upper())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", t).split())


# A fonte escreve o tipo em CAIXA ALTA; o SIGCON, "Transferência Especial". Sem
# isto, o PDF, o BI e o filtro por tipo agrupariam a mesma coisa em duas linhas
# (medido no Postgres de teste: "Transferência Especial" 1 + "TRANSFERÊNCIA
# ESPECIAL" 22 no mesmo município).
TIPOS = {
    "TRANSFERENCIA ESPECIAL": "Transferência Especial",
    "CELEBRACAO DE CONVENIO": "Convênio",
    "APLICACAO DIRETA DOACAO DE BENS": "Aplicação Direta",
    "RESOLUCAO SES": "Resolução SES",
    "RESOLUCAO SEDESE": "Resolução SEDESE",
    "EXECUCAO DIRETA": "Execução Direta",
    "EXECUCAO DIRETA CAIXA ESCOLAR": "Execução Direta - Caixa Escolar",
    "OUTROS INSTRUMENTOS": "Outros Instrumentos",
}


def tipo_como_sigcon(v) -> str | None:
    s = _texto(v)
    if s is None:
        return None
    return TIPOS.get(_norm(s), s)[:100]


def _texto(v) -> str | None:
    s = str(v).strip() if v is not None else ""
    return None if s in ("", "-") else s


def _sem_decimal(v) -> str:
    """ "3143401,0" -> "3143401" (armadilha 3)."""
    return re.sub(r"[.,]0+$", "", str(v or "").strip())


def _dec(v) -> Decimal | None:
    if v is None or (isinstance(v, str) and v.strip() in ("", "-")):
        return None
    try:
        return Decimal(str(v).strip().replace(",", "."))
    except InvalidOperation:
        return None


def _cnpj(v) -> str | None:
    d = "".join(c for c in _sem_decimal(v) if c.isdigit())
    # Exportado como número, perde o zero à esquerda (12-13 dígitos).
    if 12 <= len(d) <= 13:
        d = d.zfill(14)
    return d if len(d) == 14 else None


def _nr(v) -> str | None:
    s = _texto(v)
    if s is None:
        return None
    if re.fullmatch(r"\d+(\.0+)?", s):
        return str(int(float(s)))
    return s[:50]


def recurso(pacote: dict) -> tuple[str, date | None]:
    """(url do CSV, data da última atualização) a partir do `package_show`. O id
    do recurso muda quando o Estado o recria; o nome do arquivo, não."""
    for r in (pacote.get("result") or {}).get("resources") or []:
        if str(r.get("url") or "").rsplit("/", 1)[-1] == RECURSO:
            quando = r.get("last_modified") or r.get("metadata_modified") or r.get("created")
            try:
                em = datetime.fromisoformat(str(quando)[:19]).date() if quando else None
            except ValueError:
                em = None
            return r["url"], em
    raise ValueError(f"{RECURSO} sumiu do pacote portal_emendas_estaduais")


def ler_csv(conteudo: bytes) -> list[dict]:
    """Linhas normalizadas. ValueError se faltar coluna (armadilha 4)."""
    leitor = csv.DictReader(io.StringIO(conteudo.decode("utf-8-sig")), delimiter=";")
    cab = [c.strip() for c in leitor.fieldnames or []]
    falta = [c for c in (*COLUNAS.values(), *OBJETO, FASE) if c not in cab]
    if falta:
        raise ValueError(f"CSV fora do layout medido — faltam {falta[:5]}")
    linhas = []
    for r in leitor:
        g = lambda k: r.get(COLUNAS[k])  # noqa: E731
        nr = _nr(g("nr"))
        if not nr:
            continue
        try:
            ano = int(_sem_decimal(g("ano")))
        except (TypeError, ValueError):
            ano = None
        ibge = "".join(c for c in _sem_decimal(g("ibge")) if c.isdigit()) or None
        linhas.append({
            "nr": nr, "ano": ano,
            "tipo": tipo_como_sigcon(g("tipo")),
            "status": (_texto(g("status")) or "")[:50] or None,
            "autor": (_texto(g("autor")) or "")[:300] or None,
            "tipo_atendimento": (_texto(g("tipo_atendimento")) or "")[:300] or None,
            "uo_codigo": (_texto(_sem_decimal(g("uo_codigo"))) or "")[:20] or None,
            "uo_sigla": (_texto(g("uo_sigla")) or "")[:50] or None,
            "grupo": (_texto(g("grupo")) or "")[:200] or None,
            "ibge": ibge if ibge and len(ibge) == 7 else None,
            "municipio": _texto(g("municipio")),
            "tipo_beneficiario": (_texto(g("tipo_beneficiario")) or "")[:100] or None,
            "beneficiario": (_texto(g("beneficiario")) or "")[:300] or None,
            "cnpj": _cnpj(g("cnpj")),
            "valor_indicacao": _dec(g("valor_indicacao")),
            "valor_empenhado": _dec(g("valor_empenhado")),
            "valor_liquidado": _dec(g("valor_liquidado")),
            "valor_pago": _dec(g("valor_pago")),
            "valor_resto_saldo": None,       # o CSV aberto não tem a coluna
            "instrumento": _texto(g("instrumento")),
            "objeto": next((_texto(r.get(c)) for c in OBJETO if _texto(r.get(c))), None),
            "fase_plano": (_texto(r.get(FASE)) or "")[:80] or None,
            "extras": {k: _texto(_sem_decimal(r.get(k)) if k == "numero_siafi" else r.get(k))
                       for k in EXTRAS if _texto(r.get(k))},
        })
    return linhas


_TIPOS_MUNICIPAIS = ("MUNICIPIO", "FUNDO MUNICIPAL")


def e_municipal(linha: dict, cnpj_prefeitura: str | None) -> bool:
    """O beneficiário é o próprio município (prefeitura ou fundo municipal)?"""
    if cnpj_prefeitura and linha.get("cnpj") == cnpj_prefeitura:
        return True
    tb = _norm(linha.get("tipo_beneficiario"))
    if tb:
        return tb.startswith(_TIPOS_MUNICIPAIS)
    # Sem o tipo, pelo nome (armadilha 5).
    nome = _norm(linha.get("beneficiario"))
    return nome.startswith(("PREFEITURA", "MUNICIPIO", "FUNDO MUNICIPAL"))


def casa_municipio(linha: dict, por_ibge: dict, por_nome: dict) -> dict | None:
    if linha.get("ibge"):
        return por_ibge.get(linha["ibge"])
    return por_nome.get(_norm(linha.get("municipio")))


# ── gravação ─────────────────────────────────────────────────────────────────

def _campo_sigcon(col: str) -> str:
    """Esta fonte só preenche o vazio numa linha do SIGCON (armadilha 6); numa
    linha que ela mesma criou, ela é a dona e atualiza."""
    return (f"{col} = CASE WHEN emendas_estaduais.raw_data->>'_source' = '{FONTE_RAW}' "
            f"THEN EXCLUDED.{col} ELSE COALESCE(NULLIF(emendas_estaduais.{col}::text, ''), "
            f"EXCLUDED.{col}::text)::{{t}} END")


_TIPOS_COL = {"nome_responsavel": "varchar", "tipo_indicacao": "varchar",
              "uo_codigo": "varchar", "uo_sigla": "varchar",
              "cnpj_beneficiario": "varchar", "beneficiario": "varchar",
              "grupo_despesa": "varchar", "tipo_atendimento": "varchar",
              "status_indicacao": "varchar", "valor_indicacao": "numeric"}

_SQL = f"""
INSERT INTO emendas_estaduais (
    municipio_id, nr_indicacao, nome_responsavel, tipo_indicacao, uo_codigo, uo_sigla,
    cnpj_beneficiario, beneficiario, grupo_despesa, tipo_atendimento, valor_indicacao,
    status_indicacao, ano, raw_data, valor_empenhado, valor_liquidado, valor_pago,
    valor_resto_saldo, execucao_em, objeto, fase_plano, created_at, updated_at)
VALUES (
    %(mid)s, %(nr)s, %(autor)s, %(tipo)s, %(uo_codigo)s, %(uo_sigla)s, %(cnpj)s,
    %(beneficiario)s, %(grupo)s, %(tipo_atendimento)s, %(valor_indicacao)s, %(status)s,
    %(ano)s, %(raw)s::jsonb, %(valor_empenhado)s, %(valor_liquidado)s, %(valor_pago)s,
    %(valor_resto_saldo)s, %(execucao_em)s, %(objeto)s, %(fase_plano)s, NOW(), NOW())
ON CONFLICT (municipio_id, nr_indicacao) DO UPDATE SET
    {", ".join(_campo_sigcon(c).format(t=t) for c, t in _TIPOS_COL.items())},
    ano = COALESCE(emendas_estaduais.ano, EXCLUDED.ano),
    raw_data = CASE WHEN emendas_estaduais.raw_data->>'_source' = '{FONTE_RAW}'
                    THEN EXCLUDED.raw_data ELSE emendas_estaduais.raw_data END,
    valor_empenhado = EXCLUDED.valor_empenhado,
    valor_liquidado = EXCLUDED.valor_liquidado,
    valor_pago = EXCLUDED.valor_pago,
    valor_resto_saldo = EXCLUDED.valor_resto_saldo,
    execucao_em = EXCLUDED.execucao_em,
    -- O SIGCON não tem estes dois: a fonte é a dona (armadilha 8).
    objeto = COALESCE(EXCLUDED.objeto, emendas_estaduais.objeto),
    fase_plano = EXCLUDED.fase_plano,
    updated_at = NOW()
"""

_SQL_OUTROS = """
INSERT INTO emendas_estaduais_outros (
    municipio_id, nr_indicacao, ano, nome_responsavel, tipo_indicacao, tipo_beneficiario,
    beneficiario, cnpj_beneficiario, uo_sigla, tipo_atendimento, valor_indicacao,
    valor_empenhado, valor_liquidado, valor_pago, status_indicacao, execucao_em,
    raw_data, objeto, fase_plano, atualizado_em)
VALUES (
    %(mid)s, %(nr)s, %(ano)s, %(autor)s, %(tipo)s, %(tipo_beneficiario)s,
    %(beneficiario)s, %(cnpj)s, %(uo_sigla)s, %(tipo_atendimento)s, %(valor_indicacao)s,
    %(valor_empenhado)s, %(valor_liquidado)s, %(valor_pago)s, %(status)s,
    %(execucao_em)s, %(raw)s::jsonb, %(objeto)s, %(fase_plano)s, NOW())
ON CONFLICT (municipio_id, nr_indicacao) DO UPDATE SET
    ano = EXCLUDED.ano, nome_responsavel = EXCLUDED.nome_responsavel,
    tipo_indicacao = EXCLUDED.tipo_indicacao, tipo_beneficiario = EXCLUDED.tipo_beneficiario,
    beneficiario = EXCLUDED.beneficiario, cnpj_beneficiario = EXCLUDED.cnpj_beneficiario,
    uo_sigla = EXCLUDED.uo_sigla, tipo_atendimento = EXCLUDED.tipo_atendimento,
    valor_indicacao = EXCLUDED.valor_indicacao, valor_empenhado = EXCLUDED.valor_empenhado,
    valor_liquidado = EXCLUDED.valor_liquidado, valor_pago = EXCLUDED.valor_pago,
    status_indicacao = EXCLUDED.status_indicacao, execucao_em = EXCLUDED.execucao_em,
    raw_data = EXCLUDED.raw_data, objeto = EXCLUDED.objeto,
    fase_plano = EXCLUDED.fase_plano, atualizado_em = NOW()
"""


def registro(linha: dict, municipio_id: int, execucao_em: date | None) -> dict:
    raw = {"_source": FONTE_RAW, "municipio": linha.get("municipio"),
           "ibge": linha.get("ibge"), "tipo_beneficiario": linha.get("tipo_beneficiario"),
           "instrumento": linha.get("instrumento"),
           "execucao_em": execucao_em.isoformat() if execucao_em else None,
           **(linha.get("extras") or {})}
    return {**linha, "mid": municipio_id, "execucao_em": execucao_em,
            "raw": json.dumps(raw, ensure_ascii=False)}


def _alvos(cur) -> list[dict]:
    cur.execute("""
        SELECT id, nome, ibge_code, regexp_replace(coalesce(cnpj, ''), '\\D', '', 'g')
          FROM municipios WHERE active AND upper(coalesce(uf, '')) = %s
    """, (UF,))
    return [{"id": r[0], "nome": r[1], "ibge": (r[2] or "").strip(),
             "cnpj": r[3] if len(r[3] or "") == 14 else None} for r in cur.fetchall()]


def _log_ingest(cur, conn, status: str, n: int, nota: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES (%s, %s, %s, %s, NOW())",
            (SOURCE, status, n, nota))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def coletar(client: httpx.Client, alvos: list[dict]
            ) -> tuple[dict, dict, list[str], date | None]:
    """({(mid, nr): registro municipal}, {(mid, nr): registro de outros}, falhas,
    data do recurso no CKAN)."""
    por_ibge = {a["ibge"]: a for a in alvos if a["ibge"]}
    por_nome = {_norm(a["nome"]): a for a in alvos}
    municipais: dict = {}
    outros: dict = {}
    try:
        p = client.get(PACOTE, headers=UA, timeout=60)
        p.raise_for_status()
        url, em = recurso(p.json())
        r = client.get(url, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        linhas = ler_csv(r.content)
        if len(linhas) < MIN_LINHAS:
            raise ValueError(f"só {len(linhas)} linha(s) (< {MIN_LINHAS}) — cortado?")
    except Exception as e:
        log.warning("  %s: %s: %s", RECURSO, type(e).__name__, str(e)[:200])
        return {}, {}, [f"{RECURSO}: {type(e).__name__}: {str(e)[:120]}"], None
    n = 0
    for ln in linhas:
        alvo = casa_municipio(ln, por_ibge, por_nome)
        if not alvo:
            continue
        reg = registro(ln, alvo["id"], em)
        (municipais if e_municipal(ln, alvo["cnpj"]) else outros)[(alvo["id"], ln["nr"])] = reg
        n += 1
    log.info("  %s: %d linha(s), atualizado em %s, %d do(s) município(s)",
             RECURSO, len(linhas), em, n)
    return municipais, outros, [], em


def grava(cur, municipais: dict, outros: dict, alvos: list[dict], completa: bool) -> None:
    import psycopg2.extras
    psycopg2.extras.execute_batch(cur, _SQL, list(municipais.values()), page_size=200)
    psycopg2.extras.execute_batch(cur, _SQL_OUTROS, list(outros.values()), page_size=200)
    if completa:
        # A entidade que a fonte deixou de publicar sai — só com o arquivo
        # lido inteiro: um que falhou esconderia linhas que continuam lá.
        for a in alvos:
            nrs = [nr for (mid, nr) in outros if mid == a["id"]]
            cur.execute("DELETE FROM emendas_estaduais_outros "
                        "WHERE municipio_id = %s AND NOT (nr_indicacao = ANY(%s))",
                        (a["id"], nrs))


def ingest(dry: bool = False) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            alvos = _alvos(cur)
            if not alvos:
                log.info("nenhum município de MG — emendas estaduais de MG não se aplicam")
                if not dry:
                    _log_ingest(cur, conn, "success", 0)
                return 0
            with httpx.Client(follow_redirects=True) as client:
                municipais, outros, falhas, em = coletar(client, alvos)
            for a in alvos:
                n = sum(1 for (mid, _) in municipais if mid == a["id"])
                o = sum(1 for (mid, _) in outros if mid == a["id"])
                if n or o:
                    log.info("  %s: %d indicação(ões) ao município, %d a entidade "
                             "(fora das contas)", a["nome"], n, o)
            if dry:
                return 0
            grava(cur, municipais, outros, alvos, completa=not falhas)
            conn.commit()
            notas = list(falhas)
            if em and (date.today() - em).days > IDADE_MAX_DIAS:
                notas.append(f"o dados.mg não atualiza as emendas desde {em:%d/%m/%Y} "
                             f"({(date.today() - em).days} dias) — execução defasada")
            status = "partial" if notas else "success"
            log.info("=== Emendas MG (dados.mg): %d ao município, %d a entidade, "
                     "dados de %s, status=%s ===", len(municipais), len(outros), em, status)
            _log_ingest(cur, conn, status, len(municipais), " | ".join(notas)[:400] or None)
            return len(municipais)
        except Exception as e:
            conn.rollback()
            log.error("Emendas MG falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ingest(dry="--dry" in sys.argv)
