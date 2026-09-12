# INFRA.md — Verdade atual da infraestrutura do PACTHA

> **Fonte única de verdade sobre onde o PACTHA roda.** Medido no servidor em **2026-07-23**,
> reconferido contra a API do Coolify em **2026-09-04** (aplicações, tags e Scheduled Tasks).
> Se algum outro documento deste repositório disser coisa diferente, **este arquivo vence** —
> o outro está desatualizado.

---

## 1. Servidor (um só, hospeda tudo)

| | |
|---|---|
| Provedor | **AWS Lightsail** |
| IP | **54.232.208.118** |
| Região | **sa-east-1a** (São Paulo, Brasil) |
| Instância | **8 vCPU / 32 GB RAM / 640 GB SSD** — plano "Uso geral" do Lightsail. ⚠️ Medido na máquina em 09/09/2026 (`nproc` = 8, `free -h` = 30 GiB, `df -h /` = 619 GB com 6% em uso) e conferido no console da AWS. **Não é mais o t3.large de 2 vCPU/7,6 GB** que este arquivo descreveu até aqui — o upgrade foi feito justamente para as coletas rodarem mais rápido. |
| Orquestração | **Coolify v4.1.2** — painel em `http://54.232.208.118:8000` |
| SSH | `ssh -i ~/.ssh/coolify_localhost root@54.232.208.118` — ⚠️ **é este que funciona.** Existe também um usuário `claude` (`~/.ssh/claude_lightsail`, atalho `lightsail` no `~/.ssh/config`), mas ele **expirou** (`Your account has expired`, medido em 08/09/2026): a chave autentica e o login é recusado depois. Se for renovar, `chage -E -1 claude` no servidor. |
| Escala do host | 43 containers · 11 projetos · 24 aplicações · 12 bancos PostgreSQL |

### A máquina tem folga — mas o host é compartilhado

