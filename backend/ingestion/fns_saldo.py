"""
Saldo das contas do Fundo Municipal de Saúde — o arquivo anual do Portal FNS.

    https://portalfns.saude.gov.br/downloads/
    -> REPASSE-FAF-COM-POPULACAO-<ANO>.csv|xlsx  (2002-2022 e 2025 em 24/09/2026)

Uma linha por município x bloco x grupo x ESTRATÉGIA do fundo a fundo do ano, com
o CNPJ do fundo, BANCO/AGÊNCIA/CONTA onde o dinheiro cai, o valor bruto e líquido
repassado e — o que nenhuma outra fonte pública tem — o SALDO DA CONTA numa data
(`VL_SALDO_CONTA`, `DT_SALDO_CONTA`). Monte Sião, arquivo de 2025: 12 contas do FMS,
R$ 4,51 mi parados em 30/11/2025.

AS ARMADILHAS, medidas em 24/09/2026:

1. ⚠️ **A API DO CONSULTAFNS NÃO TEM SALDO.** O extrato da conta
   (`recursos/conta-corrente/extrato-movimentacao`) responde 404 e o botão está
   comentado no código da tela; nenhuma resposta que a tela usa traz saldo. As
   telas "Saldo PAB/MAC" são o saldo do TETO financeiro, não da conta. Este
   arquivo é a única fonte pública do número.

2. ⚠️ **O ARQUIVO É ANUAL E ATRASADO.** O de 2025 foi publicado em 16/01/2026 com
   saldo de 30/11/2025; 2023 e 2024 NÃO estão na página. `dt_saldo` vai para a tela
   sempre. A rodada é diária (a regra de coleta), mas só baixa quando aparece
   arquivo de ano novo ou um município ainda não carregado.

3. ⚠️ **O SALDO SE REPETE EM CADA ESTRATÉGIA DA MESMA CONTA.** Nenhuma das 52.885
   contas do arquivo de 2025 tem dois saldos diferentes — é UM número por conta,
   repetido. Somar as linhas contaria o mesmo dinheiro de novo por estratégia; a
   gravação é uma linha por conta.

4. ⚠️ **DOIS FORMATOS.** Até 2022 é CSV em Latin-1 com vírgula decimal e data
   "dd/mm/aaaa"; 2025 é XLSX com número e data nativos. Data "-" = sem data.
   Colunas lidas por NOME; faltando uma, o arquivo é recusado.

5. `CO_MUNICIPIO_IBGE` tem 6 dígitos (sem o verificador), como no resto do FNS.
   `TP_REPASSE = 'ESTADUAL'` é o fundo do ESTADO sediado no município e fica fora.

Rodável por Scheduled Task ou à mão:
    python -u ingestion/fns_saldo.py            # coleta de verdade
    python -u ingestion/fns_saldo.py --dry      # baixa, lê e mostra
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("fns_saldo")

PAGINA = "https://portalfns.saude.gov.br/downloads/"
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0; dados abertos FNS)"}
SOURCE = "fns_saldo"
TIMEOUT = 300
MIN_LINHAS = 50000          # 112 mil (2020) a 147 mil (2025); menos = cortado
COLUNAS = ("BLOCO", "GRUPO", "CO_MUNICIPIO_IBGE", "CNPJ", "ENTIDADE", "BANCO",
           "AGENCIA", "CONTA", "TP_REPASSE", "VL_LIQUIDO", "VL_SALDO_CONTA",
           "DT_SALDO_CONTA")
RE_ARQUIVO = re.compile(
    r'href="(https?://[^"]*REPASSE-FAF-COM-POPULACAO[^"]*\.(?:csv|xlsx))"', re.I)


def arquivo_mais_recente(html: str) -> tuple[int, str] | None:
    """(ano, url) do arquivo de ano mais alto listado na página."""
    melhores: dict[int, str] = {}
    for url in RE_ARQUIVO.findall(html or ""):
        nome = url.rsplit("/", 1)[-1]
        m = re.search(r"POPULACAO\D*?(20\d{2})", nome, re.I)
        if m:
            melhores[int(m.group(1))] = url     # o último listado do ano vence
    if not melhores:
        return None
    ano = max(melhores)
    return ano, melhores[ano]


def _dec(v) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(round(v, 2)))
    s = str(v).strip()
    if s in ("", "-"):
        return None
    try:
        return Decimal(s.replace(".", "").replace(",", ".")) if "," in s else Decimal(s)
    except InvalidOperation:
        return None


def _data(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(v or ""))
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(v or ""))
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _txt(v) -> str:
    return str(v).strip() if v is not None else ""


def linhas_do_arquivo(conteudo: bytes, url: str):
    """Itera dicts {coluna: valor} do CSV (Latin-1, ;) ou do XLSX (armadilha 4)."""
    if url.lower().endswith(".xlsx"):
        import openpyxl
        ws = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True,
                                    data_only=True).worksheets[0]
        it = ws.iter_rows(values_only=True)
        cab = [_txt(c).upper() for c in next(it)]
        faltam = [c for c in COLUNAS if c not in cab]
        if faltam:
            raise ValueError(f"colunas ausentes no arquivo do FNS: {faltam}")
        for r in it:
            if r and any(v is not None for v in r):
                yield dict(zip(cab, r))
        return
    texto = conteudo.decode("utf-8-sig") if conteudo[:3] == b"\xef\xbb\xbf" else conteudo.decode("latin-1")
    # O de 2020 separa por VÍRGULA, com tudo entre aspas ("133459,06" é um campo
    # só). Separador pela 1ª linha, para não depender do ano do arquivo.
    primeira = texto.split("\n", 1)[0]
    sep = ";" if primeira.count(";") > primeira.count(",") else ","
    leitor = csv.DictReader(io.StringIO(texto), delimiter=sep)
    cab = [c.strip().upper() for c in (leitor.fieldnames or [])]
    faltam = [c for c in COLUNAS if c not in cab]
    if faltam:
        raise ValueError(f"colunas ausentes no arquivo do FNS: {faltam}")
    for r in leitor:
        yield {k.strip().upper(): v for k, v in r.items() if k}


def contas_por_municipio(linhas, alvos_ibge6: dict[str, int]) -> tuple[dict, int]:
    """({(mid, cnpj, banco, agencia, conta): conta agregada}, linhas lidas)."""
    contas: dict = {}
    n = 0
    for r in linhas:
        n += 1
        if _txt(r.get("TP_REPASSE")).upper() != "MUNICIPAL":
            continue
        ibge6 = re.sub(r"\D", "", _txt(r.get("CO_MUNICIPIO_IBGE")))[:6]
        mid = alvos_ibge6.get(ibge6)
        if not mid:
            continue
        cnpj = re.sub(r"\D", "", _txt(r.get("CNPJ"))).zfill(14)
        k = (mid, cnpj, _txt(r.get("BANCO")), _txt(r.get("AGENCIA")), _txt(r.get("CONTA")))
        c = contas.get(k)
        if c is None:
            c = contas[k] = {
                "mid": mid, "cnpj": cnpj, "banco": k[2], "agencia": k[3], "conta": k[4],
                "entidade": _txt(r.get("ENTIDADE")) or None,
                # Armadilha 3: UM saldo por conta — o primeiro vale para todas.
                "saldo": _dec(r.get("VL_SALDO_CONTA")),
                "dt_saldo": _data(r.get("DT_SALDO_CONTA")),
                "repassado_ano": Decimal("0"), "estrategias": [],
            }
        liq = _dec(r.get("VL_LIQUIDO")) or Decimal("0")
        c["repassado_ano"] += liq
        c["estrategias"].append({
            "bloco": _txt(r.get("BLOCO")), "grupo": _txt(r.get("GRUPO")),
            "estrategia": _txt(r.get("ESTRATEGIA") or r.get("ESTRATÉGIA")),
            "liquido": str(liq)})
    return contas, n


_SQL = """
INSERT INTO fns_saldo_conta (municipio_id, ano, cnpj, entidade, banco, agencia, conta,
    saldo, dt_saldo, repassado_ano, estrategias, arquivo, atualizado_em)
