# CONTINUAR.md — Handoff PACTHA (leia isto primeiro)

> Documento de contexto para a **próxima sessão de IA** (Claude Code) que for continuar este projeto.
> É **auto-contido**: assuma que você (IA) não tem memória das sessões anteriores. Tudo que precisa está aqui.
> Última atualização: 2026-07-30.
>
> 📍 Para servidor, URLs, uuids, bancos e operações no Coolify, a fonte de verdade é o
> **[`INFRA.md`](INFRA.md)** na raiz. Este arquivo cobre o *projeto*; o `INFRA.md` cobre a *infra*.

---

## 1. O QUE É ISTO (em 30 segundos)

**PACTHA** = sistema de **monitoramento de convênios e transferências governamentais** para municípios de MG. Módulos: SIGCON-MG (convênios estaduais), TransfereGov, Emendas, Parlamentares, CAUC, Acordo FES, FNS, SIMEC/PAR, IA (Claude), DOU-MG, Relatório de Monitoramento (RM), Documentos, Cofre de Senhas (AES-256), Telegram, extensão Chrome de captura gov.br, Painel Executivo (PWA).

- **Frontend:** Next.js 16 (App Router) + Tailwind v4 + daisyUI + shadcn. Pasta `frontend/`.
- **Painel Executivo:** Next.js (PWA para o gestor/prefeito). Pasta `painel/`.
- **Backend:** Python 3.12 FastAPI (uvicorn). Pasta `backend/`. Tudo prefixado `/api`.
- **Banco:** PostgreSQL 16 puro (SQLAlchemy async+asyncpg na API; psycopg2 nos scrapers/migrations).
- **Scraping:** httpx + Playwright (Chromium) + curl_cffi. Pasta `backend/ingestion/`.

**Este repo (`alavank/pactha`) é um FORK PRÓPRIO** do repo original `MattMatiins/PACTA` (do Matheus). O usuário (alavank) **migrou** a stack para **Coolify + Postgres puro** e renomeou tudo de "PACTA" → "PACTHA". Railway, Neon e Vercel (do repo original) **não são mais usados**; a hospedagem posterior na Hetzner também já foi desativada — hoje é **AWS Lightsail**.

⚠️ **DOIS clones no PC — não confundir:**
- `C:\projetos\pactha` → **ESTE** repo (`alavank/pactha`). É onde você trabalha.
- `C:\projetos\PACTA` → clone do repo do Matheus (`MattMatiins/PACTA`), usado só para colaboração com ele. **NUNCA** pushe cruzado entre os dois.

⚠️ **Este repo tem RULESET no GitHub exigindo PR aprovado.** Não tente pushar direto na `main` — crie branch e abra PR.

---

## 2. ESTADO ATUAL (2026-07-23)

**São TRÊS tenants em produção**, todos do mesmo código, cada um com containers e banco próprios:

| Tenant | App | API |
|---|---|---|
| **Freitas** | https://pactha-54-232-208-118.sslip.io | https://pactha-api-54-232-208-118.sslip.io |
| **Trust** | https://pactha-trust-54-232-208-118.sslip.io | https://pactha-trust-api-54-232-208-118.sslip.io |
| **Monte Sião/MG** | https://pactha-montesiao-mg-54-232-208-118.sslip.io | https://pactha-montesiao-mg-api-54-232-208-118.sslip.io |

Monte Sião tem também o **Painel Executivo**: https://pactha-montesiao-mg-painel-54-232-208-118.sslip.io

Os três bancos já estão **populados com dados reais** (a migração vinda do Neon foi concluída — não é mais schema+seed). Login seed só vale em banco novo: `super-admin@alavank.com.br`, com senha ALEATÓRIA por tenant impressa no console do primeiro boot (ou via `ADMIN_PASSWORD`) — pede troca no 1º acesso.

