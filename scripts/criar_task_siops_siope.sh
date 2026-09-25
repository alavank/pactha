#!/usr/bin/env bash
# Cria a Scheduled Task `siops-siope` nos SETE workers (SIOPS, SIOPE e instrumentos
# de planejamento do SUS — `ingestion/siops_siope.py`).
#
# ⚠️ SÓ DEPOIS DO MERGE E DO DEPLOY: a task chama `ingestion/siops_siope.py`, que só
# existe na imagem nova, e grava nas tabelas de `add_siops_siope_rag.sql` (confira
# "Migration OK: add_siops_siope_rag.sql" no log das sete APIs).
#
# POR QUE NOS SETE: a fonte é NACIONAL (todo município ativo com IBGE, por UF).
#
# A AGENDA (INFRA.md §5): dentro da janela 19h-7h BRT, escada de 15 min de 04:00
# (freitas) a 05:30 UTC (juranda). Os quatro hosts (siops-consulta-publica-api,
# siops.datasus.gov.br, fnde.gov.br/olinda-ide e digisusgmp.saude.gov.br) não são
# usados por nenhuma outra task; a escada é para dois tenants não pedirem a mesma
# lista de UF no mesmo minuto. Medido num Postgres local com MG, RS e PR (24/09/2026):
# 1ª rodada 169-244 s (SIOPE é a mais lenta, ~90 s), 2ª rodada 78-84 s — o ano
# anterior completo não é perguntado de novo. Orçamento interno de 1200 s
# (`SIOPS_SIOPE_BUDGET_S`), kill em 1500 s, timeout da task 1620 s.
#
# ⚠️ O COMANDO DA TASK NÃO PODE PASSAR POR INTERPOLAÇÃO (os 25 falso-negativos de
# 08/08/2026): o JSON vai num heredoc com delimitador ENTRE ASPAS SIMPLES.
#
# COMO RODAR:
#     COOLIFY_TOKEN='86|...' bash scripts/criar_task_siops_siope.sh
# (idempotente: pula o worker que já tem a task)

set -u

B="http://54.232.208.118:8000/api/v1"
: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='86|...' antes de rodar}"

criar() {
  local nome="$1" uuid="$2" freq="$3"
  echo "== $nome  ($freq)"
  if curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
       "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"siops-siope"'; then
    echo "   já existe — nada a fazer"; echo; return
  fi
  cat <<'JSON' | sed "s|@@FREQ@@|$freq|" | curl -s --max-time 60 \
      -X POST "$B/applications/$uuid/scheduled-tasks" \
      -H "Authorization: Bearer $COOLIFY_TOKEN" \
      -H "Content-Type: application/json" --data @- | head -c 200
{
  "name": "siops-siope",
  "frequency": "@@FREQ@@",
  "command": "flock -n -E 99 /tmp/siops_siope.lock timeout -k 30 1500 python -u ingestion/siops_siope.py 2>&1; rc=$?; if [ $rc = 99 ]; then rc=0; fi; exit $rc",
  "timeout": 1620
}
JSON
  echo; echo
}

criar "freitas"       "s49c3b58lysqq0tpelneg3g3" "0 4 * * *"
criar "trust"         "xg714h8l7va4ejq70a5pmv5t" "15 4 * * *"
criar "montesiao-mg"  "jhf0kjhps5keujiyhhsnvjt6" "30 4 * * *"
criar "santamaria-rs" "wquremniv57gag3tlil8uf6d" "45 4 * * *"
criar "novapalma-rs"  "kqcnvdsdkgn1efkm4nog8oes" "0 5 * * *"
criar "bgk-rs"        "6xast9rw0wbzbownss9vamfq" "15 5 * * *"
criar "juranda-pr"    "c1spfhxrshagrrvwvhoigip1" "30 5 * * *"

echo "== conferência: 'siops-siope' tem de aparecer nos sete"
for par in "freitas:s49c3b58lysqq0tpelneg3g3" "trust:xg714h8l7va4ejq70a5pmv5t" \
           "montesiao:jhf0kjhps5keujiyhhsnvjt6" "santamaria:wquremniv57gag3tlil8uf6d" \
           "novapalma:kqcnvdsdkgn1efkm4nog8oes" "bgk:6xast9rw0wbzbownss9vamfq" \
           "juranda:c1spfhxrshagrrvwvhoigip1"; do
  nome="${par%%:*}"; uuid="${par##*:}"
  printf '  %-11s ' "$nome"
  curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"siops-siope"' \
    && echo "ok" || echo "FALTANDO"
done
