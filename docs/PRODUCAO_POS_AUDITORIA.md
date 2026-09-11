# Produção pós-auditoria — runbook por fonte (11/09/2026)

O que rodar em produção **depois** que a branch `fix/auditoria-coleta-status-e-valores`
(PR #472) entrar, fonte a fonte, com **procedência do comando explícita**. A sessão de
correção **não tem acesso a produção nem ao Coolify** — então tudo que depende de
Coolify está marcado, não inventado.

**Este documento não duplica dois vizinhos** (regra do CLAUDE.md — um fato, um lugar):
- A **lista de tarefas** de fechamento (worker externo C-1/C-2, rollout A-3, M-5/M-7)
  está em [`CHECKLIST_CORRECOES_AUDITORIA.md`](CHECKLIST_CORRECOES_AUDITORIA.md).
- O **catálogo das Scheduled Tasks** (locks, timeouts, horários por tenant, convenção
  `flock -n` + `timeout -k 30 N` + `2>&1`) está em [`INFRA.md`](../INFRA.md) §5,
  reconferido contra a API do Coolify em 04/09/2026.

Aqui fica o que falta: **por fonte, o comando exato e de onde ele vem.**

## Legenda de procedência

| Marca | Significado |
|---|---|
| **[CÓDIGO]** | O comando sai do próprio repo — o bloco `if __name__ == "__main__"` do módulo define o entry point. Posso afirmar com certeza. |
| **[COOLIFY — REQUER CONFIRMAÇÃO]** | O *wrapper* (flock/timeout/horário) e a *existência* da Scheduled Task só existem na config do Coolify, fora do repo. A string abaixo é a **convenção** de INFRA.md §5 aplicada — **conferir/rodar no Coolify**, não colar às cegas. |

---

## A. O que entra sozinho com o merge (só código — nenhum comando de produção)

Estas correções são deploy puro: a merge para `main` builda e sobe os 6 tenants
(`build-backend.yml`). Não há comando a rodar; a evidência é o **painel de frescor**
depois do deploy.

| Correção | Arquivo | Evidência pós-deploy |
|---|---|---|
| A-1/M-3 — status honesto (não 'success' cravado) | `simec_par.py`, `cauc_ingest.py`, `acordofes_ingest.py`, `sigcon_ckan_backfill.py`, `consulta_popular_rs.py`, `cofin_ses_go.py` + `status_coleta.py` | Frescor pode passar a mostrar `partial`/`error` **verdadeiros** onde antes havia verde falso. Não reverter para `success` — ajustar limiar se for falso-positivo. |
| M-2 — `_money` (ponto decimal ≠ milhar) | `siconv_emenda_backfill.py` | `valor_emenda` deixa de aparecer 100× inflado (o caso `1234.56 → 123456`). |
| M-1 — COALESCE (não zera cláusula suspensiva) | `siconv_convenio_backfill.py` | Cláusula suspensiva preservada entre passadas. |
| M-4 — SAVEPOINT por município | `cofin_ses_go.py` | Um município de GO ruim não derruba o run inteiro para `error`. |
| C-3 (código) — zero-guard + transação única no TRUNCATE | `siconv_federal_ingest.py` | Recarga vazia **não** zera a base (rollback); `status='error'`. Coberto por 5 cenários de teste com banco falso. |
| Item 6 — watchdog acha fonte crítica órfã | `watchdog_coleta.py` | Watchdog emite `fonte_nunca_executada` para `siconv_federal`/`siconv_empenho_aberto` enquanto não houver task (ver B.1). |
| §12 — 403 do TCE-RS vira `error` | `tce_rs.py`, `tce_rs_portal.py` | Bloqueio de IP sai `error` no log, nunca `partial`/`success`. |
| C-1 (log) — Transparência-MG observável | `transparencia_mg.py` | 403-por-IP passa a gravar `ingestion_log` `error` (antes: silêncio). |
| A-4 — `backfill_parlamentar` grava log | `siconv_emenda_backfill.py` | Fonte `siconv_emenda_backfill` deixa de aparecer no frescor "sem escritor". |

> Nota de risco do deploy: a única mudança de **comportamento visível** é o status
> honesto (A). Nada acima muda schema. A migration do A-3 (B.4) fica **inerte** — só
> corre se alguém a registrar em `MIGRATION_FILES`.

---

## B. O que exige um passo em produção (comando por fonte)

### B.1 — `siconv_federal_ingest` e `siconv_empenho_aberto` (federais órfãos)

A auditoria pegou as duas **sem Scheduled Task e sem uma linha** em `ingestion_log`
(por isso o BGK aparece com `siconv_federal=0`). O código está pronto; falta **criar a
task** (são pesadas — dump ~200 MB — então não entram no orçamento do `sigcon`).

- **COMANDO (script)** — **[CÓDIGO]** (`if __name__=="__main__"` roda `ingest()` / `coletar()`):
  - `python -u ingestion/siconv_federal_ingest.py`
  - `python -u ingestion/siconv_empenho_aberto.py`
- **COMANDO (Scheduled Task Coolify)** — **[COOLIFY — REQUER CONFIRMAÇÃO]** (convenção INFRA.md §5, lock próprio porque é `httpx` puro, fora do `/tmp/scraper.lock` do Chromium):
  - `flock -n /tmp/siconv_federal.lock timeout -k 30 1800 python -u ingestion/siconv_federal_ingest.py 2>&1`
  - `flock -n /tmp/siconv_empenho.lock timeout -k 30 1200 python -u ingestion/siconv_empenho_aberto.py 2>&1`
  - ⚠️ Horário/escalonamento por tenant e **se a task deve existir nos 6** são decisão de operação — não estão no código. Confirmar no Coolify.
- **LOCAL:** worker de cada tenant (a base é consultada por CNPJ em todos). 1×/dia, fora da janela do `sigcon`.
- **RESULTADO ESPERADO:** `ingestion_log source='siconv_federal' status='success'`, `records_inserted` na casa do milhão; linha `siconv_empenho_aberto`.
- **EVIDÊNCIA:** `GET /api/status/ingestao` → `counts.siconv_federal > 0` e `success` do dia; watchdog para de emitir `fonte_nunca_executada`. **BGK deve deixar de ser 0.**

### B.2 — `transparencia_mg` (403 por IP de datacenter)

Memória [transparencia-mg-403-vps]: o portal recusa o IP da VPS — o coletor está
**correto** e nunca funciona de dentro. Agora é **observável** (grava `error`).

- **COMANDO** — **[CÓDIGO]** para o script; o **LOCAL** é a parte que requer decisão:
  - `DATABASE_URL_SYNC=<url_do_tenant_MG> python -u ingestion/transparencia_mg.py`
- **LOCAL** — **[COOLIFY/INFRA — REQUER CONFIRMAÇÃO]**: host com **IP residencial/proxy permitido**, NÃO a VPS. Provisionar worker externo com rede ao Postgres do tenant.
- **RESULTADO ESPERADO:** `transparencia_mg_empenhos` cresce; `ingestion_log` `success`.
- **EVIDÊNCIA:** as colunas **Data de pagamento/empenho do estadual (PR #471) deixam de sair em branco** — é a mesma fonte RM ([memória rm-modelo], correção do dono).
- ⚠️ **Não** burlar o WAF (sem trocar UA para enganar, sem proxy abusivo). Só IP permitido.

### B.3 — `tce_rs` (CKAN) e `tce_rs_portal` (portal)

Mesmo caso do B.2 — `tce.rs.gov.br` inteiro recusa o IP da VPS (INFRA.md; docstring
do `tce_rs_portal.py`). Rodar de fora.

- **COMANDO** — **[CÓDIGO]**:
  - `DATABASE_URL_SYNC=<url_tenant_RS> python -u ingestion/tce_rs_portal.py`
  - (e/ou `tce_rs.py` — mesmo acervo, host diferente)
- **LOCAL** — **[REQUER CONFIRMAÇÃO]**: worker de IP permitido, por tenant do RS.
- **RESULTADO ESPERADO:** `tce_rs_licitacoes`/`_contratos`/`_obras` populam; `ingestion_log` `success`/`partial` (não `error` de bloqueio).
- **EVIDÊNCIA:** contagem das tabelas > 0 nos tenants RS; a nota `NOTA_BLOQUEIO` some do log. ⚠️ A 1ª carga do portal leva **várias noites** (valor só no detalhe, 1 req/contrato; Santa Maria = 6.213) — cada rodada grava `success` e continua de onde parou.

### B.4 — A-3 heartbeat (job morto) — rollout gradual

Preparado e **inerte**: `services/ingest_heartbeat.py` + `migrations/add_ingestion_log_heartbeat.sql`
(fora de `MIGRATION_FILES`). Passo a passo em [CHECKLIST](CHECKLIST_CORRECOES_AUDITORIA.md) A-3.

- **COMANDO** — **[CÓDIGO]** (registrar a migration é edição de código, validável local com pglast):
  - registrar `add_ingestion_log_heartbeat.sql` em `services/startup.py::MIGRATION_FILES` (ordem correta) → deploy → boot grava `Migration OK`.
- ⚠️ **Decisão pendente:** adotar `run_log(...)` fonte a fonte é gradual e **não** deve entrar nesta branch — cada fonte validada por 1 rodada antes da próxima.

### B.5 — Diagnóstico M-5/M-7 (read-only)

- **COMANDO** — **[CÓDIGO]** (`scripts/diagnostico_auditoria.py`, sessão `read-only`, **não corrige nada**):
  - `DATABASE_URL_SYNC=<tenant> python scripts/diagnostico_auditoria.py`
- **EVIDÊNCIA:** colar a saída por tenant. Só há correção de histórico se M-7 apontar linhas com regra inequívoca.

---

## C. O que esta sessão NÃO fez (e por quê)

| Item | Por que não | Quem decide / próximo passo |
|---|---|---|
| Criar/alterar Scheduled Task no Coolify (B.1) | Sem acesso ao Coolify; a API não tem endpoint de execução ([memória coolify-api-limites]) | Operação, no Coolify — usar as strings de B.1 como proposta |
| Rodar B.2/B.3 de fora | Sem worker de IP permitido; a VPS é justamente a bloqueada | Provisionar host externo (CHECKLIST C-1/C-2) |
| Validar em produção (`/api/status/ingestao`) | O control token disponível foi **rejeitado (401)** nos 6 tenants — rotacionado ou de outro sistema | Dono emitir token `control` válido → então dá para conferir os `counts`/`ingestion_log` sem deploy |
| Registrar a migration A-3 | Decisão de rollout gradual (§B.4); não cabe misturar com as correções de status | Dono decidir a janela |
| **Merge / deploy do PR #472** | Instrução explícita: **não** mergear/deployar nesta sessão | Dono aprovar quando quiser |

> **Estado da branch:** código pronto e **testado localmente** (suite completa verde +
> testes de comportamento com banco falso para os 5 cenários do TRUNCATE, o
> `backfill_parlamentar` e o watchdog). O que falta é **exclusivamente** o que depende
> de produção/Coolify/decisão — listado acima, sem nada inventado.
