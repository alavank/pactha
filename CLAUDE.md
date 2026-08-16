# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

PACTHA is a monitoring platform for government grants/transfers (convênios, repasses,
emendas) for Brazilian municipalities, tracking **17 official data sources** (federal +
MG/ES/GO state). This repo (`alavank/pactha`) is a fork of `MattMatiins/PACTA`, migrated
off Railway/Neon/Vercel/Hetzner onto **Coolify on AWS Lightsail**.

Everything user-facing and every commit message/comment is in **Portuguese**. Match that
convention in code comments, commit messages, and UI copy.

**⚠️ One repo, THREE tenants — a merge to `main` deploys all three.** Freitas, Trust, and
Monte Sião/MG each get their own containers and own Postgres database, all built from the
same code (`backend/**` or `frontend/**` changes trigger `.github/workflows/build-backend.yml`
/ `build-frontend.yml`, which build, then deploy all 3 tenants via the Coolify API). There is
no multi-tenancy in code — isolation is by *deploy*: env vars differ per tenant
(`INSTANCE_SLUG`, `DATABASE_URL`, `JWT_SECRET`, `COFRE_KEY`, `NEXT_PUBLIC_CLIENT_LOGO`, …). A
bug fix here ships to all three clients, and a schema change must be idempotent against all
three databases. Full infra facts (server, URLs, UUIDs, secrets) live in `INFRA.md`; project
history/decisions live in `CONTINUAR.md` — read both before large changes, they are written as
AI-session handoff docs and are kept current.

The `painel/` directory is a **deprecated** standalone Next.js app — its functionality
(`/app`, `/tv`) moved into `frontend/` as `/dashboard` and `/tela`. Don't build on `painel/`;
see `painel/DEPRECADO.md`.

## Commands

### Backend (Python 3.12, FastAPI)
```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

### Frontend (Next.js 16, App Router)
```bash
cd frontend
npm install --legacy-peer-deps
npm run dev        # http://localhost:3000
npm run build
npm run lint
```

### Tests (backend only — no frontend test suite exists)
`pytest` isn't pinned in `requirements.txt`; install it separately (`pip install pytest`).
`backend/tests/conftest.py` puts `backend/` on `sys.path`, so pytest works from either the
repo root or `backend/`:
```bash
python -m pytest backend/tests/ -q                             # from repo root
python -m pytest backend/tests/test_authz.py -q -k some_test   # single file/test
```
Tests use plain `asyncio.run(...)` inside test functions rather than `pytest-asyncio`
markers. There is no CI workflow running lint or tests — `build-backend.yml` /
`build-frontend.yml` only build and deploy Docker images on push to `main`.

### First login on a fresh database
Seed user is `super-admin@alavank.com.br`, created by `setup_db.py` only when `users` is
empty. Password is random per tenant, printed to console on first boot (or set via
`ADMIN_PASSWORD`); `must_change_password=True` forces a change on first login.

## Layout

- `backend/` — FastAPI app, all routes under `/api`. `routers/` (HTTP layer, one file per
  module) → `services/` (business logic, DB-agnostic where possible) → `models/` (SQLAlchemy).
  `backend/ingestion/` holds the scrapers/collectors, one file per data source.
- `frontend/` — Next.js App Router. `src/app/dashboard/<module>/` mirrors the backend
  routers 1:1 (e.g. `dashboard/sismob` ↔ `routers/sismob.py`). `src/lib/api.ts` is the shared
  axios client; `src/contexts/` holds cross-page state (BI scope, selected município).
- `extension/` — Chrome extension (Manifest V3, no build step) that captures an
  authenticated gov.br session and forwards it to `POST /api/session-capture` so scrapers
  needing login (SIGCON, FNS) can reuse a human-authenticated session.
- `scripts/` — one-off/maintenance scripts, not part of the running app.

## Feature flags

Several modules are gated by env vars checked at both import time and route-registration
time (not just inside the handler). Gate the **import**, not just the route — see
`TELEGRAM_MODULE` / `BI_MODULE` in `main.py`. Details in the `authz` skill.

## Deep-dive docs

Area-specific rules live in `.claude/skills/` and load automatically when the task touches
that area. Read the relevant one before making changes there:

| Skill | Area |
|---|---|
| `ingestion` | scrapers/collectors, the 17 data sources, scheduling |
| `migrations` | schema changes, `backend/migrations/`, `MIGRATION_FILES` |
| `authz` | permissions, route registration, `AUTHZ_MODO`, row-level scope |
| `secrets` | Cofre / AES credential storage, `COFRE_KEY` |
| `audit` | `audit_log` append-only trigger, hash chain |
| `frontend-auth` | cookies, same-origin proxy, silent refresh, kiosk tokens |