**Um push na `main` NÃO mexe com cliente nenhum.** As 9 aplicações rodam com `build_pack = dockerimage`: elas executam a tag gravada em `docker_registry_image_tag`, e quem constrói é o GitHub Actions publicando no GHCR. Enquanto ninguém repontar a tag de um app específico, o cliente fica na versão dele. **Cuidado com a leitura antiga:** `is_auto_deploy_enabled` está `true` nas 9 — não é ele que segura o deploy, é o `build_pack`. Detalhe e prova empírica em [`INFRA.md`](INFRA.md) §2.

---

## 3. INFRA NO COOLIFY (como mexer)

Resumo; o detalhe completo (uuids de todas as aplicações, bancos, crons por tenant) está no **[`INFRA.md`](INFRA.md)**.

- **Servidor:** **AWS Lightsail `54.232.208.118`** (sa-east-1a, São Paulo). t3.large: 2 vCPU / 7,6 GB RAM / 160 GB SSD. **Burstable, baseline 30% (~0,6 vCPU sustentado)** — hospeda mais 10 projetos além do PACTHA. **Não paralelize trabalho pesado.**
- **Instância Coolify:** `http://54.232.208.118:8000` — API REST em `http://54.232.208.118:8000/api/v1`. Versão v4.1.2.
- **SSH:** `ssh -i ~/.ssh/coolify_localhost root@54.232.208.118`.
- **Token da API do Coolify:** NÃO está neste arquivo (é segredo). O usuário fornece (formato `36|xxxx`). Use `Authorization: Bearer <TOKEN>`. **Rotacione periodicamente.**
- **GitHub App (source):** `alavank-coolify` — já dá acesso ao repo privado `alavank/pactha`. Use o `github_app_uuid` dele ao criar apps.

**Projeto Coolify `pactha`** — uuid `ksmwr13y4iyprom8i1znede8`, environment `production`, **9 aplicações + 3 bancos** (o `montesiao-mg-painel` foi removido):

| Tenant | API | Frontend | Worker | Painel | Banco |
|---|---|---|---|---|---|
| freitas | `givx3567ygxppum10p1oungn` | `qgmw4e5wjem1e8jit2wyvo1d` | `s49c3b58lysqq0tpelneg3g3` | — | `tox59kvmkrb0ywmeaty3t02a` |
| trust | `pphvk2ygkuirjhu9qptvmfs5` | `j5ghp71lff003d5rfaynvy5y` | `xg714h8l7va4ejq70a5pmv5t` | — | `p434vbj35siee57shlsyzuc2` |
| montesiao-mg | `chr0n883hp19tjh7829k85a7` | `bryvqhhcu97lc3ku7a2hss0q` | `jhf0kjhps5keujiyhhsnvjt6` | `uymt911sgynkbvifyzf6nf1h` | `iogvjlnkpqlugja9j76rktl1` |

Builds: API = `backend/Dockerfile.api` (base `/`) · Frontend = `frontend/Dockerfile` (base `/frontend`, standalone) · Worker = `backend/Dockerfile.scraper` (`sleep infinity`, roda os crons via Scheduled Tasks) · Painel = `painel/Dockerfile` (base `/painel`). Bancos: `postgres:16-alpine`, db/user `pactha`, porta 5432, host = uuid do resource.

**Segredos** (`JWT_SECRET`, `COFRE_KEY`, `ADMIN_PASSWORD`, `DATABASE_URL`, `ANTHROPIC_API_KEY`, `CONTROL_TOKEN_BOOTSTRAP`, chaves VAPID do Painel): estão **nas env vars do Coolify, por tenant** (recupere com a API — ver §7). A senha do Postgres também está no `internal_db_url` do resource DB (`GET /databases/<uuid>`). **Nunca copie a `COFRE_KEY` de um tenant para outro.**

**Scheduled Tasks:** cada worker tem as suas, com horários **escalonados entre tenants** para não competir por CPU no host burstable. Ver a tabela em [`INFRA.md`](INFRA.md) §5 e `docs/CRON_SETUP.md`. Todos os comandos são embrulhados em `flock -n` (não sobrepõe execução) + `timeout -k 30` (mata processo pendurado).

