---
name: ingestion
description: Rules for PACTHA's data collectors — the 26 official government sources, per-source gotchas, scraping stack, on-demand queue, and concurrency limits. Use when working in backend/ingestion/, adding or fixing a collector/scraper, touching scraper_jobs, changing scrape scheduling, or debugging why a source returns empty/partial data.
---

# Ingestion — `backend/ingestion/`

Each of the 26 sources has its own collector file with source-specific gotchas documented
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
`/tmp/scraper.lock`) and cron schedules are staggered across the seven tenants.

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

### The tree of each proposal (`ingestion/transferegov_arvore.py`, task `transferegov-arvore`)

Reads 50 of the zips and hangs everything on the proposals **already in the DB**
(`id_proposta_siconv`, written by the base `transferegov`), so it runs after it.
- **Where it lands:**
  - `transferegov_propostas.arvore` (JSONB, small per-proposal lists + `_resumo`);
  - `notas_empenho_aberto`, and `ops_obs_aberto` in the SAME shape as the scraped
    `ops_obs`, so the RM reads either;
  - `tg_licitacoes`, `tg_pagamentos`, `tg_documentos_liquidacao` for the big lists (up to
    12.868 payments in ONE convênio);
  - `tg_propostas_canceladas` (by IBGE; they are not in `siconv_proposta`).
- **Header guard:** `ARQUIVOS` lists every column read by name. A missing one skips the
  file, and the run is `partial` with the file named. The dump's risk is a renamed column,
  not an ignored filter. `tests/test_transferegov_arvore.py` checks against the real
  headers of 15/09/2026.
- **A failed file keeps only its own key.** `DEPENDE` maps each top-level key to its files.
  The write merges with `||`, so the old value stays and `_mantidas` says which. Numbers
  that depend on it go `None` in `_resumo`, never 0.
  - ⚠️ `siconv_convenio` is the root. Without it there are no `NR_CONVENIO`s, so reading
    licitação/pagamento would "succeed" with zero rows and the swap would wipe the tables.
    Both sections fail together with the root.
  - An empty file and a section with zero matches over a non-empty table also refuse to
    delete.
- **Writes only what changed:** `IS DISTINCT FROM` on the tree, and upsert + delete-missing
  on the tables. The nightly load repeats almost everything.
- ⚠️ **`QTD_DIAS_SEM_DESEMBOLSO` is a BAND** (90/180/365 per the official dictionary), not
  a day count. It is stored as `faixa_sem_desembolso`, and days are computed from
  `data_ultimo_desembolso` at display time. Storing a day count would also rewrite every
  tree daily.
- **The source publishes NEs with `VALOR_EMPENHO` 0.** Convênio 901671: 25.529,72 empenhado
  vs 213.220,28 desembolsado. `empenhado` is the sum of what the dump publishes.
- **Pago > desembolsado is normal:** payments include the contrapartida.
- **Cost measured on the VPS (15/09/2026): ~12 min per tenant, whatever its size.** Monte
  Sião (138 proposals) took 706 s and Trust (9.248) took 744 s. The time is downloading
  and scanning the 3,5 GB, not the carteira. Peak memory is 1,5 GB (measured locally).
  The tenants run one at a time, 30 min apart; the kill is 30 min.
- **Option B (owner, 15/09/2026):** for a proposal that is NOT the prefeitura's
  (`municipal IS FALSE`), the collector stores only the `_resumo` counts and sums, not the
  rows of the three big tables.
  - In the test carteira, 98% of those rows were state convênios seated in the capital.
  - `coleta(..., so_resumo=)` and `Coleta.agregados` feed the `_resumo` from every
    proposal.
  - The table swap's "nothing matched" guard counts what matched in the dump, so old
    rows still get cleaned.
- **Reading rules live in `services/voluntarias_dump.py`** (screen and RM share them):
  - `ops_obs_preferido`: the dump wins; NS/OP/situação come from the scraped block only
    where the OB number matches exactly, and the two lists are never summed.
  - `sinais_do_resumo`: list badges, counted TODAY and only with proof. Prestação vencida
    only when `SIT_CONVENIO` shows it was not delivered.
  - `sem_cpf`: the dump publishes CPF in two files; it never goes to the browser.
  - `notas_empenho_preferidas` (PR 4): the dump wins and the old scraped listing
    COMPLETES it. The owner's rule "não perder informação" is tested in
    `test_rm_empenho_agregado.py`: the minuta and NEs the dump publishes with value 0
    stay.
  - `processo_execucao_preferido` (PR 4): `arvore.processo_execucao` has the scraped
    format (`aceite` drives "Pendente de desembolso", `situacao` "em elaboração"). The
    count comes from `_resumo.n_licitacoes`, because the list is capped at 500.
- **Session scraping is reserve since 15/09/2026:**
  - `TG_NES=0` and `TG_OPS_OBS=0` in the six workers;
  - `TG_OBRAS=1` keeps obras, because ART/RT is not in the dump;
  - licitações need `TG_PROC_EXEC=1`, which is off by default;
  - the daily base `run()` no longer opens Chromium (`TG_LISTAGEM_BASE=1` brings it
    back). It cost ~65 min/night for `possui_parecer` (no reader), SIAFI-legacy
    proposals, and a situação ~19 h fresher than the dump. The lote still lists every
    município in its rodízio.

## Parliamentarian registry — party, UF, cargo, photo (`ingestion/parlamentares_cadastro.py`, 17/09/2026)

No amendment source carries the author's party, cargo or photo, only a name. The
registry reads Câmara (legislaturas 52–57), Senado (52–57) and ALMG (current only). It
runs inside `run_dadosabertos_cron` with a 20 h self-limit.
- **Match by name only through `services/nome_parlamentar.py::chave_nome`.** The key
  keeps letters only, without accents, apostrophes or spaces. Then
  `escolhe_cadastro` picks the record. Measured: 99,05% of the individual federal
  amendments in `siconv_emenda.zip`.
- **Name spellings accumulate** (`nomes_norm TEXT[]`), because the Câmara renames the
  same deputy between legislaturas.
- **Homonyms in the same legislatura return None.** A wrong party next to a name is
  worse than none.
- **Source typos and long civil names** go in `parlamentares_apelidos`, curated with the
  reason.
- **The Senado list per legislatura has no party.** Party comes only from `lista/atual`,
  and the upsert `COALESCE`s so a senator who left keeps the party already stored.
- **The registry never deletes.** A house that fails makes the run `partial`.

## Authenticated sources

**SIGCON** needs a logged-in session. It reuses a session captured by the Chrome extension
in `extension/` and posted to `POST /api/session-capture`. Captured sessions are encrypted
at rest — see the `secrets` skill before touching that path.

**FNS no longer does.** `run_fns_local.py` uses the public ConsultaFNS API. The
session-based `fns_scraper.py` was dead and was deleted on 15/09/2026. **InvestSUS** is
behind DATASUS login with MFA and has no collector. For health emendas from 2024 on, the
same account, statement and payment data now come openly from Gestão de Parcerias.
