#!/usr/bin/env bash
# Carga do CAGEC-MG (regularidade estadual) num tenant, rodada DE FORA DA VPS.
#
# ⚠️ ISTO E REPOSICAO, NAO REGIME PERMANENTE. O regime e a Scheduled Task
# `cagec` do worker; este script existe para dois casos:
#
#   1. **Zerar backlog.** Em 07/09/2026 a Freitas tinha 31 dos 42 municipios com
#      mais de 48h de atraso porque a task roda 1x/dia com lote de 11 — ciclo de
#      4 dias (o lote 11 foi dimensionado, no codigo, para QUATRO rodadas
#      diarias). Esperar o rodizio custaria mais 3 dias de tela errada.
#   2. **Medir o portal sem o teto do cron.** Aqui nao ha `timeout -k 30 1020`
#      matando a rodada no meio, entao da para ver se o CRC nao sai por culpa do
#      portal ou por falta de tempo.
#
# O Chromium roda AQUI (nao gasta a CPU de 0,6 vCPU da VPS) e grava LA, por um
# tunel SSH ate o Postgres do tenant. Nada e copiado para container nenhum e
# nenhum deploy e disparado.
#
# COMO RODAR (o `!` do Claude Code serve):
#     COOLIFY_TOKEN='95|...' bash scripts/carga_cagec.sh freitas
#     COOLIFY_TOKEN='95|...' CAGEC_LOTE_MUNICIPIOS=1 bash scripts/carga_cagec.sh freitas
#
# Tenants com CAGEC (so os que tem municipio de MG): freitas · montesiao · trust
# (novapalma e santamaria sao RS — a regularidade estadual la e o CHE,
# `ingestion/che_rs.py`, task `che-rs`.)
#
# `CAGEC_LOTE_MUNICIPIOS` vazio = TODOS os municipios de MG do tenant (o default
# do coletor e 11, que e a fatia do cron). Numa carga cheia da Freitas conte
# ~45s por municipio: 42 municipios ~ 35 min.
#
# O token NAO fica no arquivo de proposito — ele e segredo e este script e
# versionado. A senha do banco tambem nao: sai da API do Coolify em tempo de
# execucao e vive so na memoria deste processo.

set -euo pipefail

TENANT="${1:-}"
case "$TENANT" in
  freitas)    DB_UUID="tox59kvmkrb0ywmeaty3t02a" ;;
  montesiao)  DB_UUID="iogvjlnkpqlugja9j76rktl1" ;;
  trust)      DB_UUID="p434vbj35siee57shlsyzuc2" ;;
  *)
    echo "uso: COOLIFY_TOKEN='95|...' bash $0 {freitas|montesiao|trust}" >&2
    echo "     (novapalma e santamaria sao RS: a fonte la e o CHE, nao o CAGEC)" >&2
    exit 2 ;;
esac

: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='95|...' antes de rodar}"
HOST="${HOST:-54.232.208.118}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/coolify_localhost}"
PORTA_LOCAL="${PORTA_LOCAL:-5436}"
B="http://$HOST:8000/api/v1"
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"

echo "== carga CAGEC-MG -> tenant $TENANT"
echo "== $(date -u '+%Y-%m-%d %H:%M:%S UTC')"

# 1. Credencial do banco, da API do Coolify. O recorte e em Python porque a
#    senha gerada pelo Coolify pode conter '@', '/' ou ':'.
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

# Tunel — com morte do orfao da vez passada (SIGKILL nao roda o trap).
PID_FILE="${TMPDIR:-/tmp}/pactha-carga-cagec-$TENANT.pid"
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
# Vazio = todos os municipios de MG do tenant (o coletor so fatia se a env tiver
# numero > 0). Quem quiser uma amostra passa CAGEC_LOTE_MUNICIPIOS=N.
export CAGEC_LOTE_MUNICIPIOS="${CAGEC_LOTE_MUNICIPIOS:-0}"
echo "-- rodando o coletor (lote=$CAGEC_LOTE_MUNICIPIOS; 0 = todos)"

cd "$RAIZ/backend"
python -u ingestion/cagec_scraper.py
echo "== fim: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
