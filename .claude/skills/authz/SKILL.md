---
name: authz
description: PACTHA authorization model — permission keys per screen, the fail-closed route registry, AUTHZ_MODO, row-level scope, and import-time feature-flag traps. Use when adding or editing any router endpoint, touching services/authz.py, registro_rotas.py, permissoes.py or auth.py, adding a permission, or debugging a 403 or a boot failure.
---

# Authorization

The part of the codebase most worth understanding before touching any router.
Files: `services/authz.py`, `services/registro_rotas.py`, `services/permissoes.py`,
`services/auth.py`.

## The model, in one line

**Módulo (menu group) › Tela › Ação.** Every leaf of the sidebar menu is a *tela*;
every tela is a *recurso* in the permission catalog; every recurso has the *ações*
that screen really offers. Since 05/09/2026 the two used to be separate lists and
are now 1:1 by construction — see `docs/PERMISSOES_POR_TELA.md`.

Two tables hold it, and the Usuários modal always writes both together:

| table | holds | source of truth for the list |
|---|---|---|
| `user_telas` | which screens appear | `frontend/src/lib/telas.ts::TELAS` |
| `user_permissoes` | what you can do in each | `services/permissoes.py::CATALOGO` |

## Permission keys

Keys are `recurso.acao` strings (e.g. `"rm.excluir"`) defined in the pure catalog
`services/permissoes.py::CATALOGO`. A router declares what an endpoint needs via
`exige("recurso.acao")` in `dependencies=[...]` (see `services/registro_rotas.py`) — this both
registers the requirement (for the boot-time route audit below) and enforces it at request
time. An unknown key raises `ValueError` at **import time**, not a silent 403.

`Permissao.tela` is the hinge between the catalog and the menu. The Usuários screen
builds its tree by walking the menu and matching on that field
(`frontend/src/lib/arvorePermissoes.ts`), and
`tests/test_arvore_segue_o_menu.py` fails if the two sides drift.

⚠️ **A key that no route requires is worse than a missing key** — the admin ticks it,
saves, and nothing changes. The nine that exist today are listed, with the reason, in
`services/permissoes.py::PERMISSOES_INERTES`, and the tree **hides** them.
`tests/test_registro_rotas.py` fails if a tenth appears without being declared there.

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

## ⚠️ AUTHZ_MODO defaults to `bloqueio` (changed 05/09/2026)

`AUTHZ_MODO` (`aviso` / `bloqueio`) gates the per-tela / per-município / row-level checks
(`authz.exigir`, `authz.exigir_tela`, `authz.exigir_municipio`, `authz.exigir_dono_da_linha`)
**and** `exige(...)` in the route decorators:

- **`bloqueio` (the default)** — raises 403, and records to `audit_log`
- `aviso` — records what *would* have been denied (action `authz.negaria`) without blocking

**It used to default to `aviso`, and flipping it was the highest-blast-radius line of the
05/09/2026 increment.** It had to flip because the account-level «Somente leitura» lock was
removed in the same deploy: while the mode was `aviso`, *that lock* was what stopped writes
and these checkboxes only logged. Removing one without turning on the other would have left
the system with no write lock at all.

The fail-safe inverted with it: a typo (`AUTHZ_MODO=avisoo`) **does not** turn the lock off.
Turning it off is now the deliberate act, and `aviso` — spelled exactly — is the escape
hatch, settable in Coolify without a deploy.

⚠️ This does **not** apply to the older always-enforcing checks in `services/auth.py`
(`ensure_tela`, `ensure_municipio_access`) — those deny in both modes, unconditionally.
So `AUTHZ_MODO=aviso` will **not** rescue a broken `user_telas` state.

## ⚠️ «Somente leitura» no longer exists

The account-level write lock (`users.somente_leitura`) was removed on 05/09/2026 by the
owner's decision: *"prefiro dar permissão de visualização separada pra cada menu ou módulo,
daí eu permito só visualizar sem editar nada"*. What it did is now done by unticking the
write actions of a screen — which is finer: you can be reader in the Cofre and writer in
Gestão Interna on the same account.

The column stays in the database with **no reader**. `Permissao.escrita` also survives, but
only as UI emphasis — it no longer subtracts anything.

The public TV link is unaffected: it has its own guard (`ehQuiosque` +
`KIOSK_GET_PERMITIDOS` in `services/auth.py`), plus the `viewer` role belt in
`PAPEIS_SINTETICOS_SEM_ESCRITA`.

## ⚠️ Two compatibility nets, and they are temporary

`services/auth.py::TELAS_RENOMEADAS` / `TELAS_DE_ADMINISTRACAO` and
`services/permissoes.py::_CHAVES_RENOMEADAS` exist because
`migrations/add_permissoes_por_tela.sql` **failed to run on the 05/09/2026 deploy** and
`services/startup.py` swallows a failed migration into a log line without aborting boot.

They make access correct in **code** rather than depending on the data migration:
whoever holds an old key reaches the new ones, and `role='admin'` reopens the three
administration screens.

**Remove them once the five databases are confirmed migrated** — they are a bridge, not the
design. `tests/test_compat_telas_renomeadas.py` pins their properties (only widens, never
takes away, only the `admin` role).

## Role is a label

`users.role` (admin / usuario, plus the legacy `prefeito`, `analyst`, `viewer`) organises
the client's team and **grants nothing**. `routers/users.py::_exige_tela_usuarios` — which
used to be `_require_admin` and used to read the role — now checks the `usuarios` tela.

The one condition that bypasses every list is `super_admin` (the Alavank accounts).

## Row-level scope

`authz.exigir_dono_da_linha` / `escopo_de` is separate again: per user, per scopable module
(`gestao`, `agendamentos`, `rm`, `documentos` — the four that record `criado_por`), an admin
can restrict a user to only their own created rows (`proprios` vs `todos`).

This only ever restricts **writes** (edit/delete), never listing — the owner deliberately
chose not to hide other people's rows from view. Don't "fix" this.

## Read the docstrings

Read the module docstrings in `services/authz.py` and `services/registro_rotas.py`. They're
long but explain *why* each fail-open/fail-closed choice was made — mostly: don't let a
permission bug cause an outage at a live prefeitura.

## Feature-flag import trap

Several modules are gated by env vars checked at both import time and route-registration
time, not just inside the handler. `BI_MODULE` (backend) / `NEXT_PUBLIC_BI_MODULE` (frontend,
build-time) gates the Painel de Indicadores this way.

The trap was learned on `TELEGRAM_MODULE` (module removed 05/09/2026, but the lesson
outlives it): the flag has to guard the `from routers import <x>` import *and* the
`include_router` call, because the router's decorators call `exige(...)` at import time
against the permission catalog — importing a router whose keys aren't in the catalog crashes
the boot of the whole API. That happened for real on the first deploy of PR #168.

⚠️ Second lesson from the same module: a **conditional catalog** (permission keys that exist
only when a flag is on) makes the test suite self-contradictory. Prefer: **gate the import
and the route, but keep the catalog unconditional** — or remove the module.
