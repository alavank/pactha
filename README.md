# PACTHA - Sistema de Monitoramento de Convenios

Plataforma de monitoramento de convenios e transferencias governamentais para municipios de MG.

## Stack
- **Frontend**: Next.js 16 (App Router) + Tailwind v4 + daisyUI
- **Backend**: Python FastAPI (uvicorn)
- **Banco**: PostgreSQL
- **Scraping**: httpx + Playwright (Chromium) + curl_cffi
- **Deploy**: Coolify (Docker) no Hetzner

## Fontes de dados
- TransfereGov (federal): `http://repositorio.dados.gov.br/seges/detru/`
- SIGCON-MG (estadual): `https://dados.mg.gov.br/dataset/convenios-saida`

## Desenvolvimento local

### Backend
```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install --legacy-peer-deps
npm run dev
```

### Login padrao
- Admin: `admin@pactha.com.br` / `pactha2026`
- Equipe: `lara@freitas.com.br` / `freitas2026`

## Deploy (Coolify / Hetzner)

Um projeto no Coolify com 4 resources. Frontend e API ficam no **mesmo host**
(API sob o subpath `/api`) para evitar problemas de cookie/CSRF cross-origin.

| Resource | Build | Dominio |
|----------|-------|---------|
| Postgres 16 | database one-click | interno |
| API | `backend/Dockerfile.api` (context = raiz do repo) | `pactha.alavank.com.br/api` |
| Frontend | `frontend/Dockerfile` (Base Dir = `frontend`) | `pactha.alavank.com.br` |
| Worker | `backend/Dockerfile.scraper` (CMD `sleep infinity`) | interno |

Crons = **Scheduled Tasks** anexadas ao Worker (mesma imagem com Chromium):

| Cron | Comando |
|------|---------|
| `0 */6 * * *` | `python -u ingestion/run_sigcon_cron.py` |
| `0 5 * * *` | `python -u ingestion/transferegov_voluntarias.py` |
| `30 5 * * *` | `python -u ingestion/run_fns_local.py` |
| `*/15 * * * *` | `python -u ingestion/govbr_renew.py` |
| `*/2 * * * *` | `python -u ingestion/run_queue_sigcon.py` (fila on-demand) |

Variaveis de ambiente: ver `.env.example`. As migrations idempotentes rodam no
boot da API (`services/startup.py`).

### Migracao de dados (Neon -> Postgres)
```bash
pg_dump "<NEON_URL>?sslmode=require" --no-owner --no-privileges -Fc -f pactha.dump
pg_restore --no-owner --no-privileges -d "<POSTGRES_COOLIFY_URL>" pactha.dump
```
Use a **mesma `COFRE_KEY`** do Neon (senao o Cofre nao descriptografa).
