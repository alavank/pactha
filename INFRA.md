# INFRA.md — Verdade atual da infraestrutura do PACTHA

> **Fonte única de verdade sobre onde o PACTHA roda.** Medido no servidor em **2026-07-23**.
> Se algum outro documento deste repositório disser coisa diferente (Hetzner, Railway, Neon,
> Vercel, Supabase), **este arquivo vence** — o outro está desatualizado.

---

## 1. Servidor (um só, hospeda tudo)

| | |
|---|---|
| Provedor | **AWS Lightsail** |
| IP | **54.232.208.118** |
| Região | **sa-east-1a** (São Paulo, Brasil) |
| Instância | t3.large — **2 vCPU / 7,6 GB RAM / 160 GB SSD (nvme)** |
| Orquestração | **Coolify v4.1.2** — painel em `http://54.232.208.118:8000` |
| SSH | `ssh -i ~/.ssh/coolify_localhost root@54.232.208.118` |
| Escala do host | 43 containers · 11 projetos · 24 aplicações · 12 bancos PostgreSQL |

### ⚠️ A máquina é BURSTABLE — leia antes de rodar qualquer coisa pesada

A instância tem **baseline de CPU de 30%**, ou seja, na prática **~0,6 vCPU sustentado**.
Rajadas curtas usam créditos; carga contínua derruba a máquina inteira para o baseline —
e nesse host moram **outros 10 projetos** além do PACTHA.

Consequências práticas para este repo:

- **Não paralelizar scraping.** `SIGCON_CONCURRENCY=1` em todos os workers. Não aumente.
- **Não rodar os crons dos 3 tenants no mesmo horário.** Eles já estão **escalonados de
  propósito** (ver §4) — não "arrume" isso deixando todos às 5h.
- **Não disparar rebuild dos 10 apps ao mesmo tempo.** Build de Next.js + imagem com
  Chromium é caro; faça um de cada vez.
- Playwright/Chromium é o maior consumidor. Os crons já rodam com `flock` (não sobrepõe
  execução) e `timeout` (mata processo pendurado).

---

## 2. Um repo, TRÊS tenants (leia isto antes de dar push)

Este repositório atende **três clientes distintos**, cada um com seu **próprio conjunto de
containers e seu próprio banco**, todos buildados **do mesmo código**:

| Tenant | Slug | Quem é |
|--------|------|--------|
| Freitas | `freitas` | consultoria Freitas (instância original) |
| Trust | `trust` | consultoria Trust |
| Monte Sião | `montesiao-mg` | Prefeitura de Monte Sião/MG (tem também o Painel Executivo) |

Não existe multi-tenancy dentro do código: **o isolamento é por deploy**. O que diferencia
um tenant do outro são as **env vars no Coolify** (`INSTANCE_SLUG`, `DATABASE_URL`,
`JWT_SECRET`, `COFRE_KEY`, `NEXT_PUBLIC_CLIENT_LOGO`, `NEXT_PUBLIC_CLIENT_SUBTITLE`).

### 🚨 Um push na branch padrão pode disparar até 9 builds

São **10 aplicações** no projeto Coolify `pactha`. Hoje **7 delas acompanham a branch `main`**
e 3 acompanham `feat/painel-executivo`. Um push em `main`, com auto-deploy ligado, rebuilda
7 aplicações de uma vez — numa máquina de 0,6 vCPU sustentado. **Nunca é um deploy só.**

> **Auto-deploy está DESLIGADO em todas as 10 aplicações neste momento** (medido em
> 2026-07-23). Push não dispara build; o deploy é manual pelo painel do Coolify.
> Se você religar o auto-deploy, releia o parágrafo acima.

---

## 3. Aplicações e URLs em produção

Projeto Coolify: **`pactha`** (uuid `ksmwr13y4iyprom8i1znede8`), environment `production`.
Todas as URLs abaixo foram conferidas respondendo em 2026-07-23.

### Freitas
| Resource | Build | URL |
|---|---|---|
| `freitas-frontend` | `frontend/Dockerfile` (base `/frontend`) | https://pactha-54-232-208-118.sslip.io |
| `freitas-api` | `backend/Dockerfile.api` (base `/`) | https://pactha-api-54-232-208-118.sslip.io |
| `freitas-worker` | `backend/Dockerfile.scraper` | interno (sem domínio público) |
| `freitas-db` | `postgres:16-alpine` | interno — db/user `pactha`, uuid `tox59kvmkrb0ywmeaty3t02a` |

### Trust
| Resource | Build | URL |
|---|---|---|
| `trust-frontend` | `frontend/Dockerfile` | https://pactha-trust-54-232-208-118.sslip.io |
| `trust-api` | `backend/Dockerfile.api` | https://pactha-trust-api-54-232-208-118.sslip.io |
| `trust-worker` | `backend/Dockerfile.scraper` | interno |
| `trust-db` | `postgres:16-alpine` | interno — db/user `pactha`, uuid `p434vbj35siee57shlsyzuc2` |

