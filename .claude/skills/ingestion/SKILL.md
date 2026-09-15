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

## Gestão de Parcerias — traps measured on 14-15/09/2026 (`ingestion/parcerias.py`)

- **Text filters match by "contains".** `nm_municipio_beneficiario_emenda=SANTA MARIA`
  also returns SANTA MARIA DO HERVAL, and `nr_cnpj_beneficiario_emenda=1` returns the whole
  base (78,072). Text filters are also **accent-sensitive** (`MONTE SIAO` → 0, `Monte Sião`
  → 12).
  - Indicated emendas therefore come **per UF** (an enum the source validates: `ZZ` → 422),
    one request per UF per run.
  - The município is matched in memory by **equality** of the normalized name on both
    sides (`_chave_nome`).
- **`0` in a text filter means "no filter".** Prove a filter with a non-zero impossible
  value, such as a 14-digit CNPJ of nines.
- **Nested lists:** `meta-proposta.etapas_proposta`, `parceria-conta.classificacoes_ingresso`,
  `item-proposta.classificacao_despesa`, `beneficiario_emenda_parlamentar.indicacoes_beneficiario`.
- **The bank statement drops the CNPJ's leading zeros** (`530493000171` is FNS). `_doc_cnpj`
  pads only 12–13 digits.
- **`in_situacao_parceria` says "Aprovada" on partnerships that are already paid.** Paid
  is derived from the OB (`execucao_da_arvore`).
- **An empty list from the source is not absence.** On 14/09/2026 at 06:00 UTC every
  `/distribuicao-recurso-proposta` came back empty (HTTP 200) during the source's reload,
  and the upsert wiped every parliamentarian. The upsert now `COALESCE`s instrument and
  emenda fields, and a run with ≥20 proposals and zero emendas is logged as `partial`.

## Authenticated sources

**SIGCON** needs a logged-in session. It reuses a session captured by the Chrome extension
in `extension/` and posted to `POST /api/session-capture`. Captured sessions are encrypted
at rest — see the `secrets` skill before touching that path.

**FNS no longer does.** `run_fns_local.py` uses the public ConsultaFNS API. The
session-based `fns_scraper.py` was dead and was deleted on 15/09/2026. **InvestSUS** is
behind DATASUS login with MFA and has no collector. For health emendas from 2024 on, the
same account, statement and payment data now come openly from Gestão de Parcerias.
