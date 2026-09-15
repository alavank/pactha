---
name: migrations
description: Rules for PACTHA database schema changes — plain .sql migrations in backend/migrations/, the MIGRATION_FILES registration list, idempotency across 5 live tenant databases, ordering constraints, and the fact that a failed migration does not abort the boot. Use when adding, editing, or debugging a migration, changing models, or touching services/startup.py.
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
   runs against **6 live tenant databases**, and re-runs on every boot — including a
   **fresh** one: Santa Maria (08/2026) and Nova Palma (01/09/2026) were created from
   scratch, and the second exposed an ORDERING bug (a file altering a table created later in
   `MIGRATION_FILES`), now guarded by `tests/test_migrations_ordem_tabela.py`.

   A one-shot data backfill guards itself with a row in `migration_backfills`, so it runs
   once per database — see `add_permissoes_por_acao.sql` and `add_permissoes_por_tela.sql`.

3. ⚠️ **A FAILED MIGRATION DOES NOT ABORT THE BOOT.** `services/startup.py` catches the
   exception, writes one log line, and the API comes up healthy. So a broken migration and a
   working one look identical from outside — and the whole file is one transaction, so if any
   statement fails, *none* of it applied.

   This bit for real on 05/09/2026: `add_permissoes_por_tela.sql` failed silently, and the
   only symptom was a screen showing permissions unticked that people actually had. Two
   consequences for how you write one:

   - **Never make correctness depend on the backfill having run.** Put the compatibility in
     code (see `services/auth.py::TELAS_RENOMEADAS`), so a failure degrades the *display*
     and not the *access*.
   - **After a deploy that carries a migration, check the log** for `Migration OK: <file>`.
     Nobody will tell you otherwise.

4. **`add_auditoria_imutavel.sql` must always stay last** in the list. It installs the
   append-only trigger on `audit_log`; anything that still needs to `UPDATE`/backfill
   `audit_log` has to be registered **above** it, or the trigger will reject it.

5. A boot-time advisory lock (`pg_try_advisory_lock`) serializes the two uvicorn workers so
   migrations never run concurrently. Don't remove it.

6. ⚠️ **"Idempotent" is not "lock-free".** `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`,
   `CREATE INDEX IF NOT EXISTS` and `DROP ... CASCADE` take their lock **before** finding
   there is nothing to do. Every boot, they wait on any collector holding a long transaction
   on that table. Coolify's healthcheck gives up after about 1 min and rolls back the
   container. This hit api-freitas on 15/09/2026 while `sigcon` was running.
   - A table dropped by `drop_lean_tables.sql` must **never** be recreated — not in
     `setup_db.py`, not as a model, not in a migration. The recreate/drop cycle made every
     boot lock `parlamentares`/`municipios`/`convenios_estadual`/`users`. Guarded by
     `tests/test_boot_nao_recria_tabela_morta.py`.
   - Prefer DDL on tables the collectors don't keep open.

## Before writing one

Remember the multi-tenant constraint from CLAUDE.md: a schema change here lands on Freitas,
Trust, Monte Sião/MG, Santa Maria/RS and Nova Palma/RS. Never write a migration that assumes
data present in only one tenant — and never one that assumes a column exists because a
*migrated* database happens to have it (that was the Santa Maria lesson).

Generate the migration file and register it — do **not** apply it against a live database.
