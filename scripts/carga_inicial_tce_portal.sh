#!/usr/bin/env bash
# Carga inicial do TCE-RS pelo portal, rodada DE FORA DA VPS.
#
# POR QUE ISTO EXISTE. O `portal.tce.rs.gov.br` devolve 403 ao IP da VPS
# (medido do proprio servidor em 03/09/2026 11:53 UTC: 403 nos quatro
# enderecos, mesmo corpo e mesmo tempo do `dados.tce.rs.gov.br`, com o CHE
# respondendo 200 no mesmo minuto — e regra de borda do dominio inteiro). Mas o
# coletor **nao usa credencial nenhuma**: so precisa de um IP que o Tribunal
# aceite. De uma conexao residencial ele funciona.
#
# Entao este script faz a coleta AQUI e grava LA: abre um tunel SSH ate o
# Postgres do tenant, roda `ingestion/tce_rs_portal.py` com o banco apontado
# para o tunel, e fecha. O resultado e a tela do TCE-RS cheia — licitacoes,
# contratos, obras e a origem do recurso — sem esperar a resposta ao oficio.
#
# ⚠️ AS ATUALIZACOES SEGUINTES CONTINUAM DEPENDENDO DA LIBERACAO. Isto e uma
# carga, nao uma cadencia: a Scheduled Task segue sem ser criada, e o que a tela
# mostrar tera a data desta execucao. Repita quando quiser atualizar, ou ligue a
# task no dia em que o TCE liberar o IP (docs/fontes-rs/OFICIO-TCE-RS.md).
#
# COMO RODAR (o `!` do Claude Code serve):
#     COOLIFY_TOKEN='87|...' bash scripts/carga_inicial_tce_portal.sh novapalma
#     COOLIFY_TOKEN='87|...' bash scripts/carga_inicial_tce_portal.sh santamaria
#
# O token NAO fica no arquivo de proposito — ele e segredo e este script e
# versionado. A senha do banco tambem nao: sai da API do Coolify em tempo de
# execucao e vive so na memoria deste processo.
#
# Variaveis opcionais:
#     PASSADAS=6        quantas rodadas no maximo (cada uma commita a sua parte)
#     ORCAMENTO=900     segundos de busca de DETALHE por rodada
#     PORTA_LOCAL=5433  porta local do tunel
#     SSH_KEY=~/.ssh/coolify_localhost

set -euo pipefail

TENANT="${1:-}"
case "$TENANT" in
  novapalma)  DB_UUID="dl2jwo0q1ckbplqp6vp1hnu4" ;;
  santamaria) DB_UUID="m2ypghl41lbqhv7rdqzffdi3" ;;
  *)
    echo "uso: COOLIFY_TOKEN='87|...' bash $0 {novapalma|santamaria}" >&2
    exit 2 ;;
esac

: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='87|...' antes de rodar}"
HOST="${HOST:-54.232.208.118}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/coolify_localhost}"
PORTA_LOCAL="${PORTA_LOCAL:-5433}"
PASSADAS="${PASSADAS:-6}"
ORCAMENTO="${ORCAMENTO:-900}"
B="http://$HOST:8000/api/v1"
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"

echo "== carga inicial TCE-RS (portal) -> tenant $TENANT"
echo "== $(date -u '+%Y-%m-%d %H:%M:%S UTC')  ·  IP de saida: $(curl -s --max-time 20 https://api.ipify.org || echo '?')"

# 1. Credencial do banco, da API do Coolify. `internal_db_url` vem no formato
#    postgres://usuario:senha@<uuid-do-container>:5432/base — e o host dele so
#    resolve DENTRO da rede docker, por isso o passo 2.
#
#    ⚠️ O RECORTE E FEITO EM PYTHON, e nao com `sed`: a senha e gerada pelo
#    Coolify e pode conter `@`, `/` ou `:`. Um `[^@]+` pegaria ate o PRIMEIRO
#    arroba e produziria uma URL silenciosamente errada — que falharia como
#    "senha invalida", mandando quem depura procurar no lugar errado. O
#    `rsplit('@', 1)` corta pelo ULTIMO, que e o separador de verdade.
echo "-- lendo a credencial do banco (API do Coolify)"
DB_URL="$(curl -s --max-time 60 -H "Authorization: Bearer $COOLIFY_TOKEN" \
  "$B/databases/$DB_UUID" \
  | python -c 'import sys,json; print(json.load(sys.stdin).get("internal_db_url") or "")')"
