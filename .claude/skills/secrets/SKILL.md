---
name: secrets
description: PACTHA credential storage (Cofre) — AES-256 encryption of portal credentials and captured gov.br sessions under the per-tenant COFRE_KEY, and its silent-failure mode. Use when touching services/crypto.py, storing or reading portal credentials, working on session-capture, or debugging credentials that decrypt to empty.
---

# Secrets & credentials (Cofre)

`services/crypto.py` (Cofre) encrypts stored portal credentials and captured gov.br sessions
with **AES-256** under the `COFRE_KEY` env var — **per tenant, never shared**.

## The silent-failure trap

If the key changes, `decrypt()` **silently returns `""`** — no error, no log.

So the symptom of a rotated/mismatched `COFRE_KEY` is not an exception: it's scrapers
suddenly behaving as if no credentials were ever saved. Check the key before assuming the
credential record is missing or the portal changed.

## Reference

See `docs/SECURITY_CREDENTIALS.md` for the Cofre + service-token model.

## Rules

- Never log decrypted credentials or session payloads.
- Never move `COFRE_KEY` into code, a config file, or a shared value across tenants.
- Anything newly persisted that carries a portal login or a gov.br session must go through
  the Cofre, not straight to a column.
