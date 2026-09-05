---
name: authz
description: PACTHA authorization model — permission keys, the fail-closed route registry, AUTHZ_MODO rollout gates, row-level ownership scope, and import-time feature-flag traps. Use when adding or editing any router endpoint, touching services/authz.py, registro_rotas.py, permissoes.py or auth.py, adding a permission, or debugging a 403 or a boot failure.
---

# Authorization

This is the part of the codebase most worth understanding before touching any router.
Files: `services/authz.py`, `services/registro_rotas.py`, `services/permissoes.py`,
`services/auth.py`.

## Permission keys

Permission keys are `recurso.acao` strings (e.g. `"rm.excluir"`) defined in the pure catalog
`services/permissoes.py::CATALOGO`. A router declares what an endpoint needs via
`exige("recurso.acao")` in `dependencies=[...]` (see `services/registro_rotas.py`) — this both
registers the requirement (for the boot-time route audit below) and enforces it at request
time. An unknown key raises `ValueError` at **import time**, not a silent 403.

## The route registry fails closed

`services/registro_rotas.py` fails closed on undeclared routes. At boot it walks every
registered FastAPI route and checks it against either a declared `exige(...)` or the short,
reason-commented `ROTAS_LIVRES` allowlist (public/self-scoped routes). Anything in neither
bucket is "pending":

- development (`ENV != production`) → **the process refuses to boot**
- production → boots, but that specific route starts returning 403

Escape hatch: `AUTHZ_REGISTRO=aviso` env var, no rebuild needed.

When adding a new router endpoint, do one of:
- give it `exige(...)`, or
- `declarado(...)` if the permission is resolved inside the handler body, or
- (rarely) add a commented `Livre(...)` entry if it's genuinely public/self-scoped.

## AUTHZ_MODO — know which family your check is in

`AUTHZ_MODO` (`aviso` / `bloqueio`) is a separate, **additive gate rollout mechanism** for
newer per-tela / per-município / row-level checks (`authz.exigir_tela`,
`authz.exigir_municipio`, `authz.ensure_dono`, `authz.exigir_dono_da_linha`):

- `aviso` (default) — records what *would* have been denied to `audit_log`
  (action `authz.negaria`) without blocking anything
- `bloqueio` — raises the same 403 they always would

This does **not** apply to the older, always-enforcing checks in `services/auth.py`
(`ensure_tela`, `ensure_municipio_access` — ~128 call sites) — those negate in both modes,
unconditionally.

⚠️ When adding a new authorization check, know which family you're in. Reusing an old
always-enforcing function for a new gate would make it enforce immediately instead of going
through the observed rollout; conversely, routing an existing check through the new gate would
silently loosen access during the `aviso` window.

## Row-level scope

`authz.exigir_dono_da_linha` / `escopo_de` is separate again: per user, per scopable module
(`rm`, `gestao`, `documentos`), an admin can restrict a user to only their own created rows
(`proprios` vs `todos`).

This only ever restricts **writes** (edit/delete), never listing — the owner deliberately
chose not to hide other people's rows from view. Don't "fix" this.

## Read the docstrings

Read the module docstrings in `services/authz.py` and `services/registro_rotas.py`. They're
long but explain *why* each fail-open/fail-closed choice was made — mostly: don't let a
permission bug cause an outage at a live prefeitura.

## Feature-flag import trap

Several modules are gated by env vars checked at both import time and route-registration time,
not just inside the handler. `BI_MODULE` (backend) / `NEXT_PUBLIC_BI_MODULE` (frontend,
build-time) gates the Painel de Indicadores this way.

The trap itself was learned on `TELEGRAM_MODULE` (module removed 05/09/2026, but the lesson
outlives it): the flag has to guard the `from routers import <x>` import *and* the
`include_router` call, because the router's decorators call `exige(...)` at import time
against the permission catalog — importing a router whose keys aren't in the catalog crashes
the boot of the whole API. That happened for real on the first deploy of PR #168.

⚠️ Second lesson from the same module, and the reason it was removed: a **conditional
catalog** (permission keys that exist only when a flag is on) makes the test suite
self-contradictory. `permissoes.SECOES` listed the `telegram` section unconditionally while
`CATALOGO` only had its keys with the flag on — so with the flag off 10 tests failed on an
empty section, and with it on the catalog-size tripwire failed. There was no configuration
where the suite passed. Prefer: **gate the import and the route, but keep the catalog
unconditional** — or remove the module.