---

## 4. DECISÕES DE ARQUITETURA (e POR QUÊ) — não desfazer sem motivo

1. **Mantido Python/FastAPI (não migrou p/ Node).** A parte difícil é o scraping: Playwright p/ portais JSF/SAML (SIGCON, TransfereGov), curl_cffi anti-Cloudflare (SIMEC), e a máquina de sessão gov.br (SSO/SAML/reCAPTCHA). Reescrever isso = refazer o pedaço mais frágil, sem ganho.
2. **Scraping continua httpx+Playwright+curl_cffi (NÃO usar Scrapy).** O sistema é integração de dados abertos (CSV/JSON) + 2 portais JS-pesados, não crawling de HTML em escala. Scrapy não resolveria e pioraria o caso anti-bot do SIMEC.
3. **Isolamento por deploy, não por código.** O código é single-tenant; cada cliente é um conjunto separado de containers + banco, diferenciado por env vars (`INSTANCE_SLUG`, `DATABASE_URL`, `NEXT_PUBLIC_CLIENT_LOGO`, `NEXT_PUBLIC_CLIENT_SUBTITLE`). Foi removido o co-branding via `NEXT_PUBLIC_TENANT`. **"Freitas" NÃO é um recurso do produto — é uma consultoria cliente** (prompt de IA, "padrão Freitas" nos RMs, usuários `@freitas.com.br`).
4. **Rename PACTA→PACTHA completo:** cookies (`pactha_access/refresh/csrf`), localStorage (`pactha_token/user/theme/...`), tema daisyUI (`pactha`/`pactha-dark`), issuer JWT (`pactha-api`), prefixo service-token (`pactha_st_`), email admin, extensão Chrome, `package.json` name. **Tabelas do banco NÃO eram "pacta"** (`convenios_estadual` etc.) → schema intacto.
5. **Gatilho on-demand virou FILA no Postgres.** O `POST /api/convenios/refresh-sigcon` (que no repo original chamava a GraphQL `serviceInstanceRedeploy` do Railway) grava na tabela `scraper_jobs`; `backend/ingestion/run_queue_sigcon.py` consome, via Scheduled Task `queue-sigcon`, com dedup pending/running. CORS é env-driven (`main.py`).
6. **`setup_db.py` roda no BOOT da API** (`backend/services/startup.py`, dentro de `run_migrations`, antes das migrations incrementais). Idempotente (CREATE IF NOT EXISTS + seed só se `users` vazio). No Coolify não há passo manual "rodar setup_db uma vez" — isto se auto-cura em deploy novo.
7. **Frontend faz proxy same-origin de `/api`.** `rewrites()` em `frontend/next.config.ts` repassa `/api/:path*` para o host interno da API (`API_PROXY_TARGET`, **build-time**), e a API não precisa ser same-site com o front. Com isso cookies httpOnly + CSRF + refresh silencioso funcionam. Ver §5.

---

## 5. ARMADILHAS / GOTCHAS (leia antes de debugar)

