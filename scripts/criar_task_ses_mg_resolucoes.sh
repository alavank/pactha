#!/usr/bin/env bash
# Cria a Scheduled Task `ses-mg-resolucoes` nos SETE workers (pagamentos da SES-MG
# por Resolução SES — o fundo a fundo estadual da saúde de MG,
# `ingestion/ses_mg_resolucoes.py`).
#
# ⚠️ SÓ DEPOIS DO MERGE E DO DEPLOY: a task chama `ingestion/ses_mg_resolucoes.py`,
# que só existe na imagem nova, e grava nas tabelas de `add_ses_mg_resolucoes.sql`
# (confira "Migration OK: add_ses_mg_resolucoes.sql" no log das sete APIs).
#
# POR QUE NOS SETE, se só MG grava: onde não há município de MG o coletor sai antes
# de abrir o painel (`success`, 0), e o cliente que ganhar um município mineiro
# amanhã já está coberto.
#
# A AGENDA (INFRA.md §5; dentro da janela 22:00–10:00 UTC, sem atravessar 00:00):
# escada de 30 min entre os três tenants de MG — o painel é UM host da SES-MG e a
# escada é por ele — e os quatro sem MG ANTES deles (saem em segundos):
#   santamaria 22:00 · novapalma 22:05 · bgk 22:10 · juranda 22:15 · freitas 22:30
#   · trust 23:00 · montesiao 23:30 (UTC). ⚠️ Os sem MG em 23:35-23:50 atravessavam
#   00:00 com o kill de 1500 s, e a auditoria da agenda reprovava (25/09/2026).
# Custo medido (24/09/2026, do PC): ~1,5 s por consulta com a pausa de 1 s; 4 POSTs
# por município (orçamentário e restos do ano + um ano de histórico). Freitas (42
# municípios) ≈ 5 min. Orçamento interno de 20 min (SES_MG_BUDGET_S=1200), kill em
# 1500 s (≤ 22:55 na freitas), timeout da task 1620 s = kill + 120. O painel
# atualiza às 07:00 BRT (10:00 UTC): a rodada da noite lê o dado daquela manhã.
#
# ⚠️ O COMANDO DA TASK NÃO PODE PASSAR POR INTERPOLAÇÃO (os 25 falso-negativos de
# 08/08/2026): o JSON vai num heredoc com delimitador ENTRE ASPAS SIMPLES.
#
# COMO RODAR:
#     COOLIFY_TOKEN='86|...' bash scripts/criar_task_ses_mg_resolucoes.sh
# (idempotente: pula o worker que já tem a task)

set -u

B="http://54.232.208.118:8000/api/v1"
: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='86|...' antes de rodar}"

criar() {
  local nome="$1" uuid="$2" freq="$3"
  echo "== $nome  ($freq)"
  if curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
       "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"ses-mg-resolucoes"'; then
    echo "   já existe — nada a fazer"; echo; return
  fi
  cat <<'JSON' | sed "s|@@FREQ@@|$freq|" | curl -s --max-time 60 \
      -X POST "$B/applications/$uuid/scheduled-tasks" \
      -H "Authorization: Bearer $COOLIFY_TOKEN" \
      -H "Content-Type: application/json" --data @- | head -c 200
{
  "name": "ses-mg-resolucoes",
  "frequency": "@@FREQ@@",
  "command": "flock -n -E 99 /tmp/ses_mg_resolucoes.lock timeout -k 30 1500 env SES_MG_BUDGET_S=1200 python -u ingestion/ses_mg_resolucoes.py 2>&1; rc=$?; if [ $rc = 99 ]; then rc=0; fi; exit $rc",
  "timeout": 1620
}
JSON
  echo; echo
}

criar "freitas"       "s49c3b58lysqq0tpelneg3g3" "30 22 * * *"
criar "trust"         "xg714h8l7va4ejq70a5pmv5t" "0 23 * * *"
criar "montesiao-mg"  "jhf0kjhps5keujiyhhsnvjt6" "30 23 * * *"
criar "santamaria-rs" "wquremniv57gag3tlil8uf6d" "0 22 * * *"
criar "novapalma-rs"  "kqcnvdsdkgn1efkm4nog8oes" "5 22 * * *"
criar "bgk-rs"        "6xast9rw0wbzbownss9vamfq" "10 22 * * *"
criar "juranda-pr"    "c1spfhxrshagrrvwvhoigip1" "15 22 * * *"

echo "== conferência: 'ses-mg-resolucoes' tem de aparecer nos sete"
for par in "freitas:s49c3b58lysqq0tpelneg3g3" "trust:xg714h8l7va4ejq70a5pmv5t" \
           "montesiao:jhf0kjhps5keujiyhhsnvjt6" "santamaria:wquremniv57gag3tlil8uf6d" \
           "novapalma:kqcnvdsdkgn1efkm4nog8oes" "bgk:6xast9rw0wbzbownss9vamfq" \
           "juranda:c1spfhxrshagrrvwvhoigip1"; do
  nome="${par%%:*}"; uuid="${par##*:}"
  printf '  %-11s ' "$nome"
  curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"ses-mg-resolucoes"' \
    && echo "ok" || echo "FALTANDO"
done
