# PACTHA - Configuração de Cron no Railway

Os pipelines de ingestão rodam em 3 tiers de frequência. Cada tier deve ser
criado como um **service separado** no Railway:

## Tier DAILY (00:00 BRT)

**Cobre:** editais PNCP, oportunidades, DOU INLABS (se credencial cadastrada)

- **Service config:** `backend/railway-cron-daily.json`
- **Cron:** `0 4 * * *` (04:00 UTC = 01:00 BRT)
- **Env vars necessárias:**
  - `DATABASE_URL`, `DATABASE_URL_SYNC`, `JWT_SECRET`
  - `PORTAL_TRANSPARENCIA_KEY`
  - `INLABS_USER`, `INLABS_PASS` (opcionais, ativam DOU)
  - `CRON_TIER=daily`

## Tier WEEKLY (segunda 02:00 BRT)

**Cobre:** Câmara Deputados + Senado + ALMG + CNES + CEIS

- **Service config:** `backend/railway-cron-weekly.json`
- **Cron:** `0 5 * * 1` (05:00 UTC seg = 02:00 BRT seg)
- **Env vars:**
  - DBs + `PORTAL_TRANSPARENCIA_KEY`
  - `CRON_TIER=weekly`

## Tier MONTHLY (dia 1 do mês 03:00 BRT)

**Cobre:** TransfereGov bulk + SIGCON + emendas fed/est + PortalTransp + CODEVASF + TSE

- **Service config:** `backend/railway-cron-monthly.json`
- **Cron:** `0 6 1 * *` (06:00 UTC dia 1 = 03:00 BRT dia 1)
- **Env vars:**
  - DBs + `PORTAL_TRANSPARENCIA_KEY` + `TRANSFEREGOV_BASE_URL`
  - `CRON_TIER=monthly`

## Como criar no Railway

Para cada tier:
1. **Settings → New Service → Empty Service**
2. **Settings → Source → Repo:** `PACTHA` branch `main`
3. **Settings → Root Directory:** `backend`
4. **Settings → Config file:** apontar para o `railway-cron-{tier}.json` correspondente
5. **Variables:** copiar do backend principal + adicionar `CRON_TIER`

## Tier FULL (uso manual)

Para forçar uma execução completa sem esperar o cron:
```bash
railway run --service=pacta-cron-weekly CRON_TIER=full python ingestion/run_all.py
```

## Monitoramento

Logs ficam em `ingestion_log` (tabela). Query útil:

```sql
SELECT source, status, records_inserted, finished_at, error_message
FROM ingestion_log
WHERE finished_at > NOW() - INTERVAL '7 days'
ORDER BY finished_at DESC;
```
