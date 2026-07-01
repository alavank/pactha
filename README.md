# PACTHA - Sistema de Monitoramento de Convenios

Plataforma de monitoramento de convenios e transferencias governamentais para municipios de MG.

## Stack
- **Frontend**: Next.js 16 (Vercel)
- **Backend**: Python FastAPI (Render.com)
- **Banco**: Neon PostgreSQL
- **Ingestao**: GitHub Actions cron diario

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
npm install
npm run dev
```

### Login padrao
- Admin: `admin@pacta.com.br` / `pacta2026`
- Equipe: `lara@freitas.com.br` / `freitas2026`

## Deploy

### Backend (Render)
Configurado via `render.yaml`. Variaveis de ambiente necessarias:
- `DATABASE_URL`, `DATABASE_URL_SYNC`, `JWT_SECRET`, `FRONTEND_URL`

### Frontend (Vercel)
```bash
cd frontend
vercel --prod
```
Variavel: `NEXT_PUBLIC_API_URL` apontando para o backend no Render.

### Ingestao automatica
GitHub Actions roda `daily-ingestion.yml` todos os dias as 09:00 BRT.
Secrets necessarios: `DATABASE_URL`, `DATABASE_URL_SYNC`, `JWT_SECRET`.
