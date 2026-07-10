"""Refresh das fontes de DADOS ABERTOS (nao precisam de login/scraping):
  - CAUC (regularidade fiscal federal - STN)
  - Acordo FES (divida da saude estadual SES-MG)

Sao ingestoes leves e idempotentes (TRUNCATE/UPSERT). Rodam via o cron
existente (run_sigcon_cron.py chama run_all()), entao NAO precisam de uma
Scheduled Task nova no Coolify. Precisam so de DATABASE_URL_SYNC.

Uso direto: DATABASE_URL_SYNC=... python ingestion/run_dadosabertos_cron.py
"""
import logging

log = logging.getLogger("run_dadosabertos_cron")


def run_all() -> None:
    for nome, mod in (("CAUC", "ingestion.cauc_ingest"),
                      ("Acordo FES", "ingestion.acordofes_ingest")):
        try:
            m = __import__(mod, fromlist=["ingest"])
            n = m.ingest()
            log.info(f"[dados abertos] {nome}: {n} registros.")
        except Exception as e:  # nunca derruba o cron por causa de uma fonte
            log.warning(f"[dados abertos] {nome} falhou: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_all()
