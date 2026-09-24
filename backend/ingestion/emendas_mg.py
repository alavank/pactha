"""
Emendas estaduais de MG pela planilha OFICIAL da SEGOV (emendas.mg.gov.br) — a
EXECUÇÃO que o SIGCON não mostra, sem senha de ninguém.

    https://www.emendas.mg.gov.br/transparencia/
    .../wp-content/dados-emendas/2026_Marcel/DADOS_EMENDAS_2019_2020_2021_2022.xlsx
    .../wp-content/dados-emendas/2026_Marcel/DADOS_EMENDAS_2023_2024_2025_2026.xlsx

Uma linha por INDICAÇÃO (67 mil nos dois arquivos em 24/09/2026): autor, tipo
(Transferência Especial, Resolução SES, Convênio, Execução Direta...), situação,
beneficiário com CNPJ e — o que o SIGCON não tem — valor EMPENHADO, LIQUIDADO e
PAGO. O número da indicação é o MESMO do SIGCON ("INDICACAO: 78139"), e é por ele
que as duas fontes se completam em `emendas_estaduais`.

O QUE ESTA FONTE ACRESCENTA (medido em Monte Sião: 103 indicações 2019-2026):
- a execução de cada indicação — TE-MG 2025: R$ 2,06 mi pagos;
- a RESOLUÇÃO SES (fundo a fundo da saúde por emenda), ~3 mil/ano no Estado, que
  o "Pesquisar Emendas por Convenente" do SIGCON não lista à prefeitura;
- o município sem senha do SIGCON no Cofre (20 de 42 na Freitas em 29/08).

AS ARMADILHAS, medidas em 24/09/2026:

1. ⚠️ **A PLANILHA NÃO É "BIMESTRAL".** O cartão do relatório diz bimestral; os
   dois arquivos são de 13/05/2026 (Last-Modified) e a aba se chama "12-05". Por
   isso a data da planilha vai em `execucao_em` e a tela a mostra: "pago R$ 0" de
   2026 numa planilha de maio não é "não foi pago". Planilha com mais de
   `IDADE_MAX_DIAS` faz a rodada `partial` — a fonte parou, e o vigia diz.

2. ⚠️ **DOIS LAYOUTS.** 2019-2022 tem 26 colunas e NÃO tem código IBGE (só o
   nome do município); 2023-2026 tem 49, com IBGE. Colunas lidas por NOME; faltando
   uma, o arquivo é recusado (a rodada vira `partial` e nada daquele arquivo é
   apagado).

3. ⚠️ **O MUNICÍPIO DA LINHA É O DO BENEFICIÁRIO, E NEM TODO BENEFICIÁRIO É A
   PREFEITURA.** Entra em `emendas_estaduais` (as contas) só o ente municipal —
   tipo MUNICÍPIO / FUNDO MUNICIPAL, ou o CNPJ de `municipios.cnpj`. OSC, caixa
   escolar (escola ESTADUAL), órgão estadual e consórcio vão para
   `emendas_estaduais_outros`, fora das somas. No layout antigo, sem o tipo, vale
   o CNPJ ou o nome começando por PREFEITURA/MUNICÍPIO/FUNDO MUNICIPAL.

4. ⚠️ **O SIGCON GANHA NOS CAMPOS DELE.** Ele é raspado todo dia; a planilha tem
   meses. Numa indicação que o SIGCON já gravou, a planilha só PREENCHE o que está
   vazio e grava as colunas de execução — `raw_data` e situação continuam do SIGCON.
   Numa indicação que só a planilha tem, a planilha é dona da linha.

5. Nome do município (layout antigo) casa por IGUALDADE do nome normalizado entre
   os municípios de MG do tenant — nunca por "contém" (a lição da Santa Maria do
   Herval). Em MG o nome é único dentro do estado.

Rodável por Scheduled Task (worker de tenant com município de MG) ou à mão:
    python -u ingestion/emendas_mg.py            # coleta de verdade
    python -u ingestion/emendas_mg.py --dry      # baixa, lê, casa e mostra
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("emendas_mg")

BASE = "https://www.emendas.mg.gov.br/wp-content/dados-emendas/2026_Marcel"
ARQUIVOS = ("DADOS_EMENDAS_2019_2020_2021_2022.xlsx",
            "DADOS_EMENDAS_2023_2024_2025_2026.xlsx")
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0; dados abertos emendas MG)"}
UF = "MG"
SOURCE = "emendas_mg"
FONTE_RAW = "emendas_mg_planilha"   # raw_data->>'_source' das linhas que a planilha criou
TIMEOUT = 300
MIN_LINHAS = 10000                  # cada arquivo tinha 30-37 mil; menos = cortado
IDADE_MAX_DIAS = int(os.getenv("EMENDAS_MG_IDADE_MAX_DIAS") or "90")

# Nome no NOSSO registro -> nome da coluna em cada layout (armadilha 2).
LAYOUT_NOVO = {
    "ano": "Ano da Indicação", "nr": "Número da Indicação",
    "tipo": "Tipo de Indicação", "status": "Status da Indicação", "autor": "Autor",
    "tipo_atendimento": "Tipo de Aplicação", "uo_codigo": "Unidade Orçamentária Código",
    "uo_sigla": "Unidade Orçamentária Sigla", "grupo": "Grupo de Despesa Descrição",
    "ibge": "Código IBGE do Município", "municipio": "Município",
    "tipo_beneficiario": "Descrição do Tipo de Beneficiário",
    "beneficiario": "Nome Beneficiário", "cnpj": "Número do CNPJ do Beneficiário",
    "valor_indicacao": "Valor Indicado", "valor_empenhado": "Valor Empenhado no Ano",
    "valor_liquidado": "Valor Liquidado Atualizado", "valor_pago": "Valor Pago Atualizado",
    "valor_resto_saldo": "Saldo Restos a Pagar", "instrumento": "Número do Instrumento",
}
LAYOUT_ANTIGO = {
    "ano": "Ano Exercicio Inciso", "nr": "Nº Indicação - SIGCON",
    "tipo": "Tipo de Indicação", "status": "Status da Indicação",
    "autor": "Nome do Responsável",
    "tipo_atendimento": "Tipo de Atendimento / Tipo de aplicação",
    "uo_sigla": "Órgão - Sigla", "grupo": "Grupo de Despesa", "municipio": "Município",
    "beneficiario": "Beneficiário - Nome", "cnpj": "Beneficiário - CNPJ",
    "valor_indicacao": "Valor Indicação", "valor_empenhado": "Valor Empenhado no Ano da Emenda",
    "valor_liquidado": "Valor Liquidado no Ano da Emenda", "valor_pago": "Valor Pago Atual",
    "instrumento": "Nº Instrumento",
}


def _norm(s) -> str:
    t = unicodedata.normalize("NFD", str(s or "").upper())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", t).split())


# A planilha escreve o tipo em CAIXA ALTA; o SIGCON, "Transferência Especial". Sem
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


def _dec(v) -> Decimal | None:
    if v is None or (isinstance(v, str) and v.strip() in ("", "-")):
        return None
    try:
        return Decimal(str(v).strip().replace(",", "."))
    except InvalidOperation:
        return None


def _cnpj(v) -> str | None:
    d = "".join(c for c in str(v or "") if c.isdigit())
    # Número do Excel perde o zero à esquerda (12-13 dígitos); texto já vem com 14.
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


def data_da_aba(titulo: str, ultima_modificacao: datetime | None) -> date | None:
    """A aba se chama "12-05" (dia-mês); o ano vem do Last-Modified do arquivo."""
    m = re.fullmatch(r"\s*(\d{1,2})[-_/.](\d{1,2})\s*", titulo or "")
    ref = (ultima_modificacao or datetime.now(timezone.utc)).date()
    if not m:
        return ultima_modificacao.date() if ultima_modificacao else None
    try:
        d = date(ref.year, int(m.group(2)), int(m.group(1)))
    except ValueError:
        return ultima_modificacao.date() if ultima_modificacao else None
    # Aba "28-12" num arquivo modificado em janeiro é do ano anterior.
    return d if d <= ref else date(ref.year - 1, d.month, d.day)


def ler_xlsx(conteudo: bytes, ultima_modificacao: datetime | None = None
             ) -> tuple[list[dict], date | None]:
    """(linhas normalizadas, data da planilha). ValueError se o layout não for um
    dos dois medidos."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    it = ws.iter_rows(values_only=True)
    cab = [str(c).strip() if c is not None else "" for c in next(it)]
    for layout in (LAYOUT_NOVO, LAYOUT_ANTIGO):
        if all(col in cab for col in layout.values()):
            break
    else:
        falta_novo = [c for c in LAYOUT_NOVO.values() if c not in cab]
        falta_antigo = [c for c in LAYOUT_ANTIGO.values() if c not in cab]
        raise ValueError("planilha fora dos dois layouts medidos — faltam "
                         f"{(falta_novo if len(falta_novo) <= len(falta_antigo) else falta_antigo)[:5]}")
    ix = {k: cab.index(col) for k, col in layout.items()}
    linhas = []
    for r in it:
        if not r or all(v is None for v in r):
            continue
        g = lambda k: r[ix[k]] if k in ix and ix[k] < len(r) else None  # noqa: E731
        nr = _nr(g("nr"))
        if not nr:
            continue
        try:
            ano = int(str(g("ano")).strip())
        except (TypeError, ValueError):
            ano = None
        ibge = "".join(c for c in str(g("ibge") or "") if c.isdigit()) or None
        linhas.append({
            "nr": nr, "ano": ano,
            "tipo": tipo_como_sigcon(g("tipo")),
            "status": (_texto(g("status")) or "")[:50] or None,
            "autor": (_texto(g("autor")) or "")[:300] or None,
            "tipo_atendimento": (_texto(g("tipo_atendimento")) or "")[:300] or None,
            "uo_codigo": (_texto(g("uo_codigo")) or "")[:20] or None,
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
            "valor_resto_saldo": _dec(g("valor_resto_saldo")),
            "instrumento": _texto(g("instrumento")),
        })
    return linhas, data_da_aba(ws.title, ultima_modificacao)


