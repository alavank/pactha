# CONTINUAR.md — Handoff PACTHA (leia isto primeiro)

> Documento de contexto para a **próxima sessão de IA** (Claude Code) que for continuar este projeto.
> É **auto-contido**: assuma que você (IA) não tem memória das sessões anteriores. Tudo que precisa está aqui.
> Última atualização: 2026-07-09.

---

## 1. O QUE É ISTO (em 30 segundos)

**PACTHA** = sistema de **monitoramento de convênios e transferências governamentais** para municípios de MG (consultoria **Freitas**). Módulos: SIGCON-MG (convênios estaduais), TransfereGov, Emendas, Parlamentares, CAUC, Acordo FES, FNS, SIMEC/PAR, IA (Claude), DOU-MG, Relatório de Monitoramento (RM), Documentos, Cofre de Senhas (AES-256), Telegram, extensão Chrome de captura gov.br.

- **Frontend:** Next.js 16 (App Router) + Tailwind v4 + daisyUI + shadcn. Pasta `frontend/`.
- **Backend:** Python 3.12 FastAPI (uvicorn). Pasta `backend/`. Tudo prefixado `/api`.
- **Banco:** PostgreSQL (SQLAlchemy async+asyncpg na API; psycopg2 nos scrapers/migrations).
- **Scraping:** httpx + Playwright (Chromium) + curl_cffi. Pasta `backend/ingestion/`.

**Este repo (`alavank/pactha`) é um FORK PRÓPRIO** do repo original `MattMatiins/PACTA` (do Matheus). O usuário (alavank) **migrou** de Railway/Neon/Vercel → **Coolify/Hetzner + Postgres puro** e renomeou tudo de "PACTA" → "PACTHA".

⚠️ **DOIS clones no PC — não confundir:**
- `C:\projetos\pactha` → **ESTE** repo (`alavank/pactha`). É onde você trabalha.
- `C:\projetos\PACTA` → clone do repo do Matheus (`MattMatiins/PACTA`), usado só para colaboração com ele. **NUNCA** pushe cruzado entre os dois.

---

## 2. ESTADO ATUAL (2026-07-09)

**NO AR e validado** (login, schema, fila on-demand, seed testados end-to-end):

| | |
|---|---|
| App (frontend) | https://pactha-5-78-42-251.sslip.io |
| API | https://pactha-api-5-78-42-251.sslip.io/api |
| Login seed | `admin@pactha.com.br` / `pactha2026` (pede troca de senha no 1º acesso) |

**Banco tem só schema + seed** (6 municípios piloto + admin + analistas Freitas). **Falta popular os dados reais** → ver §6 (migração do Neon).

---

## 3. INFRA NO COOLIFY (como mexer)

- **Instância Coolify:** `http://5.78.42.251:8000` — API REST em `http://5.78.42.251:8000/api/v1`.
- **Token:** NÃO está neste arquivo (é segredo). O usuário fornece um **API token do Coolify** (formato `36|xxxx`). O último foi colado no chat e **deve ser rotacionado** — peça um novo ao usuário. Uso: header `Authorization: Bearer <TOKEN>`.
- **Servidor:** único, `nwnhw0sr8q4wnc5gepnyxoql` (localhost, o próprio host Coolify).
- **GitHub App (source):** id=2, uuid `fhdmfgnari7tlpnrao10422n` (`alavank-coolify`) — já dá acesso ao repo privado `alavank/pactha`. Use este `github_app_uuid` ao criar apps.

**Projeto Coolify `pactha`** — uuid `lpz9gkb5j6mdrd0ifqz3jvnp`, environment `production`. Resources:

