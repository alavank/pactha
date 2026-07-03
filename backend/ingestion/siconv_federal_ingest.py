"""Ingestao da base federal SICONV/TransfereGov (Brasil inteiro) p/ consulta por CNPJ.

Fonte (dados abertos, PUBLICO): repositorio.dados.gov.br/seges/detru
  - siconv_proposta.csv.zip  (~200MB) : nivel proposta, tem IDENTIF_PROPONENTE (CNPJ)
  - siconv_convenio.csv.zip  (~16MB)  : convenio celebrado, ligado por ID_PROPOSTA

Carrega tudo em `siconv_federal` (proposta + convenio via join), indexado por CNPJ.
Uso: DATABASE_URL_SYNC=... python ingestion/siconv_federal_ingest.py
"""
from __future__ import annotations
import os
import io
import csv
import zipfile
import logging
from datetime import datetime

import httpx
import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("siconv_federal_ingest")

BASE = "https://repositorio.dados.gov.br/seges/detru"
PROPOSTA_URL = f"{BASE}/siconv_proposta.csv.zip"
CONVENIO_URL = f"{BASE}/siconv_convenio.csv.zip"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/131"}


def _sync_url() -> str:
    return (os.getenv("DATABASE_URL_SYNC", "")
            .replace("&channel_binding=require", "").replace("?channel_binding=require", ""))


def _clean(c: str) -> str:
    return (c or "").strip().lstrip("ï»¿﻿ ").strip()


def _digits(s) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _money(s):
    s = (s or "").strip().replace("R$", "").strip()
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _dt(s):
    s = (s or "").strip()[:10]
    for f in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def _open_csv(url: str):
    """Baixa o zip e devolve (reader, index_by_colname). Mantem o zip em memoria."""
    log.info(f"baixando {url.split('/')[-1]} ...")
    with httpx.Client(timeout=600, verify=False, follow_redirects=True, headers=UA) as c:
        content = c.get(url).content
    zf = zipfile.ZipFile(io.BytesIO(content))
    fn = zf.namelist()[0]
    f = zf.open(fn)
    # Os CSVs do SICONV vem em UTF-8 (com BOM). Ler como latin-1 gera mojibake
    # ("Aquisicao" -> "AquisiÃ§Ã£o"). utf-8-sig remove o BOM automaticamente.
    rd = csv.reader(io.TextIOWrapper(f, encoding="utf-8-sig"), delimiter=";")
    cols = [_clean(x) for x in next(rd)]
    idx = {c: i for i, c in enumerate(cols)}
    return rd, idx


def _index_convenios() -> dict:
    """id_proposta -> (nr_convenio, sit, vl_desembolsado, dt_assin, dt_fim_vig)."""
    rd, ix = _open_csv(CONVENIO_URL)

    def g(row, c):
        i = ix.get(c)
        return row[i] if i is not None and i < len(row) else ""

    out = {}
    n = 0
    for row in rd:
        n += 1
        idp = _digits(g(row, "ID_PROPOSTA"))
        if not idp:
            continue
        out[idp] = (
            g(row, "NR_CONVENIO") or None,
            g(row, "SIT_CONVENIO") or None,
            _money(g(row, "VL_DESEMBOLSADO_CONV")),
            _dt(g(row, "DIA_ASSIN_CONV")),
            _dt(g(row, "DIA_FIM_VIGENC_CONV")),
        )
    log.info(f"convenios indexados: {len(out)} (de {n} linhas)")
    return out


def ingest() -> int:
    conv = _index_convenios()
    rd, ix = _open_csv(PROPOSTA_URL)

    def g(row, c):
        i = ix.get(c)
        return row[i] if i is not None and i < len(row) else ""

    conn = psycopg2.connect(_sync_url())
    cur = conn.cursor()
    cur.execute("TRUNCATE siconv_federal")
    conn.commit()

    SQL = """INSERT INTO siconv_federal
        (id_proposta, cnpj, proponente, uf, municipio, nr_proposta, ano, situacao,
         objeto, vl_global, vl_repasse, nr_convenio, situacao_convenio,
         vl_desembolsado, dt_assinatura, dt_fim_vigencia)
        VALUES %s ON CONFLICT (id_proposta) DO NOTHING"""

    batch = []
    total = 0
    for row in rd:
        idp_raw = _digits(g(row, "ID_PROPOSTA"))
        if not idp_raw:
            continue
        idp = int(idp_raw)
        cnpj = _digits(g(row, "IDENTIF_PROPONENTE"))[:14] or None
        ano_raw = _digits(g(row, "ANO_PROP"))
        c = conv.get(idp_raw) or (None, None, None, None, None)
        batch.append((
            idp, cnpj,
            (g(row, "NM_PROPONENTE") or None),
            (g(row, "UF_PROPONENTE") or None)[:2] if g(row, "UF_PROPONENTE") else None,
            (g(row, "MUNIC_PROPONENTE") or None),
            (g(row, "NR_PROPOSTA") or None)[:40],
            int(ano_raw) if ano_raw else None,
            (g(row, "SIT_PROPOSTA") or None),
            (g(row, "OBJETO_PROPOSTA") or "")[:600] or None,
            _money(g(row, "VL_GLOBAL_PROP")),
            _money(g(row, "VL_REPASSE_PROP")),
            c[0], c[1], c[2], c[3], c[4],
        ))
        if len(batch) >= 5000:
            execute_values(cur, SQL, batch, page_size=5000)
            conn.commit()
            total += len(batch)
            batch = []
            if total % 100000 == 0:
                log.info(f"  {total} propostas inseridas...")
    if batch:
        execute_values(cur, SQL, batch, page_size=5000)
        conn.commit()
        total += len(batch)

    # log de ingestao
    try:
        cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, finished_at) "
                    "VALUES ('siconv_federal','success',%s,NOW())", (total,))
        conn.commit()
    except Exception:
        conn.rollback()
    cur.close()
    conn.close()
    log.info(f"SICONV federal: {total} propostas carregadas (com CNPJ).")
    return total


if __name__ == "__main__":
    ingest()
