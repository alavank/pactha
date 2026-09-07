#!/usr/bin/env bash
# Carga do CADIN/RS + CFIL/RS num tenant gaucho, rodada DE FORA DA VPS.
#
# Mesma mecanica do `carga_cagec.sh` (tunel SSH ate o Postgres do tenant), e
# existe pelo mesmo motivo: a carga inicial nao precisa esperar o merge. O
# coletor roda AQUI, com o codigo da branch, e grava LA. Depois que a Scheduled
# Task `cadin-rs` subir no worker, este script vira so ferramenta de reposicao.
#
# ⚠️ SO FAZ SENTIDO NOS DOIS TENANTS DO RS: CADIN e CFIL sao cadastros
# ESTADUAIS gauchos (Leis 10.697/1996 e 11.389/1999). Em Minas o equivalente
# (CADIN-MG) ja vem dentro do CRC do CAGEC — nao ha coletor separado.
#
# COMO RODAR (o `!` do Claude Code serve):
#     COOLIFY_TOKEN='95|...' bash scripts/carga_cadin_rs.sh novapalma
#     COOLIFY_TOKEN='95|...' CADIN_RS_MUNICIPIOS='Santa Maria' bash scripts/carga_cadin_rs.sh santamaria
#
# O token NAO fica no arquivo de proposito — e segredo, e este script e versionado.

set -euo pipefail

TENANT="${1:-}"
case "$TENANT" in
  novapalma)  DB_UUID="dl2jwo0q1ckbplqp6vp1hnu4" ;;
  santamaria) DB_UUID="m2ypghl41lbqhv7rdqzffdi3" ;;
  *)
    echo "uso: COOLIFY_TOKEN='95|...' bash $0 {novapalma|santamaria}" >&2
    echo "     (CADIN/CFIL sao do RS; em MG o CADIN vem no CRC do CAGEC)" >&2
    exit 2 ;;
esac

: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='95|...' antes de rodar}"
HOST="${HOST:-54.232.208.118}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/coolify_localhost}"
PORTA_LOCAL="${PORTA_LOCAL:-5437}"
B="http://$HOST:8000/api/v1"
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"

echo "== carga CADIN/RS + CFIL/RS -> tenant $TENANT"
echo "== $(date -u '+%Y-%m-%d %H:%M:%S UTC')"

echo "-- lendo a credencial do banco (API do Coolify)"
DB_URL="$(curl -s --max-time 60 -H "Authorization: Bearer $COOLIFY_TOKEN" \
  "$B/databases/$DB_UUID" \
  | python -c 'import sys,json; print(json.load(sys.stdin).get("internal_db_url") or "")')"
[ -n "$DB_URL" ] || { echo "!! a API nao devolveu internal_db_url (token expirado?)" >&2; exit 1; }

leia_url() {
  DB_URL="$DB_URL" PORTA_LOCAL="$PORTA_LOCAL" python - "$1" <<'PY'
import os
import sys

bruto = os.environ["DB_URL"]
resto = bruto.split("://", 1)[1]
userinfo, hostpath = resto.rsplit("@", 1)
base = (hostpath.split("/", 1)[1] if "/" in hostpath else "").split("?")[0]
saida = {
    "url": f"postgresql://{userinfo}@localhost:{os.environ['PORTA_LOCAL']}/{base}",
    "base": base,
    "usuario": userinfo.split(":", 1)[0],
}
print(saida[sys.argv[1]])
PY
}

echo "   base '$(leia_url base)', usuario '$(leia_url usuario)'  (senha nao e impressa)"

echo "-- descobrindo o IP do container"
IP_DB="$(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 \
  "root@$HOST" \
  "docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' $DB_UUID" \
  | awk '{print $1}')"
[ -n "$IP_DB" ] || { echo "!! nao achei o container $DB_UUID no host" >&2; exit 1; }
echo "   $DB_UUID -> $IP_DB"

PID_FILE="${TMPDIR:-/tmp}/pactha-carga-cadin-$TENANT.pid"
if [ -f "$PID_FILE" ]; then
  velho="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$velho" ] && kill -0 "$velho" 2>/dev/null; then
    echo "-- encerrando tunel orfao da execucao anterior (pid $velho)"
    kill "$velho" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
fi

echo "-- abrindo tunel localhost:$PORTA_LOCAL -> $IP_DB:5432"
ssh -i "$SSH_KEY" -N -o ExitOnForwardFailure=yes -o ConnectTimeout=20 \
    -o StrictHostKeyChecking=accept-new \
    -L "$PORTA_LOCAL:$IP_DB:5432" "root@$HOST" &
SSH_PID=$!
echo "$SSH_PID" > "$PID_FILE"
trap 'kill "$SSH_PID" 2>/dev/null || true; rm -f "$PID_FILE"' EXIT INT TERM

echo -n "   aguardando a porta"
for _ in $(seq 1 30); do
  if python -c "
import socket,sys
s=socket.socket(); s.settimeout(1)
sys.exit(0 if s.connect_ex(('127.0.0.1', $PORTA_LOCAL))==0 else 1)
" 2>/dev/null; then
    echo " ok"
    break
  fi
  kill -0 "$SSH_PID" 2>/dev/null || { echo; echo "!! o tunel caiu ao subir" >&2; exit 1; }
  echo -n "."
  sleep 1
done

export DATABASE_URL_SYNC="$(leia_url url)"
echo "-- rodando o coletor"

cd "$RAIZ/backend"
python -u ingestion/cadin_rs.py
echo "== fim: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
