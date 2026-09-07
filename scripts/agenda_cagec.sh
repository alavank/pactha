#!/usr/bin/env bash
# Reagenda a Scheduled Task `cagec` nos tres workers que tem municipio de MG.
#
# ⚠️ POR QUE ISTO EXISTE — dois defeitos medidos em 07/09/2026, os dois de
# AGENDAMENTO, nenhum do coletor:
#
#   1. **O portal do CAGEC nao emite CRC de madrugada.** As tres tasks estavam
#      as 06:15/07:00/07:15 UTC — 03h15/04h/04h15 de Brasilia. Medido no mesmo
#      dia: as 06:15 UTC toda emissao voltou "Nao foi possivel recuperar dados
#      do Convenente/Parceiro para geracao do relatorio"; as 17:58 UTC (14h58
#      BRT) o MESMO coletor, no MESMO worker, leu as 27 obrigacoes do CRC em
#      34s. Resultado do horario errado: a situacao (Regular/Irregular) ate
#      atualizava, mas o DETALHAMENTO ficou congelado em 02-03/09 nos tres
#      tenants, e a tela seguiu mostrando obrigacao vencida que ja podia ter
#      sido renovada. Mesma licao do `fpe-rs` (INFRA.md §5): fonte com janela
#      de funcionamento e restricao de AGENDAMENTO, nao bug de coletor.
#
#   2. **Uma rodada por dia com lote de 11 = ciclo de 4 dias na Freitas.** O
#      lote 11 esta no codigo (`CAGEC_LOTE_MUNICIPIOS`, cagec_scraper.py) e foi
#      dimensionado para QUATRO rodadas diarias: ceil(44/4). Com a task em
#      `15 6 * * *` a carteira de 42 municipios levava 4 dias para dar a volta —
#      em 07/09 havia 31 municipios com mais de 48h e dois nunca coletados.
#
# Volta para as QUATRO janelas comerciais que o `docs/CRON_SETUP.md` sempre
# documentou (10/15/19/23 UTC = 07h/12h/16h/20h BRT) e sobe o kill interno da
# Freitas de 1020s para 1800s — com 1020s a rodada morria no meio (exit 124,
# EPIPE do Playwright) e, como o `ingestion_log` so e escrito no fim, a falha
# nao aparecia em lugar nenhum: o selo de frescor continuava calado.
#
# Trust (7 municipios de MG) e Monte Siao (1) cabem inteiros em uma rodada;
# ganham DUAS janelas so para ter segunda chance quando o portal recusar o CRC.
# Os minutos seguem o escalonamento ja documentado (freitas :00, montesiao :46,
# trust :48) — os tres workers dividem 0,6 vCPU sustentado.
#
# COMO RODAR (o `!` do Claude Code serve):
#     COOLIFY_TOKEN='95|...' bash scripts/agenda_cagec.sh
#
# ⚠️ O COMANDO DA TASK NAO PODE PASSAR POR INTERPOLACAO DE SHELL: `$rc` e `$?`
# viram lixo se algum shell os expandir antes de chegar ao Coolify (INFRA.md §5,
# os 25 falso-negativos de 08/08). Por isso o JSON vai em heredoc com
# delimitador ENTRE ASPAS SIMPLES e so os campos variaveis entram por `sed`.
#
# O token NAO fica no arquivo de proposito — e segredo, e este script e versionado.

set -u

B="http://54.232.208.118:8000/api/v1"
: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='95|...' antes de rodar}"

# worker uuid | uuid da task cagec | frequencia nova | kill interno (segundos)
reagendar() {
  local nome="$1" app="$2" task="$3" freq="$4" kill_s="$5"
  echo "== $nome  ->  $freq  (timeout -k 30 $kill_s)"
  cat <<'JSON' | sed -e "s|@@FREQ@@|$freq|" -e "s|@@KILL@@|$kill_s|" \
    | curl -s --max-time 60 -X PATCH \
        "$B/applications/$app/scheduled-tasks/$task" \
        -H "Authorization: Bearer $COOLIFY_TOKEN" \
        -H "Content-Type: application/json" --data @- | head -c 400
{
  "name": "cagec",
  "frequency": "@@FREQ@@",
  "command": "flock -n -E 99 /tmp/scraper.lock timeout -k 30 @@KILL@@ python -u ingestion/cagec_scraper.py 2>&1; rc=$?; if [ $rc = 99 ]; then rc=0; fi; exit $rc"
}
JSON
  echo; echo
}

# Freitas: 42 municipios de MG, lote 11 -> as QUATRO janelas sao o que fecha o
# ciclo em 24h. Kill de 1800s = 3x a rodada medida (11 municipios em ~9 min com
# o CRC saindo), e o teto da task (3420s) ja cobre 1800+120.
reagendar "freitas"   "s49c3b58lysqq0tpelneg3g3" "qmkyzs8fk6nttjj3omkrtq87" "0 10,15,19,23 * * *"  "1800"
# Monte Siao: 1 municipio (~1 min). Duas janelas = segunda chance no CRC.
reagendar "montesiao" "jhf0kjhps5keujiyhhsnvjt6" "ujutkajcur5etfu5d4c4znx9" "46 10,19 * * *"       "600"
# Trust: 7 municipios de MG (~6 min); o lote de 11 cobre a carteira inteira.
reagendar "trust"     "xg714h8l7va4ejq70a5pmv5t" "pkutg37e93x9nuxfhjmyxvfw" "48 10,19 * * *"       "900"

echo "== conferencia (frequencia e kill interno que ficaram valendo)"
for par in "freitas:s49c3b58lysqq0tpelneg3g3" \
           "montesiao:jhf0kjhps5keujiyhhsnvjt6" \
           "trust:xg714h8l7va4ejq70a5pmv5t"; do
  nome="${par%%:*}"; uuid="${par##*:}"
  printf '  %-10s ' "$nome"
  curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$B/applications/$uuid/scheduled-tasks" \
    | python -c '
import json, re, sys
for t in json.load(sys.stdin):
    if t.get("name") != "cagec":
        continue
    kill = re.search(r"timeout -k 30 (\d+)", t.get("command") or "")
    print(str(t.get("frequency")), " kill=" + (kill.group(1) if kill else "?") + "s",
          " task_timeout=" + str(t.get("timeout")))
'
done

echo
echo "Se algum PATCH voltar 404/405, esta versao do Coolify nao expoe o verbo:"
echo "ajuste os tres campos pela UI (Worker > Scheduled Tasks) com os valores acima."
