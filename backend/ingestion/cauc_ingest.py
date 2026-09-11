"""Ingestao do CAUC (regularidade fiscal FEDERAL dos municipios) — STN.

Fonte: dados abertos CKAN do Tesouro (dataset `cauc`, CSV "situacao dos
municipios no CAUC"), atualizado diariamente. Casa por IBGE com nossos
municipios e guarda o snapshot mais recente em `cauc_situacao`.

Cada exigencia (1.1, 1.2, ..., 5.7) tem valor:
  "!"            -> pendencia (irregular/impeditivo)
  data dd/mm/aa  -> regular ate essa data
  "Desabilitado" -> nao exigido

Uso: DATABASE_URL_SYNC=... python ingestion/cauc_ingest.py
"""
from __future__ import annotations
import os
import io
import csv
import json
import logging
from datetime import datetime

import httpx
import psycopg2
from psycopg2.extras import Json

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("cauc_ingest")

CKAN = "https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show?id=cauc"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/131"}


def _sync_url() -> str:
    return (os.getenv("DATABASE_URL_SYNC", "")
            .replace("&channel_binding=require", "").replace("?channel_binding=require", ""))


def _csv_url() -> str:
    """Resolve a URL do CSV de municipios no CKAN (robusto a mudanca de id)."""
    with httpx.Client(timeout=60, verify=False, follow_redirects=True, headers=UA) as c:
        pkg = c.get(CKAN).json()["result"]
    for res in pkg.get("resources", []):
        nm = (res.get("name") or "").lower()
        if res.get("format") == "CSV" and ("munic" in nm) and "todas" in (res.get("url") or "").lower():
            return res["url"]
    # fallback: qualquer CSV de municipios
    for res in pkg.get("resources", []):
        if res.get("format") == "CSV" and "munic" in (res.get("name") or "").lower():
            return res["url"]
    raise RuntimeError("CSV de municipios do CAUC nao encontrado no CKAN")


def _parse_dt(s: str):
    s = (s or "").strip()
    for f in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


try:
    from ingestion import status_coleta as _st
except ImportError:
    import status_coleta as _st


def ingest() -> int:
    url = _csv_url()
    log.info(f"baixando CSV CAUC: {url.split('/')[-1]}")
    with httpx.Client(timeout=180, verify=False, follow_redirects=True, headers=UA) as c:
        raw = c.get(url).content.decode("latin-1")

    lines = raw.splitlines()
    # preambulo: acha "Data da Pesquisa" e a linha de cabecalho (comeca com "UF";)
    data_pesquisa = None
    hdr_idx = None
    for i, l in enumerate(lines[:20]):
        if "data da pesquisa" in l.lower():
            data_pesquisa = _parse_dt(l.split(":", 1)[-1].replace('"', "").strip())
        if l.lstrip('"').upper().startswith("UF"):
            hdr_idx = i
            break
    if hdr_idx is None:
        raise RuntimeError("cabecalho do CSV CAUC nao encontrado")

    header = next(csv.reader([lines[hdr_idx]], delimiter=";"))
    codes = header[7:]  # colunas de exigencias (1.1, 1.2, ...)

    # municipios nossos por IBGE
    conn = psycopg2.connect(_sync_url())
    cur = conn.cursor()
    cur.execute("SELECT id, ibge_code FROM municipios WHERE ibge_code IS NOT NULL")
    by_ibge = {str(r[1]): r[0] for r in cur.fetchall()}
    log.info(f"municipios a casar por IBGE: {len(by_ibge)}")

    SQL = """INSERT INTO cauc_situacao
        (municipio_id, ibge, nome, uf, cod_siafi, populacao, data_pesquisa,
         itens, pendencias, pendencias_codigos, regular, atualizado_em)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        ON CONFLICT (municipio_id) DO UPDATE SET
         ibge=EXCLUDED.ibge, nome=EXCLUDED.nome, uf=EXCLUDED.uf,
         cod_siafi=EXCLUDED.cod_siafi, populacao=EXCLUDED.populacao,
         data_pesquisa=EXCLUDED.data_pesquisa, itens=EXCLUDED.itens,
         pendencias=EXCLUDED.pendencias, pendencias_codigos=EXCLUDED.pendencias_codigos,
         regular=EXCLUDED.regular, atualizado_em=NOW()"""

    n = 0
    for l in lines[hdr_idx + 1:]:
        if not l.strip():
            continue
        row = next(csv.reader([l], delimiter=";"))
        if len(row) < 8:
            continue
        ibge = (row[2] or "").strip()
        mid = by_ibge.get(ibge)
        if not mid:
            continue
        vals = row[7:]
        itens = {}
        pend = []
        for j, code in enumerate(codes):
            v = (vals[j] if j < len(vals) else "").strip()
            itens[code] = v
            if v == "!":
                pend.append(code)
        pop = None
        try:
            pop = int((row[5] or "").strip()) if (row[5] or "").strip().isdigit() else None
        except (ValueError, IndexError):
            pass
        cur.execute(SQL, (
            mid, ibge, (row[1] or "").strip(), (row[0] or "").strip()[:2],
            (row[3] or "").strip(), pop, data_pesquisa,
            Json(itens), len(pend), pend, len(pend) == 0,
        ))
        n += 1

    conn.commit()
    # ⚠️ A-1 (auditoria 11/09): status HONESTO. O CAUC e uma lista NACIONAL — todo
    # municipio ativo deveria aparecer. Entao aqui zero-inesperado FAZ sentido:
    # `n` (municipios gravados) < `esperado` (municipios do tenant) => algo casou
    # errado ou o CSV mudou de layout. Zero com municipios cadastrados => error.
    status, erro = _st.cauc(n, len(by_ibge))
    try:
        cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, error_message, finished_at) "
                    "VALUES ('cauc',%s,%s,%s,NOW())", (status, n, erro))
        conn.commit()
    except Exception:
        conn.rollback()
    cur.close()
    conn.close()
    log.info(f"CAUC: {n} municipios atualizados (data pesquisa {data_pesquisa}).")
    return n


if __name__ == "__main__":
    ingest()