VALUES (%(mid)s, %(ano)s, %(cnpj)s, %(entidade)s, %(banco)s, %(agencia)s, %(conta)s,
    %(saldo)s, %(dt_saldo)s, %(repassado_ano)s, %(estrategias)s::jsonb, %(arquivo)s, NOW())
"""


def _alvos(cur) -> dict[str, int]:
    cur.execute("SELECT id, ibge_code FROM municipios WHERE active")
    return {re.sub(r"\D", "", r[1] or "")[:6]: r[0] for r in cur.fetchall()
            if len(re.sub(r"\D", "", r[1] or "")) >= 6}


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


def ja_carregado(cur, ano: int, url: str, mids: list[int]) -> bool:
    """Todo município ativo já tem este arquivo? (armadilha 2: não rebaixar à toa)"""
    cur.execute("SELECT count(DISTINCT municipio_id) FROM fns_saldo_conta "
                "WHERE ano = %s AND arquivo = %s AND municipio_id = ANY(%s)",
                (ano, url, mids))
    return (cur.fetchone() or [0])[0] >= len(set(mids))


def grava(cur, contas: dict, ano: int, url: str, mids: list[int]) -> None:
    """Troca o ano inteiro de cada município de uma vez: o arquivo é a verdade do
    ano, e conta que saiu dele sai daqui."""
    import psycopg2.extras
    cur.execute("DELETE FROM fns_saldo_conta WHERE ano = %s AND municipio_id = ANY(%s)",
                (ano, mids))
    regs = []
    for c in contas.values():
        est = sorted(c["estrategias"], key=lambda e: Decimal(e["liquido"]), reverse=True)
        regs.append({**c, "ano": ano, "arquivo": url,
                     "estrategias": json.dumps(est[:80], ensure_ascii=False)})
    psycopg2.extras.execute_batch(cur, _SQL, regs, page_size=200)


def ingest(dry: bool = False) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            alvos = _alvos(cur)
            mids = list(alvos.values())
            if not alvos:
                if not dry:
                    _log_ingest(cur, conn, "success", 0, "nenhum município ativo")
                return 0
            with httpx.Client(follow_redirects=True, headers=UA, timeout=TIMEOUT) as client:
                pag = client.get(PAGINA)
                pag.raise_for_status()
                achado = arquivo_mais_recente(pag.text)
                if not achado:
                    raise ValueError("a página de downloads do FNS não lista mais o "
                                     "REPASSE-FAF-COM-POPULACAO — mudou de forma?")
                ano, url = achado
                if not dry and ja_carregado(cur, ano, url, mids):
                    log.info("arquivo de %s já carregado para os %d município(s) — nada a baixar",
                             ano, len(mids))
                    _log_ingest(cur, conn, "success", 0,
                                f"arquivo de {ano} já carregado (o FNS publica 1x/ano)")
                    return 0
                log.info("baixando %s", url)
                r = client.get(url)
                r.raise_for_status()
            contas, n = contas_por_municipio(linhas_do_arquivo(r.content, url), alvos)
            if n < MIN_LINHAS:
                raise ValueError(f"arquivo do FNS com só {n} linha(s) (< {MIN_LINHAS}) — cortado?")
            total = sum((c["saldo"] or 0) for c in contas.values())
            log.info("arquivo de %s: %d linhas, %d conta(s) dos municípios, saldo somado R$ %s",
                     ano, n, len(contas), total)
            if dry:
                for c in sorted(contas.values(), key=lambda x: -(x["saldo"] or 0))[:15]:
                    log.info("   %s %s/%s/%s saldo %s em %s", c["entidade"], c["banco"],
                             c["agencia"], c["conta"], c["saldo"], c["dt_saldo"])
                return 0
            grava(cur, contas, ano, url, mids)
            conn.commit()
            _log_ingest(cur, conn, "success", len(contas),
                        f"arquivo de {ano}: {len(contas)} conta(s)")
            return len(contas)
        except Exception as e:
            conn.rollback()
            log.error("FNS saldo falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, f"{type(e).__name__}: {str(e)[:380]}")
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ingest(dry="--dry" in sys.argv)
