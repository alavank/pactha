# PACTHA - Sistema de Monitoramento de Convenios

Plataforma de monitoramento de convenios, repasses e emendas para municipios e
assessorias — **17 fontes oficiais** (federais + estaduais de MG/ES/GO), coletadas
na cadencia real de cada uma, com selo "atualizado em" nas telas e vigilancia de
frescor por municipio.

> 📍 **Onde isto roda:** **AWS Lightsail `54.232.208.118` (sa-east-1), orquestrado por Coolify.**
> Toda a verdade sobre servidor, URLs, bancos, crons e segredos esta em **[`INFRA.md`](INFRA.md)**.
> Nao usamos Hetzner, Railway, Neon, Vercel, Netlify nem Supabase.

## ⚠️ Um repo, TRES tenants — e um merge na main DEPLOYA OS TRES (desde 09/08)

Este repositorio atende **tres clientes distintos**, cada um com seu proprio conjunto de
containers e seu **proprio banco**, todos buildados do **mesmo codigo**:

| Tenant | Slug | App | API |
|--------|------|-----|-----|
| Freitas | `freitas` | https://pactha-54-232-208-118.sslip.io | https://pactha-api-54-232-208-118.sslip.io |
| Trust | `trust` | https://pactha-trust-54-232-208-118.sslip.io | https://pactha-trust-api-54-232-208-118.sslip.io |
| Monte Siao/MG | `montesiao-mg` | https://pactha-montesiao-mg-54-232-208-118.sslip.io | https://pactha-montesiao-mg-api-54-232-208-118.sslip.io |

**Os TRES tenants** tem o **Painel de Indicadores** (BI) ligado — flag build-time
`NEXT_PUBLIC_BI_MODULE=1` na matriz do `build-frontend.yml`. `/dashboard` e o
painel executivo (abas por assunto, filtro multi-ano, insights de IA) e `/tela` e
o **Modo Tela** (TV de gabinete, com link publico revogavel `/t/<slug>`). O app
separado `painel/` foi descontinuado — ver `painel/DEPRECADO.md`.

Nao ha multi-tenancy no codigo: **o isolamento e por deploy**. O que muda entre um tenant e
outro sao as env vars no Coolify (`INSTANCE_SLUG`, `DATABASE_URL`, `JWT_SECRET`, `COFRE_KEY`,
`NEXT_PUBLIC_CLIENT_LOGO`, `NEXT_PUBLIC_CLIENT_SUBTITLE`).

