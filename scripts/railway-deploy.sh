#!/usr/bin/env bash
# PACTHA - Helper de deploy Railway
# Uso:
#   ./scripts/railway-deploy.sh backend   # deploy so backend
#   ./scripts/railway-deploy.sh frontend  # deploy so frontend
#   ./scripts/railway-deploy.sh all       # deploy ambos
#   ./scripts/railway-deploy.sh migrations  # roda migrations SQL no Neon
#   ./scripts/railway-deploy.sh status    # mostra dominios + health

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_URL="https://pacta-api-production-9c11.up.railway.app"
FRONTEND_URL="https://pacta-production.up.railway.app"

deploy_backend() {
  echo "==> Deploy backend (pacta-api)..."
  cd "$PROJECT_ROOT"
  railway up backend --service pacta-api --path-as-root --detach
}

deploy_frontend() {
  echo "==> Deploy frontend (pacta)..."
  cd "$PROJECT_ROOT"
  railway up frontend --service pacta --path-as-root --detach
}

run_migrations() {
  echo "==> Rodando migrations SQL no Neon..."
  cd "$PROJECT_ROOT/backend"
  python -c "
import os, psycopg2
url = os.environ['DATABASE_URL_SYNC']
conn = psycopg2.connect(url)
cur = conn.cursor()
for sqlfile in ['migrations/add_audit_and_user_cols.sql']:
    with open(sqlfile) as f:
        cur.execute(f.read())
    print(f'  {sqlfile} OK')
conn.commit()
"
  echo "==> Encriptando cofre (se houver dados legados)..."
  python migrations/encrypt_cofre.py
}

status() {
  echo "Backend ($BACKEND_URL):"
  curl -s -o /dev/null -w "  HTTP %{http_code} %{time_total}s\n" "$BACKEND_URL/api/health"
  echo "Frontend ($FRONTEND_URL):"
  curl -s -o /dev/null -w "  HTTP %{http_code} %{time_total}s\n" "$FRONTEND_URL"
}

case "${1:-all}" in
  backend)     deploy_backend ;;
  frontend)    deploy_frontend ;;
  all)         deploy_backend; deploy_frontend ;;
  migrations)  run_migrations ;;
  status)      status ;;
  *)
    echo "Uso: $0 [backend|frontend|all|migrations|status]"
    exit 1
    ;;
esac

echo "Done."