### Monte Sião / MG
| Resource | Build | URL |
|---|---|---|
| `montesiao-mg-frontend` | `frontend/Dockerfile` | https://pactha-montesiao-mg-54-232-208-118.sslip.io |
| `montesiao-mg-api` | `backend/Dockerfile.api` | https://pactha-montesiao-mg-api-54-232-208-118.sslip.io |
| `montesiao-mg-worker` | `backend/Dockerfile.scraper` | interno |
| `montesiao-mg-db` | `postgres:16-alpine` | interno — db/user `pactha`, uuid `iogvjlnkpqlugja9j76rktl1` |

> **`montesiao-mg-painel` (uuid `uymt911sgynkbvifyzf6nf1h`) está para ser removido.**
> O Painel Executivo virou parte do frontend principal: `/dashboard` é o **Painel
> de Indicadores** e `/tela` é o **Modo Tela** (janela de exibição), no mesmo
> deploy e no mesmo login. A pasta `painel/` saiu do CI (ver `painel/DEPRECADO.md`).
> Enquanto a aplicação não for deletada no Coolify ela só ocupa container e RAM —
> ninguém mais acessa aquela URL.
>
> ```bash
> B=http://54.232.208.118:8000/api/v1
> curl -X DELETE "$B/applications/uymt911sgynkbvifyzf6nf1h" \
>      -H "Authorization: Bearer <TOKEN>"
> ```

### Fora deste repo, mas do mesmo produto
| O quê | URL | Repo |
|---|---|---|
| Landing comercial | https://pactha.com.br · https://www.pactha.com.br | `alavank/pactha-landing` (projeto Coolify `pactha-landing`) |
| Central de Comando | https://control-center.pactha.com.br (fallback https://console-54-232-208-118.sslip.io) · API https://console-api-54-232-208-118.sslip.io | `console-alavank` (projeto Coolify `alavank-control`) |

A Central de Comando fala com as APIs do PACTHA usando o `CONTROL_TOKEN_BOOTSTRAP`
configurado em cada resource `*-api`.

---

## 4. Banco de dados

**PostgreSQL 16 puro, container standalone `postgres:16-alpine`, um por tenant.**
Conexão sempre por `DATABASE_URL` / `DATABASE_URL_SYNC`.

**Não existe Supabase nesta infra** (nem cloud nem self-hosted). Se você vir
`SUPABASE_URL`, `SUPABASE_ANON_KEY` ou `SERVICE_ROLE_KEY` em algum lugar, é lixo
de documentação antiga — ignore.

Os bancos são internos à rede Docker do projeto (não têm porta pública). Para
`psql`/`pg_dump`, ou exponha a porta temporariamente no Coolify (e feche depois), ou
entre pelo host:

```bash
ssh -i ~/.ssh/coolify_localhost root@54.232.208.118
docker exec -it tox59kvmkrb0ywmeaty3t02a psql -U pactha -d pactha   # freitas
docker exec -it p434vbj35siee57shlsyzuc2 psql -U pactha -d pactha   # trust
docker exec -it iogvjlnkpqlugja9j76rktl1 psql -U pactha -d pactha   # montesiao-mg
```

Os três bancos já estão **populados com dados reais de produção** — não são mais
schema+seed. Migrações idempotentes rodam no boot da API (`backend/services/startup.py`).

---

## 5. Crons (Scheduled Tasks do Coolify)

Cada worker tem suas próprias Scheduled Tasks, **com horários escalonados entre os tenants**
para não competir por CPU no host burstable. Todos os comandos usam
`flock -n` (não sobrepõe execução) + `timeout -k 30` (mata processo pendurado).

| Task | Freitas | Trust | Monte Sião |
|------|---------|-------|------------|
| `sigcon` | `0 0,6,12,18 * * *` | `0 2,8,14,20 * * *` | `0 4,10,16,22 * * *` |
| `transferegov` | `0 2 * * *` | `0 10 * * *` | `0 18 * * *` |
| `fns` | `30 5 * * *` | `30 6 * * *` | `30 7 * * *` |
| `govbr-renew` | `5 * * * *` | `25 * * * *` | `45 * * * *` |
| `queue-sigcon` | `0,30 * * * *` | `10,40 * * * *` | `20,50 * * * *` |
| `painel-alertas` | — | — | `15 */2 * * *` |
| `cagec` | — | — | `40 5 * * *` |

Detalhes de cada rotina e dos comandos completos: `docs/CRON_SETUP.md`.