- **A máquina é burstable (baseline 30%).** Não rode scraping paralelo (`SIGCON_CONCURRENCY=1`), não alinhe os crons dos 3 tenants, não rebuilde os 10 apps de uma vez. Sintoma de estouro: tudo no host fica lento ao mesmo tempo, não só o PACTHA.
- **Coolify STRIPPA o path do domínio.** Se você setar o domínio de um app como `host/api`, o Coolify tira o `/api` antes de chegar no container (testado: `host/api/health`→404, `host/api/api/health`→200). Por isso a API tem **subdomínio próprio SEM path**, e o caminho normal do usuário é o proxy do Next (`API_PROXY_TARGET`).
- **`*.sslip.io` é public suffix** → `pactha-...sslip.io` e `pactha-api-...sslip.io` são **cross-site** entre si; cookies `SameSite=Lax` httpOnly não trafegam entre eles. É exatamente por isso que existe o proxy same-origin no Next (decisão 7). **Se alguém apontar o front direto no subdomínio da API (`NEXT_PUBLIC_API_URL` absoluto), o refresh silencioso quebra e volta o re-login a cada ~60min.**
- **`API_PROXY_TARGET` e `NEXT_PUBLIC_*` são BUILD-TIME.** Mudar o valor no Coolify sem rebuildar o frontend não tem efeito nenhum. Marque `is_build_time:true` e redeploy.
- **`transferegov_propostas` é criada tarde** nas migrations (por `add_voluntarias_id_proposta_siconv.sql`), mas migrations anteriores (`add_voluntarias_valores.sql` etc.) já a ALTERam → em banco **novo do zero**, ~6/22 migrations falham com "relation does not exist". Nos três bancos atuais isso não importa (a tabela já existe). Se um dia precisar de bootstrap 100% limpo, mova a criação de `transferegov_propostas` para o `setup_db.create_tables()`.
- **COFRE_KEY:** o Cofre e as sessões gov.br são cifrados com AES-256 usando a env `COFRE_KEY` (`backend/services/crypto.py`). Se a chave mudar, `decrypt()` volta `""` **silenciosamente** — sem erro, sem log. **Cada tenant tem a sua**; trocar ou cruzar chaves destrói o Cofre daquele cliente.
- **must_change_password=True** no admin seed → o 1º login redireciona pra `/change-password`. Normal.
- Worker aparece como `running:unknown` no Coolify (é `sleep infinity`, sem healthcheck). Normal. Frontends sem healthcheck também.
- **Chromium órfão.** O worker já roda com `tini` + reaper (`backend/reaper.sh`) e os crons com `flock`+`timeout`, justamente porque Chromium pendurado comia a RAM do host. Não remova esses wrappers.
- **O SISMOB é API pública, não scraping.** `sismobcidadao.saude.gov.br/api/public/obras`
  responde JSON sem token e sem login. Três armadilhas, todas silenciosas: (1) a
  **listagem e o detalhe usam nomes diferentes para o mesmo campo**
  (`propostaId`/`coSeqProposta`, `situacaoObra`/`dsSituacaoObra`…), então um
  `{**listagem, **detalhe}` grava `NULL` calado; (2) **IBGE de 7 dígitos devolve 200 com
  zero resultado**, indistinguível de município sem obra; (3) o campo da 1ª parcela tem
  **typo do próprio MS** (`vlPrimeraParcela`, sem o "i"). E o sinal de obra parada **não é
  `dtAtualizacao`** — é o timestamp das fotos. Tudo anotado em
  `backend/ingestion/sismob_obras.py`.
- **Não existem "1ª, 2ª e 3ª parcelas" no fundo a fundo.** A norma vigente (Portaria de
  Consolidação 6/2017, Título IX) é **parcela única**; obras antigas vieram 20%+80%. O
  marco de 90% **não existe** (o de 30% sim). E a prestação de contas é o **Relatório
  Anual de Gestão** (LC 141/2012), não um "relatório final".
