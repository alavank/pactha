#!/usr/bin/env bash
# Cria a Scheduled Task `convenios-to` nos SETE workers.
#
# ⚠️ SÓ DEPOIS DO MERGE E DO DEPLOY: a task chama `ingestion/convenios_to.py`, que
# só existe na imagem nova. (Não há migration: grava em `convenios_estadual` e
# `convenios_estadual_outros`, que já existem nos sete bancos.)
#
# POR QUE NOS SETE, se só quem tem município do TO grava: o coletor sai em
# segundos (`success`, 0) onde não há município do TO, e o cliente que ganhar um
# município do TO amanhã já está coberto sem ninguém lembrar de criar a task.
#
# A AGENDA (INFRA.md §5): dentro da janela 19h-7h BRT, em escada de UMA HORA
# (01:00 a 07:00 UTC = 22:00 a 04:00 BRT). A rodada varre TODOS os ids do
# TRANSFERE.TO (~3.200, ~0,45 s cada da VPS = ~25 min), e o portal é um só: duas
# varreduras ao mesmo tempo dobrariam a carga no servidor do Estado. A escada de
# uma hora cabe o orçamento do coletor (CONVENIOS_TO_BUDGET_S=3000) com folga, e
# nenhuma rodada atravessa o reinício do Coolify (00:00 UTC).
#
# ⚠️ O COMANDO DA TASK NÃO PODE PASSAR POR INTERPOLAÇÃO (os 25 falso-negativos de
# 08/08/2026): o JSON vai num heredoc com delimitador ENTRE ASPAS SIMPLES.
#
# COMO RODAR:
#     COOLIFY_TOKEN='86|...' bash scripts/criar_task_convenios_to.sh
# (idempotente: pula o worker que já tem a task)

set -u

B="http://54.232.208.118:8000/api/v1"
: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='86|...' antes de rodar}"

criar() {
  local nome="$1" uuid="$2" freq="$3"
  echo "== $nome  ($freq)"
  if curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
       "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"convenios-to"'; then
    echo "   já existe — nada a fazer"; echo; return
  fi
  cat <<'JSON' | sed "s|@@FREQ@@|$freq|" | curl -s --max-time 60 \
      -X POST "$B/applications/$uuid/scheduled-tasks" \
      -H "Authorization: Bearer $COOLIFY_TOKEN" \
      -H "Content-Type: application/json" --data @- | head -c 200
{
  "name": "convenios-to",
  "frequency": "@@FREQ@@",
  "command": "flock -n -E 99 /tmp/convenios_to.lock timeout -k 30 3300 python -u ingestion/convenios_to.py 2>&1; rc=$?; if [ $rc = 99 ]; then rc=0; fi; exit $rc",
  "timeout": 3420
}
JSON
  echo; echo
}

criar "freitas"       "s49c3b58lysqq0tpelneg3g3" "0 1 * * *"
criar "trust"         "xg714h8l7va4ejq70a5pmv5t" "0 2 * * *"
criar "montesiao-mg"  "jhf0kjhps5keujiyhhsnvjt6" "0 3 * * *"
criar "santamaria-rs" "wquremniv57gag3tlil8uf6d" "0 4 * * *"
criar "novapalma-rs"  "kqcnvdsdkgn1efkm4nog8oes" "0 5 * * *"
criar "bgk-rs"        "6xast9rw0wbzbownss9vamfq" "0 6 * * *"
criar "juranda-pr"    "c1spfhxrshagrrvwvhoigip1" "0 7 * * *"

echo "== conferência: 'convenios-to' tem de aparecer nos sete"
for par in "freitas:s49c3b58lysqq0tpelneg3g3" "trust:xg714h8l7va4ejq70a5pmv5t" \
           "montesiao:jhf0kjhps5keujiyhhsnvjt6" "santamaria:wquremniv57gag3tlil8uf6d" \
           "novapalma:kqcnvdsdkgn1efkm4nog8oes" "bgk:6xast9rw0wbzbownss9vamfq" \
           "juranda:c1spfhxrshagrrvwvhoigip1"; do
  nome="${par%%:*}"; uuid="${par##*:}"
  printf '  %-11s ' "$nome"
  curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"convenios-to"' \
    && echo "ok" || echo "FALTANDO"
done
