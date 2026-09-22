# PACTHA — Sistema de Monitoramento de Convenios

Plataforma de monitoramento de convenios, repasses e emendas para municipios e
assessorias — **22 fontes oficiais** (federais + estaduais de MG/ES/GO/RS), coletadas
na cadencia real de cada uma, com selo "atualizado em" nas telas e vigilancia de
frescor por municipio.

> 📍 **Onde isto roda:** **AWS Lightsail `54.232.208.118` (sa-east-1), orquestrado por Coolify.**
> Toda a verdade sobre servidor, URLs, bancos, crons e segredos esta em **[`INFRA.md`](INFRA.md)**.

## ⚠️ Um repo, SETE tenants — e um merge na main DEPLOYA OS SETE

Este repositorio atende **sete clientes distintos**, cada um com seu proprio conjunto de
containers e seu **proprio banco**, todos buildados do **mesmo codigo**:

| Tenant | Slug | Quem e | Dominio de producao (conferido 05/09/2026) |
|--------|------|--------|--------------------------------------------|
| Freitas | `freitas` | consultoria (carteira MG) | `freitas.pactha.com.br` |
| Trust | `trust` | consultoria (carteira MG) | `trust.pactha.com.br` |
| Monte Siao/MG | `montesiao-mg` | prefeitura | `montesiao.mg.pactha.com.br` |
| Santa Maria/RS | `santamaria-rs` | prefeitura | `santamaria.rs.pactha.com.br` |
| Nova Palma/RS | `novapalma-rs` | prefeitura | `novapalma.rs.pactha.com.br` |
| BGK/RS | `bgk-rs` | assessoria (10 municipios do RS) | `bgk.pactha.com.br` |
| Juranda/PR | `juranda-pr` | prefeitura (aberta em 22/09/2026; so fontes federais) | `juranda.pr.pactha.com.br` (DNS pendente em 22/09/2026 — ver INFRA.md §3) |

> ⚠️ **DOIS ENDERECOS PARA O MESMO CONTAINER, e isto ja custou confusao.** Todo app tem o
> endereco cru `pactha[-slug]-54-232-208-118.sslip.io` (o IP do servidor resolvido pelo
> `sslip.io`), e os sete tem TAMBEM o dominio da tabela acima. **Sao o mesmo
> container e o mesmo banco** — nao existe ambiente de teste separado, e mexer por um
> endereco mexe no outro. A tabela completa esta em [`INFRA.md`](INFRA.md) §3.

**Todos os tenants** tem o **Painel de Indicadores** (BI) ligado — conferido em 09/09/2026
respondendo `/api/bi/overview` nas seis APIs de entao; o Juranda nasceu com ele — flag build-time
`NEXT_PUBLIC_BI_MODULE=1` na matriz do `build-frontend.yml`. `/dashboard` e o
painel executivo (abas por assunto, filtro multi-ano, insights de IA) e `/tela` e
o **Modo Tela** (TV de gabinete, com link publico revogavel `/t/<slug>`). O app
separado `painel/` foi descontinuado e removido do repositório em 12/09/2026.

Nao ha multi-tenancy no codigo: **o isolamento e por deploy**. O que muda entre um tenant e
outro sao as env vars no Coolify (`INSTANCE_SLUG`, `DATABASE_URL`, `JWT_SECRET`, `COFRE_KEY`,
`NEXT_PUBLIC_CLIENT_LOGO`, `NEXT_PUBLIC_CLIENT_SUBTITLE`).

**Consequencia pratica:** merge na `main` que toca `backend/**` ou `frontend/**` **builda no
GitHub Actions e deploya os 7 tenants sozinho**, na ordem certa: API primeiro (roda as
migrations; deployment confirmado), depois o worker do mesmo tenant **esperando janela sem
coleta em voo**. O auto-deploy por webhook do Coolify esta **desligado**: ele recriava
containers com a tag antiga e matava coleta. Deploy manual continua possivel para rollback.
Mecanica completa comentada nos proprios `.github/workflows/*.yml`; visao de infra em
[`INFRA.md`](INFRA.md) §2.

