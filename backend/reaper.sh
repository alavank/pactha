#!/usr/bin/env bash
# Guardiao do container de scrapers (freitas/trust/montesiao-worker, imagem Dockerfile.scraper).
#
# PROBLEMA que isto resolve:
#   O container roda ocioso e os crons entram via `docker exec`
#   (ex.: "python -u ingestion/run_sigcon_cron.py"). Quando um scraper e MORTO
#   sem rodar o finally -- timeout de 3600s do Scheduled Task, `docker restart`,
#   deploy ou OOM -- o Chromium do Playwright fica ORFAO. Como o PID 1 antigo era
#   `sleep infinity` (nao e um init de verdade e nao faz reap), esse Chromium
#   sobrevivia PARA SEMPRE queimando CPU -- o famoso "browser de 1h atras ainda
#   vivo" que saturou os 2 vCPU e derrubou o painel do Coolify.
#
# COMO resolve:
#   Este script e o PID 1 do container (sob o tini). A cada INTERVALO, se NENHUM
#   scraper estiver rodando, mata qualquer processo Chromium/Playwright vivo --
#   pois, sem scraper ativo, so pode ser orfao. A guarda de idade (MIN_AGE) evita
#   corrida com um browser recem-lancado. NUNCA interfere num scrape em andamento.
set -u

INTERVAL="${REAPER_INTERVAL:-90}"     # de quanto em quanto tempo varre (s)
MIN_AGE="${REAPER_MIN_AGE:-60}"       # so mata Chromium com mais de X s de vida (s)
SCRAPER_RE='ingestion[./]'            # um scraper ativo casa isto (run_*.py, *_scraper.py, ...)
CHROME_RE='chrome-headless-shell|ms-playwright'

log() { echo "[reaper $(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

log "guardiao iniciado (intervalo=${INTERVAL}s, idade_min=${MIN_AGE}s)"

while true; do
  sleep "$INTERVAL"

  # Ha scraper rodando? Entao e trabalho legitimo -- nao toca em nada.
  if pgrep -f "$SCRAPER_RE" >/dev/null 2>&1; then
    continue
  fi

  # Nenhum scraper ativo -> qualquer Chromium vivo e orfao. Mata os mais velhos.
  killed=0
  for pid in $(pgrep -f "$CHROME_RE" 2>/dev/null); do
    age="$(ps -o etimes= -p "$pid" 2>/dev/null | tr -d ' ')"
    [ -z "$age" ] && continue
    if [ "$age" -ge "$MIN_AGE" ]; then
      kill -9 "$pid" 2>/dev/null && killed=$((killed + 1))
    fi
  done

  [ "$killed" -gt 0 ] && log "sem scraper ativo; matei ${killed} processo(s) Chromium orfao(s)"
done
