#!/usr/bin/env bash
# Cria a Scheduled Task `cadin-rs` nos dois workers gauchos.
#
# ⚠️ SO NO RS. CADIN/RS e CFIL/RS sao cadastros estaduais gauchos (Leis
# 10.697/1996 e 11.389/1999). Em Minas o CADIN vem dentro do CRC do CAGEC, na
# rodada do proprio `cagec` — criar esta task nos workers mineiros seria bater
# num portal que nao responde por ente de MG.
#
# HORARIO: 10 min depois do `che-rs` de cada tenant (santamaria 05:00, novapalma
# 05:30 UTC), mantendo a escada de 30 min entre os dois — eles dividem 0,6 vCPU
# sustentado. Nao depende da rodada do CHE: os alvos saem de `municipios` +
# fontes federais, nao da tabela do cadastro estadual.
#
# LOCK PROPRIO (`/tmp/cadin_rs.lock`) e nao o `/tmp/scraper.lock`: e `httpx` +
# `pypdf`, sem navegador, entao nao disputa a fila do Chromium. Mesmo criterio
# do `portal-transparencia` e do `obrasgov`.
#
# MARGENS: kill interno 600s para ~2 requisicoes por entidade (medido: 4s por
# certidao). Coluna `timeout` da task = 720 (interno + 120), a regra de ouro do
# INFRA.md §5.
#
# COMO RODAR (o `!` do Claude Code serve):
#     COOLIFY_TOKEN='95|...' bash scripts/criar_task_cadin_rs.sh
#
# ⚠️ O COMANDO NAO PODE PASSAR POR INTERPOLACAO DE SHELL: `$rc` e `$?` viram
# lixo se algum shell os expandir antes de chegar ao Coolify (INFRA.md §5). Por
# isso o JSON vai em heredoc com delimitador ENTRE ASPAS SIMPLES.
#
# O token NAO fica no arquivo de proposito — e segredo, e este script e versionado.

set -u

B="http://54.232.208.118:8000/api/v1"
: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='95|...' antes de rodar}"

criar() {
  local nome="$1" uuid="$2" freq="$3"
  echo "== $nome  ($freq)"
  cat <<'JSON' | sed "s|@@FREQ@@|$freq|" | curl -s --max-time 60 \
      -X POST "$B/applications/$uuid/scheduled-tasks" \
      -H "Authorization: Bearer $COOLIFY_TOKEN" \
      -H "Content-Type: application/json" --data @- | head -c 320
{
  "name": "cadin-rs",
  "frequency": "@@FREQ@@",
  "command": "flock -n -E 99 /tmp/cadin_rs.lock timeout -k 30 600 python -u ingestion/cadin_rs.py 2>&1; rc=$?; if [ $rc = 99 ]; then rc=0; fi; exit $rc",
  "timeout": 720
}
JSON
  echo; echo
}

criar "santamaria-rs" "wquremniv57gag3tlil8uf6d" "10 5 * * *"
criar "novapalma-rs"  "kqcnvdsdkgn1efkm4nog8oes" "40 5 * * *"

echo "== conferencia: 'cadin-rs' tem de aparecer nas duas listas"
for par in "santamaria:wquremniv57gag3tlil8uf6d" "novapalma:kqcnvdsdkgn1efkm4nog8oes"; do
  nome="${par%%:*}"; uuid="${par##*:}"
  printf '  %-11s ' "$nome"
  curl -s --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$B/applications/$uuid/scheduled-tasks" \
    | python -c '
import json, sys
for t in json.load(sys.stdin):
    if t.get("name") == "cadin-rs":
        print(str(t.get("frequency")), "timeout=" + str(t.get("timeout")),
              "enabled=" + str(t.get("enabled")))
        break
else:
    print("NAO CRIADA")
'
done
