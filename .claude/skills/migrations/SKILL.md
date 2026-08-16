---
name: migrations
description: Rules for PACTHA database schema changes — plain .sql migrations in backend/migrations/, the MIGRATION_FILES registration list, idempotency requirements across 3 live tenant databases, and ordering constraints. Use when adding, editing, or debugging a migration, changing models, or touching services/startup.py.
---

# Database & migrations

PostgreSQL 16. SQLAlchemy async+asyncpg for the API (`database.py`), psycopg2 (sync) for
scrapers and for migrations.

**Migrations are plain `.sql` files in `backend/migrations/`, run idempotently on every API
boot** (`services/startup.py::run_migrations`, called from `main.py`'s `lifespan`).

## Rules that matter when adding one

1. **Register it.** A new migration file does nothing unless it's added to the
   `MIGRATION_FILES` list in `services/startup.py`, **in order**. A file that exists on disk
   but isn't in that list is silently never run — this has bitten the project before; see the
   comments around `add_siconv_federal.sql`.

2. **Must be idempotent** (`IF NOT EXISTS` / `ON CONFLICT DO NOTHING` / guarded `ALTER`). It
   runs against **3 live tenant databases**, and re-runs on every boot.

3. **`add_auditoria_imutavel.sql` must always stay last** in the list. It installs the
   append-only trigger on `audit_log`; anything that still needs to `UPDATE`/backfill
   `audit_log` has to be registered **above** it, or the trigger will reject it.

4. A boot-time advisory lock (`pg_try_advisory_lock`) serializes the two uvicorn workers so
   migrations never run concurrently. Don't remove it.

## Before writing one

Remember the multi-tenant constraint from CLAUDE.md: a schema change here lands on Freitas,
Trust and Monte Sião/MG. Never write a migration that assumes data present in only one tenant.

Generate the migration file and register it — do **not** apply it against a live database.
