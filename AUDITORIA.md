# AUDITORIA TÉCNICA — Workspace PACTHA

**Produto:** PACTHA — SaaS de gestão de convênios, repasses e emendas parlamentares para prefeituras, consórcios e assessorias (Alavank Tecnologia).
**Repositórios auditados:** `pactha/` (produto/tenant) e `console-alavank/` (Central de Comando / control plane).
**Data:** 2026-07-15 · **Escopo:** somente leitura (nenhum código alterado).
**Método:** 8 auditores especializados em paralelo (stack, backend, frontend, ingestão, modelo de dados, console, segurança, dívida técnica), leitura integral dos arquivos citados, com referências `arquivo:linha`. As conclusões de segurança de maior severidade foram reconferidas por leitura direta do código.

> **Nota de método sobre segurança:** a rodada de verificação adversarial automatizada foi interrompida por limite de sessão. Os achados críticos de segurança abaixo têm evidência `arquivo:linha` e foram corroborados de forma cruzada entre a dimensão de segurança e a de inventário de backend (ambas apontam, de forma independente, o IDOR do cofre, o control token onipotente e a credencial-semente). Onde marco **[confirmado por leitura direta]**, reli o arquivo pessoalmente durante a consolidação. Trate os itens não marcados como **altamente prováveis, a validar em code review** antes de qualquer conclusão de compliance.

---

## Sumário executivo

O PACTHA é um produto **real e funcional**, tecnicamente ambicioso na parte difícil (scraping de portais governamentais JS-pesados, cofre AES-256-GCM, IA com tool-use sobre o banco, control plane multi-cliente com 2FA). O escopo funcional bate com o que a pesquisa de mercado descreve e supera consultorias de captação. Mas a auditoria de código revela três problemas estruturais que precisam ser resolvidos **antes** de escalar para novos clientes:

1. **Multi-tenant é só físico (1 deploy por cliente), e o código comum está contaminado pela Freitas.** Não há `tenant_id` nem schema por cliente — o isolamento é ter um container+banco por cliente. Porém o código é **compartilhado pelos 3 clientes**, e a identidade da Freitas (cliente-fundador) está hardcoded no prompt da IA, no mapa de municípios do FNS, no rodapé do relatório e no seed. Todo cliente novo nasce "com cara de Freitas". **Esta é exatamente a bagunça que a inteligência competitiva previu.**

2. **Cadeia de segurança crítica no tenant.** Credencial-semente de super-admin fraca e commitada em docs; `must_change_password` não é enforçado no backend; **IDOR no /reveal do cofre** (qualquer admin lê credenciais e sessões gov.br de qualquer município); **control token com poder total** (`control:*`) e allowlist de IP desligada em produção. Como o cofre concentra sessões de impersonação de portais federais de vários municípios, é um alvo de altíssimo valor.

3. **Fragilidade de bootstrap e observabilidade cega.** Um deploy 100% novo (cliente novo) provavelmente **quebra** (colunas fantasma no ORM, `DROP CASCADE` a cada boot, dependência que falta). Os deploys atuais só funcionam porque vieram migrados do banco antigo (Neon). E o `ingestion_log` grava sempre `success` — falha de scraper nunca vira alarme; 3 fontes não têm agendamento e congelam sem aviso.

Nenhum arquivo `.env` real está commitado (só `.env.example` com placeholders). As exceções são a senha-semente fraca (`pactha2026` em docs) e a topologia de infra (IP fixo do Coolify + UUIDs de recursos em docs).

**A boa notícia:** a Central de Comando (`console-alavank`) tem um desenho de segurança bem mais maduro (2FA obrigatório, refresh revogado no DB com detecção de replay, validação de força de segredos em produção). Vários dos endurecimentos que faltam no tenant já existem prontos no console e podem ser portados.

---

## 1. STACK REAL

### 1.1 Visão por repositório

| Camada | `pactha` (produto) | `console-alavank` (control plane) |
|---|---|---|
| **Backend** | Python 3.12 + FastAPI + Uvicorn (`--workers 2`) | Python 3.12 + FastAPI + Uvicorn (**`--workers 1` por design** — estado in-memory) |
| **Frontend** | Next.js 16.2.3 (App Router, standalone) + React 19.2.4 + TS 5.9.3 | Next.js 16.2.3 + React 19.2.4 + TS 5.9.3 |
| **Estilo** | Tailwind v4.3.0 + daisyUI 5.6.6 (temas `pactha`/`pactha-dark`) + shadcn/base-ui | Tailwind 4.3.2 + daisyUI 5.6.18 + shadcn/base-ui |
| **Banco** | PostgreSQL 16 (Coolify) | PostgreSQL próprio (`console-db`) |
| **ORM** | SQLAlchemy 2.x async (asyncpg) na API; psycopg2 sync nos scrapers/migrations | SQLAlchemy 2.x async |
| **Worker** | Sim — Dockerfile.scraper + Chromium + 5 crons | Não tem |
| **Extensão** | Chrome MV3 (JS vanilla) — captura de sessão gov.br | — |
| **Exclusivos front** | react-markdown/remark-gfm (chat IA), recharts, date-fns | leaflet/react-leaflet/leaflet.heat (mapa da frota), qrcode.react (2FA) |

### 1.2 Bibliotecas principais (backend pactha)

