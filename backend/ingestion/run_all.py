"""
Orquestrador de pipelines PACTA - roda todos os scrapers conforme frequencia.

Uso via env CRON_TIER:
- CRON_TIER=daily     -> editais PNCP + oportunidades + DOU
- CRON_TIER=weekly    -> camara + senado + almg + cnes + ceis
- CRON_TIER=monthly   -> transferegov + sigcon + emendas (fed/est) + portal_transp + codevasf
- CRON_TIER=full      -> todos (uso manual)

Cada pipeline e isolado: falha em um nao quebra os outros.
Log via tabela ingestion_log (cada pipeline ja faz isso).
"""
import os
import sys
import importlib
import logging
import traceback
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger("run_all")
logging.basicConfig(level=logging.INFO,
                     format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")


TIERS = {
    "daily": [
        "editais",            # PNCP licitacoes (publico)
        "oportunidades",      # SICONV programas abertos
        # "dou_inlabs",       # requer INLABS_USER/INLABS_PASS
    ],
    "weekly": [
        "camara_deputados",   # API Camara publica
        "senado",             # API Senado publica
        "almg_deputados",     # API ALMG (estaduais MG) publica
        "cnes_estabelecimentos",  # API CNES publica
        "ceis_bulk",          # CEIS via Portal Transparencia API
    ],
    "monthly": [
        "transferegov",       # bulk SICONV mensal
        "sigcon",             # bulk SIGCON-MG mensal
        "emendas_federais",   # siconv_emenda.csv (depende transferegov)
        "emendas_estaduais",  # regex em objetos SIGCON
        "portal_transparencia",  # CGU API
        "codevasf_scraper",   # heuristica sobre MAPA (depende transferegov)
        "tse",                # bulk TSE
    ],
}


def main():
    tier = os.getenv("CRON_TIER", "weekly").lower().strip()
    logger.info(f"=== PACTA Pipeline Orchestrator (tier={tier}) ===")

    if tier == "full":
        modules = []
        for t in ("daily", "weekly", "monthly"):
            modules += TIERS[t]
    else:
        modules = TIERS.get(tier, [])
        if not modules:
            logger.error(f"Tier desconhecido: {tier}. Use daily/weekly/monthly/full")
            sys.exit(1)

    sucessos, falhas = [], []
    inicio = datetime.now()

    for mod_name in modules:
        logger.info(f"--- Rodando: ingestion.{mod_name} ---")
        try:
            mod = importlib.import_module(f"ingestion.{mod_name}")
            if hasattr(mod, "main"):
                mod.main()
            else:
                logger.warning(f"  Modulo {mod_name} sem funcao main()")
                continue
            sucessos.append(mod_name)
        except SystemExit as e:
            # Modulos que dao sys.exit(1) em falha
            if e.code:
                logger.error(f"  {mod_name} encerrou com codigo {e.code}")
                falhas.append((mod_name, f"exit {e.code}"))
            else:
                sucessos.append(mod_name)
        except Exception as e:
            logger.error(f"  Falha em {mod_name}: {e}")
            logger.error(traceback.format_exc()[:1000])
            falhas.append((mod_name, str(e)[:200]))

    duracao = (datetime.now() - inicio).total_seconds()
    logger.info(f"\n=== Resumo ({duracao:.0f}s) ===")
    logger.info(f"  Sucessos ({len(sucessos)}): {sucessos}")
    if falhas:
        logger.warning(f"  Falhas ({len(falhas)}):")
        for n, e in falhas:
            logger.warning(f"    {n}: {e}")

    sys.exit(0 if not falhas else 2)


if __name__ == "__main__":
    main()
