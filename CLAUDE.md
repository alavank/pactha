# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

PACTHA is a monitoring platform for government grants/transfers (convênios, repasses,
emendas) for Brazilian municipalities, tracking **36 official data sources** (federal +
MG/ES/GO/RS/PR/TO state). The newest (25/09/2026) is the **PDDE** (`pdde_info.py`): the
FNDE's PDDE Info Excel exports, per município (IBGE 6 digits) — the BALANCE parked in
each school's bank account (per account and month), the school's prestação de contas
situation and the SUSPENSION report (which school's next installment won't come, and
why) -> `pdde_saldo`/`pdde_prestacao`/`pdde_suspensao`, screen EDUCAÇÃO › "PDDE —
dinheiro nas escolas". ⚠️ An empty program filter means only 5 programs; an unpublished
month answers 200 with zero rows; many caixas escolares belong to STATE schools (the
screen counts the municipal network); the PC report says "Adimplente" where the
suspension report says "Inadimplente" — alerts come from the suspension report. Before
it (24/09/2026), SES-MG's **pagamento de
resoluções** (`ses_mg_resolucoes.py`): every payment order from the State health fund
to the Fundo Municipal, per Resolução SES — MG's ordinary health fundo a fundo, which
PACTHA did not have (Monte Sião 2026: R$ 431 mil ordinary + R$ 4,0 mi of emendas). The
form searches by NAME, so the creditor's CNPJ is checked (prefeitura, FNS by IBGE, or
Receita with the município's IBGE and a municipal legal nature); emenda payments stay
apart (they already count in Emendas › Estaduais). Screen: ESTADUAIS › Cofinanciamento
Saúde, which now opens in MG too. Also new that day: **"Recursos recebidos por pasta"**
(`cgu_transferencias.py`): the CGU's monthly `transferencias/AAAAMM` file — every federal
transfer to the município and its funds (FPM, FUNDEB, fundo a fundo, FNDE, FNAS...), by
ação and favorecido. ⚠️ Município by SIAFI code, never by name; the current month is
partial and FPM/FUNDEB only appear after it closes; the download host has an AWS WAF that
answers 405 + CAPTCHA to bursts (measured) — the collector pauses and stops on it. And **SIOPS, SIOPE and the SUS planning
instruments** (`siops_siope.py`): the detail the CAUC hides behind "!" or a date in items
3.2.3/3.2.4/5.1/5.2 — which bimestre is missing, when it was homologated/declared, the % in
ASPS (min. 15%) and MDE (min. 25%, PARTIAL until the 6th bimestre), plus Plano/PAS/RDQA/RAG
from DigiSUS -> `saude_educacao_bimestre` + `sus_instrumentos_planejamento`, tab "Saúde e
educação" of Regularidade. ⚠️ The SIOPS API answers 404 `msg03` ("não homologado") for ANY
miss, even a wrong IBGE: "not delivered" is proven by the legacy homologation list, never
by `msg03`. It also kills a false alarm: `bi_abas.prazos_dos_itens(entregues=)` stops
warning "vence em N dias" on 3.2.3/3.2.4 when the bimestre that validity covers was already
delivered. And the **RS State Health Fund
payments** (`fes_rs.py`): SES-RS's monthly `.xls` at saude.rs.gov.br/pagamentos-mes
(whole State, republished daily) -> `fes_rs_pagamentos`, shown on the Cofinanciamento
screen in RS mode. ⚠️ Its "Cód. Município" is the STATE code, not IBGE (Nova Palma 083):
matched through the versioned `services/municipios_rs_codigo_estadual.py` (497/497, built
by a CNPJ chain in `scripts/gerar_depara_municipios_rs.py`); the Fundo Municipal is split
from the hospitals that receive ASSISTIR/MAC directly (out of the prefeitura's total), and
fund retentions (CONASEMS, auditoria) are highlighted. Before them, the **FNS account balance**
(`fns_saldo.py`): the Portal FNS's yearly `REPASSE-FAF-COM-POPULACAO-<ANO>` file is the
ONLY public source of how much sits in each Fundo Municipal de Saúde bank account
(ConsultaFNS's API has no balance — its statement endpoint is 404) -> `fns_saldo_conta`,
one row per account (the file repeats the balance per estratégia), shown on the InvestSUS
screen WITH its date (the 2025 file came out in 01/2026 with the 30/11/2025 balance).
Before it, MG's **official emendas
data** (`emendas_mg.py`, SEGOV's CSV in the `portal_emendas_estaduais` package at
dados.mg.gov.br, 2023 onward, no login): it COMPLETES `emendas_estaduais` (same indicação
number as SIGCON) with empenhado/liquidado/pago, the Resolução SES health transfers and
the municípios without a SIGCON password — SIGCON keeps its own fields. ⚠️ Not the
`.xlsx` at emendas.mg.gov.br: that site returns 403 to the VPS and to GitHub runners (and
sat at 12/05/2026); `execucao_em` carries the CKAN date to the screen. Before it,
Tocantins' **TRANSFERE.TO**
(`convenios_to.py`): the State's convênio system has a PUBLIC "pesquisa externa" hidden
behind a button of the transparency portal — one page per convênio, walked by id (~3.200,
~25 min from the VPS) — with the convenente's CNPJ and the **ordens bancárias** of each
repasse, plus the emenda that originated it. -> `convenios_estadual` with
`fonte='TRANSFERE-TO'`; fundos/entities matched by name against the IBGE list, longest
name wins. Before it, the **CGU convênios spreadsheet**
(`cgu_convenios.py`): the federal money that does NOT go through TransfereGov — the
Defesa Civil *transferências legais* (Nova Palma: 8 active, R$ 22,9 mi, R$ 20,8 mi still
to be released) and the pre-2009 SIAFI history — from the Portal da Transparência's open
spreadsheet (no token), matched by the prefeitura's CNPJ and its SIAFI município code.
⚠️ Neither the API nor the spreadsheet links convênio to emenda, despite what the source
report claimed. Screen: FEDERAIS › "Defesa Civil e outros (CGU)". Before it, the **DOU
federal** (`dou_federal.py` —
the Diário Oficial da União, the captação trigger: the portaria that authorizes a repasse
comes out there before any system shows it). It uses the Imprensa Nacional's PUBLIC search
(no INLABS login) to gather candidates per município and reads each act in full; an act
only counts with strong evidence — IBGE code, CNPJ, "Município de X/UF", or published by
the prefeitura itself — because the name alone is noise ("Santa Maria" = 1.246 hits in 80
days), and a citation that is only an ADDRESS (UFSM, a federal court) is stored as
`cidade` and hidden by default. It lives as the first tab of the Diário Oficial screen,
now federal (every UF), and as an alert block in the Radar. The three before it are
Paraná's: **regularidade**
(`regularidade_pr.py` — PR has no convenentes registry, it demands CERTIDÕES; the two
public ones, SEFA's Certidão para Transferências Voluntárias and TCE-PR's Liberatória
pendências, go to `cagec_situacao` with `fonte='CERTIDOES-PR'`; ⚠️ the SEFA route ISSUES
a certificate when none is valid, so only `tipo=1`, once a day), **convênios do Estado**
(`convenios_pr.py`, the SIT in open CSV -> `convenios_estadual` with `fonte='SIT-PR'`; its
`total_repassado` matches, to the cent, what the município reports as PAID to the TCE) and
**TCE-PR/PIT** (`tce_pr.py`): the yearly
SIM-AM zip of `pit.tce.pr.gov.br` (777 MB–2 GB each), read by **HTTP Range** so only the
município's ~2 MB is fetched — convênios, obras, contratos with aditivos, and the **despesa
por fonte de recurso**, the only source that says how much of each convênio was empenhado,
liquidado and pago. Two of them landed 02/09/2026 on `feat/fontes-rs`: **SICONFI/Tesouro** (contas entregues + CAPAG — the note that decides whether the município can borrow with a federal guarantee: Nova Palma is A+, Santa Maria is C) and **TCE-RS/LicitaCon** (866 licitações and 1.202 contratos in Nova Palma, via **two collectors for the same tables**: `tce_rs.py` reads the CKAN at `dados.tce.rs.gov.br`, which returns 403 to datacenter IPs, and `tce_rs_portal.py` reads the open API at `portal.tce.rs.gov.br` — a *different host*, same acervo, plus works, measurements and the **origem do recurso** that links a construction site to the convênio that paid for it. Either way a blocked run reports `partial` with the reason instead of pretending the município has no bids). The two before them: the health **fundo a fundo**
(ConsultaFNS, consolidated by bloco — the largest recurring federal health transfer, and
the platform's only source of the money that sustains the network month to month) and the
**radar de captação** (`siconv_programa.zip` — federal programs whose proposal window is
still open; the only screen in PACTHA that looks *forward* instead of at instruments
already signed). This repo (`alavank/pactha`) is a fork of `MattMatiins/PACTA` and runs on
**Coolify on AWS Lightsail**.

Everything user-facing and every commit message/comment is in **Portuguese**. Match that
convention in code comments, commit messages, and UI copy.

## ⚠️ Mantenha os `.md` vivos — é a sua memória, não decoração

Depois de qualquer mudança que altere um fato descrito num `.md` do repo, **atualize o `.md`
no mesmo trabalho**. Regra do dono (05/09/2026): *"você tá criando um monstro e deixando ele
te confundir; essa memória é sua, você usa pra saber o que tá fazendo"*.

O custo de não fazer é medido: em 05/09/2026 a skill `authz` ainda dizia que `AUTHZ_MODO`
tinha default `aviso` (já era `bloqueio`), o `README.md` dizia "17 fontes / TRÊS tenants"
(são 23 e seis), e o `INFRA.md` não listava `freitas.pactha.com.br` — o que fez uma sessão
inteira desconfiar de estar olhando o ambiente errado.

Três regras:
- **Apague o que ficou falso.** Informação errada custa token e induz a erro; é pior que
  ausência.
- **Nada de credencial, token, senha ou dado pessoal** em `.md`. Cite o *nome* da env
  (`COFRE_KEY`) e onde o valor mora (Coolify, GitHub Secrets) — nunca o valor.
- **Um fato, um lugar.** Duplicar entre `README`/`INFRA`/`CONTINUAR` garante divergência;
  aponte para a fonte.

**⚠️ One repo, SEVEN tenants — a merge to `main` deploys all seven.** Freitas, Trust,
Monte Sião/MG, Santa Maria/RS, Nova Palma/RS, BGK (assessoria com 10 municípios do RS,
aberta em 08/09/2026) and Juranda/PR (22/09/2026 — o primeiro do Paraná, só com as fontes
federais: não há coletor estadual do PR) each get their own containers and own Postgres database,
all built from the same code (`backend/**` or `frontend/**` changes trigger `.github/workflows/build-backend.yml`
/ `build-frontend.yml`, which build, then deploy all 7 tenants via the Coolify API). There is
no multi-tenancy in code — isolation is by *deploy*: env vars differ per tenant
(`INSTANCE_SLUG`, `DATABASE_URL`, `JWT_SECRET`, `COFRE_KEY`, `NEXT_PUBLIC_CLIENT_LOGO`, …). A
bug fix here ships to all seven clients, and a schema change must be idempotent against all
seven databases — including a **fresh** one: Santa Maria/RS (08/2026) was the first database
ever created from scratch, and Nova Palma/RS (01/09/2026) was the second — it exposed a
migration ORDERING bug (`add_detalhe_pagina_rodizio.sql` altering a table created later in
`MIGRATION_FILES`), now guarded by `tests/test_migrations_ordem_tabela.py`. Juranda/PR was the
latest fresh database: 138/138 migrations on first boot. Cliente novo segue
`PROVISIONAR_CLIENTE.md`. Full infra facts (server, URLs, UUIDs, secrets) live in `INFRA.md`; project
history/decisions live in `CONTINUAR.md` — read both before large changes, they are written as
AI-session handoff docs and are kept current.

**⛔ Coleta: TODO município de TODO cliente, TODO dia, entre 19h e 7h (Brasília)** — regra
do dono (13/09/2026), vale para cliente novo sem exceção; paralelismo na máquina é
permitido (o limite é o portal). A agenda das tasks de rodízio mora em
`scripts/agenda_noturna.py`, que audita a regra no Coolify inteiro; desenho e exceção em
`INFRA.md` §5.

The old standalone `painel/` Next.js app was removed from the repo on 12/09/2026 — its
functionality (`/app`, `/tv`) lives in `frontend/` as `/dashboard` and `/tela`. The backend
still serves `/api/painel/*` (used by `/dashboard`); don't resurrect the separate app.

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
Test-only deps live in `backend/requirements-dev.txt` (pytest, pglast — the latter validates
SQL against the real Postgres grammar without a database):
```bash
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python -m pytest                                               # from repo root: the whole suite
python -m pytest backend/tests/test_authz.py -k some_test      # single file/test
```
**Run it bare.** `pytest.ini` supplies `testpaths` and `backend/tests/conftest.py` supplies the
three env vars the suite needs — `DATABASE_URL`, `JWT_SECRET` and `BI_MODULE` (the last one
because the six APIs have it in production; with the flag off, `/api/bi/*` isn't mounted and
three route-registry tests fail forever). If the bare command needs an argument to go green,
fix the repo config, not the command. It also puts `backend/` on `sys.path`, so pytest works
from the repo root or from `backend/`.

Tests use plain `asyncio.run(...)` inside test functions rather than `pytest-asyncio` markers.
`.github/workflows/testes.yml` runs the suite on every PR and push to `main`, on GitHub-hosted
runners (`ubuntu-latest`). Since 18/09/2026 `pytest (backend)` is a **required status check** in
the `protecao-main` ruleset — a red suite blocks the merge (an `--admin` merge still bypasses it,
so check it first). No lint runs in CI — the frontend has 52 pre-existing findings, and a check that is red
from day one recreates the exact problem this workflow was added to fix.

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
`BI_MODULE` in `main.py`. Details in the `authz` skill.

## Deep-dive docs

Area-specific rules live in `.claude/skills/` and load automatically when the task touches
that area. Read the relevant one before making changes there:

| Skill | Area |
|---|---|
| `ingestion` | scrapers/collectors, the data sources (count at the top), scheduling |
| `migrations` | schema changes, `backend/migrations/`, `MIGRATION_FILES` |
| `authz` | permissions, route registration, `AUTHZ_MODO`, row-level scope |
| — | **Permissão: Módulo › Tela › Ação** — a regra inteira em `docs/PERMISSOES_POR_TELA.md` |
| `secrets` | Cofre / AES credential storage, `COFRE_KEY` |
| `audit` | `audit_log` append-only trigger, hash chain |
| `frontend-auth` | cookies, same-origin proxy, silent refresh, kiosk tokens |
