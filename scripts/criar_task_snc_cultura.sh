#!/usr/bin/env bash
# Cria a Scheduled Task `snc-cultura` nos SETE workers: a adesão de cada município ao
# Sistema Nacional de Cultura e as leis registradas — o FUNDO DE CULTURA que o PNAB
# exige a partir de 2027 (Lei 14.399/2022, art. 6º, § 8º) — `ingestion/snc_cultura.py`.
# Alimenta a aba "Cultura (PNAB)" da tela de Regularidade.
#
# ⚠️ SÓ DEPOIS DO MERGE E DO DEPLOY: a task chama `ingestion/snc_cultura.py`, que só
# existe na imagem nova, e grava em `snc_cultura` (`add_snc_cultura.sql` — confira
# "Migration OK: add_snc_cultura.sql" no log das sete APIs).
#
# A AGENDA (INFRA.md §5): dentro da janela 19h-7h BRT, escada de 5 min de 06:40
# (freitas) a 07:10 UTC (juranda). Uma página (~20 KB) por município, com 1 s de pausa
# — a freitas (44) leva ~1 min. Nenhuma outra task usa `snc.cultura.gov.br`. Kill
# 600 s, timeout da task 720 s.
#
# ⚠️ O COMANDO DA TASK NÃO PODE PASSAR POR INTERPOLAÇÃO (os 25 falso-negativos de
# 08/08/2026): o JSON vai num heredoc com delimitador ENTRE ASPAS SIMPLES.
#
# COMO RODAR:
#     COOLIFY_TOKEN='86|...' bash scripts/criar_task_snc_cultura.sh
# (idempotente: pula o worker que já tem a task)

set -u

B="http://54.232.208.118:8000/api/v1"
: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='86|...' antes de rodar}"

criar() {
  local nome="$1" uuid="$2" freq="$3"
  echo "== $nome  ($freq)"
  if curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
       "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"snc-cultura"'; then
    echo "   já existe — nada a fazer"; echo; return
  fi
  cat <<'JSON' | sed "s|@@FREQ@@|$freq|" | curl -s --max-time 60 \
      -X POST "$B/applications/$uuid/scheduled-tasks" \
      -H "Authorization: Bearer $COOLIFY_TOKEN" \
      -H "Content-Type: application/json" --data @- | head -c 200
{
  "name": "snc-cultura",
  "frequency": "@@FREQ@@",
  "command": "flock -n -E 99 /tmp/snc_cultura.lock timeout -k 30 600 python -u ingestion/snc_cultura.py 2>&1; rc=$?; if [ $rc = 99 ]; then rc=0; fi; exit $rc",
  "timeout": 720
}
JSON
  echo; echo
}

criar "freitas"       "s49c3b58lysqq0tpelneg3g3" "40 6 * * *"
criar "trust"         "xg714h8l7va4ejq70a5pmv5t" "45 6 * * *"
criar "montesiao-mg"  "jhf0kjhps5keujiyhhsnvjt6" "50 6 * * *"
criar "santamaria-rs" "wquremniv57gag3tlil8uf6d" "55 6 * * *"
criar "novapalma-rs"  "kqcnvdsdkgn1efkm4nog8oes" "0 7 * * *"
criar "bgk-rs"        "6xast9rw0wbzbownss9vamfq" "5 7 * * *"
criar "juranda-pr"    "c1spfhxrshagrrvwvhoigip1" "10 7 * * *"

echo "== conferência: 'snc-cultura' tem de aparecer nos sete"
for par in "freitas:s49c3b58lysqq0tpelneg3g3" "trust:xg714h8l7va4ejq70a5pmv5t" \
           "montesiao:jhf0kjhps5keujiyhhsnvjt6" "santamaria:wquremniv57gag3tlil8uf6d" \
           "novapalma:kqcnvdsdkgn1efkm4nog8oes" "bgk:6xast9rw0wbzbownss9vamfq" \
           "juranda:c1spfhxrshagrrvwvhoigip1"; do
  nome="${par%%:*}"; uuid="${par##*:}"
  printf '  %-11s ' "$nome"
  curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"snc-cultura"' \
    && echo "ok" || echo "FALTANDO"
done
