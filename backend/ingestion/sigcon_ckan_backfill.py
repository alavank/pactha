"""Backfill de contrapartida + vigência dos convênios SIGCON-MG a partir do
dataset PÚBLICO do Estado (CKAN dados.mg.gov.br — 'convenios-saida').

POR QUE: o click-through do detalhe no portal SIGCON é instável e limitado à
1a página — pega poucos convênios por rodada. O dataset CKAN tem TODOS os
convênios do Estado (~88k) com valor de contrapartida e datas de vigência.
Aqui casamos por nr_siafi / nr_sigcon com os nossos convênios e preenchemos
valor_contrapartida + dt_vigencia_inicial/atual/final (sem scraping, completo).

NAO tem data de ASSINATURA nem responsáveis/emendas — esses seguem vindo do
scraper logado (sigcon_scraper). Este modulo cobre contrapartida/vigência/dias.

Recurso: 'Convênio' (dm_convenio.csv.gz) do pacote convenios-saida.
Uso: COFRE_KEY (nao precisa) DATABASE_URL_SYNC=... python ingestion/sigcon_ckan_backfill.py
"""
from __future__ import annotations
import os
import csv
import gzip
import io
import logging
from datetime import datetime

import httpx
import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sigcon_ckan_backfill")

# Recurso "Convênio" (dm_convenio) do pacote convenios-saida (dados.mg.gov.br)
DM_CONVENIO_URL = ("https://dados.mg.gov.br/dataset/52fcf7e5-d9a6-4b17-a491-12a5a978aecd/"
                   "resource/23de2c3f-cbf6-494a-8b32-4c9c151fb999/download/dm_convenio.csv.gz")
# Recurso "Convênio de Saída" (ft_convenio) — traz vr_rep_concede_atual = valor
# EFETIVAMENTE REPASSADO pelo concedente (o "pagamento" real). Chaveado por
# id_convenio (liga ao nr_siafi/nr_sigcon via dm_convenio).
FT_CONVENIO_URL = ("https://dados.mg.gov.br/dataset/52fcf7e5-d9a6-4b17-a491-12a5a978aecd/"
                   "resource/d8b48c2b-c2ec-451a-99f0-0421987ceeba/download/ft_convenio.csv.gz")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131 Safari/537.36"


def _clean_col(c: str) -> str:
    """Normaliza cabecalho CSV: remove BOM (UTF-8 lido como latin-1 vira 'ï»¿')."""
    return (c or "").strip().lstrip("ï»¿﻿ ").strip()


def _sync_url() -> str:
    return (os.getenv("DATABASE_URL_SYNC", "")
            .replace("&channel_binding=require", "").replace("?channel_binding=require", ""))


def _money(s: str):
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


def _dt(s: str):
    s = (s or "").strip()[:10]
    for f in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def _baixar(url: str) -> bytes:
    with httpx.Client(timeout=180, follow_redirects=True, verify=False,
                      headers={"User-Agent": UA}) as cli:
        r = cli.get(url)
        r.raise_for_status()
        return r.content


def _baixar_dataset() -> bytes:
    return _baixar(DM_CONVENIO_URL)


def _repasse_por_id(gz_bytes: bytes) -> dict:
    """id_convenio -> valor repassado real (vr_rep_concede_atual, versao mais recente)."""
    tmp: dict = {}
    with gzip.open(io.BytesIO(gz_bytes), "rt", encoding="latin-1") as f:
        rd = csv.reader(f, delimiter=";")
        idx = {_clean_col(c): i for i, c in enumerate(next(rd))}

        def g(row, c):
            i = idx.get(c)
            return row[i] if i is not None and i < len(row) else ""

        for row in rd:
            idc = (g(row, "id_convenio") or "").strip()
            if not idc:
                continue
            ano = int(g(row, "ano_particao") or 0)
            rep = _money(g(row, "vr_rep_concede_atual"))
            if idc not in tmp or ano >= tmp[idc][0]:
                tmp[idc] = (ano, rep)
    return {k: v[1] for k, v in tmp.items()}


