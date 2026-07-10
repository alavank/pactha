# PACTHA - Configuração de Crons (Coolify)

As rotinas de ingestão rodam como **Scheduled Tasks** anexadas ao resource
**Worker** no Coolify. O Worker é buildado a partir de `backend/Dockerfile.scraper`
(já traz Chromium + Playwright) e fica ocioso (`CMD sleep infinity`); cada
Scheduled Task executa um comando dentro dele via `docker exec`.

## Scheduled Tasks

| Nome | Cron | Comando | Env necessárias |
|------|------|---------|-----------------|
| sigcon | `0 */6 * * *` | `python -u ingestion/run_sigcon_cron.py` | `DATABASE_URL_SYNC`, `COFRE_KEY` |
| transferegov | `0 5 * * *` | `python -u ingestion/transferegov_voluntarias.py` | `DATABASE_URL_SYNC`, `COFRE_KEY` |
| fns | `30 5 * * *` | `python -u ingestion/run_fns_local.py` | `DATABASE_URL_SYNC`, `COFRE_KEY` |
| govbr-renew | `*/15 * * * *` | `python -u ingestion/govbr_renew.py` | `DATABASE_URL_SYNC`, `COFRE_KEY` |
| fila on-demand | `*/2 * * * *` | `python -u ingestion/run_queue_sigcon.py` | `DATABASE_URL_SYNC` |

- `run_sigcon_cron.py` já roda também as fontes de **dados abertos** (CAUC +
  Acordo FES via `run_dadosabertos_cron.run_all()`) e o backfill CKAN.
- `run_queue_sigcon.py` consome a tabela `scraper_jobs` — jobs enfileirados pelo
  botão "atualizar SIGCON" da UI (`POST /api/convenios/refresh-sigcon`).

## Como criar no Coolify

1. Abra o resource **Worker** → aba **Scheduled Tasks**.
2. **+ Add** → informe *Name*, *Frequency* (cron) e *Command* (coluna acima).
3. As env vars vêm do próprio resource Worker (defina `DATABASE_URL_SYNC`,
   `COFRE_KEY`, `PACTHA_API_URL`, `PACTHA_SERVICE_TOKEN` uma vez no Worker).
4. Para rodar sob demanda: botão **Run now** na Scheduled Task.

## Monitoramento

Logs de ingestão ficam na tabela `ingestion_log`. Query útil:

```sql
SELECT source, status, records_inserted, finished_at, error_message
FROM ingestion_log
WHERE finished_at > NOW() - INTERVAL '7 days'
ORDER BY finished_at DESC;
```

Status da fila on-demand:

```sql
SELECT id, tipo, status, requested_at, started_at, finished_at, error
FROM scraper_jobs ORDER BY id DESC LIMIT 20;
```
