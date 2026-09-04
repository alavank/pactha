#!/usr/bin/env bash
# Carga do Obras.gov.br em um tenant, rodada DE FORA DA VPS.
#
# ⚠️ ISTO NAO E O REGIME PERMANENTE — e a ponte ate o merge.
#
# Diferente do TCE-RS (`carga_inicial_tce_portal.sh`), aqui a fonte **responde
# ao servidor**: medido em 04/09/2026, `api-publica.obrasgov.gestao.gov.br`
# devolve 200 em 0,13 s a partir da VPS, tres vezes seguidas, enquanto o host
# antigo (`api.obrasgov...`) devolve 429. Ou seja: depois que o PR entrar e o
# worker subir com o coletor novo, a Scheduled Task da conta sozinha e este
# script deixa de ser necessario.
#
# Ele existe porque a carga nao precisa esperar o merge: o coletor roda AQUI,
# com o codigo da branch, e grava LA por um tunel SSH ate o Postgres do tenant.
# Nada e copiado para dentro de container nenhum, e nenhum deploy e disparado —
# o pipeline continua sendo o unico caminho do codigo para producao.
#
# COMO RODAR (o `!` do Claude Code serve):
#     COOLIFY_TOKEN='87|...' bash scripts/carga_obrasgov.sh novapalma
#
# Tenants: novapalma · santamaria · montesiao · trust · freitas
#
# O token NAO fica no arquivo de proposito — ele e segredo e este script e
# versionado. A senha do banco tambem nao: sai da API do Coolify em tempo de
# execucao e vive so na memoria deste processo.

set -euo pipefail

TENANT="${1:-}"
case "$TENANT" in
  novapalma)  DB_UUID="dl2jwo0q1ckbplqp6vp1hnu4" ;;
  santamaria) DB_UUID="m2ypghl41lbqhv7rdqzffdi3" ;;
  montesiao)  DB_UUID="iogvjlnkpqlugja9j76rktl1" ;;
  trust)      DB_UUID="p434vbj35siee57shlsyzuc2" ;;
  freitas)    DB_UUID="tox59kvmkrb0ywmeaty3t02a" ;;
  *)
    echo "uso: COOLIFY_TOKEN='87|...' bash $0 {novapalma|santamaria|montesiao|trust|freitas}" >&2
    exit 2 ;;
esac

: "${COOLIFY_TOKEN:?defina COOLIFY_TOKEN='87|...' antes de rodar}"
HOST="${HOST:-54.232.208.118}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/coolify_localhost}"
PORTA_LOCAL="${PORTA_LOCAL:-5434}"
B="http://$HOST:8000/api/v1"
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"

echo "== carga Obras.gov.br -> tenant $TENANT"
echo "== $(date -u '+%Y-%m-%d %H:%M:%S UTC')"

# 1. Credencial do banco, da API do Coolify.
#
#    ⚠️ O RECORTE E FEITO EM PYTHON, e nao com `sed`: a senha e gerada pelo
#    Coolify e pode conter `@`, `/` ou `:`. Um `[^@]+` pegaria ate o PRIMEIRO
#    arroba e produziria uma URL silenciosamente errada — que falharia como
#    "senha invalida", mandando quem depura procurar no lugar errado.
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
# vazia. Cortar pelo ULTIMO '@' resolve os dois casos.
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
# ⚠️ ANTES DE ABRIR, FECHA O ORFAO DA VEZ PASSADA. O `trap` abaixo cobre saida
# normal, Ctrl+C e SIGTERM — mas NAO cobre SIGKILL, e foi o que aconteceu duas
# vezes em 03/09/2026: o script estourou o timeout de quem o chamava, morreu sem
# rodar o trap, e deixou um tunel ABERTO PARA O BANCO DE PRODUCAO por horas.
PID_FILE="${TMPDIR:-/tmp}/pactha-carga-obrasgov-$TENANT.pid"
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

# Espera a porta atender, em vez de dormir um tempo fixo.
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
export OBRASGOV_FORCE=1

# 4. O schema que as migrations deste trabalho criam. Aplicado aqui porque a
#    carga acontece ANTES do deploy que roda as migrations no boot da API —
#    depois, o boot roda as mesmas e elas sao idempotentes de proposito.
#
#    ⚠️ O `TYPE TEXT` nao e refinamento: sem ele Santa Maria aborta INTEIRA com
#    `StringDataRightTruncation`, porque uma das categorias da fonte tem 41
#    caracteres e a coluna tinha 40. Ver add_obrasgov_taxonomias_text.sql.
echo "-- garantindo o schema (migrations deste trabalho, idempotentes)"
python - <<'PY'
import os
import psycopg2

with psycopg2.connect(os.environ["DATABASE_URL_SYNC"], connect_timeout=20) as c:
    with c.cursor() as cur:
        cur.execute("ALTER TABLE obrasgov_projetos "
                    "ADD COLUMN IF NOT EXISTS sistema_origem VARCHAR(40)")
        for coluna in ("natureza", "especie", "situacao", "sistema_origem"):
            cur.execute(f"ALTER TABLE obrasgov_projetos "
                        f"ALTER COLUMN {coluna} TYPE TEXT")
    c.commit()
print("   ok")
PY

# 5. A coleta. O coletor varre a UF inteira e recorta por CNPJ — nao ha filtro
#    territorial na fonte (ver a armadilha 1 no cabecalho de obrasgov.py).
cd "$RAIZ/backend"
python -u ingestion/obrasgov.py

# 6. O que ficou gravado, por municipio.
echo
echo "-- o que o tenant $TENANT passa a ver:"
python - <<'PY'
import os
import psycopg2

with psycopg2.connect(os.environ["DATABASE_URL_SYNC"], connect_timeout=20) as c:
    cur = c.cursor()
    cur.execute("""
        SELECT m.nome || '/' || m.uf, count(*),
               coalesce(sum(o.valor_investimento_previsto), 0)
          FROM obrasgov_projetos o JOIN municipios m ON m.id = o.municipio_id
         GROUP BY 1 ORDER BY 2 DESC
    """)
    linhas = cur.fetchall()
    for nome, n, valor in linhas:
        print("   %-30s %4d obra(s)  R$ %s" % (nome, n, format(valor, ",.2f")))
    cur.execute("SELECT count(*), coalesce(sum(valor_investimento_previsto),0) "
                "FROM obrasgov_projetos")
    n, v = cur.fetchone()
    print("   %-30s %4d obra(s)  R$ %s" % ("TOTAL", n, format(v, ",.2f")))
    cur.execute("SELECT coalesce(sistema_origem,'(sem)'), count(*) "
                "FROM obrasgov_projetos GROUP BY 1 ORDER BY 2 DESC")
    print("   origem:", ", ".join("%s=%d" % r for r in cur.fetchall()))
PY

echo
echo "== fim. Depois do merge, a Scheduled Task mantem isto atualizado sozinha —"
echo "== esta fonte responde ao servidor, diferente do TCE-RS."