def _index_dataset(gz_bytes: bytes):
    """Indexa dm_convenio por nr_siafi e nr_sigcon (versao mais recente)."""
    by_siafi: dict = {}
    by_sigcon: dict = {}
    n = 0
    with gzip.open(io.BytesIO(gz_bytes), "rt", encoding="latin-1") as f:
        rd = csv.reader(f, delimiter=";")
        cols = next(rd)
        idx = {_clean_col(c): i for i, c in enumerate(cols)}

        def g(row, c):
            i = idx.get(c)
            return row[i] if i is not None and i < len(row) else ""

        for row in rd:
            n += 1
            rec = {
                "id": (g(row, "id_convenio") or "").strip(),
                "obj": (g(row, "nome") or g(row, "objetivo") or "").strip(),
                "contra": _money(g(row, "vr_contra_public")),
                "vig_ini": _dt(g(row, "dt_vigencia_inicial")),
                "vig_fim": _dt(g(row, "dt_vigencia_final")),
                "vig_atual": _dt(g(row, "dt_vigencia_atual")),
                "ver": int(g(row, "fl_versao") or 0),
            }
            siafi = (g(row, "nr_siafi") or "").strip()
            sigcon = (g(row, "nr_sigcon") or "").strip()
            if siafi and (siafi not in by_siafi or rec["ver"] >= by_siafi[siafi]["ver"]):
                by_siafi[siafi] = rec
            if sigcon and (sigcon not in by_sigcon or rec["ver"] >= by_sigcon[sigcon]["ver"]):
                by_sigcon[sigcon] = rec
    log.info(f"dataset CKAN: {n} convenios | by_siafi={len(by_siafi)} by_sigcon={len(by_sigcon)}")
    return by_siafi, by_sigcon


def backfill() -> int:
    """Baixa o dataset, casa com os convenios SIGCON e preenche contrapartida +
    vigencia faltantes. Retorna nº de registros atualizados."""
    # Tenant sem municipio de MG nao tem convenio SIGCON para enriquecer —
    # baixar o dataset mineiro a cada 6 horas aqui era puro desperdicio.
    import os as _os
    import psycopg2 as _pg
    try:
        _c = _pg.connect(_os.environ["DATABASE_URL_SYNC"])
        _k = _c.cursor()
        _k.execute("SELECT count(*) FROM municipios "
                   "WHERE active = true AND upper(coalesce(uf, '')) = 'MG'")
        _n = _k.fetchone()[0]
        _c.close()
    except Exception:
        _n = -1  # na duvida, segue o fluxo de sempre
    if _n == 0:
        log.info("nenhum municipio de MG neste tenant — dataset SIGCON-MG nao baixado")
        return 0
    try:
        gz = _baixar_dataset()
    except Exception as e:
        log.error(f"falha ao baixar dataset CKAN: {str(e)[:120]}")
        return 0
    by_siafi, by_sigcon = _index_dataset(gz)
    # ft_convenio: valor EFETIVAMENTE REPASSADO por id_convenio (o "pagamento")
    try:
        rep_by_id = _repasse_por_id(_baixar(FT_CONVENIO_URL))
        log.info(f"ft_convenio: {len(rep_by_id)} convenios com repasse")
    except Exception as e:
        rep_by_id = {}
        log.warning(f"ft_convenio (repasse) falhou: {str(e)[:120]}")
    conn = psycopg2.connect(_sync_url()); cur = conn.cursor()
    cur.execute("SELECT id, nr_siafi, nr_sigcon, nr_proposta, nr_plano_trabalho "
                "FROM convenios_estadual WHERE fonte ILIKE 'SIGCON%'")
    ours = cur.fetchall()
    matched = upd = rep_set = 0
    for cid, siafi, sigcon, prop, plano in ours:
        rec = None
        for k in (siafi, sigcon, prop, plano):
            k = (k or "").strip()
            if not k:
                continue
            if k in by_siafi:
                rec = by_siafi[k]; break
            if k in by_sigcon:
                rec = by_sigcon[k]; break
        if not rec:
            continue
        matched += 1
        # repasse real (vr_rep_concede_atual). None = desconhecido -> mantem; 0 = nao repassado
        repassado = rep_by_id.get(rec.get("id")) if rec.get("id") else None
        if repassado is not None:
            rep_set += 1
        cur.execute("""UPDATE convenios_estadual SET
            valor_contrapartida = COALESCE(valor_contrapartida, %s),
            dt_vigencia_inicial = COALESCE(dt_vigencia_inicial, %s),
            dt_vigencia_atual   = COALESCE(dt_vigencia_atual, %s),
            dt_vigencia_final   = COALESCE(dt_vigencia_final, %s),
            objeto = CASE WHEN length(trim(coalesce(objeto, ''))) <= 3
                          THEN COALESCE(NULLIF(%s, ''), objeto) ELSE objeto END,
            valor_repassado = CASE WHEN %s::numeric IS NOT NULL THEN %s::numeric ELSE valor_repassado END,
            updated_at = NOW()
          WHERE id = %s""",
          (rec["contra"], rec["vig_ini"], rec["vig_atual"] or rec["vig_fim"], rec["vig_fim"],
           rec.get("obj"), repassado, repassado, cid))
        if cur.rowcount:
            upd += 1
    conn.commit()
    log.info(f"SIGCON: {len(ours)} convenios | casados={matched} | atualizados={upd} | repasse_preenchido={rep_set}")
    try:
        cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, finished_at) "
                    "VALUES ('sigcon_ckan_backfill','success',%s,NOW())", (upd,))
        conn.commit()
    except Exception:
        conn.rollback()
    cur.close(); conn.close()
    return upd


if __name__ == "__main__":
    backfill()