_TIPOS_MUNICIPAIS = ("MUNICIPIO", "FUNDO MUNICIPAL")


def e_municipal(linha: dict, cnpj_prefeitura: str | None) -> bool:
    """O beneficiário é o próprio município (prefeitura ou fundo municipal)?"""
    if cnpj_prefeitura and linha.get("cnpj") == cnpj_prefeitura:
        return True
    tb = _norm(linha.get("tipo_beneficiario"))
    if tb:
        return tb.startswith(_TIPOS_MUNICIPAIS)
    # Layout antigo: sem o tipo, pelo nome (armadilha 3).
    nome = _norm(linha.get("beneficiario"))
    return nome.startswith(("PREFEITURA", "MUNICIPIO", "FUNDO MUNICIPAL"))


def casa_municipio(linha: dict, por_ibge: dict, por_nome: dict) -> dict | None:
    if linha.get("ibge"):
        return por_ibge.get(linha["ibge"])
    return por_nome.get(_norm(linha.get("municipio")))


# ── gravação ─────────────────────────────────────────────────────────────────

def _campo_sigcon(col: str) -> str:
    """A planilha só preenche o vazio numa linha do SIGCON (armadilha 4); numa
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
    valor_resto_saldo, execucao_em, created_at, updated_at)
VALUES (
    %(mid)s, %(nr)s, %(autor)s, %(tipo)s, %(uo_codigo)s, %(uo_sigla)s, %(cnpj)s,
    %(beneficiario)s, %(grupo)s, %(tipo_atendimento)s, %(valor_indicacao)s, %(status)s,
    %(ano)s, %(raw)s::jsonb, %(valor_empenhado)s, %(valor_liquidado)s, %(valor_pago)s,
    %(valor_resto_saldo)s, %(execucao_em)s, NOW(), NOW())
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
    updated_at = NOW()
"""

