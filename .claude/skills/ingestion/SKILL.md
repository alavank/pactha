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

**Queries by parent id get a ceiling too.** All three trees go through a child helper
that applies a ceiling (5.000) and discards a tree with a missing middle page:
`transferegov_te._pub_filhos`, `parcerias._filhos` and `faf_planos._filhos` (bank
statement: 20.000). The reason: an ignored child filter hits a national table
(730.455 lançamentos in Especiais, 1.149.632 in Fundo a Fundo) and would save it as
one plano's bank statement. `test_te_arvore.py`, `test_parcerias_arvore.py` and
`test_faf_arvore.py` fail if a tree calls `buscar`/`_pub_todos` directly.

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

## Fundo a Fundo — traps measured on 15/09/2026 (`ingestion/faf_planos.py`)

- **Not health.** The 125 programs are SPPE, DIRPP, SENASP, MinC, FNDE and MCID. SUS
  fundo a fundo stays in `fns_faf` (ConsultaFNS).
- **`codigo_ibge_municipio_ente_recebedor_plano_acao` returns HTTP 500** (06, 07 and
  15/09). Entry is `/programas-beneficiarios` by IBGE → CNPJs → `/planos-acao` by CNPJ.
- **The CNPJ filter is "contains"** (13 digits return 94 lançamentos); keep only the equal
  CNPJ in memory. **`id_agencia_conta` is exact** (`2352-1165` → 0) and returns **400**
  on a malformed value.
- **The balance is nested:** `saldo_final_dado_bancario.saldo_final_gestao_financeira`,
  not the openapi's `saldo_final_conta_plano_acao_dado_bancario` (`saldo_da_conta` reads
  both). Credits minus debits is zero on the checking account — the money sits in the
  automatic investment — so the balance is the source's, never derived.
- **One account serves several plans** (Goiânia: 5 plans on 1126-8216). Accounts live in
  `faf_contas`, fetched once per run; the município balance is summed per account.
- **Account `NNNN-0`** = plan with no account opened: no statement to ask for.
- **The statement eats accents** on some rows ("Emisso de Ordem Bancria"): classify by
  accent-free prefixes (`classifica_lancamento`); unknown descriptions are counted in
  `nao_classificado`, never dropped.
- **A debit to CNPJ root 00394460 (Ministério da Fazenda) is a GRU** — money returned to
  the Union (`devolvido_uniao`), not a beneficiary payment.
- **Beneficiaries have no sphere field.** A capital's IBGE also returns the state and its
  secretariats; `ente_municipal` keeps the CNPJ root of a municipal plan, or a name with
  MUNICIP/PREFEITURA, and drops names with ESTADO/GOVERNO DO/DISTRITO FEDERAL.
- `relatorios-gestao-analises-responsaveis` only filters by `id_relatorio_gestao_analise`
  — the natural-looking `id_analise_relatorio_gestao` returns the national 22.182.

## Discricionárias e Legais — the CSV dumps (`ingestion/transferegov_opendata.py`)

- **No REST API:** 65 zips in `.../downloads/dadosgov/` (3,5 GB, republished daily ~11:12
  UTC; `data_carga_siconv.zip` holds the load date). The host supports HTTP Range, so a
  zip's header can be read without downloading it.
- **Keys:**
  - proposal by `COD_MUNIC_IBGE`;
  - children by `ID_PROPOSTA` or `NR_CONVENIO`;
  - grandchildren by `ID_LICITACAO`, `ID_DL`, `ID_META`, `NR_MOV_FIN`, etc.
- **⚠️ IBGE brings what is SEATED in the city, not only the prefeitura.** In Goiânia 75%
  of the value is the State of Goiás; in Santa Maria 33% is civil-society entities.
  - `NATUREZA_JURIDICA` goes to `transferegov_propostas.natureza_juridica` and the rule
    (`services/natureza.py::e_municipal`) goes to `municipal`.
  - Every reader that sums must filter `municipal IS NOT FALSE`, and
    `tests/test_voluntarias_so_a_prefeitura.py` fails on a new query without it.
  - The same trap hit Parcerias (`nm_natureza_juridica`) and Fundo a Fundo (the state
    seated in the capital).

## Authenticated sources

**SIGCON** needs a logged-in session. It reuses a session captured by the Chrome extension
in `extension/` and posted to `POST /api/session-capture`. Captured sessions are encrypted
at rest — see the `secrets` skill before touching that path.

**FNS no longer does.** `run_fns_local.py` uses the public ConsultaFNS API. The
session-based `fns_scraper.py` was dead and was deleted on 15/09/2026. **InvestSUS** is
behind DATASUS login with MFA and has no collector. For health emendas from 2024 on, the
same account, statement and payment data now come openly from Gestão de Parcerias.