Alem disso, um mesmo bug corrigido aqui **vai para os sete clientes** — e uma mudanca de
schema precisa ser idempotente nos sete bancos, inclusive num **novo**: Santa Maria (08/2026)
e Nova Palma (01/09/2026) nasceram do zero, e a segunda expos um bug de ORDEM das migrations.
Juranda (22/09/2026) foi o ultimo banco criado do zero: 138/138 no primeiro boot.

> ⚠️ **MIGRATION QUE FALHA NAO DERRUBA O BOOT.** `services/startup.py` registra o erro numa
> linha de log e segue. Depois de um deploy que traga migration, **confira no log** que ela
> saiu como `Migration OK:` — em 05/09/2026 uma falhou em silencio e so foi descoberta
> olhando o dado pela API.

## Stack
- **Frontend**: Next.js 16 (App Router) + Tailwind v4 + daisyUI
- **Backend**: Python FastAPI (uvicorn)
- **Banco**: PostgreSQL 16 puro (container standalone no Coolify, um por tenant)
- **Scraping**: httpx + Playwright (Chromium) + curl_cffi
- **Deploy**: Coolify (Docker) na **AWS Lightsail**

## Fontes de dados (22, cadencia propria por fonte)

**Federais:** TransfereGov (portal Discricionarias + dumps SICONV/Novo PAC em
`api-publica.transferegov.gestao.gov.br`), radar de captacao (`siconv_programa.zip` — a
unica tela que olha para FRENTE, com janela de proposta ainda aberta; mais
`siconv_programa_proponentes.zip` para os programas que ja nomeiam o municipio pelo CNPJ;
cada programa abre uma ficha com propostas, edicoes anteriores e emendas indicadas —
CONTINUAR §1.30), FNS (pagamentos D-1),
InvestSUS/ConsultaFNS (fundo a fundo por bloco), CAUC/STN, SISMOB, Obras.gov.br/CIPI,
SIMEC/PAR, SICONFI/Tesouro (contas entregues + CAPAG), Portal da Transparencia/CGU
(emendas parlamentares federais: a carteira sai do dump `siconv_emenda.zip` casada pelo
CNPJ do beneficiario — e por isso alcanca as ~45% que nao viraram proposta e eram
invisiveis —, e a execucao empenhado/liquidado/pago vem da API com `chave-api-dados`).
**Estaduais:** SIGCON-MG (portal logado, credencial por municipio no Cofre) + dump
`dados.mg.gov.br`, CAGEC-MG, Acordo FES (SES-MG), GConv-ES, Transf. Voluntarias GO,
COFIN/SES-GO, TCM-GO, TCE-RS/LicitaCon, Consulta Popular/COREDEs (RS), diarios oficiais
MG/ES/GO/TO/RS.

Cada coletor vive em `backend/ingestion/` com as armadilhas anotadas no proprio
arquivo. Frescor por municipio em `scraper_municipio_coleta`; resultado de cada rodada em
`ingestion_log` (`success`/`parcial`/`erro` HONESTOS).

## Permissao: Modulo › Tela › Acao

Desde 05/09/2026 a permissao tem tres niveis encaixados, e a arvore da tela de Usuarios sai
do **mesmo objeto que desenha o menu lateral** (`frontend/src/lib/menu.ts`) — modulo novo
aparece nos dois no mesmo deploy, sem codigo novo.

Regra completa, com o que foi removido e por que, em
[`docs/PERMISSOES_POR_TELA.md`](docs/PERMISSOES_POR_TELA.md).

## Desenvolvimento local

### Backend
```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install --legacy-peer-deps
npm run dev
```