| Resource | uuid | Build | Domínio / função |
|----------|------|-------|------------------|
| Postgres `pactha-db` | `tzljf8ebv1epp588c89ofo6a` | postgres:16-alpine | interno; host=uuid, porta 5432, db/user `pactha` |
| API `pactha-api` | `cqs52aowfzqkft20oz70uq89` | `backend/Dockerfile.api` (base `/`) | `https://pactha-api-5-78-42-251.sslip.io` (root, SEM strip) |
| Frontend `pactha-frontend` | `wufnp7x6ifjrapdfmb6hf596` | `frontend/Dockerfile` (base `/frontend`, standalone) | `https://pactha-5-78-42-251.sslip.io` |
| Worker `pactha-worker` | `v3e8e2shqebcd80c2vd4tv6p` | `backend/Dockerfile.scraper` (CMD `sleep infinity`) | interno; roda os crons via Scheduled Tasks |

**Segredos** (JWT_SECRET, COFRE_KEY placeholder, senha do Postgres): estão **nas env vars do Coolify** (recupere com a API — ver §7) e num arquivo local efêmero `scratchpad/pactha_secrets.env` (pode não existir em sessão nova). A senha do Postgres também está no `internal_db_url` do resource DB (`GET /databases/tzljf8ebv1epp588c89ofo6a`).

**Scheduled Tasks no Worker** (os 5 crons, já criados — `GET /applications/v3e8e2shqebcd80c2vd4tv6p/scheduled-tasks`):
| Nome | Cron | Comando | Timeout |
|------|------|---------|---------|
| sigcon | `0 */6 * * *` | `python -u ingestion/run_sigcon_cron.py` | 3600s |
| transferegov | `0 5 * * *` | `python -u ingestion/transferegov_voluntarias.py` | 3600s |
| fns | `30 5 * * *` | `python -u ingestion/run_fns_local.py` | 1800s |
| govbr-renew | `*/15 * * * *` | `python -u ingestion/govbr_renew.py` | 600s |
| queue-sigcon | `*/2 * * * *` | `python -u ingestion/run_queue_sigcon.py` | 3600s |

---

## 4. DECISÕES DE ARQUITETURA (e POR QUÊ) — não desfazer sem motivo

1. **Mantido Python/FastAPI (não migrou p/ Node).** A parte difícil é o scraping: Playwright p/ portais JSF/SAML (SIGCON, TransfereGov), curl_cffi anti-Cloudflare (SIMEC), e a máquina de sessão gov.br (SSO/SAML/reCAPTCHA). Reescrever isso = refazer o pedaço mais frágil, sem ganho.
2. **Scraping continua httpx+Playwright+curl_cffi (NÃO usar Scrapy).** O sistema é integração de dados abertos (CSV/JSON) + 2 portais JS-pesados, não crawling de HTML em escala. Scrapy não resolveria e pioraria o caso anti-bot do SIMEC.
3. **Single-tenant.** Removido o co-branding `NEXT_PUBLIC_TENANT` (logo de parceiro). **"Freitas" NÃO é tenant — é a consultoria dona** (prompt de IA, "padrão Freitas" nos RMs, usuários `@freitas.com.br`). Mantido.
4. **Rename PACTA→PACTHA completo:** cookies (`pactha_access/refresh/csrf`), localStorage (`pactha_token/user/theme/...`), tema daisyUI (`pactha`/`pactha-dark`), issuer JWT (`pactha-api`), prefixo service-token (`pactha_st_`), email admin, extensão Chrome, `package.json` name. **Tabelas do banco NÃO eram "pacta"** (`convenios_estadual` etc.) → schema intacto.
5. **Desacoplado do Railway.** O gatilho on-demand `POST /api/convenios/refresh-sigcon` (antes chamava a GraphQL `serviceInstanceRedeploy` do Railway) virou **FILA no Postgres**: tabela `scraper_jobs` + `backend/ingestion/run_queue_sigcon.py` (consumido pela Scheduled Task `queue-sigcon` a cada 2min, com dedup pending/running). CORS agora é env-driven (`main.py`).
6. **`setup_db.py` roda no BOOT da API** (`backend/services/startup.py`, dentro de `run_migrations`, antes das migrations incrementais). Idempotente (CREATE IF NOT EXISTS + seed só se `users` vazio). No Coolify não há passo manual "rodar setup_db uma vez" — isto se auto-cura em deploy novo.
7. **API em subdomínio próprio + auth por Bearer (trade-off importante).** Ver §5.

