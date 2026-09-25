#!/usr/bin/env bash
# Cria a Scheduled Task `cgu-transferencias` nos SETE workers (recursos recebidos por
# pasta, `ingestion/cgu_transferencias.py` — a fonte é federal).
#
# ⚠️ SÓ DEPOIS DO MERGE E DO DEPLOY: a task chama `ingestion/cgu_transferencias.py`,
# que só existe na imagem nova, e grava nas tabelas de `add_cgu_transferencias.sql`
# (confira "Migration OK: add_cgu_transferencias.sql" no log das sete APIs).
#
# A AGENDA (INFRA.md §5): dentro da janela 19h-7h BRT, escada de 10 min de 01:00
# (freitas) a 02:00 UTC (juranda) = 22:00 a 23:00 BRT. Fora das duas outras tasks que
# baixam do MESMO host da CGU (`dadosabertos-download.cgu.gov.br`): a
# `portal-transparencia` (03:45 em diante, pelo CONTINUAR) e a `cgu-convenios`
# (07:00-07:30). A fonte de verdade dos horários é o Coolify: confira a coluna de
# cada worker (`python scripts/agenda_noturna.py`) antes de rodar.
#
# ⛔ POR QUE A ESCADA É LARGA: esse host tem WAF (AWS) que passa a responder 405 com
# CAPTCHA depois de muitos downloads seguidos (medido em 24/09/2026: ~30 arquivos em
# 25 min, 24 deles num minuto). Um bloqueio do IP da VPS derrubaria as TRÊS fontes da
# CGU nos sete tenants. Cada rodada baixa no máximo 6 arquivos (o mês corrente, o
# anterior e até 4 da carga inicial — CGU_TRANSF_CARGA_POR_RODADA), com 30 s entre
# eles (CGU_TRANSF_PAUSA_S): ~3,5 min por tenant, e nunca dois tenants juntos. Os 24
# meses da carga inicial entram em ~6 noites. Depois disso são 2 arquivos por tenant.
#
# Orçamento interno de 600 s (CGU_TRANSF_BUDGET_S), kill em 900 s, timeout da task
# 1020 s (kill + 120 — a regra de ouro das margens).
#
# ⚠️ O COMANDO DA TASK NÃO PODE PASSAR POR INTERPOLAÇÃO (os 25 falso-negativos de
# 08/08/2026): o JSON vai num heredoc com delimitador ENTRE ASPAS SIMPLES.
#
# COMO RODAR:
#     COOLIFY_TOKEN='86|...' bash scripts/criar_task_cgu_transferencias.sh
# (idempotente: pula o worker que já tem a task)

set -u

B="http://54.232.208.118:8000/api/v1"
: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='86|...' antes de rodar}"

criar() {
  local nome="$1" uuid="$2" freq="$3"
  echo "== $nome  ($freq)"
  if curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
       "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"cgu-transferencias"'; then
    echo "   já existe — nada a fazer"; echo; return
  fi
  cat <<'JSON' | sed "s|@@FREQ@@|$freq|" | curl -s --max-time 60 \
      -X POST "$B/applications/$uuid/scheduled-tasks" \
      -H "Authorization: Bearer $COOLIFY_TOKEN" \
      -H "Content-Type: application/json" --data @- | head -c 200
{
  "name": "cgu-transferencias",
  "frequency": "@@FREQ@@",
  "command": "flock -n -E 99 /tmp/cgu_transferencias.lock timeout -k 30 900 python -u ingestion/cgu_transferencias.py 2>&1; rc=$?; if [ $rc = 99 ]; then rc=0; fi; exit $rc",
  "timeout": 1020
}
JSON
  echo; echo
}

criar "freitas"       "s49c3b58lysqq0tpelneg3g3" "0 1 * * *"
criar "trust"         "xg714h8l7va4ejq70a5pmv5t" "10 1 * * *"
criar "montesiao-mg"  "jhf0kjhps5keujiyhhsnvjt6" "20 1 * * *"
criar "santamaria-rs" "wquremniv57gag3tlil8uf6d" "30 1 * * *"
criar "novapalma-rs"  "kqcnvdsdkgn1efkm4nog8oes" "40 1 * * *"
criar "bgk-rs"        "6xast9rw0wbzbownss9vamfq" "50 1 * * *"
criar "juranda-pr"    "c1spfhxrshagrrvwvhoigip1" "0 2 * * *"

echo "== conferência: 'cgu-transferencias' tem de aparecer nos sete"
for par in "freitas:s49c3b58lysqq0tpelneg3g3" "trust:xg714h8l7va4ejq70a5pmv5t" \
           "montesiao:jhf0kjhps5keujiyhhsnvjt6" "santamaria:wquremniv57gag3tlil8uf6d" \
           "novapalma:kqcnvdsdkgn1efkm4nog8oes" "bgk:6xast9rw0wbzbownss9vamfq" \
           "juranda:c1spfhxrshagrrvwvhoigip1"; do
  nome="${par%%:*}"; uuid="${par##*:}"
  printf '  %-11s ' "$nome"
  curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"cgu-transferencias"' \
    && echo "ok" || echo "FALTANDO"
done
