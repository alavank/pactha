"""Backfill da SITUAÇÃO DE CONTRATAÇÃO + CLÁUSULA SUSPENSIVA dos instrumentos
FEDERAIS a partir do OPEN DATA do SICONV (sem login gov.br).

Resolve a dependência da sessão autenticada gov.br: o detalhe da cláusula
suspensiva (situação de contratação, motivo e data prevista) — que antes só vinha
da tela logada (reCAPTCHA periódico) — está no arquivo público
`siconv_convenio.csv` (api-publica.transferegov.gestao.gov.br/downloads/dadosgov), campos:
  - SITUACAO_CONTRATACAO  (Normal | Cláusula Suspensiva | Liminar Judicial)
  - MOTIVO_SUSPENSAO      (ex.: "Termo de Referência")
  - DATA_SUSPENSIVA       (data prevista p/ resolução, dd/mm/aaaa)
  - VL_EMPENHADO_CONV     (empenho real — bônus p/ validação)

Casa com transferegov_propostas por NR_CONVENIO=codigo_instrumento (ou
ID_PROPOSTA=id_proposta_siconv). Roda no cron transferegov (a cada dia), então
NUNCA precisa de re-captura: tudo atualiza sozinho.

Entry: main() / backfill().
"""
from __future__ import annotations
import csv
import io
import logging
import os
import sys
import zipfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("siconv_convenio_backfill")

URL = "https://api-publica.transferegov.gestao.gov.br/downloads/dadosgov/siconv_convenio.zip"
_CACHE_DIR = os.getenv("SICONV_CACHE_DIR") or os.path.join(
    os.getenv("TEMP") or os.getenv("TMPDIR") or "/tmp", "siconv_opendata"
)


def _db():
    import psycopg2
    url = os.getenv("DATABASE_URL_SYNC", "")
    url = url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    return psycopg2.connect(url)


def _download(use_cache: bool = True) -> bytes:
    import httpx
    path = os.path.join(_CACHE_DIR, "siconv_convenio.zip")
    if use_cache and os.path.exists(path) and os.path.getsize(path) > 1000:
        return open(path, "rb").read()
    logger.info(f"  baixando {URL} ...")
    r = httpx.get(URL, timeout=900, verify=False, follow_redirects=True)
    r.raise_for_status()
    if use_cache:
        try:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            open(path, "wb").write(r.content)
        except OSError:
            pass
    logger.info(f"  baixado {len(r.content)} bytes")
    return r.content


def _parse_dt(s: str):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def backfill(use_cache: bool = True) -> int:
    """Atualiza situacao_contratacao + cláusula (motivo/data) das federais
    casando com siconv_convenio. Retorna nº de linhas atualizadas."""
    conn = _db(); cur = conn.cursor()
    cur.execute("SELECT id, codigo_instrumento, id_proposta_siconv FROM transferegov_propostas")
    cod_map, idp_map = {}, {}
    for rid, ci, idp in cur.fetchall():
        if ci:
            cod_map[str(ci).strip()] = rid
        if idp:
            idp_map[str(idp).strip()] = rid
    if not cod_map and not idp_map:
        logger.info("backfill_clausula: nenhuma proposta federal — nada a fazer")
        cur.close(); conn.close()
        return 0

    content = _download(use_cache=use_cache)
    z = zipfile.ZipFile(io.BytesIO(content))
    name = z.namelist()[0]
    rd = csv.reader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig", errors="replace", newline=""),
                    delimiter=";")
    hdr = [h.strip() for h in next(rd)]
    ix = {h: i for i, h in enumerate(hdr)}

    def g(row, k):
        j = ix.get(k)
        return row[j].strip() if j is not None and j < len(row) else ""

    # row_id -> (situacao_contratacao, motivo, dt_prevista)
    achados: dict[int, tuple] = {}
    for row in rd:
        nrc = g(row, "NR_CONVENIO")
        idp = g(row, "ID_PROPOSTA")
        rid = cod_map.get(nrc) or idp_map.get(idp)
        if not rid:
            continue
        sc = g(row, "SITUACAO_CONTRATACAO") or None
        is_clausula = sc and "normal" not in sc.lower()
        motivo = (g(row, "MOTIVO_SUSPENSAO") or None) if is_clausula else None
        dt = _parse_dt(g(row, "DATA_SUSPENSIVA")) if is_clausula else None
        achados[rid] = (sc, motivo, dt)
    logger.info(f"backfill_clausula: {len(achados)} convenios casados no open data")

    if not achados:
        cur.close(); conn.close()
        return 0
    n = 0
    for rid, (sc, motivo, dt) in achados.items():
        # ⚠️ M-1 (auditoria 11/09): COALESCE, nao sobrescrita crua. Antes o UPDATE
        # gravava NULL em motivo/data (e ate na situacao) quando a linha do CSV
        # nao era clausula ("Normal") ou vinha sem o campo — ZERANDO dado valido ja
        # coletado. Ausencia da fonte nao apaga o que temos; valor presente (inclui
        # "Normal") atualiza normalmente. Regra: nao trocar dado bom por vazio.
        cur.execute(
            "UPDATE transferegov_propostas SET "
            "situacao_contratacao=COALESCE(%s, situacao_contratacao), "
            "clausula_suspensiva_motivo=COALESCE(%s, clausula_suspensiva_motivo), "
            "clausula_suspensiva_dt_prevista=COALESCE(%s, clausula_suspensiva_dt_prevista) "
            "WHERE id=%s",
            (sc, motivo, dt, rid),
        )
        n += cur.rowcount
    conn.commit()
    cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, finished_at) "
                "VALUES ('siconv_convenio_backfill','success',%s,NOW())", (n,))
    conn.commit(); cur.close(); conn.close()
    logger.info(f"backfill_clausula: {n} linhas atualizadas (situacao_contratacao + cláusula)")
    return n


def main(use_cache: bool = True):
    logger.info("=== SICONV convenio backfill (cláusula suspensiva via open data) ===")
    try:
        backfill(use_cache=use_cache)
    except Exception as e:
        logger.error(f"backfill falhou: {str(e)[:200]}")
    logger.info("=== fim ===")


if __name__ == "__main__":
    main(use_cache="--no-cache" not in sys.argv)