- **O CAGEC NÃO fica dentro do SIGCON-MG.** Perder tempo procurando no portal logado é fácil: a palavra "CAGEC" não aparece uma vez sequer no HTML do sigconv2 nem no menu de 29 itens. Ele tem portal próprio (`cagec.mg.gov.br/convenente-web`) e a consulta é **pública** — basta o CNPJ, não precisa de credencial. Duas armadilhas do portal (ambas fazem a busca *parecer* vazia): a página contém a frase "clique no botão [PESQUISAR]", então seletor por texto casa com a **instrução** e o clique não faz nada; e o cabeçalho do grid usa `th`/`.z-listheader` — fora do seletor de células ele some, e sem cabeçalho não dá para casar coluna por rótulo. Está tudo anotado em `backend/ingestion/cagec_scraper.py`.
- **O detalhe da irregularidade vem do CRC, e o CRC SAI para município irregular.** Errei isso na primeira versão (assumi que só município regular emitiria) e a diferença é grande: a linha da busca só diz "Irregular", enquanto o botão **"Emitir CRC"** da mesma linha baixa um PDF com as ~24 obrigações uma a uma, **cada uma com situação e data de validade**, mais CADIN-MG, SIAFI e o vencimento do mandato. É o que permite dizer "seu FGTS venceu em 29/07" em vez de "você está irregular". Duas armadilhas do PDF: o cabeçalho tem `SITUAÇÃO: Irregular`, que casa como se fosse item (só ler depois de `DOCUMENTAÇÃO`), e a quebra de página parte um item ao meio (há remendo dedicado).
- **Espera fixa no portal do CAGEC falha 1 em 4.** O `wait_for_timeout` fixo depois do PESQUISAR lia o grid ainda vazio e reportava **"CNPJ não encontrado no CAGEC"** — sintoma enganoso, parece que o município não existe no cadastro. Use espera adaptativa (poll até a linha aparecer). Vale para qualquer postback do ZK.

---

## 6. PENDÊNCIAS

### 6.1 Domínios definitivos (`*.pactha.com.br`)
As três instâncias ainda respondem por `*.sslip.io`. A landing (`pactha.com.br`) e a Central de Comando (`control-center.pactha.com.br`) já usam domínio próprio. Falta decidir/criar os DNS `A` → `54.232.208.118` para os apps dos clientes e trocar os domínios no Coolify (`PATCH /applications/<uuid>` + redeploy). Lembre de ajustar `FRONTEND_URL`/`CORS_ORIGIN_REGEX` na API e rebuildar o frontend (env build-time).

### 6.2 Secrets opcionais por tenant (features ficam OFF até setar)
`ANTHROPIC_API_KEY` (módulo IA — hoje só `montesiao-mg-api` tem), `TELEGRAM_BOT_TOKEN` + `TELEGRAM_WEBHOOK_SECRET` (Telegram). Setar via `PATCH /applications/<api_uuid>/envs/bulk` + redeploy.

Credencial do **SIGCON-MG** (uma por município, no Cofre com `sistema='SIGCON-MG'` /
`automation_key='sigcon'`): sem ela o `sigcon` roda e não traz nada. Monte Sião está
cadastrada desde 2026-07-30. **O CAGEC não precisa de credencial** — consulta pública.

### 6.3 Auto-deploy
`is_auto_deploy_enabled = true` nas 9 aplicações — mas **isso não importa**, porque todas usam `build_pack = dockerimage` e não constroem a partir do git. O deploy é sempre um ato explícito: repontar `docker_registry_image_tag` e chamar `/deploy`. Ver [`INFRA.md`](INFRA.md) §2.

### 6.4 Separação de papel no banco para a trilha de auditoria — **decisão do dono**
A `audit_log` já é append-only no banco (gatilho) com selo encadeado e conferência na tela
(botão **Verificar integridade** em `/dashboard/auditoria`). Falta o passo que só o dono decide:
a aplicação hoje roda como `pactha`, **dona de tudo** — ou seja, com poder de derrubar o próprio
gatilho que a impede de mexer na trilha. O ideal é um papel `pactha_app` com
`REVOKE UPDATE, DELETE, TRUNCATE ON audit_log`.

O **SQL pronto** está comentado no fim de `backend/migrations/add_auditoria_imutavel.sql` (seção
"CAMADA 3"); o **passo a passo por tenant, o teste, o rollback e o modelo de ameaça** (o que a
corrente de selos garante e o que ela **não** garante) estão em
[`docs/AUDITORIA_IMUTABILIDADE.md`](docs/AUDITORIA_IMUTABILIDADE.md). Duas coisas de lá que valem
repetir aqui:

