---
name: ingestion
description: Rules for PACTHA's data collectors — the 22 official government sources, per-source gotchas, scraping stack, on-demand queue, and concurrency limits. Use when working in backend/ingestion/, adding or fixing a collector/scraper, touching scraper_jobs, changing scrape scheduling, or debugging why a source returns empty/partial data.
---

# Ingestion — `backend/ingestion/`

Each of the 22 sources has its own collector file with source-specific gotchas documented
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
IBGE/CNPJ query that forgot it. Queries by parent id (`id_proposta`, `id_plano_acao`)
stay without a ceiling on purpose.

When adding a filter, prove it filters: send an impossible value. `9999999` must return
**0**, not everything.

## Authenticated sources

Scrapers that need a logged-in gov.br session (SIGCON, FNS) reuse a session captured by the
Chrome extension in `extension/` and posted to `POST /api/session-capture`. Captured sessions
are encrypted at rest — see the `secrets` skill before touching that path.
