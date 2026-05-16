"""
Cron entry-point para SIGCON-MG scraper.

Configurar no Railway:
  - Service: pacta-cron-sigcon
  - Cron schedule: 0 */6 * * *   (a cada 6 horas = 4x/dia: 00:00, 06:00, 12:00, 18:00)
  - Start command: python ingestion/run_sigcon_cron.py
  - Env: COFRE_KEY, DATABASE_URL_SYNC

Cada execucao:
1. Logs em ingestion_log (source='sigcon_scraper')
2. Detecta DELTAS (novos convenios, status mudou, valor mudou) e
   insere notificacoes na tabela `notificacoes` -> badge Bell no header
   do frontend mostra contador em tempo real (poll 1min)
"""
import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    from ingestion.sigcon_scraper import main
    main()