- **Não precisa de mudança de código.** Todo o DDL do boot roda em `DATABASE_URL_SYNC`
  (`services/startup.py`) e o runtime da API em `DATABASE_URL` — basta apontar cada uma para um
  papel. ⚠️ Mas `DATABASE_URL_SYNC` **precisa estar preenchida antes**: onde ela está vazia o
  fallback usa a própria `DATABASE_URL`, e trocar só essa faz as migrations rodarem sem
  privilégio de DDL e a aplicação sobe quebrada.
- **Comece por `freitas` ou `trust`, nunca por `montesiao-mg`** (prefeitura com uso real).

---

## 6.5. ABRIR CLIENTE NOVO

**Se o pedido for "cria um cliente novo" / "replica a instância para X": leia
`PROVISIONAR_CLIENTE.md` e FAÇA AS PERGUNTAS DE LÁ ANTES de tocar em qualquer
coisa.** Tipo de cliente (cidade / assessoria / consórcio), nome, UF, IBGE de 7
dígitos e quais credenciais já existem.

Monte Sião é base de **desenho**, não de dados: nenhum dado dele vai para o tenant
novo. O cliente novo nasce com as três contas de super admin e o município que
vier em `MUNICIPIO_NOME` / `MUNICIPIO_IBGE` / `MUNICIPIO_UF` — mais nada.

## 7. OPERAÇÕES COMUNS (Coolify API v1)

`B=http://54.232.208.118:8000/api/v1` · header `Authorization: Bearer <TOKEN>`

- **Redeploy:** `POST $B/deploy?uuid=<app_uuid>&force=false` → devolve `deployment_uuid`. Status: `GET $B/deployments/<deployment_uuid>` (`status`: queued/in_progress/finished/failed). **Um app por vez.**
- **Logs do app:** `GET $B/applications/<uuid>/logs?lines=120`.
- **Setar env (bulk):** `PATCH $B/applications/<uuid>/envs/bulk` body `{"data":[{"key":..,"value":..,"is_build_time":bool,"is_preview":false}]}`. ⚠️ o POST simples `/envs` **não aceita** `is_build_time` (use o bulk). `NEXT_PUBLIC_*` e `API_PROXY_TARGET` precisam `is_build_time:true`.
- **Mudar domínio:** `PATCH $B/applications/<uuid>` body `{"domains":"https://..."}` + redeploy.
- **Scheduled Tasks:** `GET/POST $B/applications/<worker_uuid>/scheduled-tasks` (POST body `{name,frequency,command}`); `PATCH .../scheduled-tasks/<task_uuid>` p/ `{timeout}`.
- **DB status/URL:** `GET $B/databases/<uuid>` (campos `status`, `internal_db_url`).
- **Abrir o banco na mão:** `ssh -i ~/.ssh/coolify_localhost root@54.232.208.118` e `docker exec -it <db_uuid> psql -U pactha -d pactha`.
- **Rodar um scraper na mão:** dispare a Scheduled Task correspondente no worker do tenant (ou `POST /api/convenios/refresh-sigcon` autenticado → enfileira, e a task `queue-sigcon` consome em ≤30min). Lembre: scrapers com login (SIGCON, FNS) só produzem dados se o **Cofre daquele tenant** tiver credenciais.

---

## 8. AO MEXER NO CÓDIGO, LEMBRE

Uma alteração aqui vai para **os três clientes**. Antes de commitar:

- Migration nova precisa ser **idempotente** e rodar limpa nos três bancos (ela executa no boot da API).
- Feature que depende de env var nova: ou tem default seguro, ou você seta a env nos **três** resources.
- Mudança no `frontend/` afeta também o build do `painel/`? (São apps Next separados, mas compartilham a API.)
- Nada de aumentar concorrência de scraping "porque tá lento" — ver §5, a CPU é compartilhada com 10 outros projetos.
