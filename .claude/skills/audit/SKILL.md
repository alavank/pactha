---
name: audit
description: PACTHA audit trail — the append-only audit_log table, its database-level trigger, the verifiable hash chain, and the known deferred gap in its threat model. Use when writing to audit_log, changing audit records, working on /dashboard/auditoria, or writing a migration that backfills audit data.
---

# Audit trail

`audit_log` is **append-only at the database level**: a trigger rejects `UPDATE`, `DELETE`
and `TRUNCATE`. It is installed by the `add_auditoria_imutavel.sql` migration, which must
always stay **last** in `MIGRATION_FILES` (see the `migrations` skill).

The table carries a **hash chain**, verifiable from `/dashboard/auditoria`.

## Consequences to keep in mind

- Any migration that needs to `UPDATE` or backfill `audit_log` must be registered **above**
  `add_auditoria_imutavel.sql`, or the trigger rejects it.
- Never write code that tries to correct an audit row in place. Corrections are new rows.
- `AUTHZ_MODO=aviso` writes `authz.negaria` entries here (see the `authz` skill) — expect
  those rows in normal operation; they are observations, not denials that happened.

## Known deferred gap

See `docs/AUDITORIA_IMUTABILIDADE.md` for the threat model. Notably, the app's DB role today
can still drop its own trigger; splitting that out into a restricted role is a known,
**deliberately deferred** pending item (`CONTINUAR.md` §6.4). Don't re-raise it as a bug or
"fix" it unprompted.