---

## 5. ARMADILHAS / GOTCHAS (leia antes de debugar)

- **Coolify STRIPPA o path do domínio.** Se você setar o domínio de um app como `host/api`, o Coolify tira o `/api` antes de chegar no container (testado: `host/api/health`→404, `host/api/api/health`→200). Por isso a API está num **subdomínio próprio SEM path** (`pactha-api-...sslip.io`), assim o FastAPI recebe `/api/...` inteiro.
- **`*.sslip.io` é public suffix.** Logo `pactha-...sslip.io` e `pactha-api-...sslip.io` são **cross-site**. Cookies `SameSite=Lax` httpOnly não trafegam entre eles. Por isso a auth usa **Bearer token** (o login devolve `access_token` no corpo; o front guarda em `localStorage.pactha_token` e manda `Authorization: Bearer`; o CSRF é **pulado** para Bearer — ver `backend/services/auth.py:160`). **Consequência: o refresh silencioso (cookie) não funciona → re-login a cada ~60min.** Isso é aceitável por ora; o fix "bonito" é o domínio custom same-origin (§6.3).
- **`transferegov_propostas` é criada tarde** nas migrations (por `add_voluntarias_id_proposta_siconv.sql`), mas migrations anteriores (`add_voluntarias_valores.sql` etc.) já a ALTERam → em DB novo, ~6/22 migrations falham com "relation does not exist". **Não é bug crítico:** a migração do Neon traz a tabela pronta. Se um dia quiser bootstrap 100% limpo sem migração, mova a criação de `transferegov_propostas` para o `setup_db.create_tables()`.
- **COFRE_KEY:** o Cofre e as sessões gov.br são cifrados com AES-256 usando a env `COFRE_KEY` (`backend/services/crypto.py`). Se a chave mudar, `decrypt()` volta `""` **silenciosamente**. Ao migrar do Neon, use **exatamente a mesma COFRE_KEY** do Neon.
- **must_change_password=True** no admin seed → o 1º login redireciona pra `/change-password`. Normal.
- Worker aparece como `running:unknown` no Coolify (é `sleep infinity`, sem healthcheck). Normal.

---

## 6. PENDÊNCIAS (com passos exatos)

### 6.1 ⭐ Migrar dados do Neon → Postgres do Coolify (PRINCIPAL)
Hoje o banco só tem schema+seed. **Scraping NÃO substitui a migração** (usuários, Cofre, sessões gov.br, RMs/documentos não são dados públicos; e SIGCON/FNS nem rodam sem as credenciais do Cofre — catch-22). Precisa do usuário:
- **Connection string do Neon** (ambiente do Matheus — o usuário precisa conseguir).
- **`COFRE_KEY` atual do Neon** (senão Cofre/sessões não descriptografam).

Passos:
```bash
# 1. Dump do Neon (de uma máquina com pg_dump 16)
pg_dump "postgresql://USER:PASS@HOST/db?sslmode=require" \
  --no-owner --no-privileges -Fc -f pactha.dump

# 2. Restaurar no Postgres do Coolify. Pegue a connection string interna em
#    GET /api/v1/databases/tzljf8ebv1epp588c89ofo6a (campo internal_db_url).
#    O DB não é público: OU exponha a porta temporariamente no Coolify (e feche
#    depois), OU rode o pg_restore de um container na rede do Coolify.
pg_restore --no-owner --no-privileges --clean --if-exists \
  -d "postgresql://pactha:SENHA@HOST:PORTA/pactha" pactha.dump

# 3. Trocar a env COFRE_KEY da API (e do Worker) pela do Neon, via API do Coolify
#    (PATCH .../envs/bulk), e redeploy da API.

# 4. Alinhar o email do super-admin com o rename:
#    UPDATE users SET email='admin@pactha.com.br' WHERE email='admin@pacta.com.br';
#    (o guard de super-admin está hardcoded em backend/routers/service_tokens.py
#     e frontend/src/app/dashboard/layout.tsx como admin@pactha.com.br)
```
Depois: validar login com um usuário real, abrir um item do Cofre (decrypt OK), conferir contagem de linhas por tabela.

