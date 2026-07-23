"""
Consumidor da fila de scraping on-demand (SIGCON) para o Worker no Coolify.

Roda como Scheduled Task a cada ~2min. Reclama 1 job 'pending' do tipo
'sigcon' (FOR UPDATE SKIP LOCKED), executa o mesmo pipeline do
run_sigcon_cron.py e marca o job como 'done' ou 'error'.

Substitui o antigo gatilho on-demand que chamava a API do Railway
(serviceInstanceRedeploy). Enfileiramento feito por
POST /api/convenios/refresh-sigcon (routers/convenios.py).
"""
import os
import sys
import logging
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import psycopg2

logger = logging.getLogger("run_queue_sigcon")


def _sync_url() -> str:
    url = os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
    # Neon usa channel_binding=require (psycopg2 nao suporta); em Postgres puro e no-op.
    return url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")


def _claim_job(conn) -> Optional[int]:
    """Reclama 1 job 'pending' do tipo sigcon. Retorna o id ou None.

    Antes de reclamar, cura jobs 'running' orfaos para a fila nao travar caso um
    Worker tenha morrido no meio da execucao.

    ATENCAO ao limiar: ele PRECISA ser maior que a duracao real de uma rodada.
    Ate 2026-07-23 era de 30 minutos enquanto o pipeline levava 4 a 5 HORAS --
    entao um job legitimo era declarado orfao aos 30min, re-enfileirado, e o poll
    seguinte subia um SEGUNDO scraper por cima do primeiro, que continuava vivo.
    Isso empilhava copias, cada uma com seus proprios Chromium, ate saturar a VPS.
    As Scheduled Tasks agora usam `timeout -k 30 3000` (50 min), entao nenhuma
    rodada legitima passa disso; 6h deixa margem folgada mesmo assim.
    """
    stale_min = int(os.getenv("SIGCON_STALE_MINUTES", "360") or "360")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE scraper_jobs SET status = 'error', finished_at = now(), "
            "error = %s "
            "WHERE tipo = 'sigcon' AND status = 'running' "
            "AND started_at < now() - make_interval(mins => %s)",
            (f"timeout (stale running > {stale_min}min)", stale_min),
        )
        cur.execute(
            "SELECT id FROM scraper_jobs "
            "WHERE tipo = 'sigcon' AND status = 'pending' "
            "ORDER BY requested_at "
            "FOR UPDATE SKIP LOCKED LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            conn.commit()
            return None
        job_id = row[0]
        cur.execute(
            "UPDATE scraper_jobs SET status = 'running', started_at = now() WHERE id = %s",
            (job_id,),
        )
    conn.commit()  # libera o FOR UPDATE lock antes de rodar o pipeline (pode demorar minutos)
    return job_id


def _finish_job(conn, job_id: int, ok: bool, err: Optional[str] = None):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE scraper_jobs SET status = %s, finished_at = now(), error = %s WHERE id = %s",
            ("done" if ok else "error", None if ok else (err or "erro desconhecido"), job_id),
        )
    conn.commit()


def _run_sigcon_pipeline():
    """Mesmo pipeline do run_sigcon_cron.py (dados abertos -> SIGCON -> CKAN backfill)."""
    try:
        from ingestion.run_dadosabertos_cron import run_all
        run_all()
    except Exception as e:
        logger.warning(f"dados abertos falhou: {e}")
    from ingestion.sigcon_scraper import main as sigcon_main
    sigcon_main()
    try:
        from ingestion.sigcon_ckan_backfill import backfill
        backfill()
    except Exception as e:
        logger.warning(f"ckan backfill falhou: {e}")


def main():
    url = _sync_url()
    if not url:
        logger.error("DATABASE_URL_SYNC/DATABASE_URL ausente")
        return
    conn = psycopg2.connect(url)
    try:
        job_id = _claim_job(conn)
        if job_id is None:
            logger.info("Nenhum job sigcon pendente.")
            return
        logger.info(f"Job sigcon #{job_id} reclamado. Executando pipeline...")
        try:
            _run_sigcon_pipeline()
            _finish_job(conn, job_id, ok=True)
            logger.info(f"Job sigcon #{job_id} concluido.")
        except Exception as e:
            logger.exception(f"Job sigcon #{job_id} falhou")
            _finish_job(conn, job_id, ok=False, err=str(e)[:2000])
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    main()