_SQL_OUTROS = """
INSERT INTO emendas_estaduais_outros (
    municipio_id, nr_indicacao, ano, nome_responsavel, tipo_indicacao, tipo_beneficiario,
    beneficiario, cnpj_beneficiario, uo_sigla, tipo_atendimento, valor_indicacao,
    valor_empenhado, valor_liquidado, valor_pago, status_indicacao, execucao_em,
    raw_data, atualizado_em)
VALUES (
    %(mid)s, %(nr)s, %(ano)s, %(autor)s, %(tipo)s, %(tipo_beneficiario)s,
    %(beneficiario)s, %(cnpj)s, %(uo_sigla)s, %(tipo_atendimento)s, %(valor_indicacao)s,
    %(valor_empenhado)s, %(valor_liquidado)s, %(valor_pago)s, %(status)s,
    %(execucao_em)s, %(raw)s::jsonb, NOW())
ON CONFLICT (municipio_id, nr_indicacao) DO UPDATE SET
    ano = EXCLUDED.ano, nome_responsavel = EXCLUDED.nome_responsavel,
    tipo_indicacao = EXCLUDED.tipo_indicacao, tipo_beneficiario = EXCLUDED.tipo_beneficiario,
    beneficiario = EXCLUDED.beneficiario, cnpj_beneficiario = EXCLUDED.cnpj_beneficiario,
    uo_sigla = EXCLUDED.uo_sigla, tipo_atendimento = EXCLUDED.tipo_atendimento,
    valor_indicacao = EXCLUDED.valor_indicacao, valor_empenhado = EXCLUDED.valor_empenhado,
    valor_liquidado = EXCLUDED.valor_liquidado, valor_pago = EXCLUDED.valor_pago,
    status_indicacao = EXCLUDED.status_indicacao, execucao_em = EXCLUDED.execucao_em,
    raw_data = EXCLUDED.raw_data, atualizado_em = NOW()
"""


