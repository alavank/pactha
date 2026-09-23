#!/usr/bin/env bash
# Cria a Scheduled Task `cgu-convenios` nos SETE workers (a fonte é federal).
#
# ⚠️ SÓ DEPOIS DO MERGE E DO DEPLOY: a task chama `ingestion/cgu_convenios.py`, que
# só existe na imagem nova, e grava nas tabelas de `add_cgu_convenios.sql`.
#
# A AGENDA (INFRA.md §5): dentro da janela 19h-7h BRT, em escada de 5 min (07:00 a
# 07:30 UTC = 04:00 a 04:30 BRT). Cada rodada baixa a planilha da CGU (67 MB) e o
# `siconv_convenio.zip` do TransfereGov (18 MB) e lê em ~20 s; a planilha da CGU
# muda poucas vezes por mês, e a rodada que acha o MESMO arquivo em todos os
# municípios não baixa nada (0 s). A escada é pelo host de download, que os sete
# dividem pelo mesmo IP.
#
# ⚠️ O COMANDO DA TASK NÃO PODE PASSAR POR INTERPOLAÇÃO (os 25 falso-negativos de
# 08/08/2026): o JSON vai num heredoc com delimitador ENTRE ASPAS SIMPLES.
#
# COMO RODAR:
#     COOLIFY_TOKEN='86|...' bash scripts/criar_task_cgu_convenios.sh
# (idempotente: pula o worker que já tem a task)

set -u

B="http://54.232.208.118:8000/api/v1"
: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='86|...' antes de rodar}"

criar() {
  local nome="$1" uuid="$2" freq="$3"
  echo "== $nome  ($freq)"
  if curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
       "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"cgu-convenios"'; then
    echo "   já existe — nada a fazer"; echo; return
  fi
  cat <<'JSON' | sed "s|@@FREQ@@|$freq|" | curl -s --max-time 60 \
      -X POST "$B/applications/$uuid/scheduled-tasks" \
      -H "Authorization: Bearer $COOLIFY_TOKEN" \
      -H "Content-Type: application/json" --data @- | head -c 200
{
  "name": "cgu-convenios",
  "frequency": "@@FREQ@@",
  "command": "flock -n -E 99 /tmp/cgu_convenios.lock timeout -k 30 900 python -u ingestion/cgu_convenios.py 2>&1; rc=$?; if [ $rc = 99 ]; then rc=0; fi; exit $rc",
  "timeout": 1020
}
JSON
  echo; echo
}

criar "freitas"       "s49c3b58lysqq0tpelneg3g3" "0 7 * * *"
criar "trust"         "xg714h8l7va4ejq70a5pmv5t" "5 7 * * *"
criar "montesiao-mg"  "jhf0kjhps5keujiyhhsnvjt6" "10 7 * * *"
criar "santamaria-rs" "wquremniv57gag3tlil8uf6d" "15 7 * * *"
criar "novapalma-rs"  "kqcnvdsdkgn1efkm4nog8oes" "20 7 * * *"
criar "bgk-rs"        "6xast9rw0wbzbownss9vamfq" "25 7 * * *"
criar "juranda-pr"    "c1spfhxrshagrrvwvhoigip1" "30 7 * * *"

echo "== conferência: 'cgu-convenios' tem de aparecer nos sete"
for par in "freitas:s49c3b58lysqq0tpelneg3g3" "trust:xg714h8l7va4ejq70a5pmv5t" \
           "montesiao:jhf0kjhps5keujiyhhsnvjt6" "santamaria:wquremniv57gag3tlil8uf6d" \
           "novapalma:kqcnvdsdkgn1efkm4nog8oes" "bgk:6xast9rw0wbzbownss9vamfq" \
           "juranda:c1spfhxrshagrrvwvhoigip1"; do
  nome="${par%%:*}"; uuid="${par##*:}"
  printf '  %-11s ' "$nome"
  curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"cgu-convenios"' \
    && echo "ok" || echo "FALTANDO"
done
