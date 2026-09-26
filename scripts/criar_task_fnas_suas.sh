#!/usr/bin/env bash
# Cria a Scheduled Task `fnas-suas` nos SETE workers (a fonte é federal): o saldo de
# cada conta do fundo municipal de assistência social mês a mês, os repasses do FNAS
# e as emendas, pelo painel do MDS (`ingestion/fnas_suas.py`).
#
# ⚠️ SÓ DEPOIS DO MERGE E DO DEPLOY: a task chama `ingestion/fnas_suas.py`, que só
# existe na imagem nova, e grava nas tabelas de `add_fnas_suas.sql` (confira
# "Migration OK: add_fnas_suas.sql" no log das sete APIs).
#
# A AGENDA (INFRA.md §5): dentro da janela 19h-7h BRT, escada de 5 min de 02:10
# (freitas) a 02:40 UTC (juranda). Nenhuma outra task usa `paineis.mds.gov.br`.
# CUSTO MEDIDO (26/09/2026, Postgres local + painel real, Monte Sião e Nova Palma):
# 1ª rodada (histórico desde 2007) ~8 s de painel para os dois municípios, 6.350
# linhas; as seguintes (janela do ano passado para cá) ~4 s. Um cubo por app com
# TODOS os municípios do tenant — a freitas (44) é o pior caso, bem dentro do kill
# de 600 s.
#
# ⚠️ O COMANDO DA TASK NÃO PODE PASSAR POR INTERPOLAÇÃO (os 25 falso-negativos de
# 08/08/2026): o JSON vai num heredoc com delimitador ENTRE ASPAS SIMPLES.
#
# COMO RODAR:
#     COOLIFY_TOKEN='86|...' bash scripts/criar_task_fnas_suas.sh
# (idempotente: pula o worker que já tem a task)

set -u

B="http://54.232.208.118:8000/api/v1"
: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='86|...' antes de rodar}"

criar() {
  local nome="$1" uuid="$2" freq="$3"
  echo "== $nome  ($freq)"
  if curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
       "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"fnas-suas"'; then
    echo "   já existe — nada a fazer"; echo; return
  fi
  cat <<'JSON' | sed "s|@@FREQ@@|$freq|" | curl -s --max-time 60 \
      -X POST "$B/applications/$uuid/scheduled-tasks" \
      -H "Authorization: Bearer $COOLIFY_TOKEN" \
      -H "Content-Type: application/json" --data @- | head -c 200
{
  "name": "fnas-suas",
  "frequency": "@@FREQ@@",
  "command": "flock -n -E 99 /tmp/fnas_suas.lock timeout -k 30 600 python -u ingestion/fnas_suas.py 2>&1; rc=$?; if [ $rc = 99 ]; then rc=0; fi; exit $rc",
  "timeout": 720
}
JSON
  echo; echo
}

criar "freitas"       "s49c3b58lysqq0tpelneg3g3" "10 2 * * *"
criar "trust"         "xg714h8l7va4ejq70a5pmv5t" "15 2 * * *"
criar "montesiao-mg"  "jhf0kjhps5keujiyhhsnvjt6" "20 2 * * *"
criar "santamaria-rs" "wquremniv57gag3tlil8uf6d" "25 2 * * *"
criar "novapalma-rs"  "kqcnvdsdkgn1efkm4nog8oes" "30 2 * * *"
criar "bgk-rs"        "6xast9rw0wbzbownss9vamfq" "35 2 * * *"
criar "juranda-pr"    "c1spfhxrshagrrvwvhoigip1" "40 2 * * *"

echo "== conferência: 'fnas-suas' tem de aparecer nos sete"
for par in "freitas:s49c3b58lysqq0tpelneg3g3" "trust:xg714h8l7va4ejq70a5pmv5t" \
           "montesiao:jhf0kjhps5keujiyhhsnvjt6" "santamaria:wquremniv57gag3tlil8uf6d" \
           "novapalma:kqcnvdsdkgn1efkm4nog8oes" "bgk:6xast9rw0wbzbownss9vamfq" \
           "juranda:c1spfhxrshagrrvwvhoigip1"; do
  nome="${par%%:*}"; uuid="${par##*:}"
  printf '  %-11s ' "$nome"
  curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"fnas-suas"' \
    && echo "ok" || echo "FALTANDO"
done
