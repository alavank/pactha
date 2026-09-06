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
`/tmp/scraper.lock`) and cron schedules are staggered across the five tenants — the host is
a burstable 2-vCPU instance shared with ~10 other projects.

**Never raise scraping concurrency to "speed things up".**

## Authenticated sources

Scrapers that need a logged-in gov.br session (SIGCON, FNS) reuse a session captured by the
Chrome extension in `extension/` and posted to `POST /api/session-capture`. Captured sessions
are encrypted at rest — see the `secrets` skill before touching that path.