⚠️ **Este bloco dizia o contrário até 09/09/2026** ("burstable, baseline de 30%,
~0,6 vCPU sustentado, não paralelize nada"). Aquilo descrevia o t3.large antigo e
**parou de valer com o upgrade**. O texto velho custou caro em sessão: levou a
recusar carga manual nos seis tenants por medo de derrubar o host, quando a
medição no momento do disparo mostrou **load 3.97 em 8 CPUs** — menos da metade.

Referência medida em 09/09/2026, com os seis workers coletando TransfereGov ao
mesmo tempo:

| | |
|---|---|
| Load com os 6 em coleta | **3.97** (teto confortável = 8) |
| RAM | 30 GiB total · 6,5 usados · 22 em cache · **24 disponíveis** |
| Disco | 619 GB · **6% em uso** |

O que continua valendo, e por outros motivos que não a falta de CPU:

- **`SIGCON_CONCURRENCY=1`** — aqui o limite é o PORTAL, não a máquina: o SIGCON
  recusa e chega a bloquear credencial sob paralelismo. Não aumente.
- **Crons escalonados entre tenants** (ver §5) — o motivo agora é não bater seis
  vezes no mesmo portal federal no mesmo minuto, e não poupar vCPU.
- **Outros 10 projetos moram neste host.** Folga não é convite para ocupar tudo:
  meça (`uptime`, `free -h`) antes e depois de qualquer carga fora do comum.
- Playwright/Chromium continua sendo o processo mais pesado, e os crons seguem
  com `flock` (não sobrepõe execução) e `timeout` (mata processo pendurado) —
  isso protege contra coleta duplicada, não contra CPU.

---

## 2. Um repo, SEIS tenants (leia isto antes de dar push)

Este repositório atende **seis clientes distintos**, cada um com seu **próprio conjunto de
containers e seu próprio banco**, todos buildados **do mesmo código**:

| Tenant | Slug | Quem é |
|--------|------|--------|
| Freitas | `freitas` | consultoria Freitas (instância original) |
| Trust | `trust` | consultoria Trust |
| Monte Sião | `montesiao-mg` | Prefeitura de Monte Sião/MG (tem também o Painel Executivo) |
| Santa Maria | `santamaria-rs` | Prefeitura de Santa Maria/RS — **aberto em 16/08/2026**, em avaliação |
| Nova Palma | `novapalma-rs` | Prefeitura de Nova Palma/RS — **aberto em 01/09/2026** |
| BGK | `bgk-rs` | **Assessoria BGK** — 10 municípios do RS (Bento Gonçalves, Veranópolis, Nova Prata, Guaporé, Serafina Corrêa, São Marcos, Carlos Barbosa, Garibaldi, Portão, Giruá). **Aberto em 08/09/2026.** Environment Coolify `bgk-rs` (id 24). Domínio **`bgk.pactha.com.br` no ar desde 09/09/2026**. |

Não existe multi-tenancy dentro do código: **o isolamento é por deploy**. O que diferencia
um tenant do outro são as **env vars no Coolify** (`INSTANCE_SLUG`, `DATABASE_URL`,
`JWT_SECRET`, `COFRE_KEY`, `NEXT_PUBLIC_CLIENT_LOGO`, `NEXT_PUBLIC_CLIENT_SUBTITLE`).

### 🚀 Um merge na `main` deploya os SEIS tenants — sozinho, na ordem certa

> Corrigido em **2026-08-09** (o modelo mudou de novo, e desta vez de propósito). A versão
> de 31/07 dizia — corretamente, à época — que push nenhum mexia em cliente e que o deploy
> era sempre um ato manual de repontar tag. **Isso acabou em 09/08 (PRs #161/#162/#163):
> o CI agora fecha o ciclo.** E o `is_auto_deploy_enabled`, que era `true` e inofensivo,
> foi **desligado nas 9 aplicações** — o webhook do Coolify recriava containers com a tag
> ANTIGA (churn que matou coleta em voo duas vezes em 08/08).

As **18** aplicações (eram 9 em 09/08 com três tenants, 15 com cinco) continuam com
**`build_pack = dockerimage`** (rodam a tag gravada em `docker_registry_image_tag`; quem
constrói é o GitHub Actions publicando no `ghcr.io`).
A diferença: o job `deploy` dos workflows **avança a tag e dispara o deploy** ao fim de
cada build da `main`:

| Ação | O que acontece em produção |
|---|---|
| merge/push na `main` (toca `backend/**`) | Builda `pactha-api`+`pactha-worker` e deploya os 6 tenants: **API primeiro** (roda migrations; deployment confirmado via `GET /deployments/{uuid}`), depois o **worker do mesmo tenant esperando janela sem coleta em voo**. API que não subiu = worker daquele tenant intocado. |
| merge/push na `main` (toca `frontend/**`) | Builda as 6 imagens de frontend e deploya as 6 (sem gate — frontend não roda coleta). |
| deploy manual (rollback/exceção) | Continua possível: repontar `docker_registry_image_tag` + `GET /deploy?uuid=` — o mesmo que o CI faz. |

Segredos do CI: `COOLIFY_URL` + `COOLIFY_TOKEN` nos **GitHub Secrets** do repo. Sem eles
o job de deploy falha com barulho (proposital — nunca em silêncio).

> ⚠️ **ROTACIONOU O TOKEN DO COOLIFY? ATUALIZE O SECRET NO MESMO ATO.** Em 16/08/2026 o
> token foi rotacionado e o secret não acompanhou: **quatro merges seguidos (#220–#223)
> passaram no build e nenhum chegou em produção**, com os quatro tenants rodando código
> antigo por horas. O CI só dizia `deploy nao disparou — revertendo tag para '?'`, porque
> as chamadas voltavam 401 e o `jq` apenas não achava o campo — sintoma idêntico ao de um
> deploy recusado. Desde então os dois workflows **conferem o status HTTP antes do laço** e
> falham dizendo "COOLIFY_TOKEN inválido ou revogado", sem tocar em tag nenhuma.
>
> Sintoma para reconhecer de longe: a tag no Coolify avança, mas o container continua na
> imagem anterior. Conferir com `GET /applications/<uuid>` (campo `docker_registry_image_tag`)
> **e** o `status` — os dois concordando é o que prova o deploy. A fonte de verdade da
mecânica (gates, margens, rollback de tag em falha) são os próprios
`.github/workflows/build-backend.yml` e `build-frontend.yml`, comentados linha a linha.

⚠️ A fila de deploy do Coolify tem **`concurrent_builds = 1`** e apps de OUTROS projetos
buildam na própria VPS (licity: 15–20 min por build) — um deployment do pactha (que é só
*pull*, 15–50s) pode esperar `queued` por >10 min. O CI já tolera isso; ao deployar na
mão, não interprete `queued` demorado como falha.

O campo `git_branch` voltou a importar de leve: `main` nas 9 (webhook desligado, mas o
CI só deploya o que buildar da `main`).

⚠️ As imagens de **frontend são uma por tenant** (`pactha-frontend-freitas`,
`-trust`, `-montesiao-mg`, `-santamaria-rs`, `-novapalma-rs`), porque a marca do cliente
entra no build. **API e worker compartilham** a mesma imagem (`pactha-api`,
`pactha-worker`). E as **tags divergem de formato**: backend usa sha **curto**, frontend usa
sha **completo** — o CI cuida disso. Conferido em 04/09/2026: as 15 apps na mesma
`sha-4d5a37f` / `sha-4d5a37fcb9d542418…`, as 5 APIs `running:healthy`.

---

## 3. Aplicações e URLs em produção

Projeto Coolify: **`pactha`** (uuid `ksmwr13y4iyprom8i1znede8`), environment `production`.

> ⚠️⚠️ **CADA APP TEM DOIS ENDERECOS, E OS DOIS SAO O MESMO CONTAINER.** O `sslip.io`
> resolve o IP do servidor dentro do proprio nome (`...-54-232-208-118.sslip.io` → 54.232.208.118),
> e por isso todo app tem esse endereco cru de graca. Os SEIS tem TAMBEM um dominio
> proprio. **Nao ha ambiente de teste separado**: mexer por um endereco mexe no outro, no
> mesmo banco.
>
> Conferido respondendo em **05/09/2026**:
>
> | Tenant | Dominio proprio | Endereco cru |
> |---|---|---|
> | Freitas | `freitas.pactha.com.br` | `pactha-54-232-208-118.sslip.io` |
> | Trust | `trust.pactha.com.br` | `pactha-trust-54-232-208-118.sslip.io` |
> | Monte Siao | `montesiao.mg.pactha.com.br` | `pactha-montesiao-mg-54-232-208-118.sslip.io` |
> | Santa Maria | `santamaria.rs.pactha.com.br` | `pactha-santamaria-rs-54-232-208-118.sslip.io` |
> | Nova Palma | `novapalma.rs.pactha.com.br` | `pactha-novapalma-rs-54-232-208-118.sslip.io` |
> | BGK | `bgk.pactha.com.br` | `pactha-bgk-rs-54-232-208-118.sslip.io` |
>
> ⚠️ Os dois primeiros **faltavam neste arquivo** ate 05/09/2026, e a ausencia custou uma
> sessao inteira de desconfianca: quem le so o `INFRA.md` conclui que `freitas.pactha.com.br`
> e outro ambiente. Dominio novo entra AQUI no mesmo dia em que e apontado.

### Freitas
| Resource | Build | URL |
|---|---|---|
| `freitas-frontend` | `frontend/Dockerfile` (base `/frontend`) | https://freitas.pactha.com.br · https://pactha-54-232-208-118.sslip.io |
| `freitas-api` | `backend/Dockerfile.api` (base `/`) | https://pactha-api-54-232-208-118.sslip.io |
| `freitas-worker` | `backend/Dockerfile.scraper` | interno (sem domínio público) |
| `freitas-db` | `postgres:16-alpine` | interno — db/user `pactha`, uuid `tox59kvmkrb0ywmeaty3t02a` |

### Trust
| Resource | Build | URL |
|---|---|---|
| `trust-frontend` | `frontend/Dockerfile` | https://trust.pactha.com.br · https://pactha-trust-54-232-208-118.sslip.io |
| `trust-api` | `backend/Dockerfile.api` | https://pactha-trust-api-54-232-208-118.sslip.io |
| `trust-worker` | `backend/Dockerfile.scraper` | interno |
| `trust-db` | `postgres:16-alpine` | interno — db/user `pactha`, uuid `p434vbj35siee57shlsyzuc2` |

### Monte Sião / MG
| Resource | Build | URL |
|---|---|---|
| `montesiao-mg-frontend` | `frontend/Dockerfile` | https://montesiao.mg.pactha.com.br · https://pactha-montesiao-mg-54-232-208-118.sslip.io |
| `montesiao-mg-api` | `backend/Dockerfile.api` | https://pactha-montesiao-mg-api-54-232-208-118.sslip.io |
| `montesiao-mg-worker` | `backend/Dockerfile.scraper` | interno |
| `montesiao-mg-db` | `postgres:16-alpine` | interno — db/user `pactha`, uuid `iogvjlnkpqlugja9j76rktl1` |

### Santa Maria / RS
| Resource | Build | URL |
|---|---|---|
| `santamaria-rs-frontend` | imagem `pactha-frontend-santamaria-rs` | https://santamaria.rs.pactha.com.br · https://pactha-santamaria-rs-54-232-208-118.sslip.io |
| `santamaria-rs-api` | imagem `pactha-api` | https://pactha-santamaria-rs-api-54-232-208-118.sslip.io |
| `santamaria-rs-worker` | imagem `pactha-worker` | interno |
| `santamaria-rs-db` | `postgres:16-alpine` | interno — db/user `pactha`, uuid `m2ypghl41lbqhv7rdqzffdi3` |

> ⚠️ **Environment por tenant, não `production`.** O projeto `pactha` tem um environment por
> cliente (`freitas`, `trust`, `montesiao-mg`, `santamaria-rs`, `novapalma-rs`, `bgk-rs`); o
> `production` está **vazio**.
> Tenant novo ganha o seu (`POST /projects/{uuid}/environments`, que responde 201).
>
> **Santa Maria foi o primeiro banco criado do zero** — os outros três vieram migrados do Neon,
> já com o schema completo. Isso expôs 12 colunas de `convenios_estadual` (`fonte` + os campos
> do RM) que existiam **só por herança**: não estavam no `setup_db` nem em migration nenhuma.
> Corrigido por `add_convenios_estadual_colunas_faltantes.sql`, que é no-op nos três antigos.
> Sem ela, um bootstrap limpo termina em `62/64 migrations` e a tela de convênios quebra.

> **`montesiao-mg-painel` JÁ FOI REMOVIDO** — conferido em 2026-07-31: zero linhas
> em `applications` com o uuid `uymt911sgynkbvifyzf6nf1h`. São **9** aplicações no
> projeto, não 10. O Painel Executivo virou parte do frontend principal:
> `/dashboard` é o **Painel de Indicadores** e `/tela` é o **Modo Tela** (janela de
> exibição), no mesmo deploy e no mesmo login. A pasta `painel/` saiu do CI em 07/2026 e do
> repositório em 12/09/2026.
>
> **Resíduo vivo:** o cron `painel-alertas` monta o payload de push apontando para
> `/app/alertas`, que era rota **daquele** app — hoje 404 no frontend novo. Sem
> efeito prático, porque o canal de push está morto nas três pontas: nenhum
> `pushManager.subscribe` no frontend, nenhum handler de `push` em
> `public/sw.js`, e `painel_push_subscriptions` vazia. Ou se reconstrói o cliente,
> ou se remove cron e tabelas — manter código morto vivo já custou tempo de
> auditoria discutindo notificação que ninguém pode receber.

### Nova Palma / RS

| App | Origem | URL |
|---|---|---|
| `novapalma-rs-frontend` | imagem `pactha-frontend-novapalma-rs` | https://pactha-novapalma-rs-54-232-208-118.sslip.io |
| `novapalma-rs-api` | imagem `pactha-api` | https://pactha-novapalma-rs-api-54-232-208-118.sslip.io |
| `novapalma-rs-worker` | imagem `pactha-worker` | interno |
| `novapalma-rs-db` | `postgres:16-alpine` | interno — db/user `pactha`, uuid `dl2jwo0q1ckbplqp6vp1hnu4` |

> **5o tenant, aberto em 01/09/2026.** Nasce so com Nova Palma/RS (IBGE 4313102).
> **Sem brasao ainda** — `NEXT_PUBLIC_CLIENT_LOGO` e `RM_LOGO` estao VAZIOS de
> proposito: a marca entra embutida na imagem e subir com logo errado e pior que
> subir sem. Quando o brasao chegar, e um arquivo em `frontend/public/` + uma
> linha na matriz do CI + um rebuild.
>
> **Os crons dele estao 25 min a frente dos do santamaria-rs** (mesmo conjunto de
> fontes do RS). Nao "arrume" isso alinhando os dois: os dois workers rodam o
> mesmo scraping contra o MESMO PORTAL, e o `flock` de cada tarefa protege ela de
> si mesma, nao da tarefa irma no outro container. (O motivo escrito aqui era
> "host de 0,6 vCPU sustentado"; a maquina tem 8 vCPU desde o upgrade — §1 — e a
> razao de verdade sempre foi o portal do outro lado.)

### BGK / RS

| App | Origem | URL |
|---|---|---|
| `bgk-rs-frontend` | imagem `pactha-frontend-bgk-rs` | https://pactha-bgk-rs-54-232-208-118.sslip.io |
| `bgk-rs-api` | imagem `pactha-api` | https://pactha-bgk-rs-api-54-232-208-118.sslip.io |
| `bgk-rs-worker` | imagem `pactha-worker` | interno |
| `bgk-rs-db` | `postgres:16-alpine` | interno — container `evdmnadr2iiwqhjvnzvqrgvs` |

> **6o tenant, aberto em 08/09/2026 (PR #447).** Primeira **assessoria** com mais de um
> município: 10 do RS (Bento Gonçalves, Veranópolis, Nova Prata, Guaporé, Serafina
> Corrêa, São Marcos, Carlos Barbosa, Garibaldi, Portão, Giruá). Environment Coolify
> `bgk-rs` (id 24); domínio `bgk.pactha.com.br` **no ar desde 09/09/2026**.
>
> Frontend e API **responderam 200 em 09/09/2026**, e a API já subiu com o código do
> merge #446 (`/api/control/resumo-coleta` devolvendo 401 sem token, que é o certo).
>
> ⚠️ **O que ainda NÃO foi conferido neste tenant: se ele coleta.** As medições de
> Scheduled Task deste arquivo (§5) são todas anteriores a 08/09 e falam de **5**
> workers — o worker do bgk pode ter nascido sem tarefa nenhuma, e tarefa que não
> existe não avisa que não existe (ver *"criar task não é ligar a fonte"*). Confira com
> `GET /applications/6xast9rw0wbzbownss9vamfq/scheduled-tasks` antes de assumir que os
> 10 municípios estão sendo varridos.

### Servidor MCP (leitura por IA) — um por tenant

Cada `*-api` expõe **`/api/mcp`** (Streamable HTTP, SDK oficial `mcp` 2.x): um
servidor MCP **somente leitura** para um assistente de IA (Claude, ChatGPT)
consultar os dados do município. Autentica por **Bearer token por usuário**
(`mcp_tokens`, hash SHA-256), que **herda o escopo de município do dono** — não é
chave-mestra (ao contrário do `service_tokens`). Sem token válido → 401. Ferramentas
(convênios, parlamentares, obras, regularidade, fundo a fundo, visão do município)
reusam as funções de agregação da própria API. Os tokens se geram na tela de
**Usuários** (cada um os seus; admin, os de qualquer pessoa). Código: `backend/mcp_app.py`,
`backend/services/mcp_auth.py`, `backend/routers/mcp_tokens.py`. URL para o cliente:
`<URL da *-api do tenant>/api/mcp/` — **com a barra no fim** (o Mount +
`redirect_slashes=False` faz `/api/mcp` sem barra devolver 404; com barra, 401 sem
token e 200 com token válido). Confirmado nos 5 em 07/09/2026.

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

Os bancos são internos à rede Docker do projeto (não têm porta pública). Para
`psql`/`pg_dump`, ou exponha a porta temporariamente no Coolify (e feche depois), ou
entre pelo host:

```bash
ssh -i ~/.ssh/coolify_localhost root@54.232.208.118
docker exec -it tox59kvmkrb0ywmeaty3t02a psql -U pactha -d pactha   # freitas
docker exec -it p434vbj35siee57shlsyzuc2 psql -U pactha -d pactha   # trust
docker exec -it iogvjlnkpqlugja9j76rktl1 psql -U pactha -d pactha   # montesiao-mg
docker exec -it m2ypghl41lbqhv7rdqzffdi3 psql -U pactha -d pactha   # santamaria-rs
docker exec -it dl2jwo0q1ckbplqp6vp1hnu4 psql -U pactha -d pactha   # novapalma-rs
```

Os cinco bancos já estão **populados com dados reais de produção** — não são mais
schema+seed. Migrações idempotentes rodam no boot da API (`backend/services/startup.py`).

---

## 5. Crons (Scheduled Tasks do Coolify)

> ⚠️ Atualizado em **2026-08-09**: a tabela de horários que vivia aqui ficou obsoleta DUAS
> vezes numa semana. **A fonte de verdade das agendas é o próprio Coolify**
> (`GET /applications/<worker_uuid>/scheduled-tasks`, ou `scheduled_tasks` no coolify-db).
> Este parágrafo documenta o **desenho**, que muda devagar; os horários, não copie daqui.
>
> ⚠️ **Todo "nos 5 workers" desta seção é anterior a 08/09/2026** e portanto NÃO fala do
> `bgk-rs`, que é o 6º. Tenant novo não herda Scheduled Task nenhuma — elas se criam uma a
> uma pela API do Coolify. Antes de assumir que o bgk coleta, pergunte ao Coolify (§3).

O desenho atual (redesenho de 09/08, "tuning da madrugada"):

- **Lock compartilhado `/tmp/scraper.lock`** por worker: `sigcon`, `transferegov-lote` e
  `cagec` **nunca rodam ao mesmo tempo no mesmo tenant** (quem chega com o lock tomado
  sai com `flock -E 99` → remapeado para sucesso = pulou a vez, a próxima rodada cobre).
- **Agendas entrelaçadas — nas DUAS direções.** Na vertical (o mesmo worker): quem cai
  dentro da janela de outra task do `/tmp/scraper.lock` pula a vez **sem log**, então a
  janela nova precisa terminar (`timeout` inteiro) antes da próxima vizinha. Na horizontal
  (tenants diferentes): o lote de dois tenants não se cruza no portal do TransfereGov,
  porque todos saem do mesmo IP.
  ⚠️ O "lote nas horas pares, sigcon nas ímpares" que vivia aqui acabou em algum ponto
  de 2026 sem ninguém anotar. Medido em 10/09/2026: o lote é **1x/dia** na madrugada
  em montesiao, santamaria, novapalma e bgk, e passou a **4x/dia** em freitas e trust
  (alternados: freitas `25 1,3,7,21`, trust `10 2,4,8,22` UTC — fora do horário
  comercial, fora do bloco 03:25–07:00 dos outros tenants e longe das 00:00 UTC, quando
  o Coolify reinicia e marca como falha o que estiver rodando). Com uma rodada só, a
  fila de ~60 municípios do freitas (`TG_LOTE_MUNICIPIOS=4`) levava ~15 dias para dar a
  volta, e o watchdog acusava 30 municípios parados.
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
  GConv-ES 2×/dia; GO (transfvol/cofin) 1×/dia; `siconv-federal` **mensal, e escalonado
  por DIA do mês, não por hora** — freitas dia 2, trust dia 3, montesiao dia 4,
  santamaria dia 5, novapalma dia 6 (é um dump grande; um dia por tenant evita cinco
  downloads pesados na mesma madrugada). Existe **nos 5 workers**; desde 17/08, quando
  trust e montesiao não a tinham e ficaram meses com `siconv_federal` = 0, a aba CNPJ do
  TransfereGov abrindo vazia.
- **`transferegov-te` é escalonado ENTRE TENANTS de propósito** (17/08). Os tenants saem
  do MESMO IP e a API `especiais` do TransfereGov tem quota por IP (~10 páginas/janela,
  renova em ~15 min): com todos no mesmo minuto — como era — quem roda por último só
  coleta 403. Medido ao vivo durante a auditoria de 17/08 (o montesiao errava TODA rodada
  que caía logo após a janela de outro tenant). Com o 5º tenant a escada foi refeita e o
  passo subiu de 20 para **30 min** (medido 04/09): freitas 03:00, trust 03:30,
  montesiao 04:00, santamaria 04:30, **novapalma 05:00** UTC. Tenant novo continua a
  escada. No mesmo dia de 17/08 o `timeout` da task subiu de 300 para 1720s em todos os
  workers: estava ABAIXO do orçamento interno (1600s), o Coolify matava primeiro e
  descartava o stdout — a task nunca tinha logado nada em nenhum tenant.
  ⛔ **E a quota tem uma segunda camada: PENALIDADE ESTENDIDA por martelada.**
  Também medido em 17/08: depois de ~1h30 de rodadas encadeadas (cron a cada
  minuto nos 4 tenants), o IP da VPS passou **>6 horas** com TODO primeiro fetch
  levando 403 — em qualquer janela, com a API respondendo 200 normalmente a
  outro IP no mesmo instante. E requisição REJEITADA também renova a pena: as
  próprias retentativas (5 requests de backoff por rodada) mantinham o bloqueio
  vivo. Sob penalidade, a única saída é SILÊNCIO longo (60-90 min sem nenhuma
  requisição do IP) e, depois, disparos únicos espaçados (≥18 min) — nunca
  encadear de novo. Sintoma inequívoco: `error: nenhuma pagina coletada` em toda
  rodada, inclusive em janela "limpa".
  ⭐ **06/09/2026: a LISTAGEM saiu dessa API e o parágrafo acima passou a valer só
  para os PAGAMENTOS.** Os planos de ação agora vêm da API pública oficial
  (`api-publica.transferegov.gestao.gov.br/especiais`, Comunicado nº 23/2026 do
  MGI), que não pagina estado inteiro: são 2 requisições por município, entrando
  pelo CNPJ. O que continua batendo em `especiais.transferegov.sistema.gov.br`
  são os documentos hábeis e as OP/OB — lookups por id, que **nunca** foram o
  que disparava a quota (590 requisições sequenciais, zero 403, medido em
  23/08). A escada entre tenants e o `timeout` da task seguem valendo: eles
  protegem justamente essa fase. Ver `ingestion/transferegov_te.py`.

> 🕐 **TUDO EM UTC. Brasília é UTC−3.** Host, `instance_timezone` do Coolify e
> PHP do container em `Etc/UTC`. As faixas do CAGEC (10/15/19/23 UTC) são
> **07h, 12h, 16h e 20h de Brasília** — um cron escrito como "07:00" rodaria às
> 4h da manhã para o cliente, e rodou.

> **`cauc-manha`** existe porque `cauc_situacao.data_pesquisa` é a data do
> extrato **do Tesouro**, não da nossa coleta, e eles só publicam o arquivo do
> dia entre **07h e 09h20 BRT**. A rodada do CAUC pendurada no `sigcon` pegava o
> arquivo de ontem, e às 8h a tela ainda mostrava a data anterior. Esta task
> insiste de hora em hora (10–14 UTC) até a data virar; é HTTP puro, ~2s.

> ⚠️ **`cagec` é o mesmo tipo de restrição, e custou quatro dias de tela errada.**
> O portal do CAGEC **não emite o CRC de madrugada** (medido em 07/09/2026, no mesmo
> worker: 06:15 UTC → "não foi possível recuperar dados do Convenente/Parceiro" em toda
> entidade; 17:58 UTC → as 27 obrigações em 34s). As três tasks estavam em 03h–04h BRT,
> então a situação atualizava e o **detalhamento** ficava congelado. Voltaram para a
> faixa comercial (freitas `0 10,15,19,23`, montesiao `46 10,19`, trust `48 10,19` UTC).
> A Freitas ainda somava um segundo defeito: 1 rodada/dia × lote 11 = ciclo de 4 dias.
> Os números, as medições e a regra do lote estão em `docs/CRON_SETUP.md` → *cagec — a
> fonte tem JANELA*.

Detalhes de cada rotina e dos comandos completos: `docs/CRON_SETUP.md`.

**SISMOB** (obras de saúde do MS) é **API JSON pública** — sem token, sem login, sem
Playwright. Como a fonte muda a cada ~60 dias por obra, o `ingest()` se auto-limita a
1×/dia (`SISMOB_MIN_INTERVAL_H=20`; `SISMOB_FORCE=1` força, `SISMOB_ENABLED=0` desliga
por tenant).

> ⚠️ **Ele tem DOIS caminhos vivos, e a versão anterior deste arquivo dizia que não tinha
> nenhum.** Medido em 04/09: existe Scheduled Task **`sismob` nos 5 workers** (freitas
> 03:18 → novapalma 05:18 UTC, lock próprio `/tmp/sismob.lock`, criadas entre 02/08 e
> 01/09) **e** a entrada `("SISMOB", "ingestion.sismob_obras")` continua em
> `run_dadosabertos_cron.run_all()`, que o `run_sigcon_cron.py` chama na linha 32.
>
> **Hoje isso não duplica coleta, mas por margem e não por desenho:** os dois caminhos
> entram pelo mesmo `ingest()` e batem no mesmo gate de 20h (`_deve_pular()`, que consulta
> `ingestion_log`). No freitas a task roda 03:18 e o `sigcon` chega às 05:45 — 2h27 depois,
> gate fechado. Estreitar essa folga, ou trocar a task para chamar `run()` direto, ressuscita
> exatamente o incidente do **PR #259** (duas coletas/dia, a segunda descontando do
> orçamento do SIGCON). Nos dois tenants do RS **não há `sigcon`**, então lá a task é o
> único caminho — não é redundância, é a coleta.
>
> Duas afirmações vencidas que ainda circulam: o docstring de `_deve_pular()` diz *"sem uma
> Scheduled Task própria no Coolify, o intervalo mora aqui"* (tem, nos cinco) e *"o cron
> hospedeiro roda 4×/dia"* (o `sigcon` roda **1×/dia** por tenant). Corrigir esse comentário
> é mudança em `backend/**`, ou seja, deploy nos cinco — não vale sozinho, mas vá junto na
> próxima leva.

> ⚠️ **`SISMOB_ENABLED=0` deixa o watchdog reclamando para sempre.** O `ingest()`
> retorna antes de rodar, então nunca grava linha em `ingestion_log`, e o
> `watchdog_coleta` — cujo catálogo `FRESCOR_HORAS` é **global aos 5 tenants**,
> constante no código — passa a registrar "sismob: nenhum sucesso registrado" a
> cada ciclo. Hoje isso é uma linha WARN no log da Scheduled Task e uma linha na
> aba Status dos Dados, mas no dia em que existir um canal que **avisa gente**
> (o WhatsApp da API oficial da Meta), vira alarme recorrente sobre uma fonte
> desligada de propósito — resolva antes de ligar o canal. Não é defeito do SISMOB: é a lacuna entre expectativa global e
> desligamento por tenant. Prefira **não deployar** o módulo no tenant do que
> deployar e desligar pela env.

**`SISMOB_ALLOW_SHRINK=1`** destrava a GUARDA 4 do coletor. Por padrão, se a
listagem devolver itens sem `proposta_id`, ou se mais de 1/5 da carteira do
município fosse marcada como ausente de uma vez, a rodada **falha e faz rollback**
em vez de marcar — porque obra marcada como ausente some da tela, do BI, da TV e
dos alertas ao mesmo tempo, e a rodada era gravada como `success`. Use a válvula
só quando o encolhimento for real (obra de fato retirada do programa); sem ela, um
município que legitimamente perca obras fica repetindo a falha.

**SIMEC — Termos de Compromisso** (`ingestion/simec_termos.py`, PR #258) tem **Scheduled
Task própria nos 5 workers** (escada de 30 min como a do `transferegov-te`: freitas 03:12
→ novapalma 05:12 UTC), com lock **próprio**
(`/tmp/simec_termos.lock`) e `timeout -k 30 1700`. O lock é separado de propósito: o
`/tmp/scraper.lock` existe para serializar **Chromium**, e esta fonte é `httpx` puro, sem
login e sem navegador — não precisa disputar aquela fila. 1×/dia basta porque o que ela
traz é o **instrumento** (processo, vigência, valor), que muda em MESES; quem se move é o
pagamento, e isso vem 4×/dia por `simec_par_liberacoes` dentro do `run_all()`.

> ⚠️ **NÃO pendurar esta fonte no `run_dadosabertos_cron.run_all()`.** O PR #259 fez isso
> por premissa errada (documentou que "não tem task em nenhum worker" — tem, nos quatro) e
> criou DOIS caminhos vivos: o `run_all()` disparava por volta das 05:25, quando o gate de
> 20h do `ingest()` já havia vencido desde as 06:10 do dia anterior, e a task coletava de
> novo 45 min depois. Duas coletas por dia, e a do `run_all()` ainda descontava do
> orçamento do SIGCON. Desfeito no PR seguinte. `ingest()` continua no arquivo como porta
> alternativa (com `SIMEC_TERMOS_ENABLED=0` / `SIMEC_TERMOS_MIN_INTERVAL_H` /
> `SIMEC_TERMOS_FORCE=1`), mas ninguém o chama — a task executa o `__main__`, que vai
> direto no `run()`.
>
> O orçamento interno é `SIMEC_TERMOS_BUDGET_S=1500`, pela regra de ouro: interno +
> 1 município pesado, e a coluna `timeout` da task = interno + 120s (daí os 1700).
> Mexer num sem mexer no outro é o erro clássico aqui.

**`cagec`** (desde 2026-07-30; hoje nos **três tenants com município de MG** — freitas
06:15, trust 07:00, montesiao 07:15 UTC; os dois tenants do RS não têm, e não devem ter):
regularidade **estadual** de MG. Roda depois da rodada do `sigcon` — de propósito, porque o
CNPJ do município é inferido das emendas estaduais que o SIGCON acabou de coletar.
Não usa credencial: a consulta do CAGEC é **pública** e basta o CNPJ. O detalhe
(cada obrigação com situação e validade) vem do **CRC em PDF**, que a própria
consulta emite mesmo para município irregular — por isso o worker precisa de
`pypdf`. Custa ~20s por município, então um tenant com 18 municípios gasta ~6min
de uma vez ao dia; não há download em massa (os botões de exportar só existem
depois de uma busca). Onde o portal fica e as armadilhas dele:
`backend/ingestion/cagec_scraper.py`.

**`parcerias`** (Gestão de Parcerias do Transferegov.br · 07/09/2026): Scheduled Task
**nos 5 workers**, escada de 30 min — freitas 06:00, trust 06:30, montesião 07:00,
santa maria 07:30, **nova palma 08:30** UTC, com `timeout -k 30 1500`. Lock próprio
(`/tmp/parcerias.lock`): é `httpx` puro, sem login e sem navegador.

> ⭐ **É onde a emenda de saúde do município vive.** O módulo processa as transferências
> de 2024 em diante — 144 dos 176 programas publicados são Fundo a Fundo da Saúde — e
> era o único instrumento federal invisível à plataforma. Em Nova Palma são 11
> propostas, R$ 2,18 mi, **11 de 11 com emenda e parlamentar identificados**.
>
> ⚠️ **NÃO entra por CNPJ, e essa é a diferença para a Transferência Especial.** As 11
> propostas de Nova Palma são todas do FUNDO MUNICIPAL DA SAUDE (`12240183000100`),
> não da prefeitura (`88488358000156`): um coletor que casasse por `municipios.cnpj`
> não acharia nenhuma. O `cd_ibge_recebedor` filtra no servidor e o vínculo vem pronto.
>
> ⚠️ **A execução financeira ficou de fora por custo medido.** Os tenants têm 547
> (freitas) e 706 (trust) propostas; buscar os 8 filhos de cada uma custaria 27 e 35
> min, contra ~420s e ~530s do núcleo. O `/extrato-bancario` sozinho tem **1.275.217
> registros** (6.377 páginas) — varrer a fonte inteira, o que funciona no Obras.gov,
> aqui é inviável.

**`cadin-rs`** (CADIN/RS + CFIL/RS · 07/09/2026): Scheduled Task **só nos dois workers do
RS** — santamaria `10 5 * * *`, novapalma `40 5 * * *` UTC (10 min depois do `che-rs` de
cada um). Lock próprio (`/tmp/cadin_rs.lock`), `httpx` + `pypdf`, sem navegador. Certidão
**pública, sem login**: `POST cadin.sefaz.rs.gov.br/api/Certidao/EmitirCertidao[Cfil]`.
Em Minas **não há task**: o CADIN-MG vem dentro do CRC, na rodada do `cagec`.

> ⚠️ **A certidão não tem validade** — ela afirma a situação *"na data de …"*. Por isso a
> coleta é diária **e** a tela tem botão *consultar agora*
> (`POST /api/cadastros-negativos/refresh?municipio_id=`, só RS). Detalhes da fonte e das
> margens: `docs/CRON_SETUP.md` → *cadin-rs*.

**`siconfi`** (contas entregues no Tesouro + CAPAG · 07/09/2026): Scheduled Task **nos 5
workers**, escada de 30 min — **freitas 00:30, trust 01:00, montesiao 01:30**, santamaria
02:00, novapalma 02:30 UTC. Lock próprio (`/tmp/siconfi.lock`): é `httpx` puro, sem login
e sem navegador.

> ⚠️ **CRIAR A TASK NÃO É LIGAR A FONTE.** As três tasks novas (freitas, trust,
> montesião) foram criadas em 07/09 às **02:17 UTC** — *depois* dos horários agendados
> (00:30, 01:00, 01:30) —, então nenhuma delas rodou naquele dia. O freitas tinha dados só
> porque alguém rodou a carga na mão às 02:13; montesião e trust ficaram com **zero** CAPAG
> e zero entregas, sem erro em lugar nenhum. Ao criar uma task cujo horário do dia já
> passou, **rode a primeira carga à mão** ou confira o banco no dia seguinte.

> ⚠️ **Existia só nos DOIS tenants do RS até 07/09/2026** — freitas, trust e montesião
> nunca tinham rodado. Não é só a tela de Regularidade que fica vazia sem ele: este
> coletor é quem **preenche `municipios.cnpj`** a partir do cadastro de entes do Tesouro,
> e esse campo virou a CHAVE da Transferência Especial quando a listagem migrou para a
> API oficial (PR #404). Sem ele, o município cai no casamento por nome — o defeito que
> aquela migração existiu para matar. Descoberto ao validar o #404 em produção: dos 60
> municípios do freitas, os 18 sem CNPJ eram exatamente os 18 **inativos**, porque o
> `siconfi` filtra `WHERE active` e nunca os visitara.
>
> ⚠️ **A CAPAG morria inteira por causa de `"n.d."`.** As notas parciais eram `VARCHAR(2)`
> e o Tesouro publica `n.d.` (4 caracteres) quando o indicador não é apurado: a exception
> derrubava o bloco todo, então UM município zerava a nota de TODOS e o log dizia apenas
> "1 falha(s)". Corrigido para `TEXT` em `fix_siconfi_capag_notas_texto.sql`. Depois do
> conserto, o freitas gravou 1.427 linhas com 0 falhas (antes: 1.385 com a CAPAG perdida).

**`obrasgov`** (obras federais do Obras.gov.br/CIPI, PRs #367–#370, 03–04/09/2026):
Scheduled Task **nos 5 workers**, escada de **30 min** — santamaria 03:05, novapalma
03:35, montesiao 04:05, trust 04:35, **freitas 05:05** UTC, com `timeout -k 30 1800`.
Lock **próprio** (`/tmp/obrasgov.lock`) pelo mesmo motivo do `simec-termos`: é `httpx`
puro, sem login e sem navegador, então não disputa a fila do Chromium do
`/tmp/scraper.lock`.

> ⭐ **A escada era de 5 min e o timeout de 900s até 07/09/2026** — os dois mudaram
> juntos, e por causa da mesma coisa: a fase de DETALHE, que varre os endpoints filhos
> (execução física, empenho, contrato, paralisação, estudo de viabilidade) e leva a
> rodada de ~75s para ~8-10 min.
>
> ⚠️ **Varrer os cinco custa 1.020s medidos** — `execucao-fisica` 384s, `empenho` 301s,
> `estudo-viabilidade` 276s, `contrato` 30s, `historico-paralisada` 29s. Por isso o
> coletor faz **rodízio**: os dois baratos toda noite e um dos três caros por vez, cada
> um se atualizando a cada três dias. Sem isso seriam 17 min por tenant, com os cinco
> baixando as mesmas 1.278 páginas da mesma fonte federal todo dia.
> Com 5 min entre tenants, os cinco varreriam a fonte federal **ao mesmo tempo, do
> mesmo IP** — 5× a carga, que é exatamente como se conquista um bloqueio. A escada de
> 30 min é a mesma disciplina que o `transferegov-te` já segue.
>
> ⚠️ Varrer a fonte inteira e casar em memória é mais barato do que perguntar projeto a
> projeto, e a diferença cresce com a carteira: em Santa Maria seriam 2.180 requisições
> (~13 min) contra ~450s fixos. O coletor tem `OBRASGOV_TETO_TAREFA_S` (1700) e pula a
> fase de detalhe inteira se não couber, em vez de ser morto no meio e perder o log.

> ⚠️ **O freitas estava em 03:25, no MESMO minuto do `transferegov-lote`** (corrigido para
> 03:30 em 04/09). Como os locks são diferentes de propósito, os dois **não** se
> serializam: largavam juntos, e o lote é a task Chromium mais cara do tenant com a maior
> carteira (`TG_LOTE_MUNICIPIOS=4`). A escada de 5 min foi desenhada **entre tenants** e
> ninguém a conferiu contra as tasks 03:xx que cada tenant já tinha. **Ao criar task nova
> em escada, confira também a coluna vertical de cada worker.**

⭐ **O host é `api-publica.obrasgov.gestao.gov.br`, NÃO `api.obrasgov...`** O host sem o
`-publica` devolve **429 na primeira requisição** vinda da VPS (medido: 0,06 s, sem corpo),
e foi o que manteve o coletor pronto e desligado desde 02/09. O mesmo acervo, no host
público, responde **200 em 0,13 s** — era host, não era o Governo nos recusando. Trocar de
host matou três das quatro armadilhas antigas (paginação que mente, páginas que se
sobrepõem, rate limit apertado) e derrubou a varredura de uma UF de ~8 min para ~75 s.

As armadilhas que **sobraram**, todas silenciosas e anotadas em `backend/ingestion/obrasgov.py`:

- **O filtro territorial não existe e é ignorado em silêncio**: `codigo_ibge` devolve o
  **estado inteiro** com HTTP 200. O recorte é feito em memória.
- **O município sai do CNPJ, NUNCA do nome** (diretriz do dono, 04/09): casar por nome
  trouxe 379 obras da UFSM como se fossem da prefeitura de Santa Maria.
- **As taxonomias são `TEXT`, não `VARCHAR`** — `natureza`/`especie`/`situacao`/`sistema`
  são vocabulário de fonte externa (5 a 9 valores distintos) e o Governo renomeia categoria
  sem avisar. Uma categoria de 41 caracteres numa coluna `VARCHAR(40)` **abortou a carga
  inteira do santamaria** depois do novapalma ter passado limpo minutos antes. Só continuam
  `VARCHAR` os campos que têm *formato*: `id_unico`, `cep`, `uf`.
- **A fonte manda acento codificado DUAS vezes** (`Proinf\xc3\x83\xc2\xa2ncia`): o Governo
  leu latin-1 como UTF-8 e gravou o resultado. O conserto está na **ingestão** e desiste se
  a reinterpretação não melhorar — um conserto cego corromperia 32.000 obras para arrumar 2.
- **A data efetiva não é sinal de nada**: vazia em 100% das 1.011 obras coletadas, e 65
  obras "Concluída" não têm data de conclusão. Quem classifica é a `situacao`; a data
  prevista só gradua.

**`fpe-rs` — a fonte tem HORÁRIO COMERCIAL, e o cron precisa respeitar.** O FPE
(`portalfpe.sefaz.rs.gov.br`) atende **segunda a sábado, das 7h às 22h30 BRT**; fora
disso responde **500** com essa frase. Até 04/09 as duas tasks estavam em **02:04 e 02:34
BRT** (santamaria `4 5 * * *`, novapalma `34 5 * * *`) — madrugada, e `* * *` ainda incluía
domingo. Corrigidas para `14 14 * * 1-6` e `44 14 * * 1-6` (11:14 e 11:44 BRT, seg–sáb).

> ⚠️ **Isso não estava doendo, e é exatamente por isso que sobreviveu 18 dias.** O coletor
> é inerte enquanto não houver credencial PCPRS no Cofre: ele sai antes de tocar no portal
> e grava `success` ("sem credencial" é nota, nunca alarme — regra do dono). No dia em que
> a credencial entrasse, os dois tenants passariam a falhar **todo dia**, e o sintoma
> pareceria coletor quebrado, não cron errado. **Fonte com janela de funcionamento é
> restrição de agendamento — anote-a no cron, não só no docstring do coletor.**

---

## 6. Plataformas que NÃO usamos

Não usamos Hetzner, Railway, Neon, Vercel, Netlify nem Supabase — infra atual é Coolify na AWS Lightsail (ver INFRA.md).

---

## 7. Onde estão os segredos

`JWT_SECRET`, `COFRE_KEY`, `ADMIN_PASSWORD`, `DATABASE_URL`, `ANTHROPIC_API_KEY`,
`CONTROL_TOKEN_BOOTSTRAP` e as chaves VAPID vivem **nas env vars do resource no Coolify**
(criptografadas no banco do Coolify), **por tenant**. Não estão no git nem em
arquivo no host.

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
- **Restart (sem rebuild):** `POST $B/applications/<uuid>/restart` → `{"message":"Restart
  request queued.","deployment_uuid":...}`. ⚠️ **É POST; o `GET` devolve 405** — e 405 num
  endpoint que existe parece endpoint errado, o que faz procurar o nome certo em vez do
  verbo certo. É o caminho para **env nova entrar em vigor**, que não precisa de deploy.
  ⚠️ **Env alterada DEPOIS do início de um deploy não entra nos containers dele** — o
  Coolify injeta as envs na criação do container. Medido em 08/09/2026 ao ligar o canal do
  watchdog: o deploy do merge subiu os cinco workers com `WATCHDOG_TELEGRAM_TOKEN` vazia
  porque o valor foi corrigido minutos depois; o sintoma é o pior possível — deploy verde,
  código novo lá dentro e a feature morta. Confira **dentro do container**
  (`docker exec <c> sh -c 'echo ${#MINHA_ENV}'`), nunca no painel.
- **Logs:** `GET $B/applications/<uuid>/logs?lines=120`.
- **Env vars (bulk):** `PATCH $B/applications/<uuid>/envs/bulk` com
  `{"data":[{"key":..,"value":..,"is_build_time":bool,"is_preview":false}]}`.
  ⚠️ O `POST /envs` simples **não aceita** `is_build_time` — use o bulk.
  `NEXT_PUBLIC_*` e `API_PROXY_TARGET` precisam de `is_build_time:true`.
  ✅ **O bulk é UPSERT, não substituição** — medido em 08/09/2026 nos cinco workers ao
  ligar o canal do watchdog: mandando 2 chaves, o freitas foi de 11 para 13 envs de
  produção e **nenhuma** das outras sumiu. O nome "bulk" sugere o contrário e já fez
  sessão hesitar; mesmo assim, `GET /envs` antes é barato e é a única rede se a
  próxima versão do Coolify mudar isso.
- **Domínio:** `PATCH $B/applications/<uuid>` com `{"domains":"https://..."}` + redeploy.
- **Scheduled Tasks:** `GET/POST $B/applications/<worker_uuid>/scheduled-tasks`.
- **Banco:** `GET $B/databases/<uuid>` (campos `status`, `internal_db_url`).
- **Coleta forçada ("run now")**: a API v1 **não tem** disparo imediato de task, e o
  endpoint `/execute` não existe nesta versão. A manobra que funciona (auditoria de
  17/08): `PATCH` a `frequency` da task para `* * * * *`, esperar ~90s (um fire), e
  **restaurar o cron original num `finally`** — cron esquecido em `* * * * *` é o
  coletor batendo 1440×/dia no portal do governo. O processo já iniciado sobrevive à
  restauração (roda até o fim). Três regras aprendidas a caro:
  1. **Um Chromium por worker por vez.** Os workers têm 2 GB; duas tasks de browser
     simultâneas (sigcon + lote, ou um one-shot durante uma cadeia) morrem por
     memória **sem log nenhum** — o fire parece não ter acontecido. Foi por isso que
     o sigcon do trust "falhou" 3× em 17/08: só rodou quando ganhou janela exclusiva.
  2. **Deploy mata coleta em voo** (restart do worker) e o fire diário perdido para
     um `flock` ocupado não se repete sozinho — conferir o `ingestion_log` depois.
  3. ⚠️ **O `finally` já falhou de verdade — task descartável também precisa de dono.**
     Em 04/09 apareceu uma `tmp-g9umo` no `montesiao-mg-worker`, criada em 03/09
     01:58Z e ainda em `* * * * *`: **34 horas, ~1.440 execuções**. Era só uma sonda de
     diagnóstico (`select uf,count(*) from municipios where active group by 1` jogado
     no stdout do PID 1), então não bateu em portal nenhum — mas foram 1.440 processos
     Python e 1.440 conexões novas ao Postgres da **prefeitura com uso real**, além de
     encher o log do container e atrapalhar a leitura de
     log de verdade. Apagada em 04/09. **Ao terminar uma auditoria, releia
     `GET /applications/<worker>/scheduled-tasks` dos cinco workers e confirme que
     nenhuma task ficou em `* * * * *` e que não sobrou nome `tmp-*`.** É uma chamada,
     e é a única prova de que o `finally` rodou.
- **Auditoria município × fonte**: `GET /api/control/cobertura` na API de cada tenant
  (header `X-Control-Token`, valor na env `CONTROL_TOKEN_BOOTSTRAP` da app) devolve,
  por município, a contagem POR FONTE (separada p/ `convenios_estadual` e
  `cagec_situacao`, PR #245) e o carimbo do rodízio (`scraper_municipio_coleta`).
  Para frescor por fonte use `ultimo_por_fonte` de `GET /api/control/ingestion` —
  as 80 linhas do `log` são janela e, em dia de coleta intensa, fonte diária "some"
  e parece parada (falso-positivo que atrapalhou a auditoria de 17/08 duas vezes).
  ⚠️ Contagem **zero é estado legítimo** (município sem emenda Pix, sem obra, sem
  conta irregular): o veredito é *o coletor visitou sem erro*, nunca a contagem.

UUIDs das aplicações medidos em 2026-07-23 (os três do `bgk-rs` vieram dos workflows do CI
em 09/09/2026 — `build-backend.yml` e `build-frontend.yml` deployam por esses uuids):

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
| `santamaria-rs-api` | `ufjctldngc14dsdw8pxnqivl` |
| `santamaria-rs-frontend` | `eohjo0cy4nbl6t7hiaqwagwf` |
| `santamaria-rs-worker` | `wquremniv57gag3tlil8uf6d` |
| `novapalma-rs-api` | `gemcwirmbelk1dztp2pbcqpf` |
| `novapalma-rs-frontend` | `rpqpxroy5orsuidrbfezlzkt` |
| `novapalma-rs-worker` | `kqcnvdsdkgn1efkm4nog8oes` |
| `bgk-rs-api` | `qhafp9uqmsvny75rzykmibdx` |
| `bgk-rs-frontend` | `srbi2qotciphxdxhn6io25a3` |
| `bgk-rs-worker` | `6xast9rw0wbzbownss9vamfq` |