FastAPI ≥0.115 · Uvicorn ≥0.34 · SQLAlchemy[asyncio] ≥2.0 · asyncpg ≥0.30 (async, API) · **psycopg2-binary** ≥2.9 (sync, scrapers+migrations) · pydantic ≥2.10 · PyJWT[crypto] ≥2.9 · bcrypt ≥4.2 · **cryptography** ≥43 (cofre AES-256-GCM) · httpx ≥0.28 · **curl_cffi** ≥0.7 (anti-Cloudflare do SIMEC) · **playwright** ≥1.49 + playwright-stealth ≥2.0 (SIGCON, TransfereGov, gov.br) · beautifulsoup4 ≥4.12 · **anthropic** ≥0.50 (IA — modelo `claude-opus-4-8` fixado em `routers/ai.py:38`) · reportlab ≥4.2 + python-docx ≥1.1 (PDF/DOCX).

**Deps declaradas e NÃO usadas:** `pandas` (nenhum import — ingestão usa `csv` da stdlib) e `slowapi` (o rate-limit real é custom in-memory). Incham as imagens e o `slowapi` fantasma sugere um rate-limit global que não existe.

### 1.3 Infra / deploy real

- **Coolify em 1 VPS Hetzner** (IP `5.78.42.251`). Dois projetos: `pactha` (tenants) e `alavank-control` (console).
- **Por tenant: 4 resources** — Postgres 16-alpine (interno) · API (`Dockerfile.api`) · Frontend (`Dockerfile`, standalone) · **Worker** (`Dockerfile.scraper`, `CMD sleep infinity`, roda os crons).
- **5 Scheduled Tasks (crons)** anexadas ao Worker: `sigcon` (0 */6 * * *), `transferegov` (0 5 * * *), `fns` (30 5 * * *), `govbr-renew` (*/15 * * * *), `queue-sigcon` (*/2 * * * * — fila on-demand).
- **Domínios `*.sslip.io`** (sem DNS custom completo). Migração para `pactha.alavank.com.br` / `console.alavank.com.br` em transição. O Next.js faz rewrite de `/api` para a API interna (same-origin, contorna o problema de cookie cross-site do sufixo público `sslip.io`).
- **Sem CI/CD.** Nenhum `.github/`, docker-compose ou Caddyfile. Deploy = **push no `main` → webhook do Coolify** com Watch Paths (`frontend/**` vs `backend/**`). **Os 3 tenants compartilham `alavank/pactha`** → um push em `backend/**` rebuilda as 3 APIs ao mesmo tempo.

### 1.4 Riscos de versão

- **[ALTA] Backend Python sem pin e sem lockfile.** Todos os ranges são `>=` sem lockfile/hashes. Cada build resolve o "latest" do PyPI → builds não reprodutíveis. Como um push rebuilda os 3 clientes, um breaking change de dependência derruba a frota inteira num único deploy.
- **[MÉDIA] Imagens com tag flutuante** (`python:3.12-slim`, `node:20-slim`, `postgres:16-alpine`) sem digest. Node 20 provavelmente já no EOL (verificar) → migrar para Node 22 LTS.
- **[MÉDIA] `npm install --legacy-peer-deps`** em vez de `npm ci`, com lockfile opcional (`package-lock.json*`) → build de produção pode divergir do lock testado.
- **[BAIXA] Frontends "gêmeos com deriva":** console sistematicamente mais novo que o tenant (tailwind, daisyui, axios, recharts) — componentes espelhados (permissões, UI) podem divergir de comportamento.

---

## 2. INVENTÁRIO DE MÓDULOS

### 2.1 Três eixos de autenticação (backend pactha)

| Principal | Header/origem | Escopo | Usado por |
|---|---|---|---|
| **Usuário (JWT)** | Cookie `pactha_access` ou `Authorization: Bearer` | role + telas + municípios | maioria dos routers |
| **Service token (scraper)** | `X-Service-Token`, `kind='scraper'` | `secret:*`, `session:write` | session_capture |
| **Control token (Console)** | `X-Control-Token` + `X-Tenant-Slug`, `kind='control'` | `control:*` | control.py |

RBAC de tela: `admin` vê tudo; não-admin tem conjuntos em `user_telas`/`user_municipios`, enforçados por `ensure_tela` / `ensure_municipio_access`. Catálogo de 15–17 telas em `telas_catalog.py`; `cofre` e `sessoes` são excluídos do usuário-cliente de propósito (operacionais Alavank).

### 2.2 Módulos por domínio funcional (produto `pactha`)

