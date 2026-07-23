#!/usr/bin/env bash
# Guardiao do container de scrapers (freitas/trust/montesiao-worker, imagem Dockerfile.scraper).
#
# PROBLEMA que isto resolve:
#   O container roda ocioso e os crons entram via `docker exec`
#   (ex.: "python -u ingestion/run_sigcon_cron.py"). Duas patologias observadas
#   em producao (auditoria de 2026-07-23):
#
#   (a) O Scheduled Task do Coolify ABORTA aos 3600s e marca "failed", mas o
#       processo Python DENTRO do container CONTINUA VIVO indefinidamente. Foram
#       medidos scrapers com 4h49m de vida, cada um segurando 5 a 8 processos
#       chrome-headless-shell. Como o cron seguinte sobe outra copia por cima, o
#       consumo cresce monotonicamente ate saturar os 2 vCPU da VPS.
#   (b) Quando um scraper morre sem rodar o finally, o Chromium fica ORFAO e
#       sobrevive para sempre queimando CPU.
#
# POR QUE A VERSAO ANTERIOR NAO FUNCIONAVA:
#   A guarda era `if pgrep -f 'ingestion[./]'; then continue; fi` -- "se ha
#   scraper rodando, nao mexe em nada". Mas os processos ABANDONADOS sao
#   exatamente `python -u ingestion/<script>.py`: eles casavam a guarda, o
#   guardiao concluia "ha trabalho legitimo" e NUNCA varria nada. Medido:
#   0 kills em 24h com 21 Chromium vivos. O tini tambem nao resolve -- ele faz
#   reap de ZUMBIS, e Chromium orfao vivo nao e zumbi, continua escalonado.
#
# COMO RESOLVE AGORA -- duas regras que nao dependem de "ha scraper rodando":
#   1. IDADE (guarda absoluta): mata qualquer processo de ingestao ou Chromium
#      com mais de MAX_AGE. Com `timeout -k 30 3000` nas Scheduled Tasks nenhuma
#      rodada legitima passa de ~3030s, entao passar de MAX_AGE = estar travado.
#   2. PARENTESCO: mata Chromium que nao tenha nenhum ancestral
#      `python ... ingestion/...` -- sem dono, so pode ser orfao.
#   A varredura e SEMPRE logada (antes ela era invisivel), com contagem viva.
set -u

INTERVAL="${REAPER_INTERVAL:-90}"      # de quanto em quanto tempo varre (s)
MIN_AGE="${REAPER_MIN_AGE:-60}"        # nao toca em Chromium recem-lancado (s)
MAX_AGE="${REAPER_MAX_AGE:-3600}"      # acima disto, qualquer coisa e considerada travada (s)
SCRAPER_RE='ingestion[./]'             # um processo de ingestao casa isto
CHROME_RE='chrome-headless-shell|ms-playwright'

log() { echo "[reaper $(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

idade() { ps -o etimes= -p "$1" 2>/dev/null | tr -d ' '; }

# Verdadeiro se o processo tiver algum ancestral que seja um scraper de ingestao.
tem_dono_ingestao() {
  local pid="$1" nivel=0 ppid cmd
  while [ "$nivel" -lt 12 ]; do
    ppid="$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')"
    [ -z "$ppid" ] && return 1
    [ "$ppid" -le 1 ] 2>/dev/null && return 1     # chegou no init/fora do namespace: sem dono
    cmd="$(ps -o args= -p "$ppid" 2>/dev/null)"
    case "$cmd" in
      *ingestion/*|*ingestion.*) return 0 ;;
    esac
    pid="$ppid"
    nivel=$((nivel + 1))
  done
  return 1
}

log "guardiao iniciado (intervalo=${INTERVAL}s, idade_min=${MIN_AGE}s, idade_max=${MAX_AGE}s)"

while true; do
  sleep "$INTERVAL"

  mortos_idade=0
  mortos_orfaos=0

  # --- Regra 1: idade. Vale para processos de ingestao E para Chromium. ---
  for pid in $(pgrep -f "$SCRAPER_RE" 2>/dev/null); do
    age="$(idade "$pid")"
    [ -z "$age" ] && continue
    if [ "$age" -ge "$MAX_AGE" ]; then
      cmd="$(ps -o args= -p "$pid" 2>/dev/null | cut -c1-70)"
      log "TRAVADO ha ${age}s -> matando pid=${pid}: ${cmd}"
      kill -9 "$pid" 2>/dev/null && mortos_idade=$((mortos_idade + 1))
    fi
  done

  # --- Regra 2: Chromium sem dono (orfao) ou velho demais. ---
  for pid in $(pgrep -f "$CHROME_RE" 2>/dev/null); do
    age="$(idade "$pid")"
    [ -z "$age" ] && continue
    [ "$age" -lt "$MIN_AGE" ] && continue          # recem-lancado: deixa em paz

    if [ "$age" -ge "$MAX_AGE" ]; then
      kill -9 "$pid" 2>/dev/null && mortos_idade=$((mortos_idade + 1))
    elif ! tem_dono_ingestao "$pid"; then
      kill -9 "$pid" 2>/dev/null && mortos_orfaos=$((mortos_orfaos + 1))
    fi
  done

  # Log SEMPRE -- sem isto e impossivel saber se o guardiao esta funcionando.
  vivos_scraper="$(pgrep -c -f "$SCRAPER_RE" 2>/dev/null || echo 0)"
  vivos_chrome="$(pgrep -c -f "$CHROME_RE" 2>/dev/null || echo 0)"
  log "varredura: scrapers=${vivos_scraper} chromium=${vivos_chrome} mortos_por_idade=${mortos_idade} mortos_orfaos=${mortos_orfaos}"
done
