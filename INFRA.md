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

### 🚀 Um merge na `main` deploya os TRÊS tenants — sozinho, na ordem certa

> Corrigido em **2026-08-09** (o modelo mudou de novo, e desta vez de propósito). A versão
> de 31/07 dizia — corretamente, à época — que push nenhum mexia em cliente e que o deploy
> era sempre um ato manual de repontar tag. **Isso acabou em 09/08 (PRs #161/#162/#163):
> o CI agora fecha o ciclo.** E o `is_auto_deploy_enabled`, que era `true` e inofensivo,
> foi **desligado nas 9 aplicações** — o webhook do Coolify recriava containers com a tag
> ANTIGA (churn que matou coleta em voo duas vezes em 08/08).

As 9 aplicações continuam com **`build_pack = dockerimage`** (rodam a tag gravada em
`docker_registry_image_tag`; quem constrói é o GitHub Actions publicando no `ghcr.io`).
A diferença: o job `deploy` dos workflows **avança a tag e dispara o deploy** ao fim de
cada build da `main`:

| Ação | O que acontece em produção |
|---|---|
| merge/push na `main` (toca `backend/**`) | Builda `pactha-api`+`pactha-worker` e deploya os 3 tenants: **API primeiro** (roda migrations; deployment confirmado via `GET /deployments/{uuid}`), depois o **worker do mesmo tenant esperando janela sem coleta em voo**. API que não subiu = worker daquele tenant intocado. |
| merge/push na `main` (toca `frontend/**`) | Builda as 3 imagens de frontend e deploya as 3 (sem gate — frontend não roda coleta). |
| deploy manual (rollback/exceção) | Continua possível: repontar `docker_registry_image_tag` + `GET /deploy?uuid=` — o mesmo que o CI faz. |

Segredos do CI: `COOLIFY_URL` + `COOLIFY_TOKEN` nos **GitHub Secrets** do repo. Sem eles
o job de deploy falha com barulho (proposital — nunca em silêncio). A fonte de verdade da
mecânica (gates, margens, rollback de tag em falha) são os próprios
`.github/workflows/build-backend.yml` e `build-frontend.yml`, comentados linha a linha.

⚠️ A fila de deploy do Coolify tem **`concurrent_builds = 1`** e apps de OUTROS projetos
buildam na própria VPS (licity: 15–20 min por build) — um deployment do pactha (que é só
*pull*, 15–50s) pode esperar `queued` por >10 min. O CI já tolera isso; ao deployar na
mão, não interprete `queued` demorado como falha.

O campo `git_branch` voltou a importar de leve: `main` nas 9 (webhook desligado, mas o
CI só deploya o que buildar da `main`).

⚠️ As imagens de **frontend são uma por tenant** (`pactha-frontend-freitas`,
`-trust`, `-montesiao-mg`), porque a marca do cliente entra no build. **API e worker
compartilham** a mesma imagem (`pactha-api`, `pactha-worker`). E as **tags divergem de
formato**: backend usa sha **curto**, frontend usa sha **completo** — o CI cuida disso.

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

> **`montesiao-mg-painel` JÁ FOI REMOVIDO** — conferido em 2026-07-31: zero linhas
> em `applications` com o uuid `uymt911sgynkbvifyzf6nf1h`. São **9** aplicações no
> projeto, não 10. O Painel Executivo virou parte do frontend principal:
> `/dashboard` é o **Painel de Indicadores** e `/tela` é o **Modo Tela** (janela de
> exibição), no mesmo deploy e no mesmo login. A pasta `painel/` saiu do CI (ver
> `painel/DEPRECADO.md`).
>
> **Resíduo vivo:** o cron `painel-alertas` monta o payload de push apontando para
> `/app/alertas`, que era rota **daquele** app — hoje 404 no frontend novo. Sem
> efeito prático, porque o canal de push está morto nas três pontas: nenhum
> `pushManager.subscribe` no frontend, nenhum handler de `push` em
> `public/sw.js`, e `painel_push_subscriptions` vazia. Ou se reconstrói o cliente,
> ou se remove cron e tabelas — manter código morto vivo já custou tempo de
> auditoria discutindo notificação que ninguém pode receber.

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

> ⚠️ Atualizado em **2026-08-09**: a tabela de horários que vivia aqui ficou obsoleta DUAS
> vezes numa semana. **A fonte de verdade das agendas é o próprio Coolify**
> (`GET /applications/<worker_uuid>/scheduled-tasks`, ou `scheduled_tasks` no coolify-db).
> Este parágrafo documenta o **desenho**, que muda devagar; os horários, não copie daqui.

O desenho atual (redesenho de 09/08, "tuning da madrugada"):

- **Lock compartilhado `/tmp/scraper.lock`** por worker: `sigcon`, `transferegov-lote` e
  `cagec` **nunca rodam ao mesmo tempo no mesmo tenant** (quem chega com o lock tomado
  sai com `flock -E 99` → remapeado para sucesso = pulou a vez, a próxima rodada cobre).
- **Agendas entrelaçadas**: lote nas horas pares (`:00`), sigcon nas ímpares (`:25`),
  cagec nos `:50-58` — cada task tem uma janela que a vizinha respeita.
- **Rodadas curtas com rodízio**: `SIGCON_LOTE_MUNICIPIOS` / `TG_LOTE_MUNICIPIOS` fatiam a
  carteira; o rodízio (ordenação por staleness + backoff por falha, PR #159) garante que
  ninguém starva. É o modelo que levou o TransfereGov a 41/41 frescos.
- **REGRA DE OURO das margens** (aprendida em produção 09/08): o `timeout -k 30 N` interno
  precisa de `N ≥ orçamento interno + 1 município PESADO` (Bom Despacho sozinho = 22 min).
  Margem colada no orçamento = `exit 124` recorrente, sem log e sem `ingestion_log`.
  E a coluna `timeout` da task (pcntl do Coolify) precisa de `≥ N + 120s`, senão o Coolify
  mata primeiro e **descarta o stdout**.
- Todos os comandos: `flock -n` + `timeout -k 30 N` + `2>&1` (o Python loga em stderr e o
  Coolify só guarda stdout no sucesso) + sufixo `rc=$?; if [ $rc = 99 ]...` — **nunca
  editar esses comandos com string interpolada de PowerShell** (`$rc`/`$?` viram lixo;
  foi a causa dos 25 falso-negativos de 08/08). Editar via JSON literal na API.
- Fontes de **dump** coletam na cadência da fonte (a tabela de cadências oficiais está no
  relatório de diagnóstico de 08/08): dumps federais/MG diários de manhã = 1×/dia;
  GConv-ES 2×/dia; GO (transfvol/cofin) 1×/dia; `siconv-federal` mensal (dia 2).

> 🕐 **TUDO EM UTC. Brasília é UTC−3.** Host, `instance_timezone` do Coolify e
> PHP do container em `Etc/UTC`. As faixas do CAGEC (10/15/19/23 UTC) são
> **07h, 12h, 16h e 20h de Brasília** — um cron escrito como "07:00" rodaria às
> 4h da manhã para o cliente, e rodou.

> **`cauc-manha`** existe porque `cauc_situacao.data_pesquisa` é a data do
> extrato **do Tesouro**, não da nossa coleta, e eles só publicam o arquivo do
> dia entre **07h e 09h20 BRT**. A rodada do CAUC pendurada no `sigcon` pegava o
> arquivo de ontem, e às 8h a tela ainda mostrava a data anterior. Esta task
> insiste de hora em hora (10–14 UTC) até a data virar; é HTTP puro, ~2s.

Detalhes de cada rotina e dos comandos completos: `docs/CRON_SETUP.md`.

**SISMOB** (obras de saúde do MS) **não tem linha nesta tabela de propósito**: em vez
de uma Scheduled Task nova em cada um dos 3 workers, ele foi pendurado em
`run_dadosabertos_cron.run_all()`, que o `sigcon` já chama 4×/dia. Como a fonte muda
a cada ~60 dias por obra, o próprio `ingest()` se auto-limita a 1×/dia
(`SISMOB_MIN_INTERVAL_H=20`; `SISMOB_FORCE=1` força, `SISMOB_ENABLED=0` desliga por
tenant). A fonte é **API JSON pública** — sem token, sem login, sem Playwright.

> ⚠️ **`SISMOB_ENABLED=0` deixa o watchdog reclamando para sempre.** O `ingest()`
> retorna antes de rodar, então nunca grava linha em `ingestion_log`, e o
> `watchdog_coleta` — cujo catálogo `FRESCOR_HORAS` é **global aos 3 tenants**,
> constante no código — passa a registrar "sismob: nenhum sucesso registrado" a
> cada ciclo. Hoje isso é só uma linha WARN no log da Scheduled Task (nenhum app
> do PACTHA tem `TELEGRAM_BOT_TOKEN` configurado), mas se você ligar o Telegram
> antes de resolver isso, vira alarme recorrente sobre uma fonte desligada de
> propósito. Não é defeito do SISMOB: é a lacuna entre expectativa global e
> desligamento por tenant. Prefira **não deployar** o módulo no tenant do que
> deployar e desligar pela env.

**`SISMOB_ALLOW_SHRINK=1`** destrava a GUARDA 4 do coletor. Por padrão, se a
listagem devolver itens sem `proposta_id`, ou se mais de 1/5 da carteira do
município fosse marcada como ausente de uma vez, a rodada **falha e faz rollback**
em vez de marcar — porque obra marcada como ausente some da tela, do BI, da TV e
dos alertas ao mesmo tempo, e a rodada era gravada como `success`. Use a válvula
só quando o encolhimento for real (obra de fato retirada do programa); sem ela, um
município que legitimamente perca obras fica repetindo a falha.

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
| `montesiao-mg-worker` | `jhf0kjhps5keujiyhhsnvjt6` |