**`cagec`** (desde 2026-07-30, só Monte Sião por enquanto): regularidade **estadual**
de MG. Roda às 5h40, depois da rodada do `sigcon` das 4h — de propósito, porque o
CNPJ do município é inferido das emendas estaduais que o SIGCON acabou de coletar.
Não usa credencial: a consulta do CAGEC é **pública** e basta o CNPJ. O detalhe
(cada obrigação com situação e validade) vem do **CRC em PDF**, que a própria
consulta emite mesmo para município irregular — por isso o worker precisa de
`pypdf`. Custa ~20s por município, então um tenant com 18 municípios gasta ~6min
de uma vez ao dia; não há download em massa (os botões de exportar só existem
depois de uma busca). Onde o portal fica e as armadilhas dele:
`backend/ingestion/cagec_scraper.py`.

---

## 6. Plataformas que NÃO usamos mais

Nada abaixo está no ar. Se um documento, script ou env var apontar para isso, está errado:

- **Hetzner** e o IP **5.78.42.251** — servidor **cancelado**, não responde.
  Qualquer host `*-5-78-42-251.sslip.io` está morto.
- **Railway** — não hospeda mais API, worker nem crons. A `COFRE_KEY` **não** mora lá.
- **Neon** — não é mais o banco. A migração Neon → Postgres do Coolify **já foi feita**.
- **Vercel**, **Netlify** — o frontend Next.js é buildado como imagem Docker no Coolify.
- **Supabase** (cloud ou self-hosted) — nunca esteve nesta infra.
- Especificações de máquina tipo **CCX33 / CPX31 / "8 vCPU dedicado" / "32 GB RAM" /
  região "us-west"** são de servidores que não existem mais.

---

## 7. Onde estão os segredos

`JWT_SECRET`, `COFRE_KEY`, `ADMIN_PASSWORD`, `DATABASE_URL`, `ANTHROPIC_API_KEY`,
`CONTROL_TOKEN_BOOTSTRAP` e as chaves VAPID vivem **nas env vars do resource no Coolify**
(criptografadas no banco do Coolify), **por tenant**. Não estão no git, não estão em
arquivo no host, e **não estão em Railway/Vercel**.

Para lê-las/alterá-las: painel do Coolify → resource → aba *Environment Variables*, ou a
API REST em `http://54.232.208.118:8000/api/v1` com `Authorization: Bearer <token>`
(o token do Coolify é fornecido pelo usuário e deve ser rotacionado periodicamente).

⚠️ **`COFRE_KEY` é irreversível na prática:** se ela mudar, `decrypt()` devolve `""`
**silenciosamente** (`backend/services/crypto.py`) e todo o Cofre + as sessões gov.br
daquele tenant viram lixo. Cada tenant tem a sua — **nunca copie a de um para o outro**.

---

## 8. Operações comuns (Coolify API v1)

`B=http://54.232.208.118:8000/api/v1` · header `Authorization: Bearer <TOKEN>`

- **Redeploy:** `POST $B/deploy?uuid=<app_uuid>&force=false` → devolve `deployment_uuid`.
  Status: `GET $B/deployments/<deployment_uuid>`.
- **Logs:** `GET $B/applications/<uuid>/logs?lines=120`.
- **Env vars (bulk):** `PATCH $B/applications/<uuid>/envs/bulk` com
  `{"data":[{"key":..,"value":..,"is_build_time":bool,"is_preview":false}]}`.
  ⚠️ O `POST /envs` simples **não aceita** `is_build_time` — use o bulk.
  `NEXT_PUBLIC_*` e `API_PROXY_TARGET` precisam de `is_build_time:true`.
- **Domínio:** `PATCH $B/applications/<uuid>` com `{"domains":"https://..."}` + redeploy.
- **Scheduled Tasks:** `GET/POST $B/applications/<worker_uuid>/scheduled-tasks`.
- **Banco:** `GET $B/databases/<uuid>` (campos `status`, `internal_db_url`).

UUIDs das aplicações medidos em 2026-07-23:

| App | uuid |
|---|---|
| `freitas-api` | `givx3567ygxppum10p1oungn` |
| `freitas-frontend` | `qgmw4e5wjem1e8jit2wyvo1d` |
| `freitas-worker` | `s49c3b58lysqq0tpelneg3g3` |
| `trust-api` | `pphvk2ygkuirjhu9qptvmfs5` |
| `trust-frontend` | `j5ghp71lff003d5rfaynvy5y` |
| `trust-worker` | `xg714h8l7va4ejq70a5pmv5t` |
| `montesiao-mg-api` | `chr0n883hp19tjh7829k85a7` |
| `montesiao-mg-frontend` | `bryvqhhcu97lc3ku7a2hss0q` |
| `montesiao-mg-painel` | `uymt911sgynkbvifyzf6nf1h` (a remover — ver §3) |
| `montesiao-mg-worker` | `jhf0kjhps5keujiyhhsnvjt6` |
