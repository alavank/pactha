#!/usr/bin/env bash
# Cria a Scheduled Task `fes-rs` nos SETE workers: os pagamentos do Fundo Estadual
# de Saúde do RS (SES-RS) ao fundo municipal e aos hospitais
# (`ingestion/fes_rs.py`).
#
# ⚠️ SÓ DEPOIS DO MERGE E DO DEPLOY: a task chama `ingestion/fes_rs.py`, que só
# existe na imagem nova, e grava em `fes_rs_pagamentos`/`fes_rs_arquivos`
# (`add_fes_rs_pagamentos.sql` — confira "Migration OK" no log das APIs).
#
# POR QUE NOS SETE, se só o RS grava: onde não há município do RS o coletor sai
# antes de baixar qualquer coisa (`success`, 0), e o cliente que ganhar um
# município gaúcho amanhã já está coberto.
#
# A AGENDA (INFRA.md §5): dentro da janela 19h-7h BRT, escada de 5 min de 05:00
# (freitas) a 05:30 UTC (juranda). Nos três tenants gaúchos a rodada baixa as
# planilhas do ano (~5 MB cada, ~20 s no total) do mesmo host da SES — a escada é
# pelo host; as que vierem iguais (hash) não são relidas. A SES publica às ~07:40
# BRT (10:40 UTC), então a rodada da madrugada pega a planilha da manhã anterior.
#
# ⚠️ O COMANDO DA TASK NÃO PODE PASSAR POR INTERPOLAÇÃO (os 25 falso-negativos de
# 08/08/2026): o JSON vai num heredoc com delimitador ENTRE ASPAS SIMPLES.
#
# COMO RODAR:
#     COOLIFY_TOKEN='86|...' bash scripts/criar_task_fes_rs.sh
# (idempotente: pula o worker que já tem a task)

set -u

B="http://54.232.208.118:8000/api/v1"
: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='86|...' antes de rodar}"

criar() {
  local nome="$1" uuid="$2" freq="$3"
  echo "== $nome  ($freq)"
  if curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
       "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"fes-rs"'; then
    echo "   já existe — nada a fazer"; echo; return
  fi
  cat <<'JSON' | sed "s|@@FREQ@@|$freq|" | curl -s --max-time 60 \
      -X POST "$B/applications/$uuid/scheduled-tasks" \
      -H "Authorization: Bearer $COOLIFY_TOKEN" \
      -H "Content-Type: application/json" --data @- | head -c 200
{
  "name": "fes-rs",
  "frequency": "@@FREQ@@",
  "command": "flock -n -E 99 /tmp/fes_rs.lock timeout -k 30 900 python -u ingestion/fes_rs.py 2>&1; rc=$?; if [ $rc = 99 ]; then rc=0; fi; exit $rc",
  "timeout": 1020
}
JSON
  echo; echo
}

criar "freitas"       "s49c3b58lysqq0tpelneg3g3" "0 5 * * *"
criar "trust"         "xg714h8l7va4ejq70a5pmv5t" "5 5 * * *"
criar "montesiao-mg"  "jhf0kjhps5keujiyhhsnvjt6" "10 5 * * *"
criar "santamaria-rs" "wquremniv57gag3tlil8uf6d" "15 5 * * *"
criar "novapalma-rs"  "kqcnvdsdkgn1efkm4nog8oes" "20 5 * * *"
criar "bgk-rs"        "6xast9rw0wbzbownss9vamfq" "25 5 * * *"
criar "juranda-pr"    "c1spfhxrshagrrvwvhoigip1" "30 5 * * *"

echo "== conferência: 'fes-rs' tem de aparecer nos sete"
for par in "freitas:s49c3b58lysqq0tpelneg3g3" "trust:xg714h8l7va4ejq70a5pmv5t" \
           "montesiao:jhf0kjhps5keujiyhhsnvjt6" "santamaria:wquremniv57gag3tlil8uf6d" \
           "novapalma:kqcnvdsdkgn1efkm4nog8oes" "bgk:6xast9rw0wbzbownss9vamfq" \
           "juranda:c1spfhxrshagrrvwvhoigip1"; do
  nome="${par%%:*}"; uuid="${par##*:}"
  printf '  %-11s ' "$nome"
  curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"fes-rs"' \
    && echo "ok" || echo "FALTANDO"
done
