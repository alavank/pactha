#!/usr/bin/env bash
# Cria a Scheduled Task `emendas-mg` nos SETE workers (planilha oficial de emendas
# da SEGOV-MG, `ingestion/emendas_mg.py`).
#
# ⚠️ SÓ DEPOIS DO MERGE E DO DEPLOY: a task chama `ingestion/emendas_mg.py`, que só
# existe na imagem nova, e grava nas colunas/tabela de
# `add_emendas_estaduais_execucao.sql` (confira "Migration OK" no log das APIs).
#
# POR QUE NOS SETE, se só MG grava: onde não há município de MG o coletor sai antes
# de baixar qualquer coisa (`success`, 0), e o cliente que ganhar um município
# mineiro amanhã já está coberto.
#
# A AGENDA (INFRA.md §5): dentro da janela 19h-7h BRT, escada de 10 min de 07:40
# (freitas) a 08:40 UTC (juranda). Cada rodada de tenant mineiro baixa os dois
# xlsx (~14 MB) do mesmo host da SEGOV e lê em ~1 min; a escada é pelo host.
#
# ⚠️ O COMANDO DA TASK NÃO PODE PASSAR POR INTERPOLAÇÃO (os 25 falso-negativos de
# 08/08/2026): o JSON vai num heredoc com delimitador ENTRE ASPAS SIMPLES.
#
# COMO RODAR:
#     COOLIFY_TOKEN='86|...' bash scripts/criar_task_emendas_mg.sh
# (idempotente: pula o worker que já tem a task)

set -u

B="http://54.232.208.118:8000/api/v1"
: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='86|...' antes de rodar}"

criar() {
  local nome="$1" uuid="$2" freq="$3"
  echo "== $nome  ($freq)"
  if curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
       "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"emendas-mg"'; then
    echo "   já existe — nada a fazer"; echo; return
  fi
  cat <<'JSON' | sed "s|@@FREQ@@|$freq|" | curl -s --max-time 60 \
      -X POST "$B/applications/$uuid/scheduled-tasks" \
      -H "Authorization: Bearer $COOLIFY_TOKEN" \
      -H "Content-Type: application/json" --data @- | head -c 200
{
  "name": "emendas-mg",
  "frequency": "@@FREQ@@",
  "command": "flock -n -E 99 /tmp/emendas_mg.lock timeout -k 30 900 python -u ingestion/emendas_mg.py 2>&1; rc=$?; if [ $rc = 99 ]; then rc=0; fi; exit $rc",
  "timeout": 1020
}
JSON
  echo; echo
}

criar "freitas"       "s49c3b58lysqq0tpelneg3g3" "40 7 * * *"
criar "trust"         "xg714h8l7va4ejq70a5pmv5t" "50 7 * * *"
criar "montesiao-mg"  "jhf0kjhps5keujiyhhsnvjt6" "0 8 * * *"
criar "santamaria-rs" "wquremniv57gag3tlil8uf6d" "10 8 * * *"
criar "novapalma-rs"  "kqcnvdsdkgn1efkm4nog8oes" "20 8 * * *"
criar "bgk-rs"        "6xast9rw0wbzbownss9vamfq" "30 8 * * *"
criar "juranda-pr"    "c1spfhxrshagrrvwvhoigip1" "40 8 * * *"

echo "== conferência: 'emendas-mg' tem de aparecer nos sete"
for par in "freitas:s49c3b58lysqq0tpelneg3g3" "trust:xg714h8l7va4ejq70a5pmv5t" \
           "montesiao:jhf0kjhps5keujiyhhsnvjt6" "santamaria:wquremniv57gag3tlil8uf6d" \
           "novapalma:kqcnvdsdkgn1efkm4nog8oes" "bgk:6xast9rw0wbzbownss9vamfq" \
           "juranda:c1spfhxrshagrrvwvhoigip1"; do
  nome="${par%%:*}"; uuid="${par##*:}"
  printf '  %-11s ' "$nome"
  curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"emendas-mg"' \
    && echo "ok" || echo "FALTANDO"
done