### 6.2 Secrets opcionais (features ficam OFF até setar) — no resource API
`ANTHROPIC_API_KEY` (módulo IA), `TELEGRAM_BOT_TOKEN` + `TELEGRAM_WEBHOOK_SECRET` (Telegram). Setar via `PATCH /applications/cqs52aowfzqkft20oz70uq89/envs/bulk` + redeploy.

### 6.3 (Opcional, recomendado) Domínio custom + same-origin (cookie/refresh completos)
Quando o usuário criar o DNS `A: pactha → 5.78.42.251`:
1. Colocar frontend em `https://pactha.alavank.com.br`.
2. Fazer o **Next.js proxiar `/api`** para a API interna (rewrite em `next.config.ts`: `/api/:path*` → `http://cqs52aowfzqkft20oz70uq89:8000/api/:path*`), e **tirar o domínio público da API** (ela vira interna). Assim tudo é same-origin → cookies httpOnly + CSRF + refresh silencioso voltam a funcionar (sem re-login de 60min). Setar `NEXT_PUBLIC_API_URL=/api` (relativo) e rebuildar o frontend. Validar que o frontend alcança a API interna (a API↔DB já provou que a rede interna do projeto funciona).

---

## 7. OPERAÇÕES COMUNS (Coolify API v1)

`B=http://5.78.42.251:8000/api/v1` · header `Authorization: Bearer <TOKEN>`

- **Redeploy:** `POST $B/deploy?uuid=<app_uuid>&force=false` → devolve `deployment_uuid`. Status: `GET $B/deployments/<deployment_uuid>` (`status`: queued/in_progress/finished/failed).
- **Logs do app:** `GET $B/applications/<uuid>/logs?lines=120`.
- **Setar env (bulk):** `PATCH $B/applications/<uuid>/envs/bulk` body `{"data":[{"key":..,"value":..,"is_build_time":bool,"is_preview":false}]}`. ⚠️ o POST simples `/envs` **não aceita** `is_build_time` (use o bulk). `NEXT_PUBLIC_*` do frontend precisa `is_build_time:true`.
- **Mudar domínio:** `PATCH $B/applications/<uuid>` body `{"domains":"https://..."}` + redeploy.
- **Scheduled Tasks:** `GET/POST $B/applications/<worker_uuid>/scheduled-tasks` (POST body `{name,frequency,command}`); `PATCH .../scheduled-tasks/<task_uuid>` p/ `{timeout}`.
- **DB status/URL:** `GET $B/databases/<uuid>` (campos `status`, `internal_db_url`).
- **Rodar um scraper na mão:** dispare a Scheduled Task correspondente (ou `POST /api/convenios/refresh-sigcon` autenticado → enfileira, e a task `queue-sigcon` consome em ≤2min). Lembre: scrapers com login (SIGCON, FNS) só produzem dados se o **Cofre** tiver credenciais.

---

## 8. RESUMO: por que MIGRAR > popular por scraping
Scraping só recria **dado público** (CAUC, Acordo FES, SIMEC, TransfereGov guest, CSVs siconv — ~1-3h de execuções). **NÃO** recria: usuários, Cofre (credenciais), sessões gov.br, Gestão/RM/documentos. E os scrapers principais (**SIGCON, FNS**) **precisam** das credenciais do Cofre pra rodar — que o scraping não reconstrói. Migração (`pg_dump`/`pg_restore`, ~10-20min) preserva tudo e resolve o catch-22. **Recomendação firme: migrar.**
