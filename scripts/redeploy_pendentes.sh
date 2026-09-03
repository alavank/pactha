#!/usr/bin/env bash
# Deploya os apps que ficaram para tras — e DIZ POR QUE, quando nao conseguir.
#
# POR QUE ISTO EXISTE. Em 03/09/2026 o merge do PR #355 buildou as dez imagens
# e **nao deployou quase nada**: `freitas-api` passou, e os outros nove apps do
# backend mais os cinco frontends foram recusados com a mesma linha cega —
# "deploy nao disparou — revertendo tag". O CI joga fora exatamente o que
# explicaria a recusa.
#
# O endpoint devolve `{"deployments":[{message, resource_uuid, deployment_uuid}]}`
# e o **`deployment_uuid` e OPCIONAL**: vem so quando o deploy foi de fato
# enfileirado. Sem ele, a `message` diz o motivo (fila cheia -> HTTP 429,
# `skipped`, `Unauthorized to deploy this application`...). O workflow faz
# `jq -r '.deployments[0].deployment_uuid // ""'`, recebe vazio nos quatro casos
# e imprime a mesma frase para todos. Este script mostra HTTP e `message`.
#
# E ele NAO faz o que o CI faz de arriscado: o CI trata `curl -X PATCH` sem `-f`
# como sucesso, e `curl` devolve 0 mesmo em HTTP 403 — foi por isso que as tags
# dos cinco frontends nao mudaram e ninguem reclamou do PATCH. Aqui cada PATCH e
# conferido pelo codigo HTTP.
#
# COMO RODAR (o `!` do Claude Code serve):
#     COOLIFY_TOKEN='87|...' bash scripts/redeploy_pendentes.sh            # so mostra
#     COOLIFY_TOKEN='87|...' bash scripts/redeploy_pendentes.sh --aplicar  # deploya
#
# Sem `--aplicar` ele nao muda nada: lista quem esta atrasado e para. Com
# `--aplicar`, vai um app por vez (concurrent_builds=1 no servidor) e espera
# cada um terminar antes do proximo.
#
# Variaveis opcionais:
#     TAG=sha-<sha40>   imagem alvo (default: o HEAD do repo local)
#     ESPERA=40         quantas conferencias de 15s por deployment (10min)
#     TENTATIVAS=4      quantas vezes reofertar quando a recusa e de FILA

set -uo pipefail

APLICAR=0
[ "${1:-}" = "--aplicar" ] && APLICAR=1

: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='87|...' antes de rodar}"
HOST="${HOST:-54.232.208.118}"
B="http://$HOST:8000/api/v1"
SHA="${SHA:-$(git -C "$(dirname "$0")/.." rev-parse HEAD)}"
# ⚠️ OS DOIS WORKFLOWS USAM FORMATOS DIFERENTES DE TAG, e nao e escolha deste
# script: `build-backend.yml` publica com `type=sha,format=short` e grava
# `sha-${GITHUB_SHA::7}`; `build-frontend.yml` publica e grava o SHA de 40.
# Comparar todo mundo com um formato so faria a metade dos apps parecer
# eternamente atrasada — e o "conserto" seria gravar uma tag cuja imagem nao
# existe no registry, o que derruba o app no proximo pull.
TAG_CURTA="sha-${SHA:0:7}"
TAG_LONGA="sha-$SHA"
ESPERA="${ESPERA:-40}"
TENTATIVAS="${TENTATIVAS:-4}"
CURL=(curl -sS --connect-timeout 10 --max-time 40 -H "Authorization: Bearer $COOLIFY_TOKEN")

echo "== alvo: $TAG_CURTA (api/worker)  ·  $TAG_LONGA (frontend)"
echo "== $(date -u '+%Y-%m-%d %H:%M:%S UTC')  ·  modo: $([ "$APLICAR" = 1 ] && echo APLICAR || echo 'somente listar')"

# ---------------------------------------------------------------------------
# Quem esta atrasado
# ---------------------------------------------------------------------------
LISTA="$("${CURL[@]}" "$B/applications")" || { echo "!! nao consegui listar" >&2; exit 1; }

pendentes="$(printf '%s' "$LISTA" \
  | TAG_CURTA="$TAG_CURTA" TAG_LONGA="$TAG_LONGA" python -c '
import json, os, sys

curta, longa = os.environ["TAG_CURTA"], os.environ["TAG_LONGA"]
# Ordem deliberada: API antes do worker do mesmo tenant (a API roda as
# migrations no boot, e o worker novo pode depender de coluna nova), e os
# tenants em avaliacao por ultimo.
peso = {"api": 0, "worker": 1, "frontend": 2}


def papel(nome):
    for p in peso:
        if nome.endswith("-" + p):
            return p
    return None


def chave(a):
    n = a.get("name") or ""
    novo = 1 if ("novapalma" in n or "santamaria" in n) else 0
    return (novo, peso.get(papel(n), 9), n)


fora = []
for a in json.load(sys.stdin):
    n = a.get("name") or ""
    p = papel(n)
    if p is None:
        continue
    alvo = longa if p == "frontend" else curta
    if (a.get("docker_registry_image_tag") or "") != alvo:
        fora.append((a, alvo))
for a, alvo in sorted(fora, key=lambda par: chave(par[0])):
    print(a["uuid"], a["name"], (a.get("docker_registry_image_tag") or "?"), alvo)
')"

if [ -z "$pendentes" ]; then
  echo "== nada atrasado: todos os apps ja estao na imagem deste commit"
  exit 0
fi

echo
echo "-- atrasados:"
printf '%s\n' "$pendentes" | while read -r uuid nome tag_atual tag_alvo; do
  printf '   %-24s %-44s -> %s\n' "$nome" "$tag_atual" "$tag_alvo"
