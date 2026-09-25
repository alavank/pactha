#!/usr/bin/env bash
# Cria a Scheduled Task `fnde-liberacoes` nos SETE workers (liberações do FNDE por
# entidade do município, `ingestion/fnde_liberacoes.py` — a consulta `pls/simad`).
#
# ⚠️ SÓ DEPOIS DO MERGE E DO DEPLOY: a task chama `ingestion/fnde_liberacoes.py`, que
# só existe na imagem nova, e grava nas colunas/tabela de
# `add_fnde_liberacoes_favorecido.sql` (confira "Migration OK:
# add_fnde_liberacoes_favorecido.sql" no log das sete APIs).
#
# POR QUE NOS SETE: a fonte é federal (todo município tem prefeitura, secretaria e
# caixas escolares recebendo do FNDE).
#
# A AGENDA (INFRA.md §5): dentro da janela 19h-7h BRT, escada de 10 min de 03:00
# (freitas) a 04:00 UTC (juranda) = 00:00 a 01:00 BRT, sem atravessar 00:00 UTC. O
# PDDE Info (outra fonte no MESMO host www.fnde.gov.br) fica em 05:00-06:00 UTC. A
# fonte de verdade dos horários é o Coolify: confira a coluna de cada worker
# (`python scripts/agenda_noturna.py`) antes de rodar.
#
# O CUSTO (medido 24/09/2026 do IP de casa; a VPS também responde 200): 0,15-0,6 s
# por página, sem Cloudflare. Por (município, ano): 1 página de lista + 1 por
# entidade (Monte Sião 16, Nova Palma 8-9, Santa Maria ~56). Toda noite o ano
# corrente e o anterior; a carga inicial (desde FNDE_LIB_ANO_INICIAL=2015) entra
# FNDE_LIB_ANOS_CARGA=3 anos por município por rodada. Pausa FNDE_LIB_PAUSA_S=0,3 s
# entre páginas. Monte Sião + Nova Palma, 2 anos: ~53 páginas em 15 s.
#
# Orçamento interno de 2400 s (FNDE_LIB_BUDGET_S), kill em 2700 s, timeout da task
# 2820 s (kill + 120 — a regra de ouro das margens). O corrente/anterior de TODOS os
# municípios vem antes da carga inicial: o orçamento que sobra vai para o histórico.
#
# ⚠️ O COMANDO DA TASK NÃO PODE PASSAR POR INTERPOLAÇÃO (os 25 falso-negativos de
# 08/08/2026): o JSON vai num heredoc com delimitador ENTRE ASPAS SIMPLES.
#
# COMO RODAR:
#     COOLIFY_TOKEN='86|...' bash scripts/criar_task_fnde_liberacoes.sh
# (idempotente: pula o worker que já tem a task)

set -u

B="http://54.232.208.118:8000/api/v1"
: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='86|...' antes de rodar}"

criar() {
  local nome="$1" uuid="$2" freq="$3"
  echo "== $nome  ($freq)"
  if curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
       "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"fnde-liberacoes"'; then
    echo "   já existe — nada a fazer"; echo; return
  fi
  cat <<'JSON' | sed "s|@@FREQ@@|$freq|" | curl -s --max-time 60 \
      -X POST "$B/applications/$uuid/scheduled-tasks" \
      -H "Authorization: Bearer $COOLIFY_TOKEN" \
      -H "Content-Type: application/json" --data @- | head -c 200
{
  "name": "fnde-liberacoes",
  "frequency": "@@FREQ@@",
  "command": "flock -n -E 99 /tmp/fnde_liberacoes.lock timeout -k 30 2700 python -u ingestion/fnde_liberacoes.py 2>&1; rc=$?; if [ $rc = 99 ]; then rc=0; fi; exit $rc",
  "timeout": 2820
}
JSON
  echo; echo
}

criar "freitas"       "s49c3b58lysqq0tpelneg3g3" "0 3 * * *"
criar "trust"         "xg714h8l7va4ejq70a5pmv5t" "10 3 * * *"
criar "montesiao-mg"  "jhf0kjhps5keujiyhhsnvjt6" "20 3 * * *"
criar "santamaria-rs" "wquremniv57gag3tlil8uf6d" "30 3 * * *"
criar "novapalma-rs"  "kqcnvdsdkgn1efkm4nog8oes" "40 3 * * *"
criar "bgk-rs"        "6xast9rw0wbzbownss9vamfq" "50 3 * * *"
criar "juranda-pr"    "c1spfhxrshagrrvwvhoigip1" "0 4 * * *"

echo "== conferência: 'fnde-liberacoes' tem de aparecer nos sete"
for par in "freitas:s49c3b58lysqq0tpelneg3g3" "trust:xg714h8l7va4ejq70a5pmv5t" \
           "montesiao:jhf0kjhps5keujiyhhsnvjt6" "santamaria:wquremniv57gag3tlil8uf6d" \
           "novapalma:kqcnvdsdkgn1efkm4nog8oes" "bgk:6xast9rw0wbzbownss9vamfq" \
           "juranda:c1spfhxrshagrrvwvhoigip1"; do
  nome="${par%%:*}"; uuid="${par##*:}"
  printf '  %-11s ' "$nome"
  curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"fnde-liberacoes"' \
    && echo "ok" || echo "FALTANDO"
done