**Consequencia pratica (modelo de 09/08, PRs #161-#163):** merge na `main` que toca
`backend/**` ou `frontend/**` **builda no GitHub Actions e deploya os 3 tenants sozinho**,
na ordem certa: API primeiro (roda as migrations; deployment confirmado), depois o worker
do mesmo tenant **esperando janela sem coleta em voo**. O auto-deploy por webhook do
Coolify esta **desligado nas 9 aplicacoes** (recriava containers com a tag antiga e matava
coleta). Deploy manual continua possivel para rollback. Mecanica completa comentada nos
proprios `.github/workflows/*.yml`; visao de infra em [`INFRA.md`](INFRA.md) §2.

Alem disso, um mesmo bug corrigido aqui **vai para os tres clientes** — e uma mudanca de
schema precisa ser idempotente nos tres bancos.

## Stack
- **Frontend**: Next.js 16 (App Router) + Tailwind v4 + daisyUI
- **Backend**: Python FastAPI (uvicorn)
- **Banco**: PostgreSQL 16 puro (container standalone no Coolify, um por tenant)
- **Scraping**: httpx + Playwright (Chromium) + curl_cffi
- **Deploy**: Coolify (Docker) na **AWS Lightsail**

## Fontes de dados (17, cadencia propria por fonte)

**Federais:** TransfereGov (portal Discricionarias + dumps SICONV/Novo PAC em
`api-publica.transferegov.gestao.gov.br` — diarios ate 9h BRT), FNS (pagamentos D-1),
CAUC/STN (diario em dias uteis), SISMOB (API publica), SIMEC/PAR.
**Estaduais:** SIGCON-MG (portal logado, credencial por municipio no Cofre) + dump
`dados.mg.gov.br/convenios-saida` (diario ~8h14), CAGEC-MG (consulta publica + CRC),
Acordo FES (SES-MG), GConv-ES (diario em dias uteis), Transf. Voluntarias GO
(mensal-irregular!), COFIN/SES-GO, TCM-GO, diarios oficiais MG/ES/GO/TO.

Cada coletor vive em `backend/ingestion/` com as armadilhas anotadas no proprio
arquivo. Frescor por municipio em `scraper_municipio_coleta` (fontes `sigcon`,
`sigcon_emendas`, `transferegov`); resultado de cada rodada em `ingestion_log`
(`success`/`parcial`/`erro` HONESTOS desde o PR #160).

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

### Primeiro acesso (banco NOVO)
- `super-admin@alavank.com.br` — a conta de bootstrap, semeada por `setup_db.py`
  em tenant novo (so quando `users` esta vazia).
- **A senha nao esta escrita em lugar nenhum**: e gerada aleatoria por tenant e
  IMPRESSA NO CONSOLE do primeiro boot (`_gen_password`), ou definida via
  `ADMIN_PASSWORD`. `must_change_password` e TRUE, entao o primeiro login troca.
- Senha padrao publicada em README e senha padrao em producao — as duas versoes
  anteriores desta secao traziam uma.

(validos no seed de um banco novo; em producao as senhas ja foram trocadas)

## Deploy (Coolify / AWS Lightsail)

Painel do Coolify: `http://54.232.208.118:8000` — projeto `pactha`, environment `production`.

**Cada tenant** tem o mesmo conjunto de 4 resources:

| Resource | Build | Dominio |
|----------|-------|---------|
| Postgres 16 (`<tenant>-db`) | `postgres:16-alpine` (database one-click) | interno |
| API (`<tenant>-api`) | `backend/Dockerfile.api` (Base Dir = `/`) | subdominio proprio |
| Frontend (`<tenant>-frontend`) | `frontend/Dockerfile` (Base Dir = `frontend`) | subdominio proprio |
| Worker (`<tenant>-worker`) | `backend/Dockerfile.scraper` (PID 1 = `tini` + `reaper.sh`; crons via Scheduled Tasks) | interno |

O frontend faz **proxy same-origin** de `/api` para o host interno da API
(`rewrites()` em `frontend/next.config.ts`, alvo em `API_PROXY_TARGET`, build-time). Por isso
cookies httpOnly + CSRF + refresh silencioso funcionam sem re-login a cada hora.

Crons = **Scheduled Tasks** anexadas ao Worker de cada tenant (mesma imagem com Chromium),
com horarios **escalonados entre tenants** de proposito — ver `docs/CRON_SETUP.md` e
[`INFRA.md`](INFRA.md). Nao alinhe os horarios: a maquina e burstable e nao aguenta os tres
raspando ao mesmo tempo.

Variaveis de ambiente: ver `.env.example`. As migrations idempotentes rodam no
boot da API (`services/startup.py`).

## Documentacao

| Arquivo | Para que serve |
|---------|----------------|
| [`INFRA.md`](INFRA.md) | Servidor, URLs, bancos, segredos, operacoes no Coolify — **fonte de verdade** |
| [`CONTINUAR.md`](CONTINUAR.md) | Handoff para a proxima sessao de IA/dev |
| [`docs/CRON_SETUP.md`](docs/CRON_SETUP.md) | Rotinas de ingestao e Scheduled Tasks |
| [`docs/SECURITY_CREDENTIALS.md`](docs/SECURITY_CREDENTIALS.md) | Cofre AES-256 + Service Tokens |
| [`extension/README.md`](extension/README.md) | Extensao Chrome de captura de sessao gov.br |
