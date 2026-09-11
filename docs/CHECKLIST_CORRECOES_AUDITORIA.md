# Checklist de produção — correções da auditoria (11/09/2026)

Tudo aqui depende de **acesso a produção/Coolify** que a sessão de correção **não tem**.
O código está pronto (PRs #472 + continuação); estes passos são o que falta executar,
com **COMANDO · LOCAL · RESULTADO ESPERADO · EVIDÊNCIA**. Rodar por tenant; validar nos 6.

Convenção: `<worker_uuid>` = uuid do worker do tenant no Coolify; horários **UTC**.

---

## C-3 — Coletores federais órfãos (Scheduled Task)

`siconv_federal_ingest` e `siconv_empenho_aberto` já têm `ingest()`, `ingestion_log`
honesto (zero-guard no federal) e entrada no watchdog (`fonte_nunca_executada`). Falta
**criar a Scheduled Task** (são pesados — dump ~200 MB / 437k linhas — então NÃO entram
no orçamento do `sigcon`; task própria).

- [ ] **siconv_federal_ingest** (base nacional por CNPJ)
  - COMANDO: `flock -n /tmp/siconv_federal.lock timeout -k 30 1800 python -u ingestion/siconv_federal_ingest.py`
  - LOCAL: Scheduled Task no worker de **cada tenant** (é usada por todos via CNPJ). Sugestão: 1×/dia, escalonado (ex.: freitas `10 2`, trust `25 2`, …), fora da janela do `sigcon`.
  - RESULTADO ESPERADO: `ingestion_log` com `source='siconv_federal'`, `status='success'`, `records_inserted` ~1,1 M (nos tenants que consultam a base).
  - EVIDÊNCIA: `GET /api/status/ingestao` → `counts.siconv_federal > 0` e linha `success` do dia. Hoje **BGK=0** — deve deixar de ser 0.
- [ ] **siconv_empenho_aberto** (fallback de notas de empenho)
  - COMANDO: `flock -n /tmp/siconv_empenho.lock timeout -k 30 1200 python -u ingestion/siconv_empenho_aberto.py`
  - LOCAL: Scheduled Task por tenant, 1×/dia.
  - RESULTADO ESPERADO: linha `ingestion_log source='siconv_empenho_aberto'`.
  - EVIDÊNCIA: watchdog deixa de emitir `fonte_nunca_executada` para essa fonte.

---

## C-1 — Transparência-MG (403 por IP → worker externo)

Código pronto e agora **observável** (`transparencia_mg.coletar()` grava `ingestion_log`;
403 vira `error` explícito). O portal recusa o IP do datacenter — precisa rodar de um
**IP permitido** (residencial/proxy), escrevendo no mesmo banco do tenant.

- [ ] Provisionar worker externo (mínimo: Python + rede ao Postgres do tenant).
  - COMANDO: `DATABASE_URL_SYNC=<url_do_tenant_MG> python -u ingestion/transparencia_mg.py`
  - LOCAL: host com IP residencial/proxy (NÃO a VPS).
  - RESULTADO ESPERADO: `ingestion_log source='transparencia_mg' status='success'`; `transparencia_mg_empenhos` recebe empenhos/pagamentos.
  - EVIDÊNCIA: `SELECT count(*), max(updated_at) FROM transparencia_mg_empenhos` cresce; **as colunas Data de pagamento/empenho do estadual (PR #471) deixam de sair em branco**.
- [ ] NÃO burlar bloqueio (sem trocar UA para enganar WAF, sem proxy abusivo). Só IP permitido.

---

## C-2 — TCE-RS (403 por IP → worker externo)

`tce_rs.py` (CKAN) e `tce_rs_portal.py` (portal) já distinguem 403-de-IP de
403-de-conexão e logam `partial` com nota. Mesmo caso do C-1: rodar de fora da VPS.

- [ ] Worker externo (IP permitido), por tenant do RS.
  - COMANDO: `DATABASE_URL_SYNC=<url_tenant_RS> python -u ingestion/tce_rs_portal.py` (e/ou `tce_rs.py`)
  - RESULTADO ESPERADO: `tce_rs_licitacoes`/`tce_rs_contratos`/`tce_rs_obras` populam; `ingestion_log` sai `success`/`partial` (não bloqueado).
  - EVIDÊNCIA: contagem das tabelas > 0 nos tenants RS; nota `NOTA_BLOQUEIO` some do log.

---

## A-3 — heartbeat / job morto (rollout gradual)

Código PREPARADO: `backend/services/ingest_heartbeat.py` + migration
`add_ingestion_log_heartbeat.sql` (inerte até ser registrada).

- [ ] Registrar `add_ingestion_log_heartbeat.sql` em `services/startup.py::MIGRATION_FILES` (na ordem correta) e validar em 1 tenant.
  - EVIDÊNCIA: colunas `started_at`/`heartbeat_at` existem; boot sem erro (`Migration OK`).
- [ ] Adotar `run_log(...)` fonte a fonte (trocar o `INSERT ... ingestion_log` do fim). Gradual — validar cada fonte por 1 rodada antes da próxima.
- [ ] Watchdog: marcar `status='running'` com `heartbeat_at` velho (> limite) como stale/error (código a acrescentar em `watchdog_coleta.py` quando a coluna existir).

---

## M-5 / M-7 — diagnóstico (read-only, produção pendente)

- [ ] `DATABASE_URL_SYNC=<tenant> python scripts/diagnostico_auditoria.py` em cada tenant.
  - RESULTADO ESPERADO: M-5 sem colisões de chave CAGE-RS; M-7 sem planos TE com CNPJ divergente do município.
  - EVIDÊNCIA: colar a saída. Só há correção de histórico se M-7 apontar linhas com regra inequívoca (o script NÃO corrige nada).

---

## A-2 — sessão gov.br / SIGCON

- [ ] Confirmar keepalive de pé (processo `govbr_keepalive` vivo) e `govbr_sessao`=`success` (hoje `parcial` nos 6).
  - EVIDÊNCIA: `GET /api/status/ingestao` → `govbr_sessao` success; próxima rodada `sigcon_scraper` com `rec>0` (hoje 0 por sessão morta às 06:05).

---

## Validação pós-deploy (obrigatória nos 6)

- [ ] Freitas · [ ] Trust · [ ] Monte Sião · [ ] Santa Maria · [ ] Nova Palma · [ ] BGK
  - Após o deploy das correções de código, observar o **painel de frescor** por ~24 h: nenhum `partial`/`error` NOVO que seja falso-positivo das mudanças de status (A-1/M-3). Se aparecer, ajustar o limiar da fonte — **não** reverter para `success` cravado.
