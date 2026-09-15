---
name: ingestion
description: Rules for PACTHA's data collectors — the 23 official government sources, per-source gotchas, scraping stack, on-demand queue, and concurrency limits. Use when working in backend/ingestion/, adding or fixing a collector/scraper, touching scraper_jobs, changing scrape scheduling, or debugging why a source returns empty/partial data.
---

# Ingestion — `backend/ingestion/`

Each of the 23 sources has its own collector file with source-specific gotchas documented
**inline in that file** (field-name mismatches between endpoints, silent-empty-result traps,
pagination quirks, portal-specific JS/postback timing). Read the target collector's own
comments before touching it — `CONTINUAR.md` §5 also summarizes the sharpest traps
(SISMOB field typos, CAGEC's ZK-framework grid, session-capture races).

## Stack — do not substitute

- `httpx` — plain HTTP / open dumps
- `Playwright` (Chromium) — JS-heavy logged-in portals (SIGCON, TransfereGov)
- `curl_cffi` — anti-bot-hardened endpoints (SIMEC)

Do **not** introduce Scrapy. This is data integration (open CSV/JSON dumps + 2 JS-heavy
portals), not large-scale crawling.

## On-demand collection

On-demand collection (e.g. "refresh SIGCON now" from the UI) does **not** call the scraper
directly — it enqueues into the `scraper_jobs` table, consumed by
`ingestion/run_queue_sigcon.py` via a Coolify Scheduled Task.

## Concurrency — hard limit, do not raise

Collection is intentionally **not concurrent** across sources on a worker (`flock`-guarded
`/tmp/scraper.lock`) and cron schedules are staggered across the six tenants.

⚠️ **The reason is the PORTAL, not the host.** This paragraph used to say the box was
"a burstable 2-vCPU instance" — that described the old t3.large and stopped being true
after an upgrade. Measured 09/09/2026 with all six workers scraping TransfereGov at once:
**load 3.97 on 8 vCPUs**, 24 GiB RAM free. The host has room; the portals do not. SIGCON
refuses and eventually blocks the credential under parallelism, and six collectors hitting
one federal portal in the same minute is how this project earned an IP block before.

**Never raise scraping concurrency to "speed things up".**

## Filters that are ignored in silence — always pass `teto_itens`

The four `api-publica.transferegov.gestao.gov.br` modules answer **HTTP 200 with the
whole national base** when a query parameter is not recognised — no error, no warning.
Measured 07/09/2026: `?cd_ibge_recebedorX=4313102` returns all **89.400** propostas,
identical to sending no filter at all. A typo, or a rename on their side (Obras.gov has
already renamed *every* field in one host migration), would write Brazil into one
município's rows with a success log.

So `buscar()` / `_pub_todos()` in `parcerias.py`, `faf_planos.py` and
`transferegov_te.py` take a `teto_itens`, and **every query that establishes the
município ↔ data link must pass it** — above the ceiling they return `None`, which the
collectors already treat as "could not ask", never as absence.
`tests/test_filtro_ignorado_em_silencio.py` parses the collectors and fails naming any
IBGE/CNPJ query that forgot it.

**Queries by parent id get a ceiling too once a child table is big.** `parcerias` and
`faf_planos` still query their few children without one. The Transferência Especial
tree (`transferegov_te.arvore_do_plano`) goes through `_pub_filhos`, which applies
`_TETO_FILHOS` (5.000) and discards a tree with a missing middle page. The reason: an
ignored child filter hits a national table of 730.455 lançamentos (3.653 pages)
and would save it as one plano's bank statement. `tests/test_te_arvore.py` fails if the
tree calls `_pub_todos` directly.

When adding a filter, prove it filters: send an impossible value. `9999999` (or id `0`)
must return **0**, not everything. The 21 child filters of `/especiais` were proven this
way on 14/09/2026.

## The official APIs return field names that differ from their own openapi

`api-publica.transferegov.gestao.gov.br/especiais`, measured 14/09/2026:
- **Filter name ≠ response name.** You filter by
  `tx_identificacao_recebedor_relatorio_gestao_dl`, but the field comes back as
  `tx_identificacao_recebedor_mascarado_relatorio_gestao_dl`. Same for
  `tx_cpf_responsavel_mascarado_devolucao`. Read the field names from a real response,
  never from the openapi or the data model. A wrong key gives `None` and raises no error.
- **CNPJ comes as float text.** `doc_favorecido_gestao_financeira = '394460055477.0'`
  is CNPJ 00.394.460/0554-77, with the leading zeros lost. Normalize it with
  `_doc_normalizado` (type 2 → 14 digits, type 1 → 11). Values masked by the source
  (`'***47295***'`) stay as they are.
- **The official API updates once a day** (`/data-atualizacao`); the internal SPA API
  updates in real time. An OB issued today shows up in the official API tomorrow.

## Transferência Especial — who provides what (14/09/2026)

- **Official API:** everything. Plano listing, the tree with 21 resources, and
  **payments** (`pagamentos_da_arvore`, in the same format as the SPA path).
- **Internal SPA API** (`especiais.transferegov.sistema.gov.br`, quota per IP): only
  phase 3, `run_reserva_spa`. It fetches the ordenador/gestor CPF and the OP event
  history, **once per OP**, and the result is inherited on later runs. It stops at the
  first refusal, because a rejected request extends the IP penalty.
- **`TE_PGTO_FONTE=spa`** switches the old payment path back on as a full fallback.

## Authenticated sources

Scrapers that need a logged-in gov.br session (SIGCON, FNS) reuse a session captured by the
Chrome extension in `extension/` and posted to `POST /api/session-capture`. Captured sessions
are encrypted at rest — see the `secrets` skill before touching that path.
