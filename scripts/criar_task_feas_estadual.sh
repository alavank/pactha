#!/usr/bin/env bash
# Cria a Scheduled Task `feas-estadual` nos SETE workers: o cofinanciamento ESTADUAL da
# assistência social — cada pagamento do FEAS de MG e do RS ao fundo municipal ou à
# prefeitura, pela despesa aberta do Estado (`ingestion/feas_estadual.py`). Em tenant
# sem município de MG ou RS (juranda) a rodada sai em segundos, `success` com nota — a
# task existe mesmo assim, pela regra "todo município de todo cliente" e para o dia
# em que entrar município de MG/RS nele.
#
# ⚠️ SÓ DEPOIS DO MERGE E DO DEPLOY: a task chama `ingestion/feas_estadual.py`, que só
# existe na imagem nova, e grava nas tabelas de `add_feas_estadual.sql` (confira
# "Migration OK: add_feas_estadual.sql" no log das sete APIs).
#
# A AGENDA (INFRA.md §5): dentro da janela 19h-7h BRT, a partir de 03:10 UTC — UMA
# HORA DEPOIS da `fnas-suas` (02:10-02:40), porque o CNPJ do fundo municipal, onde cai
# o Piso Mineiro, vem do painel do FNAS. Os tenants de MG em escada de 5 min (03:10,
# 03:15, 03:20); os do RS a 30 MIN um do outro (03:30, 04:00, 04:30), porque a 1ª
# carga do RS leva ~20 min e dois downloads simultâneos do dados.rs travaram (medido).
# CUSTO MEDIDO (26/09/2026, Postgres local, Monte Sião + Nova Palma + Santa Maria):
# 1ª rodada baixa os anos corrente e anterior dos dois Estados (MG ~130 MB em ~5 min;
# RS 19 ZIPs de ~15 MB em 1.170 s); as seguintes só o recurso cujo `last_modified`
# mudou (2ª rodada: 2 s — nada mudou). Kill 1800 s, timeout da task 1920 s.
#
# ⚠️ O COMANDO DA TASK NÃO PODE PASSAR POR INTERPOLAÇÃO (os 25 falso-negativos de
# 08/08/2026): o JSON vai num heredoc com delimitador ENTRE ASPAS SIMPLES.
#
# COMO RODAR:
#     COOLIFY_TOKEN='86|...' bash scripts/criar_task_feas_estadual.sh
# (idempotente: pula o worker que já tem a task)

set -u

B="http://54.232.208.118:8000/api/v1"
: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='86|...' antes de rodar}"

criar() {
  local nome="$1" uuid="$2" freq="$3"
  echo "== $nome  ($freq)"
  if curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
       "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"feas-estadual"'; then
    echo "   já existe — nada a fazer"; echo; return
  fi
  cat <<'JSON' | sed "s|@@FREQ@@|$freq|" | curl -s --max-time 60 \
      -X POST "$B/applications/$uuid/scheduled-tasks" \
      -H "Authorization: Bearer $COOLIFY_TOKEN" \
      -H "Content-Type: application/json" --data @- | head -c 200
{
  "name": "feas-estadual",
  "frequency": "@@FREQ@@",
  "command": "flock -n -E 99 /tmp/feas_estadual.lock timeout -k 30 1800 python -u ingestion/feas_estadual.py 2>&1; rc=$?; if [ $rc = 99 ]; then rc=0; fi; exit $rc",
  "timeout": 1920
}
JSON
  echo; echo
}

criar "freitas"       "s49c3b58lysqq0tpelneg3g3" "10 3 * * *"
criar "trust"         "xg714h8l7va4ejq70a5pmv5t" "15 3 * * *"
criar "montesiao-mg"  "jhf0kjhps5keujiyhhsnvjt6" "20 3 * * *"
criar "santamaria-rs" "wquremniv57gag3tlil8uf6d" "30 3 * * *"
criar "novapalma-rs"  "kqcnvdsdkgn1efkm4nog8oes" "0 4 * * *"
criar "bgk-rs"        "6xast9rw0wbzbownss9vamfq" "30 4 * * *"
criar "juranda-pr"    "c1spfhxrshagrrvwvhoigip1" "25 3 * * *"

echo "== conferência: 'feas-estadual' tem de aparecer nos sete"
for par in "freitas:s49c3b58lysqq0tpelneg3g3" "trust:xg714h8l7va4ejq70a5pmv5t" \
           "montesiao:jhf0kjhps5keujiyhhsnvjt6" "santamaria:wquremniv57gag3tlil8uf6d" \
           "novapalma:kqcnvdsdkgn1efkm4nog8oes" "bgk:6xast9rw0wbzbownss9vamfq" \
           "juranda:c1spfhxrshagrrvwvhoigip1"; do
  nome="${par%%:*}"; uuid="${par##*:}"
  printf '  %-11s ' "$nome"
  curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"feas-estadual"' \
    && echo "ok" || echo "FALTANDO"
done