### Testes (so backend — nao existe suite de frontend)
```bash
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python -m pytest        # da raiz, SEM argumento: pytest.ini e conftest.py cuidam do resto
```

### Primeiro acesso (banco NOVO)
- `super-admin@alavank.com.br` — a conta de bootstrap, semeada por `setup_db.py`
  em tenant novo (so quando `users` esta vazia).
- **A senha nao esta escrita em lugar nenhum**: e gerada aleatoria por tenant e
  IMPRESSA NO CONSOLE do primeiro boot (`_gen_password`), ou definida via
  `ADMIN_PASSWORD`. `must_change_password` e TRUE, entao o primeiro login troca.

> ⚠️ Duas versoes anteriores desta secao traziam uma senha padrao escrita. Nao repita:
> senha em README e senha em producao ao mesmo tempo.

## Deploy (Coolify / AWS Lightsail)

Painel do Coolify: `http://54.232.208.118:8000` — projeto `pactha`, **um environment por
tenant** (o `production` esta vazio). Cliente novo: [`PROVISIONAR_CLIENTE.md`](PROVISIONAR_CLIENTE.md).

**Cada tenant** tem o mesmo conjunto de 4 resources (7 tenants = 28 resources):

| Resource | Build | Dominio |
|----------|-------|---------|
| Postgres 16 (`<tenant>-db`) | `postgres:16-alpine` (database one-click) | interno |
| API (`<tenant>-api`) | `backend/Dockerfile.api` (Base Dir = `/`) | subdominio proprio |
| Frontend (`<tenant>-frontend`) | `frontend/Dockerfile` (Base Dir = `frontend`) | subdominio proprio |
| Worker (`<tenant>-worker`) | `backend/Dockerfile.scraper` (PID 1 = `tini` + `reaper.sh`) | interno |

O frontend faz **proxy same-origin** de `/api` para o host interno da API
(`rewrites()` em `frontend/next.config.ts`, alvo em `API_PROXY_TARGET`, build-time). Por isso
cookies httpOnly + CSRF + refresh silencioso funcionam sem re-login a cada hora.

Crons = **Scheduled Tasks** anexadas ao Worker de cada tenant (mesma imagem com Chromium),
com horarios **escalonados entre tenants** de proposito — ver `docs/CRON_SETUP.md` e
[`INFRA.md`](INFRA.md). Nao alinhe os horarios — mas o motivo NAO e a maquina: ela tem 8
vCPU e 32 GB e aguenta os seis (medido em 09/09/2026: load 3.97 com os seis coletando).
O motivo e o PORTAL, que responde com bloqueio de IP e credencial recusada quando seis
coletores batem nele no mesmo minuto.

Variaveis de ambiente: ver `.env.example`. As migrations idempotentes rodam no
boot da API (`services/startup.py`).

## Documentacao

| Arquivo | Para que serve |
|---------|----------------|
| [`INFRA.md`](INFRA.md) | Servidor, URLs, bancos, operacoes no Coolify — **fonte de verdade de infra** |
| [`CLAUDE.md`](CLAUDE.md) | Contexto que a IA le em toda sessao — regras do repo |
| [`CONTINUAR.md`](CONTINUAR.md) | Handoff: decisoes e historico entre sessoes |
| [`docs/PERMISSOES_POR_TELA.md`](docs/PERMISSOES_POR_TELA.md) | Modulo › Tela › Acao, e o cadastro de usuario |
| [`docs/CRON_SETUP.md`](docs/CRON_SETUP.md) | Rotinas de ingestao e Scheduled Tasks |
| [`docs/SECURITY_CREDENTIALS.md`](docs/SECURITY_CREDENTIALS.md) | Cofre AES-256 + Service Tokens |
| [`docs/MAPA_RS.md`](docs/MAPA_RS.md) | As fontes do Rio Grande do Sul |
| [`extension/README.md`](extension/README.md) | Extensao Chrome de captura de sessao gov.br |