[ -n "$DB_URL" ] || { echo "!! a API nao devolveu internal_db_url (token expirado?)" >&2; exit 1; }

leia_url() {
  DB_URL="$DB_URL" PORTA_LOCAL="$PORTA_LOCAL" python - "$1" <<'PY'
import os
import sys

# ⚠️ NAO usa urlsplit: a senha do Coolify nao vem percent-encoded, e uma barra
# dentro dela faria o parser tratar o resto como caminho — devolvendo base
# vazia. Cortar pelo ULTIMO '@' resolve os dois casos (@ e / na senha), porque
# depois dele so existe host:porta/base.
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

BASE="$(leia_url base)"
echo "   base '$BASE', usuario '$(leia_url usuario)'  (senha nao e impressa)"

# 2. IP do container do Postgres na rede docker do host.
echo "-- descobrindo o IP do container"
IP_DB="$(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 \
  "root@$HOST" \
  "docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' $DB_UUID" \
  | awk '{print $1}')"
[ -n "$IP_DB" ] || { echo "!! nao achei o container $DB_UUID no host" >&2; exit 1; }
echo "   $DB_UUID -> $IP_DB"

# 3. Tunel.
#
#    ⚠️ SEM ControlMaster de proposito: `-M -S <socket>` NAO funciona no OpenSSH
#    do Windows (multiplexing depende de socket unix), e este script roda da
#    maquina do dono. O jeito portatil e o processo em background do proprio
#    shell, cujo PID da para guardar — um `ssh -f` iria para background sozinho
#    e deixaria um tunel orfao se o script morresse no meio.
echo "-- abrindo tunel localhost:$PORTA_LOCAL -> $IP_DB:5432"
ssh -i "$SSH_KEY" -N -o ExitOnForwardFailure=yes -o ConnectTimeout=20 \
    -o StrictHostKeyChecking=accept-new \
    -L "$PORTA_LOCAL:$IP_DB:5432" "root@$HOST" &
SSH_PID=$!
trap 'kill "$SSH_PID" 2>/dev/null || true' EXIT INT TERM

# Espera a porta atender, em vez de dormir um tempo fixo: o tunel sobe em menos
# de um segundo numa rede boa e pode levar cinco numa ruim, e um `sleep 2` chuta
# errado nos dois casos.
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
export TCE_RS_PORTAL_ORCAMENTO_S="$ORCAMENTO"

# 4. Quantas linhas ainda esperam o detalhe. E o unico jeito honesto de dizer
#    "acabou": a fila esvaziar. Contar rodadas nao serve — o volume por
#    municipio varia dez vezes entre Nova Palma e Santa Maria.
pendencias() {
  python - <<'PY'
import os
import psycopg2

with psycopg2.connect(os.environ["DATABASE_URL_SYNC"], connect_timeout=15) as c:
    cur = c.cursor()
    total = 0
    for tabela in ("tce_rs_contratos", "tce_rs_licitacoes"):
        try:
            cur.execute(f"SELECT count(*) FROM {tabela} "
                        "WHERE detalhe_da_versao IS DISTINCT FROM atualizado_na_fonte")
            total += cur.fetchone()[0]
        except Exception:
            # Tabela ou coluna ainda nao existe: a migration deste PR nao rodou
            # naquele tenant. -1 e o sinal de "nao da para saber", e o laco para.
            print(-1)
            raise SystemExit
    print(total)
PY
}

cd "$RAIZ/backend"
for i in $(seq 1 "$PASSADAS"); do
  echo
  echo "== passada $i de $PASSADAS  (orcamento de detalhe: ${ORCAMENTO}s)"
  python -u ingestion/tce_rs_portal.py

  restam="$(pendencias || echo -1)"
  if [ "$restam" = "-1" ]; then
    echo "!! nao consegui contar as pendencias — a migration add_tce_rs_portal.sql"
    echo "   ja rodou neste tenant? (ela roda no boot da API, apos o merge)"
    break
  fi
  echo "-- ainda sem detalhe: $restam registro(s)"
  if [ "$restam" -eq 0 ]; then
    echo "== fila vazia: a carga esta completa."
    break
  fi
done

echo
echo "== fim. A tela /dashboard/tce-rs do tenant $TENANT ja mostra o que entrou."
echo "== Se ainda restarem pendencias, rode de novo — cada passada continua de"
echo "== onde a anterior parou."
