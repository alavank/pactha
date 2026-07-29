# PACTHA - Sistema de Monitoramento de Convenios

Plataforma de monitoramento de convenios e transferencias governamentais para municipios de MG.

> 📍 **Onde isto roda:** **AWS Lightsail `54.232.208.118` (sa-east-1), orquestrado por Coolify.**
> Toda a verdade sobre servidor, URLs, bancos, crons e segredos esta em **[`INFRA.md`](INFRA.md)**.
> Nao usamos Hetzner, Railway, Neon, Vercel, Netlify nem Supabase.

## ⚠️ Um repo, TRES tenants — um push nao e um deploy so

Este repositorio atende **tres clientes distintos**, cada um com seu proprio conjunto de
containers e seu **proprio banco**, todos buildados do **mesmo codigo**:

| Tenant | Slug | App | API |
|--------|------|-----|-----|
| Freitas | `freitas` | https://pactha-54-232-208-118.sslip.io | https://pactha-api-54-232-208-118.sslip.io |
| Trust | `trust` | https://pactha-trust-54-232-208-118.sslip.io | https://pactha-trust-api-54-232-208-118.sslip.io |
| Monte Siao/MG | `montesiao-mg` | https://pactha-montesiao-mg-54-232-208-118.sslip.io | https://pactha-montesiao-mg-api-54-232-208-118.sslip.io |

O Monte Siao tem o **Painel de Indicadores** (BI) ligado — flag build-time
`NEXT_PUBLIC_BI_MODULE=1`. Com ela, `/dashboard` **e** o painel executivo (abas
por assunto, filtro multi-ano, insights de IA) e `/tela` e o **Modo Tela**, a
janela de exibicao com as abas em fichario passando em slideshow. O app separado
`painel/` foi descontinuado — ver `painel/DEPRECADO.md`.

Nao ha multi-tenancy no codigo: **o isolamento e por deploy**. O que muda entre um tenant e
outro sao as env vars no Coolify (`INSTANCE_SLUG`, `DATABASE_URL`, `JWT_SECRET`, `COFRE_KEY`,
`NEXT_PUBLIC_CLIENT_LOGO`, `NEXT_PUBLIC_CLIENT_SUBTITLE`).

**Consequencia pratica:** sao **10 aplicacoes** no projeto Coolify `pactha`. Com auto-deploy
ligado, **um unico push na `main` dispara ate 9 builds simultaneos** (hoje 7 aplicacoes
acompanham `main` e 3 acompanham `feat/painel-executivo`) — numa maquina **burstable de
baseline 30% (~0,6 vCPU sustentado)**. Nunca trate um push como "um deploy".

> **Agora o auto-deploy esta DESLIGADO** nas 10 aplicacoes (medido em 2026-07-23): o push
> nao dispara build, o deploy e manual pelo painel do Coolify. Detalhes em [`INFRA.md`](INFRA.md).

Alem disso, um mesmo bug corrigido aqui **vai para os tres clientes** — e uma mudanca de
schema precisa ser idempotente nos tres bancos.

## Stack
- **Frontend**: Next.js 16 (App Router) + Tailwind v4 + daisyUI
- **Backend**: Python FastAPI (uvicorn)
- **Banco**: PostgreSQL 16 puro (container standalone no Coolify, um por tenant)
- **Scraping**: httpx + Playwright (Chromium) + curl_cffi
- **Deploy**: Coolify (Docker) na **AWS Lightsail**

## Fontes de dados
- TransfereGov (federal): `http://repositorio.dados.gov.br/seges/detru/`
- SIGCON-MG (estadual): `https://dados.mg.gov.br/dataset/convenios-saida`

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

### Login padrao
- Admin: `admin@pactha.com.br` / `pactha2026`
- Equipe: `lara@freitas.com.br` / `freitas2026`

(validos no seed de um banco novo; em producao as senhas ja foram trocadas)

## Deploy (Coolify / AWS Lightsail)

Painel do Coolify: `http://54.232.208.118:8000` — projeto `pactha`, environment `production`.

**Cada tenant** tem o mesmo conjunto de 4 resources (o Monte Siao tem um 5o, o Painel):

| Resource | Build | Dominio |
|----------|-------|---------|
| Postgres 16 (`<tenant>-db`) | `postgres:16-alpine` (database one-click) | interno |
| API (`<tenant>-api`) | `backend/Dockerfile.api` (Base Dir = `/`) | subdominio proprio |
| Frontend (`<tenant>-frontend`) | `frontend/Dockerfile` (Base Dir = `frontend`) | subdominio proprio |
| Worker (`<tenant>-worker`) | `backend/Dockerfile.scraper` (CMD `sleep infinity`) | interno |
| Painel (so `montesiao-mg`) | `painel/Dockerfile` (Base Dir = `painel`) | subdominio proprio |

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
