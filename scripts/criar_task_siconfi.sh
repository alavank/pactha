#!/usr/bin/env bash
# Cria a Scheduled Task `siconfi` nos dois workers gauchos.
#
# POR QUE SO O SICONFI. Das tres fontes que entraram no PR #351:
#   * `siconfi`  -> medido 200 da VPS (174 KB em 227ms). Entra agora.
#   * `tce_rs`   -> 403 do IP da VPS, medido tres vezes. NAO criar enquanto o
#                   bloqueio valer (ver docs/fontes-rs/OFICIO-TCE-RS.md).
#   * `obrasgov` -> 429 na primeira requisicao, causa ainda indefinida. Rodar
#                   antes o `scripts/medir_obrasgov_vps.sh`.
#
# ⚠️ O COMANDO DA TASK NAO PODE PASSAR POR INTERPOLACAO. O `$rc` e o `$?` viram
# lixo se algum shell os expandir antes de chegar ao Coolify — foi a causa dos
# 25 falso-negativos de 08/08/2026 (INFRA.md §5). Por isso o JSON vai num
# heredoc com delimitador ENTRE ASPAS SIMPLES (<<'JSON'), que desliga a
# expansao; so a frequencia entra depois, por `sed`, que nao toca no resto.
#
# COMO RODAR (de casa; o `!` do Claude Code serve):
#     COOLIFY_TOKEN='86|...' bash scripts/criar_task_siconfi.sh
#
# O token NAO fica no arquivo de proposito — ele e segredo e este script e
# versionado.

set -u

B="http://54.232.208.118:8000/api/v1"
: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='86|...' antes de rodar}"

# Janela das 2h UTC (23h de Brasilia): livre nos dois workers hoje. Nova Palma
# fica 30 min a frente, seguindo o escalonamento que os outros crons ja usam —
# os dois rodam no MESMO host, de CPU compartilhada.
criar() {
  local nome="$1" uuid="$2" freq="$3"
  echo "== $nome  ($freq)"
  cat <<'JSON' | sed "s|@@FREQ@@|$freq|" | curl -s --max-time 60 \
      -X POST "$B/applications/$uuid/scheduled-tasks" \
      -H "Authorization: Bearer $COOLIFY_TOKEN" \
      -H "Content-Type: application/json" --data @- | head -c 300
{
  "name": "siconfi",
  "frequency": "@@FREQ@@",
  "command": "flock -n -E 99 /tmp/siconfi.lock timeout -k 30 900 python -u ingestion/siconfi.py 2>&1; rc=$?; if [ $rc = 99 ]; then rc=0; fi; exit $rc",
  "timeout": 1020
}
JSON
  echo; echo
}

criar "santamaria-rs" "wquremniv57gag3tlil8uf6d" "0 2 * * *"
criar "novapalma-rs"  "kqcnvdsdkgn1efkm4nog8oes" "30 2 * * *"

echo "== conferencia: 'siconfi' tem de aparecer nas duas listas"
for par in "santamaria:wquremniv57gag3tlil8uf6d" "novapalma:kqcnvdsdkgn1efkm4nog8oes"; do
  nome="${par%%:*}"; uuid="${par##*:}"
  printf '  %s: ' "$nome"
  curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$B/applications/$uuid/scheduled-tasks" \
    | tr ',' '\n' | grep -i '"name"' | tr '\n' ' '
  echo
done
