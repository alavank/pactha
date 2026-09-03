# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

PACTHA is a monitoring platform for government grants/transfers (convênios, repasses,
emendas) for Brazilian municipalities, tracking **21 official data sources** (federal +
MG/ES/GO/RS state). Two of them landed 02/09/2026 on `feat/fontes-rs`: **SICONFI/Tesouro** (contas entregues + CAPAG — the note that decides whether the município can borrow with a federal guarantee: Nova Palma is A+, Santa Maria is C) and **TCE-RS/LicitaCon** (866 licitações and 1.202 contratos in Nova Palma, via **two collectors for the same tables**: `tce_rs.py` reads the CKAN at `dados.tce.rs.gov.br`, which returns 403 to datacenter IPs, and `tce_rs_portal.py` reads the open API at `portal.tce.rs.gov.br` — a *different host*, same acervo, plus works, measurements and the **origem do recurso** that links a construction site to the convênio that paid for it. Either way a blocked run reports `partial` with the reason instead of pretending the município has no bids). The two before them: the health **fundo a fundo**
(ConsultaFNS, consolidated by bloco — the largest recurring federal health transfer, and
the platform's only source of the money that sustains the network month to month) and the
**radar de captação** (`siconv_programa.zip` — federal programs whose proposal window is
still open; the only screen in PACTHA that looks *forward* instead of at instruments
already signed). This repo (`alavank/pactha`) is a fork of `MattMatiins/PACTA`, migrated
off Railway/Neon/Vercel/Hetzner onto **Coolify on AWS Lightsail**.

Everything user-facing and every commit message/comment is in **Portuguese**. Match that
convention in code comments, commit messages, and UI copy.

**⚠️ One repo, FIVE tenants — a merge to `main` deploys all five.** Freitas, Trust,
Monte Sião/MG, Santa Maria/RS and Nova Palma/RS each get their own containers and own Postgres database,
all built from the same code (`backend/**` or `frontend/**` changes trigger `.github/workflows/build-backend.yml`
/ `build-frontend.yml`, which build, then deploy all 5 tenants via the Coolify API). There is
no multi-tenancy in code — isolation is by *deploy*: env vars differ per tenant
(`INSTANCE_SLUG`, `DATABASE_URL`, `JWT_SECRET`, `COFRE_KEY`, `NEXT_PUBLIC_CLIENT_LOGO`, …). A
bug fix here ships to all five clients, and a schema change must be idempotent against all
five databases — including a **fresh** one: Santa Maria/RS (08/2026) was the first database
ever created from scratch, and Nova Palma/RS (01/09/2026) was the second — it exposed a
migration ORDERING bug (`add_detalhe_pagina_rodizio.sql` altering a table created later in
`MIGRATION_FILES`), now guarded by `tests/test_migrations_ordem_tabela.py`. Full infra facts (server, URLs, UUIDs, secrets) live in `INFRA.md`; project
history/decisions live in `CONTINUAR.md` — read both before large changes, they are written as
AI-session handoff docs and are kept current.

The `painel/` directory is a **deprecated** standalone Next.js app — its functionality
(`/app`, `/tv`) moved into `frontend/` as `/dashboard` and `/tela`. Don't build on `painel/`;
see `painel/DEPRECADO.md`.

## Escrita de arquivos

Para criar ou sobrescrever arquivos, use a ferramenta Write/Edit. Não use `cat <<EOF`,
heredoc ou `echo > arquivo` via Bash.

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
| `ingestion` | scrapers/collectors, the 21 data sources, scheduling |
| `migrations` | schema changes, `backend/migrations/`, `MIGRATION_FILES` |
| `authz` | permissions, route registration, `AUTHZ_MODO`, row-level scope |
| `secrets` | Cofre / AES credential storage, `COFRE_KEY` |
| `audit` | `audit_log` append-only trigger, hash chain |
| `frontend-auth` | cookies, same-origin proxy, silent refresh, kiosk tokens |