done
n_pend=$(printf '%s\n' "$pendentes" | grep -c .)
echo "   ($n_pend app(s))"

if [ "$APLICAR" != 1 ]; then
  echo
  echo "== nada foi alterado. Para deployar: bash $0 --aplicar"
  exit 0
fi

# ---------------------------------------------------------------------------
# Deploy, um por vez
# ---------------------------------------------------------------------------
patch_tag() {  # $1 uuid, $2 tag -> 0 se gravou
  local http
  http="$("${CURL[@]}" -o /dev/null -w '%{http_code}' -X PATCH \
          -H "Content-Type: application/json" \
          -d "{\"docker_registry_image_tag\":\"$2\"}" "$B/applications/$1")"
  case "$http" in
    200|201|204) return 0 ;;
    *) echo "   !! PATCH da tag devolveu HTTP $http (app intocado)"; return 1 ;;
  esac
}

# stdout: deployment_uuid, ou vazio. stderr: o motivo, quando vazio.
disparar() {  # $1 uuid
  local resposta http corpo dep msg
  resposta="$("${CURL[@]}" -X POST -w $'\n%{http_code}' "$B/deploy?uuid=$1")"
  http="${resposta##*$'\n'}"
  corpo="${resposta%$'\n'*}"
  dep="$(printf '%s' "$corpo" | python -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    raise SystemExit
alvo = (d.get("deployments") or [{}])[0] if isinstance(d, dict) else {}
print(alvo.get("deployment_uuid") or "")
' 2>/dev/null)"
  if [ -z "$dep" ]; then
    msg="$(printf '%s' "$corpo" | python -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("(resposta nao era JSON)"); raise SystemExit
if isinstance(d, dict):
    dep = (d.get("deployments") or [{}])[0]
    print(dep.get("message") or d.get("message") or json.dumps(d)[:200])
else:
    print(json.dumps(d)[:200])
' 2>/dev/null)"
    echo "   HTTP $http · $msg" >&2
  fi
  printf '%s' "$dep"
}

# Uma recusa por FILA se resolve esperando; uma por autorizacao ou por app
# inexistente, nao. A distincao decide se vale reofertar.
recusa_temporaria() {  # $1 texto da recusa
  printf '%s' "$1" | grep -qiE '429|queue|fila|skipped|in progress|already|limit'
}

acompanhar() {  # $1 deployment_uuid -> 0 se finished
  local i st
  for i in $(seq 1 "$ESPERA"); do
    st="$("${CURL[@]}" "$B/deployments/$1" | python -c '
import json, sys
try:
    print((json.load(sys.stdin) or {}).get("status") or "")
except Exception:
    print("")
' 2>/dev/null)"
    case "$st" in
      finished) echo "   deployment finished"; return 0 ;;
      failed|cancelled*) echo "   !! deployment '$st'"; return 1 ;;
      "") echo "   !! nao consegui ler o status do deployment"; return 1 ;;
    esac
    [ $((i % 4)) -eq 0 ] && echo "   ... $st (${i}/${ESPERA})"
    sleep 15
  done
  echo "   !! ainda '$st' apos $((ESPERA * 15 / 60))min — conferir no Coolify"
  return 1
}

FALHOU=""
MOTIVO_TMP="$(mktemp)"
trap 'rm -f "$MOTIVO_TMP"' EXIT

# ⚠️ `while read` com HERE-STRING, e nao `printf | while`: um `while` do lado
# direito de um pipe roda em SUBSHELL, e `$FALHOU` acumulado la dentro morre com
# ele — o resumo do fim sairia sempre vazio, dizendo que tudo deu certo.
while read -r uuid nome tag_atual tag_alvo; do
  [ -n "${uuid:-}" ] || continue
  echo
  echo "== $nome ($tag_atual -> $tag_alvo)"
  patch_tag "$uuid" "$tag_alvo" || { FALHOU="$FALHOU $nome"; continue; }

  dep=""
  for t in $(seq 1 "$TENTATIVAS"); do
    # ⚠️ UMA CHAMADA SO. Chamar `disparar` duas vezes (uma para o stdout, outra
    # para o stderr) enfileiraria DOIS deploys do mesmo app — o stderr vai para
    # arquivo justamente para isso nao acontecer.
    dep="$(disparar "$uuid" 2>"$MOTIVO_TMP")"
    motivo="$(cat "$MOTIVO_TMP")"
    [ -n "$motivo" ] && printf '%s\n' "$motivo"
    if [ -n "$dep" ]; then break; fi
    if recusa_temporaria "$motivo" && [ "$t" -lt "$TENTATIVAS" ]; then
      echo "   recusa parece de fila — nova oferta em 60s ($t/$TENTATIVAS)"
      sleep 60
      continue
    fi
    break
  done

  if [ -z "$dep" ]; then
    echo "   !! nao enfileirou; revertendo a tag para $tag_atual"
    patch_tag "$uuid" "$tag_atual" >/dev/null || true
    FALHOU="$FALHOU $nome"
    continue
  fi
  echo "   deployment $dep"
  acompanhar "$dep" || FALHOU="$FALHOU $nome"
done <<EOF
$pendentes
EOF

echo
if [ -n "$FALHOU" ]; then
  echo "!! NAO deployaram:$FALHOU"
  echo "!! A linha 'HTTP xxx · <mensagem>' de cada um, acima, e o motivo que o CI"
  echo "!! nao mostra. Cole-a de volta no chat."
else
  echo "== todos os pendentes deployaram."
fi
echo "== confira as tags com: bash $0   (sem --aplicar)"
