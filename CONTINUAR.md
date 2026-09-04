# CONTINUAR.md — Handoff PACTHA (leia isto primeiro)

> Documento de contexto para a **próxima sessão de IA** (Claude Code) que for continuar este projeto.
> É **auto-contido**: assuma que você (IA) não tem memória das sessões anteriores. Tudo que precisa está aqui.
> Última atualização: 2026-09-04.
>
> 📍 Para servidor, URLs, uuids, bancos e operações no Coolify, a fonte de verdade é o
> **[`INFRA.md`](INFRA.md)** na raiz. Este arquivo cobre o *projeto*; o `INFRA.md` cobre a *infra*.

---

## 1. O QUE É ISTO (em 30 segundos)

**PACTHA** = sistema de **monitoramento de convênios e transferências governamentais** para municípios e assessorias (MG/ES/GO/RS). Módulos: SIGCON-MG (convênios estaduais), TransfereGov, Emendas, Parlamentares, CAUC, Acordo FES, FNS, SIMEC/PAR, **Obras** (SISMOB + Obras.gov.br/CIPI), IA (Claude), DOU-MG, Relatório de Monitoramento (RM), Documentos, Cofre de Senhas (AES-256), Telegram, extensão Chrome de captura gov.br, Painel de Indicadores (BI, nos 5 tenants) com Modo Tela/links públicos, selos de frescor por tela e watchdog de coleta. São **21 fontes oficiais** (o `CLAUDE.md` mantém a contagem em dia).

- **Frontend:** Next.js 16 (App Router) + Tailwind v4 + daisyUI + shadcn. Pasta `frontend/`.
- **Painel (pasta `painel/`):** DEPRECADO — o BI virou módulo do frontend principal (`/dashboard` + `/tela`). Ver `painel/DEPRECADO.md`.
- **Backend:** Python 3.12 FastAPI (uvicorn). Pasta `backend/`. Tudo prefixado `/api`.
- **Banco:** PostgreSQL 16 puro (SQLAlchemy async+asyncpg na API; psycopg2 nos scrapers/migrations).
- **Scraping:** httpx + Playwright (Chromium) + curl_cffi. Pasta `backend/ingestion/`.

**Este repo (`alavank/pactha`) é um FORK PRÓPRIO** do repo original `MattMatiins/PACTA` (do Matheus). O usuário (alavank) **migrou** a stack para **Coolify + Postgres puro** e renomeou tudo de "PACTA" → "PACTHA". Railway, Neon e Vercel (do repo original) **não são mais usados**; a hospedagem posterior na Hetzner também já foi desativada — hoje é **AWS Lightsail**.

⚠️ **DOIS clones no PC — não confundir:**
- `C:\dev\pactha` → **ESTE** repo (`alavank/pactha`). É onde você trabalha.
- `C:\projetos\PACTA` → clone do repo do Matheus (`MattMatiins/PACTA`), usado só para colaboração com ele. **NUNCA** pushe cruzado entre os dois.

⚠️ **Este repo tem RULESET no GitHub exigindo PR aprovado.** Não tente pushar direto na `main` — crie branch e abra PR.

---

## 1.5. A SEMANA DE 08–09/08 EM 60 SEGUNDOS (o que mudou de grande)

Partiu de "as atualizações diárias estão falhando e não sabemos por quê" e terminou com o
sistema operando sozinho. Se você só ler um bloco deste arquivo, leia este:

1. **Deploy é AUTOMÁTICO** (PRs #161-#163): merge na `main` → CI builda → deploya os 3
   tenants (API→migrations confirmadas→worker esperando janela sem coleta). Auto-deploy
   por webhook do Coolify DESLIGADO nas 9 apps. Secrets `COOLIFY_URL`/`COOLIFY_TOKEN` no
   GitHub. Rollback = repontar tag na mão (continua funcionando).
2. **Coleta fatiada com rodízio anti-starvation** (PRs #158/#159 + tuning de 09/08):
   rodadas curtas e frequentes, lock compartilhado `/tmp/scraper.lock` por worker
   (sigcon/lote/cagec nunca simultâneos), agendas entrelaçadas. REGRA: margem do
   `timeout` interno = orçamento + 1 município pesado (22 min); coluna `timeout` da task
   = interno + 120s. Fonte de verdade das agendas = o Coolify, não docs.
3. **Observabilidade honesta** (PR #160): `ingestion_log` com `success`/`parcial`/`erro`
   reais; watchdog com staleness POR MUNICÍPIO (agregado, anti-spam; credencial falhando
   = nota, nunca alarme — regra do dono); paginação validada contra o total oficial.
   Telegram do watchdog ainda SEM token (alertas ficam no log).
4. **Selo "Atualizado em" nas telas** (PR #164): CAUC/CAGEC já tinham; Convênios
   Estaduais e Emendas ganharam — só data com coleta saudável (`tentativas=0`), senão
   avisa sem afirmar causa. Emendas têm carimbo próprio (`fonte='sigcon_emendas'`).
5. **Carteira da Freitas corrigida (09/08, lista oficial do cliente): 44 municípios** —
   18 ex-clientes DESATIVADOS (`active=false`, histórico preservado; credenciais deles
   `INATIVO-SIGCON-MG`) e 21 novos inseridos (IBGE da API oficial). Os "municípios com
   credencial revogada" do diagnóstico eram, em maioria, ex-clientes.
6. **Diagnóstico completo de 08/08** (6 causas verificadas + cadência oficial das 17
   fontes + capacidade): relatório no artifact da sessão e em
   `Downloads\PACTHA-diagnostico-ingestao-2026-08-08.html` na máquina do dono.

---

## 1.6. A SESSÃO DE 28/08/2026 EM 60 SEGUNDOS (PRs #309–#313, todos mergeados e no ar)

Diretriz do dono, repetida e agora em código: **Minas NUNCA é padrão** — cada estado tem
suas particularidades, e nome de fonte/cadastro sai de catálogo por UF, não de literal.

1. **Nome do cadastro estadual pelo estado do município** (PR #309). Santa Maria/RS via
   "CAGEC — Minas Gerais" e "Regular no CAGEC" em cima do CHE gaúcho. Entrou
   `backend/services/cadastro_estadual.py`, ESPELHO de `frontend/src/lib/estadual.ts`
   (sigla, nome, fonte, portal, certificado, o que a irregularidade trava). Os payloads do BI
   trazem `ufs_na_fonte` (par de `ufs_sem_fonte`); IA, narrativa, push e `/api/cagec` usam o
   catálogo. Sem UF conhecida o rótulo é o genérico "Cadastro estadual" — nunca "CAGEC".
   ⚠️ Estado novo entra nos DOIS arquivos, só com coletor no ar.
2. **Telemetria (Configurações → Telemetria)** (PRs #310 e #311). A sessão de uso era o `sid`
   do TOKEN (30 dias): quem fechava o navegador e voltava no dia seguinte "estava logado há
   15h". Agora cada linha de `uso_sessao` é um **trecho contíguo** (`add_uso_trechos.sql`:
   `sessao_token` + `motivo_fim` largo): silêncio > 5 min ou logout abre linha nova; a
   anterior fecha como `logout` / `navegador_fechado` / `expirou`. **Sair encerra na hora**
   (o próprio `POST /auth/logout` fecha a sessão; `/uso/presenca` não segura logout).
   Captura de eventos **genérica** em `lib/uso.ts`: clique (rótulo visível), parâmetros de
   GET (= filtro aplicado) e POST/PUT/DELETE 2xx (= o que gravou); nada de texto digitado;
   `data-uso` / `data-uso-alvo` / `data-uso-ignorar` para dizer melhor ou calar. Frases em
   `lib/uso-rotulos.ts` (tela por rota, escrita por caminho — acrescentar linha lá quando
   sair "gravou dados em X"). Retenção 6 meses (expurgo oportunista em `/uso/lote`).
   Card "Online no Sistema"; Eventos à esquerda (por dia, filtro por pessoa/tipo, modal);
   Sessões à direita (por dia → pessoa → sessão, com como terminou, modal).
3. **Menu por esfera** (PR #312): grupos **FEDERAIS** (ex-"Transfere Gov") e **ESTADUAIS**,
   em maiúsculo — municipais virão. A fonte foi para o card: campo "Fonte: TransfereGov"
   no canto inferior direito de cada proposta (Em execução, Especiais, PAC, Voluntárias,
   Rejeitadas, Encerradas). Rótulos do catálogo de permissões não mudaram.
4. **Logo do Freitas** (PRs #312 e #313): arte nova `frontend/public/logo-freitas.png`
   (PNG transparente, corte do dono, 998×354); `build-frontend.yml` do `frontend-freitas`
   aponta para `/logo-freitas.png`. O RM em PDF lê `backend/assets/freitas-logo.jpeg`
   (regerado da arte nova sobre branco — a env `RM_LOGO` NÃO mudou). Em `Marca.tsx`,
   `AJUSTE_LOGO`: fundo claro só no tema escuro e deslocamento óptico de 14% (centro de
   massa da arte a 36% da altura) para o "FREITAS" ficar na linha do nome da cidade —
   se a arte for recortada de novo, remedir.
5. **Fluxo de trabalho desta sessão**: branch → PR → dono merge → CI deploya os 4 tenants.
   Testes do backend: 1931 passando; **11 falhas pré-existentes** em
   `test_permissoes_*`/`test_registro_rotas.py` (não são regressão — conferir com
   `git stash` antes de culpar uma mudança). ESLint tem erros `set-state-in-effect`
   pré-existentes nas telas do TransfereGov e no `dashboard/page.tsx`.

---

## 1.7. A SESSÃO DE 03–04/09/2026 EM 60 SEGUNDOS (PRs #367–#370, todos mergeados e no ar)

Entrou o **Obras.gov.br / CIPI** nos cinco tenants — **1.011 obras federais**, o menu
**OBRAS** e a tela `/dashboard/obrasgov`. É a fonte que mostra o que nenhuma outra
mostrava: SISMOB cobre saúde e SIMEC cobre educação, mas mobilidade, saneamento,
habitação, segurança e a **reconstrução da Defesa Civil** não apareciam em lugar nenhum
(em Nova Palma são 21 das 30 obras — a reconstrução pós-enchente inteira).

1. **O bloqueio era do HOST, não do Governo** (PR #367). O coletor ficou pronto e
   desligado desde 02/09 porque `api.obrasgov.gestao.gov.br` devolve **429 na primeira
   requisição** vinda da VPS. O mesmo acervo está em
   **`api-publica.obrasgov.gestao.gov.br`**, que responde **200 em 0,13 s**. A troca de
   host matou três das quatro armadilhas antigas e derrubou a varredura de uma UF de ~8 min
   para ~75 s. ⭐ **O município sai do CNPJ, NUNCA do nome** (diretriz do dono): casar por
   nome trouxe 379 obras da UFSM como se fossem da prefeitura de Santa Maria.
2. **Uma categoria de 41 caracteres derrubou a carga inteira de um tenant** (PR #368).
   `natureza = 'Projeto de Investimento em Infraestrutura'` contra `VARCHAR(40)`, e o
   novapalma tinha passado limpo minutos antes — a pior forma de bug, some no primeiro
   tenant e derruba o segundo. Taxonomia de fonte externa agora é **`TEXT`**; só continua
   `VARCHAR` o que tem *formato* (`id_unico`, `cep`, `uf`).
3. **A tela que faltava** (PR #369). A tabela era lida só pelo painel de frescor — provava
   que a fonte estava viva sem mostrar obra nenhuma. O grupo OBRAS nasce com dois itens e
   cresce; ⚠️ o **SISMOB aparece em OBRAS e em SAÚDE**, o mesmo link nos dois lugares, de
   propósito. E as duas telas **se sobrepõem nos dados** (o CIPI reúne obras que o SISMOB
   publica: 45 das 360 do freitas): decisão do dono é mostrar a visão geral e **dizer**
   quais são — selo "também no SISMOB" e bloco «Por sistema de origem».
4. **A data efetiva não é sinal de nada, e por isso 27 de 30 obras "exigiam atenção"**
   (PR #370). `data_inicial_efetiva`/`data_final_efetiva` vêm **vazias em 100% das 1.011
   obras**, e 65 obras "Concluída" não têm data de conclusão — o Governo encerra mudando a
   **situação**, não preenchendo data. Quem classifica passou a ser a `situacao`, e são
   **quatro** grupos, não três: ⚠️ **«não saiu do papel»** (Cadastrada + previsto vencido) é
   grupo PRÓPRIO, não um pedaço de «ação» — obra parada se cobra do executor, projeto
   encalhado se cobra do município e do órgão repassador. Somar as duas escondia as duas.
   ⭐ E **a fonte manda acento codificado duas vezes** (latin-1 lido como UTF-8 e gravado
   assim); o conserto vai na ingestão e **desiste** se a reinterpretação não melhorar.

**Auditoria de infra do mesmo dia** (04/09, contra a API do Coolify — as 15 apps na tag
`sha-4d5a37f`, as 5 APIs `running:healthy`). Três achados corrigidos na hora, todos de
agendamento e nenhum de código:

- 🔴 **`tmp-g9umo` rodando a cada minuto há 34h** no `montesiao-mg-worker` — sonda de
  diagnóstico de 03/09 cujo `finally` nunca restaurou o cron. ~1.440 execuções/dia contra o
  banco da prefeitura com uso real. Apagada. Detalhe e a regra nova em [`INFRA.md`](INFRA.md) §8.
- 🟠 **`fpe-rs` agendado fora da janela do portal** nos dois tenants do RS (ver §2).
- 🟡 **`obrasgov` do freitas no mesmo minuto do `transferegov-lote`** (03:25). Os locks são
  diferentes de propósito, então **não** se serializavam. Movido para 03:30. A escada de 5 min
  foi desenhada entre tenants sem conferir a coluna vertical de cada worker.

⚠️ E ficou **uma pendência de código** achada nessa auditoria, não corrigida porque mexer em
`backend/**` deploya os cinco: o **SISMOB tem DOIS caminhos vivos** (Scheduled Task própria
nos 5 workers **e** a entrada em `run_dadosabertos_cron.run_all()`). Hoje não duplica coleta
— os dois passam pelo gate de 20h —, mas o docstring de `_deve_pular()` ainda afirma que não
existe task própria, que é a premissa exata que causou o incidente do PR #259. Ver
[`INFRA.md`](INFRA.md) §5.

---

## 2. ESTADO ATUAL (2026-09-04)

**São CINCO tenants em produção**, todos do mesmo código, cada um com containers e banco próprios:

| Tenant | App | API |
|---|---|---|
| **Freitas** | https://pactha-54-232-208-118.sslip.io | https://pactha-api-54-232-208-118.sslip.io |
| **Trust** | https://pactha-trust-54-232-208-118.sslip.io | https://pactha-trust-api-54-232-208-118.sslip.io |
| **Monte Sião/MG** | https://montesiao.mg.pactha.com.br | https://pactha-montesiao-mg-api-54-232-208-118.sslip.io |
| **Santa Maria/RS** | https://santamaria.rs.pactha.com.br | https://pactha-santamaria-rs-api-54-232-208-118.sslip.io |
| **Nova Palma/RS** | https://pactha-novapalma-rs-54-232-208-118.sslip.io | https://pactha-novapalma-rs-api-54-232-208-118.sslip.io |

⚠️ **Santa Maria (16/08/2026) é o 4º tenant e o primeiro banco criado DO ZERO** — os três
primeiros vieram migrados do Neon. Ele nasceu só com Santa Maria/RS (IBGE 4316907) e as
coletas federais. **Nova Palma (01/09/2026) é o 5º e o segundo banco do zero** — nasceu só
com Nova Palma/RS (IBGE 4313102) e expôs um bug de **ORDEM** nas migrations
(`add_detalhe_pagina_rodizio.sql` alterando tabela criada depois dela em `MIGRATION_FILES`),
hoje guardado por `tests/test_migrations_ordem_tabela.py`. Ele ainda está **sem brasão** de
propósito: `NEXT_PUBLIC_CLIENT_LOGO` e `RM_LOGO` vazios — subir com logo errado é pior que
subir sem.

> ⚠️ **Este parágrafo dizia "nenhuma fonte do RS existe em código ainda". Isso venceu.**
> Era verdade em 16/08; hoje coletam CHE (`che_rs.py`), convênios da CAGE
> (`convenios_rs.py`), Consulta Popular (`consulta_popular_rs.py`) e o DOE-RS
> (`services/diario_rs.py`), com Scheduled Task ativa. Em 02/09/2026 entraram
> ainda **SICONFI/CAPAG** (federal, nacional) e **TCE-RS/LicitaCon** — este
> último pronto mas dependente de liberação de IP (ver `docs/fontes-rs/`).
> O que segue inerte é o **FPE-RS**, esperando credencial PCPRS, por decisão.
>
> ⚠️ **Mas "inerte" escondeu um cron errado por 18 dias.** O portal do FPE só atende
> **seg–sáb, 7h–22h30 BRT** (fora disso: HTTP 500), e as duas tasks estavam agendadas às
> **02:04 e 02:34 BRT**, com `* * *` incluindo domingo. Ninguém viu porque o coletor sai
> antes de tocar no portal e grava `success` por falta de credencial. No dia em que a
> credencial PCPRS entrasse, os dois tenants passariam a falhar todo dia e o sintoma
> pareceria coletor quebrado. Corrigido em 04/09 para `14 14 * * 1-6` (santamaria) e
> `44 14 * * 1-6` (novapalma). **Fonte com janela de funcionamento é restrição de
> agendamento — anote no cron, não só no docstring.**

Os cinco bancos já estão **populados com dados reais** (a migração vinda do Neon foi concluída — não é mais schema+seed). Login seed só vale em banco novo: `super-admin@alavank.com.br`, com senha ALEATÓRIA por tenant impressa no console do primeiro boot (ou via `ADMIN_PASSWORD`) — pede troca no 1º acesso.

**⚠️ INVERTIDO EM 09/08: um merge na `main` DEPLOYA os cinco clientes, sozinho.** As 15
aplicações seguem `build_pack = dockerimage`, mas o job `deploy` do CI avança a tag e
dispara o deploy ao fim de cada build (API primeiro com migrations confirmadas; worker do
mesmo tenant só em janela sem coleta em voo; falha = rollback de tag + run vermelho).
`is_auto_deploy_enabled` agora está **false** nas 9 (o webhook recriava containers com a
tag antiga e matou coleta em voo). Mecânica e provas em [`INFRA.md`](INFRA.md) §2 e nos
próprios workflows. **Tratar todo merge na `main` como um deploy em produção.**

**Carteira Freitas = 44 municípios ativos** (lista oficial de 09/08; 18 ex-clientes com
`active=false` e histórico preservado — NUNCA deletar município, desativar).

---

## 3. INFRA NO COOLIFY (como mexer)

Resumo; o detalhe completo (uuids de todas as aplicações, bancos, crons por tenant) está no **[`INFRA.md`](INFRA.md)**.

- **Servidor:** **AWS Lightsail `54.232.208.118`** (sa-east-1a, São Paulo). t3.large: 2 vCPU / 7,6 GB RAM / 160 GB SSD. **Burstable, baseline 30% (~0,6 vCPU sustentado)** — hospeda mais 10 projetos além do PACTHA. **Não paralelize trabalho pesado.**
- **Instância Coolify:** `http://54.232.208.118:8000` — API REST em `http://54.232.208.118:8000/api/v1`. Versão v4.1.2.
- **SSH:** `ssh -i ~/.ssh/coolify_localhost root@54.232.208.118`.
- **Token da API do Coolify:** NÃO está neste arquivo (é segredo). O usuário fornece (formato `36|xxxx`). Use `Authorization: Bearer <TOKEN>`. **Rotacione periodicamente.**
- **GitHub App (source):** `alavank-coolify` — já dá acesso ao repo privado `alavank/pactha`. Use o `github_app_uuid` dele ao criar apps.

**Projeto Coolify `pactha`** — uuid `ksmwr13y4iyprom8i1znede8`, **um environment por tenant** (`production` está vazio), **15 aplicações + 5 bancos** (o `montesiao-mg-painel` foi removido):

| Tenant | API | Frontend | Worker | Banco |
|---|---|---|---|---|
| freitas | `givx3567ygxppum10p1oungn` | `qgmw4e5wjem1e8jit2wyvo1d` | `s49c3b58lysqq0tpelneg3g3` | `tox59kvmkrb0ywmeaty3t02a` |
| trust | `pphvk2ygkuirjhu9qptvmfs5` | `j5ghp71lff003d5rfaynvy5y` | `xg714h8l7va4ejq70a5pmv5t` | `p434vbj35siee57shlsyzuc2` |
| montesiao-mg | `chr0n883hp19tjh7829k85a7` | `bryvqhhcu97lc3ku7a2hss0q` | `jhf0kjhps5keujiyhhsnvjt6` | `iogvjlnkpqlugja9j76rktl1` |
| santamaria-rs | `ufjctldngc14dsdw8pxnqivl` | `eohjo0cy4nbl6t7hiaqwagwf` | `wquremniv57gag3tlil8uf6d` | `m2ypghl41lbqhv7rdqzffdi3` |
| novapalma-rs | `gemcwirmbelk1dztp2pbcqpf` | `rpqpxroy5orsuidrbfezlzkt` | `kqcnvdsdkgn1efkm4nog8oes` | `dl2jwo0q1ckbplqp6vp1hnu4` |

Builds: API = `backend/Dockerfile.api` (base `/`) · Frontend = `frontend/Dockerfile` (base `/frontend`, standalone) · Worker = `backend/Dockerfile.scraper` (PID 1 = `tini` + `reaper.sh`, que mata ingestão >1h e Chromium órfão; crons via Scheduled Tasks). Bancos: `postgres:16-alpine`, db/user `pactha`, porta 5432, host = uuid do resource.

**Segredos** (`JWT_SECRET`, `COFRE_KEY`, `ADMIN_PASSWORD`, `DATABASE_URL`, `ANTHROPIC_API_KEY`, `CONTROL_TOKEN_BOOTSTRAP`, chaves VAPID do Painel): estão **nas env vars do Coolify, por tenant** (recupere com a API — ver §7). A senha do Postgres também está no `internal_db_url` do resource DB (`GET /databases/<uuid>`). **Nunca copie a `COFRE_KEY` de um tenant para outro.**

**Scheduled Tasks:** cada worker tem as suas, no desenho de 09/08: **lock compartilhado
`/tmp/scraper.lock`** (sigcon/lote/cagec nunca simultâneos no tenant) + agendas
entrelaçadas + rodadas fatiadas com rodízio. **A fonte de verdade dos horários é o
Coolify** (a tabela do `INFRA.md` §5 virou descrição de desenho; `docs/CRON_SETUP.md`
está histórico). Regra das margens e proibição de editar comando via PowerShell
interpolado: [`INFRA.md`](INFRA.md) §5.

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

- **A máquina é burstable (baseline 30%).** Não rode scraping paralelo (`SIGCON_CONCURRENCY=1`), não alinhe os crons dos 5 tenants, não rebuilde os apps de uma vez. Sintoma de estouro: tudo no host fica lento ao mesmo tempo, não só o PACTHA.
- **Coolify STRIPPA o path do domínio.** Se você setar o domínio de um app como `host/api`, o Coolify tira o `/api` antes de chegar no container (testado: `host/api/health`→404, `host/api/api/health`→200). Por isso a API tem **subdomínio próprio SEM path**, e o caminho normal do usuário é o proxy do Next (`API_PROXY_TARGET`).
- **`*.sslip.io` é public suffix** → `pactha-...sslip.io` e `pactha-api-...sslip.io` são **cross-site** entre si; cookies `SameSite=Lax` httpOnly não trafegam entre eles. É exatamente por isso que existe o proxy same-origin no Next (decisão 7). **Se alguém apontar o front direto no subdomínio da API (`NEXT_PUBLIC_API_URL` absoluto), o refresh silencioso quebra e volta o re-login a cada ~60min.**
- **`API_PROXY_TARGET` e `NEXT_PUBLIC_*` são BUILD-TIME.** Mudar o valor no Coolify sem rebuildar o frontend não tem efeito nenhum. Marque `is_build_time:true` e redeploy.
- ~~**`transferegov_propostas` é criada tarde** nas migrations~~ — **RESOLVIDO.** A tabela foi movida para o `setup_db.py` (`CREATE TABLE IF NOT EXISTS`, hoje na linha 105), que é exatamente o conserto que este parágrafo propunha. **A lição fica, porque a classe do bug voltou:** migration que ALTERA tabela criada mais tarde em `MIGRATION_FILES` só quebra em **banco novo do zero** — invisível nos bancos herdados. Foi assim com `transferegov_propostas` e de novo com `add_detalhe_pagina_rodizio.sql` quando o Nova Palma nasceu (01/09). Hoje há guarda automática: `backend/tests/test_migrations_ordem_tabela.py`. São **127** migrations registradas, não 22.
- **COFRE_KEY:** o Cofre e as sessões gov.br são cifrados com AES-256 usando a env `COFRE_KEY` (`backend/services/crypto.py`). Se a chave mudar, `decrypt()` volta `""` **silenciosamente** — sem erro, sem log. **Cada tenant tem a sua**; trocar ou cruzar chaves destrói o Cofre daquele cliente.
- **must_change_password=True** no admin seed → o 1º login redireciona pra `/change-password`. Normal.
- Worker aparece como `running:unknown` no Coolify (roda o reaper, sem healthcheck). Normal. Frontends sem healthcheck também.
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
- **O Obras.gov.br tem DOIS hosts, e só um funciona daqui.** `api.obrasgov.gestao.gov.br`
  devolve **429 na primeira requisição** vinda da VPS; use
  **`api-publica.obrasgov.gestao.gov.br`**, que responde 200 em 0,13 s. Três armadilhas
  silenciosas: (1) o **filtro territorial não existe** — `codigo_ibge` devolve o estado
  inteiro com HTTP 200, e o recorte é feito em memória; (2) **o município sai do CNPJ,
  nunca do nome** (por nome, 379 obras da UFSM viram obras da prefeitura de Santa Maria);
  (3) **a fonte manda acento codificado duas vezes** (latin-1 lido como UTF-8), e o
  conserto na ingestão precisa desistir quando a reinterpretação não melhora — senão
  corrompe 32.000 obras para arrumar 2. E **a data efetiva não classifica nada**: vem
  vazia em 100% das obras. Detalhe em [`INFRA.md`](INFRA.md) §5 e em
  `backend/ingestion/obrasgov.py`.
- **Não existem "1ª, 2ª e 3ª parcelas" no fundo a fundo.** A norma vigente (Portaria de
  Consolidação 6/2017, Título IX) é **parcela única**; obras antigas vieram 20%+80%. O
  marco de 90% **não existe** (o de 30% sim). E a prestação de contas é o **Relatório
  Anual de Gestão** (LC 141/2012), não um "relatório final".
- **O CAGEC NÃO fica dentro do SIGCON-MG.** Perder tempo procurando no portal logado é fácil: a palavra "CAGEC" não aparece uma vez sequer no HTML do sigconv2 nem no menu de 29 itens. Ele tem portal próprio (`cagec.mg.gov.br/convenente-web`) e a consulta é **pública** — basta o CNPJ, não precisa de credencial. Duas armadilhas do portal (ambas fazem a busca *parecer* vazia): a página contém a frase "clique no botão [PESQUISAR]", então seletor por texto casa com a **instrução** e o clique não faz nada; e o cabeçalho do grid usa `th`/`.z-listheader` — fora do seletor de células ele some, e sem cabeçalho não dá para casar coluna por rótulo. Está tudo anotado em `backend/ingestion/cagec_scraper.py`.
- **O detalhe da irregularidade vem do CRC, e o CRC SAI para município irregular.** Errei isso na primeira versão (assumi que só município regular emitiria) e a diferença é grande: a linha da busca só diz "Irregular", enquanto o botão **"Emitir CRC"** da mesma linha baixa um PDF com as ~24 obrigações uma a uma, **cada uma com situação e data de validade**, mais CADIN-MG, SIAFI e o vencimento do mandato. É o que permite dizer "seu FGTS venceu em 29/07" em vez de "você está irregular". Duas armadilhas do PDF: o cabeçalho tem `SITUAÇÃO: Irregular`, que casa como se fosse item (só ler depois de `DOCUMENTAÇÃO`), e a quebra de página parte um item ao meio (há remendo dedicado).
- **Espera fixa no portal do CAGEC falha 1 em 4.** O `wait_for_timeout` fixo depois do PESQUISAR lia o grid ainda vazio e reportava **"CNPJ não encontrado no CAGEC"** — sintoma enganoso, parece que o município não existe no cadastro. Use espera adaptativa (poll até a linha aparecer). Vale para qualquer postback do ZK.

---

## 6. PENDÊNCIAS

> 📍 **O backlog por estado vive em [`docs/BACKLOG_POR_ESTADO.md`](docs/BACKLOG_POR_ESTADO.md).**
> Ele confere o plano da auditoria de 17/08/2026 contra o repositório (conferência de
> 25/08: **o plano não foi executado**) e lista, na ordem de prioridade do dono
> — **MG → RS → GO → ES → TO** —, o que falta em cada estado, com arquivo/linha já
> verificados. As decisões da Onda 0 e o achado do CAGEC (falha em massa em 17-18/08)
> estão lá. Ler antes de abrir frente nova de cobertura estadual.


### 6.1 Domínios definitivos (`*.pactha.com.br`)
Faltam **três**: `freitas`, `trust` e `novapalma-rs` ainda respondem só por `*.sslip.io`. Monte Sião e Santa Maria já têm domínio próprio (`montesiao.mg.pactha.com.br`, `santamaria.rs.pactha.com.br`), assim como a landing (`pactha.com.br`) e a Central de Comando (`control-center.pactha.com.br`). Falta decidir/criar os DNS `A` → `54.232.208.118` para os apps dos clientes e trocar os domínios no Coolify (`PATCH /applications/<uuid>` + redeploy). Lembre de ajustar `FRONTEND_URL`/`CORS_ORIGIN_REGEX` na API e rebuildar o frontend (env build-time).

### 6.2 Secrets opcionais por tenant (features ficam OFF até setar)
`ANTHROPIC_API_KEY` (módulo IA — hoje só `montesiao-mg-api` tem), `TELEGRAM_BOT_TOKEN` + `TELEGRAM_WEBHOOK_SECRET` (Telegram). Setar via `PATCH /applications/<api_uuid>/envs/bulk` + redeploy.

Credencial do **SIGCON-MG** (uma por município, no Cofre com `sistema='SIGCON-MG'` /
`automation_key='sigcon'`): sem ela o `sigcon` roda e não traz nada — e agora grava
`success` com a nota "sem credenciais" (não alarma; regra do dono: credencial não trava
o jogo). **O CAGEC não precisa de credencial** — consulta pública.

Estado em 09/08: Monte Sião ok · **Freitas: 24 credenciais ativas** p/ 23 municípios
antigos; **2 PAUSADAS aguardando reset do dono** (Piracema e Ribeirão das Neves —
portal respondeu "USUÁRIO REVOGADO"; fluxo "Esqueci minha senha" resolve) e **21
municípios novos SEM credencial** (pedir à Freitas) · **Trust: ZERO credenciais
SIGCON** apesar de 7 municípios MG (pedir ao cliente). Pausar credencial = trocar
`sistema` p/ valor fora de `SIGCON%` + `automation_key=NULL` (reversível).

### 6.3 Deploy (automático desde 09/08)
Merge na `main` = deploy nos 5 tenants via CI (ver §1.5 e [`INFRA.md`](INFRA.md) §2).
`is_auto_deploy_enabled = false` (webhook desligado de propósito). Deploy manual
para rollback: repontar `docker_registry_image_tag` + `GET /deploy?uuid=`. Pendências do
plano de médio prazo: **M1** (executor de fila por fonte×município — substitui os crons
com teto de 1h) e **M5** (host de scraping dedicado quando a carteira crescer).

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

Uma alteração aqui vai para **os cinco clientes**. Antes de commitar:

- Migration nova precisa ser **idempotente** e rodar limpa nos cinco bancos (ela executa no boot da API) — **e num banco criado do zero**, que é onde erro de ordem aparece (ver §5).
- Feature que depende de env var nova: ou tem default seguro, ou você seta a env nos **cinco** resources.
- Nada de aumentar concorrência de scraping "porque tá lento" — ver §5, a CPU é compartilhada com 10 outros projetos.
