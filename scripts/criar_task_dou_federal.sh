#!/usr/bin/env bash
# Cria a Scheduled Task `dou-federal` nos SETE workers (a fonte é federal).
#
# ⚠️ SÓ DEPOIS DO MERGE E DO DEPLOY: a task chama `ingestion/dou_federal.py`, que
# só existe na imagem nova, e grava em tabelas da migration `add_dou_federal.sql`
# (que roda no boot da API nova). Task criada antes disso falha toda noite.
#
# A AGENDA (INFRA.md §5): dentro da janela 19h-7h BRT, em ESCADA de 10 min, porque
# os sete saem do MESMO IP para o in.gov.br e a regra é "fila só por portal". O
# orçamento interno é 8 min (DOU_BUDGET_S=480) e o que não couber fica para a noite
# seguinte, na ordem de quem está há mais tempo sem conferir (`dou_cobertura`) —
# só a PRIMEIRA carga (30 dias por município) chega perto disso. Rodada normal:
# segundos no município pequeno, ~1 min em Santa Maria (medido 22/09/2026).
#
# No fim da janela (08:00-09:00 UTC = 05:00-06:00 BRT) para pegar a edição do dia;
# a revisão de 2 dias (DOU_DIAS_REVISAO) cobre a edição extra que sair depois.
#
# ⚠️ O COMANDO DA TASK NÃO PODE PASSAR POR INTERPOLAÇÃO (os 25 falso-negativos de
# 08/08/2026): o JSON vai num heredoc com delimitador ENTRE ASPAS SIMPLES.
#
# COMO RODAR (de casa; o `!` do Claude Code serve):
#     COOLIFY_TOKEN='86|...' bash scripts/criar_task_dou_federal.sh
#
# ⚠️ "Criar task não é ligar a fonte": criada depois do horário do dia, ela só roda
# na noite seguinte. Confira `scheduled_task_executions` / o `ingestion_log`
# (source `dou_federal`) na manhã seguinte.

set -u

B="http://54.232.208.118:8000/api/v1"
: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='86|...' antes de rodar}"

criar() {
  local nome="$1" uuid="$2" freq="$3"
  echo "== $nome  ($freq)"
  if curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
       "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"dou-federal"'; then
    echo "   já existe — nada a fazer"; echo; return
  fi
  cat <<'JSON' | sed "s|@@FREQ@@|$freq|" | curl -s --max-time 60 \
      -X POST "$B/applications/$uuid/scheduled-tasks" \
      -H "Authorization: Bearer $COOLIFY_TOKEN" \
      -H "Content-Type: application/json" --data @- | head -c 300
{
  "name": "dou-federal",
  "frequency": "@@FREQ@@",
  "command": "flock -n -E 99 /tmp/dou_federal.lock timeout -k 30 600 env DOU_BUDGET_S=480 python -u ingestion/dou_federal.py 2>&1; rc=$?; if [ $rc = 99 ]; then rc=0; fi; exit $rc",
  "timeout": 720
}
JSON
  echo; echo
}

criar "freitas"       "s49c3b58lysqq0tpelneg3g3" "0 8 * * *"
criar "trust"         "xg714h8l7va4ejq70a5pmv5t" "10 8 * * *"
criar "montesiao-mg"  "jhf0kjhps5keujiyhhsnvjt6" "20 8 * * *"
criar "santamaria-rs" "wquremniv57gag3tlil8uf6d" "30 8 * * *"
criar "novapalma-rs"  "kqcnvdsdkgn1efkm4nog8oes" "40 8 * * *"
criar "bgk-rs"        "6xast9rw0wbzbownss9vamfq" "50 8 * * *"
criar "juranda-pr"    "c1spfhxrshagrrvwvhoigip1" "0 9 * * *"

echo "== conferência: 'dou-federal' tem de aparecer nos sete"
for par in "freitas:s49c3b58lysqq0tpelneg3g3" "trust:xg714h8l7va4ejq70a5pmv5t" \
           "montesiao:jhf0kjhps5keujiyhhsnvjt6" "santamaria:wquremniv57gag3tlil8uf6d" \
           "novapalma:kqcnvdsdkgn1efkm4nog8oes" "bgk:6xast9rw0wbzbownss9vamfq" \
           "juranda:c1spfhxrshagrrvwvhoigip1"; do
  nome="${par%%:*}"; uuid="${par##*:}"
  printf '  %-11s ' "$nome"
  curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"dou-federal"' \
    && echo "ok" || echo "FALTANDO"
done