def registro(linha: dict, municipio_id: int, execucao_em: date | None) -> dict:
    raw = {"_source": FONTE_RAW, "municipio": linha.get("municipio"),
           "ibge": linha.get("ibge"), "tipo_beneficiario": linha.get("tipo_beneficiario"),
           "instrumento": linha.get("instrumento"),
           "execucao_em": execucao_em.isoformat() if execucao_em else None}
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
    data mais recente das planilhas)."""
    por_ibge = {a["ibge"]: a for a in alvos if a["ibge"]}
    por_nome = {_norm(a["nome"]): a for a in alvos}
    municipais: dict = {}
    outros: dict = {}
    falhas: list[str] = []
    datas: list[date] = []
    for arq in ARQUIVOS:
        try:
            r = client.get(f"{BASE}/{arq}", headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            lm = r.headers.get("last-modified")
            modificado = parsedate_to_datetime(lm) if lm else None
            linhas, em = ler_xlsx(r.content, modificado)
            if len(linhas) < MIN_LINHAS:
                raise ValueError(f"só {len(linhas)} linha(s) (< {MIN_LINHAS}) — cortada?")
        except Exception as e:
            falhas.append(f"{arq}: {type(e).__name__}: {str(e)[:120]}")
            log.warning("  %s: %s: %s", arq, type(e).__name__, str(e)[:200])
            continue
        if em:
            datas.append(em)
        n = 0
        for ln in linhas:
            alvo = casa_municipio(ln, por_ibge, por_nome)
            if not alvo:
                continue
            reg = registro(ln, alvo["id"], em)
            (municipais if e_municipal(ln, alvo["cnpj"]) else outros)[(alvo["id"], ln["nr"])] = reg
            n += 1
        log.info("  %s: %d linha(s), planilha de %s, %d do(s) município(s)",
                 arq, len(linhas), em, n)
    return municipais, outros, falhas, (max(datas) if datas else None)


def grava(cur, municipais: dict, outros: dict, alvos: list[dict], completa: bool) -> None:
    import psycopg2.extras
    psycopg2.extras.execute_batch(cur, _SQL, list(municipais.values()), page_size=200)
    psycopg2.extras.execute_batch(cur, _SQL_OUTROS, list(outros.values()), page_size=200)
    if completa:
        # A entidade que a planilha deixou de publicar sai — só com os dois
        # arquivos lidos: um que falhou esconderia linhas que continuam lá.
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
                log.info("nenhum município de MG — planilha de emendas de MG não se aplica")
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
                notas.append(f"a SEGOV não regera a planilha desde {em:%d/%m/%Y} "
                             f"({(date.today() - em).days} dias) — execução defasada")
            status = "partial" if notas else "success"
            log.info("=== Emendas MG (planilha): %d ao município, %d a entidade, "
                     "planilha de %s, status=%s ===", len(municipais), len(outros), em, status)
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