**MONITORAMENTO**
| Tela / rota | Backend | O que faz |
|---|---|---|
| `/dashboard` | `municipios`, `convenios` | KPIs (convênios, voluntárias, valores, alertas 60/120d, prestação de contas), gráfico por situação, mudanças de status |
| `/dashboard/convenios` | `routers/convenios.py` (`/api/convenios`) | SIGCON-MG estadual + federais: lista paginada, filtros, refresh on-demand (enfileira job), export PDF, detalhe |
| `/dashboard/emendas` | `routers/emendas_estaduais.py` | Emendas parlamentares estaduais MG por ano, stats |
| `/dashboard/transferegov` (+6 rotas) | `routers/transferegov.py` | Plano de Ação / Transferência Especial (Pix parlamentar) ao vivo; voluntárias/rejeitadas/encerradas (SICONV); por-CNPJ |
| `/dashboard/fns` | `routers/fns.py` | Fundo Nacional de Saúde ao vivo (proxy `consultafns.saude.gov.br` com cookies do cofre) |
| `/dashboard/simec` | `routers/simec.py` | SIMEC-PAR/MEC: dimensões do PAR + liberações (PNAE/PNATE/PDDE) |
| `/dashboard/cauc` | `routers/cauc.py` | Regularidade fiscal federal (CAUC/Tesouro) |
| `/dashboard/acordofes` | `routers/acordofes.py` | Dívida da saúde SES-MG (Acordo FES) |
| `/dashboard/dou` | `routers/dou_mg.py` | Diário Oficial MG (proxy ao vivo, extrai PDF de PKCS#7) |

**ALERTAS** — Não há página dedicada; alertas de vigência e mudanças de status vivem no dashboard. Notificação externa é o Telegram: `routers/telegram.py` + `routers/status_changes.py` (trigger no banco alimenta o aviso). O bot Telegram encaminha mensagens livres para a IA.

**PARLAMENTARES** — `routers/parlamentares.py`: agrega 4 fontes (SIGCON, voluntárias, emendas estaduais, planos de ação RP9) por parlamentar e finalidade.

**COFRE + SESSÕES GOV.BR** — `routers/cofre.py` (CRUD + reveal de credenciais AES-256-GCM) e `routers/session_capture.py` (recebe cookies capturados pela extensão/bookmarklet, cifra no cofre, auto-dispara scraper). Telas `/dashboard/cofre` e `/dashboard/sessoes` (super-admin only no front).

**IA** — `routers/ai.py` (`/api/ai/chat`): Claude `claude-opus-4-8` com tool-use manual (11 ferramentas sobre o banco: SIGCON, voluntárias, SIMEC, emendas, FNS, plano de ação, busca por parlamentar). Padrão text-to-query sobre base estruturada. Reusado pelo bot Telegram **sem os gates de tela/município**.

**RELATÓRIOS / DOCUMENTOS** — `routers/rm.py` (Relatório de Monitoramento "padrão Freitas", conteúdo em JSONB, PDF), `routers/documentos.py` (geração dirigida por schema, export DOCX/PDF), `routers/export_pdf.py` (PDFs de cada tela).

**GESTÃO INTERNA** — `routers/gestao.py`: anotações internas (status próprio, protocolo, anexos base64) paralelas ao dado oficial, sem corromper a fonte.

**ADMIN** — `routers/users.py` (CRUD de usuários, admin-only), `routers/municipios.py`, `routers/service_tokens.py` (**super-admin único por e-mail hardcoded**), `routers/control.py` (canal do Console, 25+ endpoints escopados por `control:*`).

### 2.3 Endpoints mortos, quebrados ou suspeitos

- **QUEBRADOS:** `export-pdf/voluntarias` e `export-pdf/plano-acao` (`export_pdf.py:148,218`) chamam `transferegov.voluntarias(..., _=None)` / `buscar(..., _=None)`, mas o parâmetro é `current`, não `_` → **`TypeError` em runtime**. Evidência de refactor que renomeou `_`→`current` sem atualizar 2 call sites. **[confirmado por leitura direta do relatório de backend]**
- **IDOR sistemático:** endpoints de detalhe/mutação por ID em `rm`, `documentos`, `gestao`, `convenios /estadual/{id}` e `fns` exigem apenas `get_current_user` — sem `ensure_tela`/`ensure_municipio_access`. Usuário restrito lê/altera recurso de outro município. (Ver §6.)
- **Tela `dou` nunca aplicada** no backend — qualquer autenticado usa o proxy do Jornal MG.
- **Webhook Telegram fail-open:** se `TELEGRAM_WEBHOOK_SECRET` estiver vazio, a validação é pulada e o webhook fica público.
- **`/api/status/ingestao` aberto sem auth** — expõe contagens de tabelas, fontes e erros de jobs.
- **Role `gestor` inatingível:** o cofre exige `{admin, gestor}`, mas a criação de usuário só aceita `admin|analyst|user` → cofre é de facto admin-only e o ramo `gestor` é código morto.

### 2.4 Central de Comando (`console-alavank`) — inventário

- **Auth:** `/api/auth` com 2FA TOTP obrigatório (login em 2 passos), refresh revogado no DB com rotação atômica e detecção de replay, CPF como fator N2.
- **Instâncias:** `/api/instances` (CRUD, escopo por `allowed_instance_ids`) + `/api/instances/{id}/control/*` (proxy para `/api/control/*` do tenant: status, jobs, ingestão, fontes, auditoria, cofre, sessão, SSO, municípios, usuários do cliente).
- **Equipe:** `/api/console-users` (RBAC com CATALOG de 19 permissões, ROLE_BASELINE, OWNER_ONLY_GRANTS; trava do último owner ativo com `SELECT ... FOR UPDATE`).
- **CRM:** `/api/clientes`, `/api/archive` (municípios arquivados), `/api/overview` (KPIs + mapa da frota + atividade em tempo real).
- **Provisionamento:** `/api/provision/control-token` (server-to-server via `X-Provision-Secret`). **Não cria nada no Coolify** — apesar dos 7 UUIDs Coolify no modelo `Instance`, não existe cliente HTTP para o Coolify no código; o provisionamento real de infra é escopo futuro e hoje é manual.
- **Hub da instância (por abas):** Dados & ingestão, Monitor de APIs, Credenciais (cofre + sessão gov.br), Usuários, Auditoria — todas funcionando. **Contratos / Financeiro / Chamados são placeholders** (permissões existem no CATALOG, nenhum endpoint as consome).
- **SSO técnico "entrar no sistema do cliente":** cria usuário de suporte `alavank-sso.*` com role **admin** no tenant + token SSO de uso único (2min).

---

## 3. FONTES DE DADOS E COLETA

### 3.1 Panorama

~16 fontes/pipelines, mas **apenas 5 têm Scheduled Task**. A "interface comum" entre scrapers **praticamente não existe** — os 3 módulos-base (`_resilience.py`, `base.py`, `scraper_base.py`) têm **zero importadores** em produção; cada script reimplementa conexão, cookies e decode de JWT (15+ cópias).

| Fonte | Método | Login/credencial | Agendamento | Grava em |
|---|---|---|---|---|
| **SIGCON-MG** (convênios+emendas estaduais) | Playwright (portal JSF) | CPF+senha do Cofre | cron 6/6h + fila on-demand | `convenios_estadual`, `emendas_estaduais` |
| **SIGCON CKAN backfill** | httpx (CSV.gz `dados.mg.gov.br`) | — | dentro do cron sigcon | `convenios_estadual` (UPDATE) |
| **CAUC** | httpx (CKAN Tesouro, CSV) | — | dentro do cron sigcon/fila | `cauc_situacao` |
| **Acordo FES** | httpx + **openpyxl** (XLSX SES-MG) | — | dentro do cron sigcon/fila | `acordofes_credor` (TRUNCATE+INSERT) |
| **TransfereGov Voluntárias** | Playwright **guest** (`Usr=guest`) | nenhum (auth gov.br desativada) | cron 05:00 + auto-dispatch na captura | `transferegov_propostas` |
| **SICONV backfills** (emenda/convênio) | httpx (ZIPs open data, até 199 MB) | — | encadeado no run do transferegov | `transferegov_propostas` (UPDATE) |
| **FNS** | httpx REST (`consultafns`) | **sessão (cookies)** do Cofre | cron 05:30 (`run_fns_local.py`) | `convenios_estadual` (fonte='FNS') |
| **SIMEC-PAR** | **curl_cffi** (anti-Cloudflare) | — | **SEM agendamento** ⚠️ | `simec_par_*` |
| **SICONV federal** (por CNPJ) | httpx (ZIPs 200MB) | — | **SEM agendamento** ⚠️ (manual) | `siconv_federal` (TRUNCATE) |
| **Extractor emendas estaduais** | SQLAlchemy (regex sobre `convenios_estadual`) | — | **SEM agendamento** ⚠️ (manual) | `emendas`, `parlamentares` |
| **Diário Oficial MG** | httpx proxy tempo-real | JWT público | on-demand | não persiste |
| **gov.br renew** (máquina de sessão) | Playwright re-deriva SAML sem login | cofre `automation_key='govbr'` | cron */15min | `cofre_senhas` (UPDATE cookies) |
| **Extensão Chrome** | MV3 service worker (cookies httpOnly) | service token `session:write` | client-side (nav/cookie/keep-alive 12min) | `cofre_senhas` via `session_capture` |

### 3.2 Fila on-demand (`scraper_jobs` → `run_queue_sigcon`)

```
UI "Atualizar SIGCON"  /  Console POST /api/control/refresh
        └──► INSERT scraper_jobs (tipo='sigcon', status='pending')
             WHERE NOT EXISTS (pending|running)   ← dedup robusto
                       │  (fila no Postgres)
 Coolify Scheduled Task "queue-sigcon" (*/2min)
        └──► _claim_job: cura órfãos (running > 30min → error) ;
             SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1 (1 job por vez)
        └──► pipeline: CAUC+AcordoFES → sigcon_scraper → ckan_backfill
        └──► _finish_job: status 'done' ou 'error'+mensagem
```
Dedup e cura de órfãos bem feitos. **Mas a fila só suporta `tipo='sigcon'`** — não há fila para FNS/TransfereGov/SIMEC.

### 3.3 Fragilidades de coleta (ordenadas)

1. **[ALTA] `openpyxl` não está no `requirements.txt`** (usado em `acordofes_ingest.py:20`) → Acordo FES quebra com `ModuleNotFoundError`, engolido pelo except genérico → tabela **nunca populada, falha silenciosa**.
2. **[ALTA] SIMEC, SICONV federal e extractor de emendas sem agendamento** — tabelas lidas pelo produto (telas, RM, IA) **congelam** desde a última execução manual, sem qualquer alarme. O docstring do SIMEC ainda diz "cron (Railway)" — cron que não existe no Coolify.
3. **[ALTA] `ingestion_log` sempre `status='success'`** — hardcoded em 100% dos 10 INSERTs, gravado só ao fim de uma run bem-sucedida. Nenhum scraper grava `error`/`running`. `run_fns_local` **nem grava**. Observabilidade de falha inexistente; o Monitor da Central só vê `success` ou nada.
4. **[MÉDIA] `verify=False` (TLS desabilitado) generalizado** — em ~13 coletores, inclusive downloads de 199 MB e leitura de sessão FNS. Como muitos fazem `TRUNCATE+INSERT`, conteúdo adulterado (MITM) seria persistido direto.
5. **[MÉDIA] `TRUNCATE` sem proteção** em `acordofes` e `siconv_federal` — se o parse subsequente falhar, a tabela fica vazia até a próxima run.
6. **[MÉDIA] Dependência frágil de sessão gov.br / anti-bot** — SICONV legado exige SAML em browser real; SIMEC exige curl_cffi; login gov.br tem reCAPTCHA e é explicitamente não-automatizável → toda atualização federal depende de re-captura manual pela extensão quando o SSO expira.
7. **Escopo por convenente do SIGCON** — só municípios com credencial própria no Cofre são cobertos (hoje efetivamente só Araújos).
8. **Colisão de nomes:** `ingestion/emendas_estaduais.py` grava na tabela **`emendas`**; a tabela **`emendas_estaduais`** é gravada por `sigcon_scraper.py`.

### 3.4 Scripts obsoletos/duplicados

`govbr_keepalive.py` (loop Railway, órfão), `renovar_sessao_govbr.py` (login com reCAPTCHA, abandonado), `fns_scraper.py`+`scraper_base.py` (arquitetura service-token que aponta para `/api/internal/*` **inexistente** — e o `docs/SECURITY_CREDENTIALS.md` ainda documenta essa arquitetura morta como vigente), `_resilience.py`/`base.py` (0 importadores), `run_one` em `transferegov_voluntarias.py` (caminho legado divergente).

---

## 4. MODELO DE DADOS

### 4.1 Como o multi-tenant está modelado HOJE

**Resposta direta: NÃO existe `tenant_id` e NÃO existem schemas separados. O isolamento é 100% físico, por deploy — cada cliente tem seu conjunto de containers + banco Postgres próprio.** A identidade do deploy é a env `INSTANCE_SLUG`, usada só como checagem anti-misrouting no canal de controle (o Console manda `X-Tenant-Slug`, o tenant rejeita com 409 se divergir).

**Dentro de um deploy, a dimensão de escopo é `municipio_id`** (uma assessoria atende N municípios). Controle de acesso é **por usuário**, não por linha (RLS): admin vê tudo; não-admin só o que está em `user_municipios`, enforçado em runtime pela aplicação. **Não há Row-Level Security no Postgres.**

- **Amarrado a município:** `convenios_estadual`, `transferegov_propostas`, `emendas_estaduais`, `cauc_situacao`, `acordofes_credor`, `simec_par_*`, `rm_relatorios`, `gestao_anotacoes`, `documentos_gerados`, `status_changes`, `cofre_senhas`, `telegram_users`.
- **Global ao deploy:** `users`, `user_telas`, `service_tokens`, `audit_log`, `ingestion_log`, `scraper_jobs`, `sso_used_jti`, `parlamentares`, e `siconv_federal` (base nacional consultada por CNPJ).

### 4.2 Como o schema nasce (frágil)

O tenant **não usa Alembic**. Três fontes aplicadas a cada boot: (1) `setup_db.create_tables()` (SQL cru idempotente), (2) `Base.metadata.create_all(checkfirst=True)` sobre **7 dos ~27 models**, (3) 28 migrations SQL numa lista fixa, com advisory lock e tolerância a erro por arquivo. O Console é 100% derivado dos models + lista de `ALTER ... ADD COLUMN IF NOT EXISTS`.

**Tabelas:** ~27 vivas no tenant, 9 no console. Todas com finalidade clara (ver relatórios de origem). Destaques:
- `cofre_senhas` guarda credenciais **e** as sessões gov.br capturadas; coluna física `senha_hash` na verdade guarda **AES-GCM reversível** (nome legado enganoso).
- `service_tokens.kind` separa `scraper` de `control`.
- Console: `instances` (1 linha = 1 cliente = 1 deploy, com token de controle cifrado + 7 UUIDs Coolify), `console_users` (pool separado dos users dos tenants, 2FA e CPF cifrados).

### 4.3 Divergências e riscos estruturais (ordenados)

1. **[ALTA] `ConvenioEstadual` declara 12 colunas que nenhum SQL cria** (`models/convenio.py:32-44`: `fonte, banco, saldo_bancario`…). `create_all(checkfirst=True)` pula tabela existente. **Em deploy 100% novo, o ORM, o INSERT do FNS e o trigger de status quebram.** Só funciona hoje porque os bancos vieram do dump do Neon. **É o achado estrutural mais grave.**
2. **[ALTA] `drop_lean_tables.sql` (DROP CASCADE) roda a cada boot**, e `setup_db` recria as 7 tabelas-vítima antes — churn de DDL por boot e destruição silenciosa de qualquer dado que caia nelas.
3. **[MÉDIA] Integridade referencial ausente** nos módulos de 2026: `gestao_anotacoes`, `rm_relatorios`, `documentos_gerados`, `status_changes`, `simec_par_*` têm `municipio_id`/`criado_por` como INT **sem FK**. `gestao_anotacoes.anexos` guarda **arquivos base64 dentro do JSONB** (risco de inflar o banco).
4. **[MÉDIA] `transferegov_propostas` sem model e sem migration de criação** — só o `setup_db`; 6 migrations a ALTERam. Se o `setup_db` falhar (o startup segue mesmo assim), a cadeia quebra. (O gotcha do CONTINUAR.md:85 está **desatualizado** — a criação já foi movida para o setup_db.)
5. **[MÉDIA] `startup.py:81` referencia migration inexistente** `dedupe_convenios_unique.sql`.
6. **Tabela órfã** `edital_acompanhamento` (mismatch singular/plural com o drop); `automation_kv` criada ad-hoc em runtime, fora do pipeline de schema.
7. **Console:** cadeia tamper-evident `prev_hash`/`entry_hash` do `console_audit_log` **declarada mas nunca preenchida**; `instance_audit_events` e `coolify_targets` prontos mas sem código que os popule.

---

## 5. DÍVIDA E BAGUNÇA

### 5.1 Features de cliente (Freitas) no core — a bagunça central

O produto é single-tenant por deploy, mas **o código é comum aos 3 clientes**. Tudo hardcoded "Freitas" (o cliente-fundador) vaza para Trust, Monte Sião e qualquer cliente futuro. **Nenhum hardcode de "Trust" ou "Monte Sião" existe no core** — a contaminação é exclusivamente da Freitas, confirmando a hipótese da inteligência competitiva ("a assessoria quis ajustar tanto pra ela que bagunçou as funções").

| Local | Hardcode |
|---|---|
| `routers/ai.py:40` | Prompt da IA: "plataforma da **Freitas Consultoria**" + "**6 municípios de MG**" |
| `routers/fns.py:31` | `FNS_CODE_OVERRIDE` = os 6 municípios da Freitas |
| `routers/transferegov.py:231` | Regra de status "a Freitas considera também…" na SQL |
| `migrations/add_rm.sql:10` | Rodapé default do RM = **endereço físico** da Freitas |
| `services/rm_builder.py`, `rm_pdf.py`, `startup.py:44` | "padrão Freitas" no builder/PDF do RM |
| `setup_db.py:288-292` | **Seed cria 5 usuárias @freitas.com.br em TODO deploy** |
| extensão `popup.js`, `background.js:160` | Município default `6` = Piracema (município da Freitas) |

### 5.2 Duplicações

- **6 rotas `transferegov-*` → 3 telas reais** (4 wrappers de 13 linhas idênticos sobre o mesmo componente).
- **3 scrapers de sessão gov.br** (`govbr_renew` vivo, `govbr_keepalive` e `renovar_sessao_govbr` mortos).
- **`INSERT INTO ingestion_log` copiado em 10 scrapers**; conexão ao banco reimplementada em 15.
- **`crypto.py`/`audit.py` gêmeos derivados** entre os dois repos — o endurecimento da derivação de chave existe **só no Console**.
- **Componentes de UI** (`Section`/`Grid`/`Field`/`StatCard`) reimplementados por página; helpers de cookie duplicados entre `background.js` e `popup.js`.
- **Lógica de negócio duplicada** entre routers (sessão gov.br, categorias de voluntárias triplicadas, KPI de município).

### 5.3 Código morto

- `pactha/desing-inspiration-console/` — **368 KB** (print de tela + md de inspiração) versionado no repo do produto; nome com erro de digitação.
- `fns_scraper.py`+`scraper_base.py`+`_resilience.py`+`base.py` (0 importadores / endpoints inexistentes).
- 7 "tabelas-zumbi" recriadas e dropadas a cada boot.
- `Procfile` (Railway), deps `pandas`/`slowapi`, `run_one` legado.

### 5.4 Hardcodes de infra e nomenclatura

- **Guard de super-admin por e-mail** `admin@pactha.com.br` (backend `service_tokens.py` + front `layout.tsx`).
- **IP fixo do Coolify `5.78.42.251`** em 6 arquivos (código + docs + seed); UUIDs de recursos em `CONTINUAR.md`.
- Modelo de IA `claude-opus-4-8` hardcoded (deveria ser env).
- Nomenclatura: colisão `emendas`×`emendas_estaduais`; `senha_hash` que guarda ciframento; `edital_acompanhamento`×`editais_acompanhamento`; role `gestor` inatingível.

### 5.5 Ranking dos 10 piores focos

1. Hardcodes da Freitas no core comum → quebram a promessa multi-cliente.
2. `ConvenioEstadual` com colunas fantasma → bootstrap de cliente novo quebra.
3. `drop_lean_tables.sql` DROP CASCADE a cada boot.
4. `ingestion_log` sempre `success` + 3 fontes sem agendamento.
5. `openpyxl` faltando → Acordo FES quebra silenciosamente.
6. 3 módulos-base ignorados + 15 reimplementações de conexão.
7. `crypto.py`/`audit.py` gêmeos derivados (fix só no Console).
8. 6 rotas transferegov-* para 3 telas.
9. Código morto disfarçado de arquitetura (SECURITY_CREDENTIALS.md descrevendo `/api/internal/*` inexistente).
10. `desing-inspiration-console/` versionado.

---

## 6. SEGURANÇA

O cofre AES-256-GCM está **algoritmicamente correto** (AEAD, nonce aleatório de 12 bytes por operação, tag de integridade, formato `v1:base64`). O desenho do Console é maduro. Mas há uma cadeia de comprometimento crítica no **tenant**.

### 6.1 Achados críticos e altos

| # | Severidade | Achado | Evidência |
|---|---|---|---|
| 1 | **CRÍTICA** | **Credencial-semente de super-admin commitada + `must_change_password` não enforçado no backend.** `admin@pactha.com.br`/`pactha2026` está em `README.md:33` e `CONTINUAR.md:34`. O login devolve token válido mesmo com a flag ligada; `get_current_user` não a verifica → a troca é só um redirect de frontend. Um atacante que fala direto com a API loga como super-admin e cunha service tokens que leem todas as sessões gov.br. | `README.md:33`, `routers/auth.py:113`, `services/auth.py:162` **[confirmado — senha real em docs]** |
| 2 | **CRÍTICA** | **IDOR no `/reveal` do Cofre (e create/update/delete).** `cofre.py:121-222` só checa role `{admin,gestor}`, **sem** `ensure_municipio_access`/`ensure_tela` (contraste com a listagem, que checa). Um gestor escopado ao município A revela em claro a credencial e a **sessão gov.br** (cookies httpOnly) de qualquer outro município iterando o `item_id`. | `cofre.py:129` **[confirmado — 2 dimensões independentes apontam]** |
| 3 | **ALTA** | **Control token = god-mode do tenant.** Com `control:*` (bootstrap), um único token longevo (sem `expires_at`) revela qualquer credencial do cofre e **cunha usuário admin + SSO** (sessão admin completa). A allowlist `CONTROL_PLANE_ALLOWED_IPS` está **desligada em produção** → canal `/api/control/*` público, protegido só por token+HTTPS+slug. | `control.py:474`, `startup.py:206`, `console/CONTINUAR.md:134` |
| 4 | **ALTA** | **JWT em `localStorage` + CSRF pulado para Bearer.** O login grava o access token em `localStorage`; enviado como Bearer em todo lugar. CSRF só cobre cookie. Qualquer XSS = roubo de conta por ~60min, sem gate server-side de troca de senha e com revogação in-memory. | `login/page.tsx:37`, `lib/api.ts:20`, `services/auth.py:181` |
| 5 | **ALTA** | **Extensão exfiltra cookies httpOnly do gov.br.** `chrome.cookies.getAll` lê JSESSIONID/Session_Gov_Br_Prod/Govbrid (httpOnly) dos portais federais e POSTa para `/api/session-capture`, derrotando a proteção httpOnly. Centraliza credenciais de impersonação federal de vários municípios num alvo único (agravado pelos itens 2 e 3). | `extension/background.js:150` |
| 6 | **ALTA** | **Provisionamento sem 2FA, comparação não constant-time.** `POST /api/provision/control-token` sobrescreve o control token de qualquer instância só com `X-Provision-Secret` (comparação `!=`), sem auth de usuário; `PROVISION_SECRET` não é validado em produção. | `provision.py:22` |

### 6.2 Achados médios

- **Derivação de chave fraca no cofre do tenant** (zero-pad de chave curta) + `config.py` não valida força de `COFRE_KEY` (só do JWT). O Console já corrigiu isso — o tenant não.
- **`decrypt()` silencioso** retorna `""` em qualquer falha (inclusive AEAD/tamper) → adulteração indistinguível de vazio; erro de chave transforma o cofre em vazio sem alarme. Tokens sem prefixo `v1:` são servidos como plaintext.
- **Webhook Telegram fail-open** (secret vazio → sem auth).
- **Revogação de token in-memory** no tenant (logout/refresh perdem efeito em restart; refresh vive 30 dias).
- **Console sem CSP/HSTS** (headers mais fracos que o tenant, apesar de ser a "joia da coroa").
- **Reset de owner por env `OWNER_PASSWORD_RESET`** roda a cada boot se a env ficar setada (zera 2FA).
- **`reset-password` do painel de usuário gera senha fixa `"1234"`**.

### 6.3 Segredos / credenciais commitados (arquivo:linha, SEM valores)

**Nenhum `.env` real está commitado** (`.gitignore` cobre `.env*`; só `.env.example` com placeholders). Achados:

| Arquivo:linha | Tipo |
|---|---|
| `pactha/README.md:33`, `pactha/CONTINUAR.md:34` | **Senha de super-admin (valor real fraco)** — único segredo real no repo |
| `pactha/CONTINUAR.md:42-56` | IP fixo do Coolify + UUIDs de recursos (server, GitHub App, projeto, API/Front/Worker/DB) |
| `console/backend/config.py:25`, `.env.example:25`, `coolify_target.py:15` | IP fixo do Coolify (HTTP) como default no código |
| `console/backend/setup_console_db.py:124-128` | URLs/slugs dos 3 tenants |
| `pactha/backend/setup_db.py:287-293` | **PII: e-mails de analistas @freitas.com.br** semeados em todo deploy |
| `console/CONTINUAR.md:128`, `pptcc.md:99`, `relatório de desenvolvimento.md:208` | Referências (REDIGIDAS no repo) a token Coolify `41|…` e control token `pactha_ct_…` **expostos em chat** — os docs registram que **devem ser rotacionados** |

**Ação imediata recomendada:** rotacionar o token do Coolify e o control token da Freitas (os próprios docs pedem isso), trocar a senha de qualquer conta `admin@pactha.com.br` em produção, e remover a senha-semente do README.

### 6.4 Pontos fortes a preservar

Separação de 3 principais com `kind`+scope+slug; anti-misrouting por `X-Tenant-Slug`; SSO de uso único real (UNIQUE em `sso_used_jti`); 2FA obrigatório + rotação de refresh com detecção de replay no Console; validação de força de segredos em produção no Console; `.env` reais fora do git.

---

## 7. PLANO DE REORGANIZAÇÃO

Objetivo duplo: **(a) arrumar a casa** (o que esta auditoria encontrou) e **(b) posicionar para ser o mais competitivo do Brasil** (o que a inteligência competitiva pede). A pesquisa de mercado já apontava, sem ver o código, que "co-branding, multi-município e cofre por cliente, se implementados dentro do core em vez de numa camada de configuração por tenant, geram a bagunça descrita" — esta auditoria **confirma** exatamente isso.

Estimativas de esforço: **P** = ≤2 dias · **M** = 3–10 dias · **G** = 2–4 semanas · **GG** = 1–2+ meses.

### Fase 0 — Segurança urgente (fazer já, dias)

| # | Ação | Esforço |
|---|---|---|
| 0.1 | **Rotacionar** token Coolify + control token Freitas + senha `admin@pactha.com.br`; remover senha-semente do README. | P |
| 0.2 | **Enforçar `must_change_password` no backend** (`get_current_user` recusa até a troca). | P |
| 0.3 | **Fechar o IDOR do Cofre:** aplicar `ensure_municipio_access`/`ensure_tela` em reveal/create/update/delete. | P |
| 0.4 | Portar a **derivação de chave endurecida** do Console para o tenant; fazer `decrypt()` falhar alto (ou logar) em erro de AEAD. | P |
| 0.5 | Ligar `CONTROL_PLANE_ALLOWED_IPS` em produção; dar `expires_at`/rotação ao control token. | M |
| 0.6 | Corrigir o webhook Telegram fail-open; tirar o Bearer/JWT do `localStorage` (usar só cookie httpOnly same-origin, agora que o domínio custom permite). | M |

### Fase 1 — Arrumar a casa (semanas)

| # | Ação | Esforço |
|---|---|---|
| 1.1 | **Extrair as customizações da Freitas para uma camada de configuração por tenant.** Criar uma tabela/arquivo `tenant_config` (ou envs estruturadas) com: **feature flags**, **tema/co-branding** (logo, subtítulo, cores — já parcialmente via `NEXT_PUBLIC_CLIENT_*`), **identidade da IA** (nome da consultoria, contexto), **rodapé do RM** (endereço), **mapa de municípios do FNS**, **escopo de dados**. Regra de ouro: **nada específico de um cliente no core — só configuração.** Remove os hardcodes de `ai.py:40`, `fns.py:31`, `add_rm.sql:10`, `rm_pdf.py`, `setup_db.py:288`. | G |
| 1.2 | **Consertar o bootstrap de cliente novo:** alinhar `ConvenioEstadual` (model) com o schema (adicionar as 12 colunas via migration OU removê-las do model); resolver o ciclo `setup_db`↔`drop_lean_tables` (remover as tabelas-zumbi de vez); mover a criação de `transferegov_propostas` para migration própria. **Validar com um deploy do zero.** | M |
| 1.3 | **Padronizar a ingestão:** adicionar `openpyxl`; agendar SIMEC/SICONV federal/extractor de emendas; refazer o `ingestion_log` para gravar `running`/`error`/`started_at`/contadores e ligar ao Monitor da Central; fazer `run_fns_local` gravar log. | M |
| 1.4 | **Consolidar duplicações:** unificar as 6 rotas transferegov-* num componente parametrizado; extrair um módulo `pactha_common` (ou biblioteca compartilhada) para `crypto`/`audit`/conexão-DB/`ingestion_log` usado pelos dois repos; remover os 3 scripts-scraper mortos + `desing-inspiration-console/` + deps `pandas`/`slowapi`. | M |
| 1.5 | **Pinning de dependências:** gerar lockfile do backend (pip-tools/uv) e trocar `npm install` por `npm ci`. Reduz o risco de derrubar os 3 clientes num deploy. | P |
| 1.6 | **Adicionar integridade referencial** (FKs para `municipios`/`users`) nos módulos de 2026; tirar anexos base64 do JSONB (mover para storage). | M |

### Fase 2 — Fechar os gaps competitivos (o "melhor do Brasil")

Conforme a inteligência competitiva, os concorrentes (Gestor de Convênios, CNM Êxitos) têm o que o PACTHA ainda não tem. Com a casa arrumada (Fase 1), estes gaps viram diferencial:

| # | Ação | Esforço |
|---|---|---|
| 2.1 | **Separar conectores de fontes em plugins com interface comum** (SIGCON-MG, TransfereGov, FNS, SIMEC, CAUC, DOMG como módulos independentes com contrato único). É pré-requisito para escalar a outros estados sem tocar no core — o gargalo "MG vs. nacional" da pesquisa. | G |
| 2.2 | **Matching de oportunidades por perfil do município** (gap vs. Gestor de Convênios e CNM Êxitos): cruzar programas/editais com CNPJ, UF, população (IBGE), IDH-M, áreas de atuação. Começar por regras; evoluir para matching semântico por embeddings — diferencial que nem o Êxitos tem. Usar APIs públicas onde existem (TransfereGov dados abertos, Portal da Transparência) para reduzir scraping. | GG |
| 2.3 | **IA de leitura de editais e diários (RAG)** (gap vs. Gestor de Convênios): pipeline PDF→chunking→embeddings→resposta estruturada (órgão, objeto, valor, prazos, riscos) + alerta quando um diário citar o CNPJ/temas do ente. Ninguém faz isso sobre diários de forma contínua. | GG |
| 2.4 | **Geração assistida de Plano de Trabalho** (aderente ao Decreto 11.531/2023) com dados do ente pré-preenchidos — paridade com o rival direto. | G |
| 2.5 | **Módulo de conformidade/rastreabilidade ADPF 854/2026** — vira obrigação legal para municípios em 2026; empacotar como add-on de venda rápida. | M |

### Sequência recomendada

**Fase 0 (segurança) → Fase 1 (arrumar a casa) → Fase 2 (gaps competitivos).** Não pular a Fase 1: construir os diferenciais da Fase 2 sobre o core contaminado pela Freitas e com bootstrap quebrado só multiplicaria a dívida. A extração da camada por tenant (1.1) e a plugin-ização dos conectores (2.1) são os dois refactors que mais destravam o roadmap de mercado — são o que transforma "um sistema da Freitas que outros clientes usam" em "um produto multi-cliente pronto para escalar nacionalmente".

---

## Anexo — Metodologia e limitações

- Auditoria conduzida por 8 agentes especializados em paralelo, com leitura integral dos arquivos citados. A dimensão de dívida técnica foi levantada por leitura/grep direto durante a consolidação.
- A rodada de verificação adversarial automatizada dos achados críticos foi **interrompida por limite de sessão**; os achados de maior severidade foram reconferidos por leitura direta e por corroboração cruzada entre dimensões, mas recomenda-se um code review focado nos itens da §6.1 antes de conclusões de compliance.
- Referências cruzadas com dois relatórios de contexto fornecidos pela Alavank: *PACTHA — Pesquisa de mercado e precificação* e *PACTHA vs. concorrentes — Inteligência competitiva* (Julho/2026). Ambos anteciparam a hipótese de contaminação do core pela assessoria, que esta auditoria de código **confirma**.
