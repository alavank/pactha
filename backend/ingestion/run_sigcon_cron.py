"""
Cron entry-point para SIGCON-MG scraper.

Coolify: Scheduled Task no resource Worker
  - Cron schedule: 0 */6 * * *   (a cada 6 horas = 4x/dia: 00:00, 06:00, 12:00, 18:00)
  - Comando: python -u ingestion/run_sigcon_cron.py
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
    import time
    _t0 = time.monotonic()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    # Fontes de DADOS ABERTOS (CAUC + Acordo FES) — leves, idempotentes e sem
    # login. Rodam PRIMEIRO (sempre executam, mesmo se o scraper SIGCON falhar).
    try:
        from ingestion.run_dadosabertos_cron import run_all
        run_all()
    except Exception as e:
        logging.getLogger("run_sigcon_cron").warning(f"dados abertos falhou: {e}")
    # Backfill de contrapartida + vigencia a partir do dataset CKAN do Estado
    # (cobre TODOS os convenios — o detalhe logado pega so alguns por rodada).
    # Roda ANTES do scraper de browser: na Freitas a maioria das rodadas morre
    # no teto de tempo DENTRO do main(), entao aqui atras o backfill rodava
    # ~1x/dia (em 03/08/2026: zero vezes). Mesmo antipadrao ja corrigido nos
    # backfills do transferegov (transferegov_voluntarias.py, bloco pos-open-data).
    try:
        from ingestion.sigcon_ckan_backfill import backfill
        backfill()
    except Exception as e:
        logging.getLogger("run_sigcon_cron").warning(f"ckan backfill falhou: {e}")
    # O orcamento interno do scraper (SIGCON_BUDGET_SECONDS, default 2700) foi
    # dimensionado para caber no teto externo do cron (timeout -k 30 3000)
    # CONTADO DO INICIO DO PROCESSO. Com dados abertos + backfill na frente,
    # desconta o tempo ja gasto — senao o kill externo volta a acertar o MEIO
    # do scrape (Chromium orfao e rodada sem ingestion_log). Se sobrou menos de
    # 5 min, nem inicia: o rodizio cobre na proxima janela.
    try:
        _base = max(0, int(os.getenv("SIGCON_BUDGET_SECONDS", "2700") or "2700"))
    except ValueError:
        _base = 2700
    _restante = _base - int(time.monotonic() - _t0)
    if _restante < 300:
        logging.getLogger("run_sigcon_cron").warning(
            f"pre-scraper consumiu {int(time.monotonic() - _t0)}s do orcamento de {_base}s: "
            "scraper adiado para a proxima janela (rodizio cobre)")
    else:
        os.environ["SIGCON_BUDGET_SECONDS"] = str(_restante)
        from ingestion.sigcon_scraper import main
        main()
