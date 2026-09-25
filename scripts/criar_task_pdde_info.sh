#!/usr/bin/env bash
# Cria a Scheduled Task `pdde-info` nos SETE workers (PDDE: saldo das contas das
# escolas, situação da prestação de contas e suspensões — `ingestion/pdde_info.py`;
# a fonte é federal, todo município de todo cliente).
#
# ⚠️ SÓ DEPOIS DO MERGE E DO DEPLOY: a task chama `ingestion/pdde_info.py`, que só
# existe na imagem nova, e grava nas tabelas de `add_pdde_info.sql` (confira
# "Migration OK: add_pdde_info.sql" no log das sete APIs).
#
# A AGENDA (INFRA.md §5): dentro da janela 19h-7h BRT, TODA entre 05:00 e 06:00 UTC
# (02:00-03:00 BRT), sem atravessar 00:00 UTC. O host `www.fnde.gov.br` também é
# usado pela consulta legada `pls/simad` (outro PR), que fica FORA desta hora, e
# pelo SIOPE da `siops-siope` (OData, poucas consultas por UF; novapalma 05:00, bgk
# 05:15, juranda 05:30) — sobreposição leve, ver INFRA.md. Escada por TAMANHO da
# carteira, um tenant por vez no PDDE Info:
#
#   tenant         início  orçamento  kill  timeout  fim no pior caso
#   freitas        05:00   1080 s     1140  1260     05:19   (44 municípios)
#   trust          05:20    540 s      600   720     05:30   (20)
#   bgk-rs         05:31    300 s      360   480     05:37   (10)
#   santamaria-rs  05:38    180 s      240   360     05:42   (1)
#   novapalma-rs   05:43    180 s      240   360     05:47   (1)
#   montesiao-mg   05:48    180 s      240   360     05:52   (1)
#   juranda-pr     05:53    180 s      240   360     05:57   (1)
#
# CUSTO MEDIDO (25/09/2026, Postgres local + fonte real, Monte Sião e Nova Palma):
# 1ª noite ~22 s por município (9 planilhas: suspensão e PC dos dois anos, saldo do
# mês e 2 meses de histórico); noites seguintes ~10 s por município (suspensão + PC
# do ano = 3 planilhas, mais 2 meses de histórico até completar 12). A parte DIÁRIA
# de todo município vem antes da fila; o que a fila não couber fica para a noite
# seguinte (`success`, com nota). Kill = orçamento + 60 s (um município pesado);
# timeout da task = kill + 120 s (a regra de ouro das margens).
#
# ⚠️ O COMANDO DA TASK NÃO PODE PASSAR POR INTERPOLAÇÃO (os 25 falso-negativos de
# 08/08/2026): o JSON vai num heredoc com delimitador ENTRE ASPAS SIMPLES, e o sed só
# troca os marcadores @@...@@ por números.
#
# COMO RODAR:
#     COOLIFY_TOKEN='86|...' bash scripts/criar_task_pdde_info.sh
# (idempotente: pula o worker que já tem a task)

set -u

B="http://54.232.208.118:8000/api/v1"
: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='86|...' antes de rodar}"

criar() {
  local nome="$1" uuid="$2" freq="$3" orcamento="$4" kill="$5" timeout="$6"
  echo "== $nome  ($freq, orçamento ${orcamento}s, kill ${kill}s, timeout ${timeout}s)"
  if curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
       "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"pdde-info"'; then
    echo "   já existe — nada a fazer"; echo; return
  fi
  cat <<'JSON' | sed -e "s|@@FREQ@@|$freq|" -e "s|@@ORCAMENTO@@|$orcamento|" \
                     -e "s|@@KILL@@|$kill|" -e "s|@@TIMEOUT@@|$timeout|" | curl -s --max-time 60 \
      -X POST "$B/applications/$uuid/scheduled-tasks" \
      -H "Authorization: Bearer $COOLIFY_TOKEN" \
      -H "Content-Type: application/json" --data @- | head -c 200
{
  "name": "pdde-info",
  "frequency": "@@FREQ@@",
  "command": "PDDE_BUDGET_S=@@ORCAMENTO@@ flock -n -E 99 /tmp/pdde_info.lock timeout -k 30 @@KILL@@ python -u ingestion/pdde_info.py 2>&1; rc=$?; if [ $rc = 99 ]; then rc=0; fi; exit $rc",
  "timeout": @@TIMEOUT@@
}
JSON
  echo; echo
}

criar "freitas"       "s49c3b58lysqq0tpelneg3g3" "0 5 * * *"  1080 1140 1260
criar "trust"         "xg714h8l7va4ejq70a5pmv5t" "20 5 * * *"  540  600  720
criar "bgk-rs"        "6xast9rw0wbzbownss9vamfq" "31 5 * * *"  300  360  480
criar "santamaria-rs" "wquremniv57gag3tlil8uf6d" "38 5 * * *"  180  240  360
criar "novapalma-rs"  "kqcnvdsdkgn1efkm4nog8oes" "43 5 * * *"  180  240  360
criar "montesiao-mg"  "jhf0kjhps5keujiyhhsnvjt6" "48 5 * * *"  180  240  360
criar "juranda-pr"    "c1spfhxrshagrrvwvhoigip1" "53 5 * * *"  180  240  360

echo "== conferência: 'pdde-info' tem de aparecer nos sete"
for par in "freitas:s49c3b58lysqq0tpelneg3g3" "trust:xg714h8l7va4ejq70a5pmv5t" \
           "montesiao:jhf0kjhps5keujiyhhsnvjt6" "santamaria:wquremniv57gag3tlil8uf6d" \
           "novapalma:kqcnvdsdkgn1efkm4nog8oes" "bgk:6xast9rw0wbzbownss9vamfq" \
           "juranda:c1spfhxrshagrrvwvhoigip1"; do
  nome="${par%%:*}"; uuid="${par##*:}"
  printf '  %-11s ' "$nome"
  curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$B/applications/$uuid/scheduled-tasks" | grep -q '"name":"pdde-info"' \
    && echo "ok" || echo "FALTANDO"
done
