#!/usr/bin/env bash
# Cria a Scheduled Task `fns-saldo` nos SETE workers (a fonte é federal): o saldo
# das contas do Fundo Municipal de Saúde, pelo arquivo anual do Portal FNS
# (`ingestion/fns_saldo.py`).
#
# ⚠️ SÓ DEPOIS DO MERGE E DO DEPLOY: a task chama `ingestion/fns_saldo.py`, que só
# existe na imagem nova, e grava em `fns_saldo_conta` (`add_fns_saldo_conta.sql`).
#
# A AGENDA (INFRA.md §5): dentro da janela 19h-7h BRT, escada de 5 min de 06:00
# (freitas) a 06:30 UTC (juranda). Quase toda rodada é UM GET da página de
# downloads (~125 KB) e sai com "já carregado"; o arquivo (~16 MB) só é baixado
# quando o FNS publica o ano novo (1x/ano, em janeiro) ou entra município novo.
#
# ⚠️ O COMANDO DA TASK NÃO PODE PASSAR POR INTERPOLAÇÃO (os 25 falso-negativos de
# 08/08/2026): o JSON vai num heredoc com delimitador ENTRE ASPAS SIMPLES.
#
# COMO RODAR:
#     COOLIFY_TOKEN='86|...' bash scripts/criar_task_fns_saldo.sh
# (idempotente: pula o worker que já tem a task)

set -u

B="http://54.232.208.118:8000/api/v1"
: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='86|...' antes de rodar}"

criar() {
  local nome="$1" uuid="$2" freq="$3"
  echo "== $nome  ($freq)"
  if curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
       "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"fns-saldo"'; then
    echo "   já existe — nada a fazer"; echo; return
  fi
  cat <<'JSON' | sed "s|@@FREQ@@|$freq|" | curl -s --max-time 60 \
      -X POST "$B/applications/$uuid/scheduled-tasks" \
      -H "Authorization: Bearer $COOLIFY_TOKEN" \
      -H "Content-Type: application/json" --data @- | head -c 200
{
  "name": "fns-saldo",
  "frequency": "@@FREQ@@",
  "command": "flock -n -E 99 /tmp/fns_saldo.lock timeout -k 30 900 python -u ingestion/fns_saldo.py 2>&1; rc=$?; if [ $rc = 99 ]; then rc=0; fi; exit $rc",
  "timeout": 1020
}
JSON
  echo; echo
}

criar "freitas"       "s49c3b58lysqq0tpelneg3g3" "0 6 * * *"
criar "trust"         "xg714h8l7va4ejq70a5pmv5t" "5 6 * * *"
criar "montesiao-mg"  "jhf0kjhps5keujiyhhsnvjt6" "10 6 * * *"
criar "santamaria-rs" "wquremniv57gag3tlil8uf6d" "15 6 * * *"
criar "novapalma-rs"  "kqcnvdsdkgn1efkm4nog8oes" "20 6 * * *"
criar "bgk-rs"        "6xast9rw0wbzbownss9vamfq" "25 6 * * *"
criar "juranda-pr"    "c1spfhxrshagrrvwvhoigip1" "30 6 * * *"

echo "== conferência: 'fns-saldo' tem de aparecer nos sete"
for par in "freitas:s49c3b58lysqq0tpelneg3g3" "trust:xg714h8l7va4ejq70a5pmv5t" \
           "montesiao:jhf0kjhps5keujiyhhsnvjt6" "santamaria:wquremniv57gag3tlil8uf6d" \
           "novapalma:kqcnvdsdkgn1efkm4nog8oes" "bgk:6xast9rw0wbzbownss9vamfq" \
           "juranda:c1spfhxrshagrrvwvhoigip1"; do
  nome="${par%%:*}"; uuid="${par##*:}"
  printf '  %-11s ' "$nome"
  curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"fns-saldo"' \
    && echo "ok" || echo "FALTANDO"
done
