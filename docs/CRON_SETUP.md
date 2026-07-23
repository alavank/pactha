# PACTHA - Configuração de Crons (Coolify)

> Infra: **Coolify na AWS Lightsail `54.232.208.118`**. Ver [`../INFRA.md`](../INFRA.md).

As rotinas de ingestão rodam como **Scheduled Tasks** anexadas ao resource
**Worker** no Coolify. O Worker é buildado a partir de `backend/Dockerfile.scraper`
(já traz Chromium + Playwright, `tini` e o reaper `backend/reaper.sh`) e fica ocioso
(`CMD sleep infinity`); cada Scheduled Task executa um comando dentro dele via
`docker exec`.

⚠️ **Existe um Worker por tenant** (`freitas-worker`, `trust-worker`,
`montesiao-mg-worker`), cada um com seu banco e sua `COFRE_KEY`. As tasks abaixo
existem em triplicata, **com horários diferentes de propósito**.

## Por que os horários são escalonados (não "arrume" isso)

A máquina é **burstable, com baseline de CPU de 30%** (~0,6 vCPU sustentado) e hospeda
outros 10 projetos. Se os três tenants rodarem SIGCON/TransfereGov ao mesmo tempo, com
três Chromium abertos, o host inteiro cai para o baseline. Por isso:

- horários deslocados entre tenants (ver tabela);
- `SIGCON_CONCURRENCY=1` em todos os workers — **não aumente**;
- todo comando é embrulhado em `flock -n` (não sobrepõe execução) e
  `timeout -k 30 <seg>` (mata processo pendurado).

## Scheduled Tasks

| Task | Freitas | Trust | Monte Sião | Comando | Env necessárias |
|------|---------|-------|------------|---------|-----------------|
| `sigcon` | `0 0,6,12,18 * * *` | `0 2,8,14,20 * * *` | `0 4,10,16,22 * * *` | `run_sigcon_cron.py` | `DATABASE_URL_SYNC`, `COFRE_KEY` |
| `transferegov` | `0 2 * * *` | `0 10 * * *` | `0 18 * * *` | `transferegov_voluntarias.py` | `DATABASE_URL_SYNC`, `COFRE_KEY` |
| `fns` | `30 5 * * *` | `30 6 * * *` | `30 7 * * *` | `run_fns_local.py` | `DATABASE_URL_SYNC`, `COFRE_KEY` |
| `govbr-renew` | `5 * * * *` | `25 * * * *` | `45 * * * *` | `govbr_renew.py` | `DATABASE_URL_SYNC`, `COFRE_KEY` |
| `queue-sigcon` | `0,30 * * * *` | `10,40 * * * *` | `20,50 * * * *` | `run_queue_sigcon.py` | `DATABASE_URL_SYNC` |
| `painel-alertas` | — | — | `15 */2 * * *` | `run_painel_alertas_cron.py` | `DATABASE_URL_SYNC`, chaves VAPID |

Comandos completos, exatamente como estão no Coolify:

```bash
# sigcon
SIGCON_CONCURRENCY=1 SIGCON_STALE_MINUTES=360 flock -n /tmp/sigcon.lock \
  timeout -k 30 3000 python -u ingestion/run_sigcon_cron.py \
  || echo "[aviso] sigcon rc=$? (1=ja rodando, 124=timeout)"

# transferegov
TG_SKIP_ENRICH=1 SIGCON_CONCURRENCY=1 flock -n /tmp/transferegov.lock \
  timeout -k 30 3000 python -u ingestion/transferegov_voluntarias.py \
  || echo "[aviso] transferegov rc=$? (1=ja rodando, 124=timeout)"

# fns
flock -n /tmp/fns.lock timeout -k 30 1800 python -u ingestion/run_fns_local.py \
  || echo "[aviso] fns rc=$? (1=ja rodando, 124=timeout)"

# govbr-renew
flock -n /tmp/govbr.lock timeout -k 30 600 python -u ingestion/govbr_renew.py \
  || echo "[aviso] govbr-renew rc=$? (1=ja rodando, 124=timeout)"

# queue-sigcon
SIGCON_CONCURRENCY=1 SIGCON_STALE_MINUTES=360 flock -n /tmp/queue-sigcon.lock \
  timeout -k 30 900 python -u ingestion/run_queue_sigcon.py \
  || echo "[aviso] queue-sigcon rc=$? (1=ja rodando, 124=timeout)"

# painel-alertas (so montesiao-mg)
flock -n /tmp/painel-alertas.lock timeout -k 30 900 \
  python -u ingestion/run_painel_alertas_cron.py \
  || echo "[aviso] painel-alertas rc=$? (1=ja rodando, 124=timeout)"
```

- `run_sigcon_cron.py` já roda também as fontes de **dados abertos** (CAUC +
  Acordo FES via `run_dadosabertos_cron.run_all()`) e o backfill CKAN.
- `run_queue_sigcon.py` consome a tabela `scraper_jobs` — jobs enfileirados pelo
  botão "atualizar SIGCON" da UI (`POST /api/convenios/refresh-sigcon`). Como a task
  roda a cada 30min, o job enfileirado sai em **até 30 minutos** (não em 2min).

## Como criar/alterar no Coolify

1. Painel em `http://54.232.208.118:8000` → projeto **`pactha`** → resource
   **`<tenant>-worker`** → aba **Scheduled Tasks**.
2. **+ Add** → informe *Name*, *Frequency* (cron) e *Command* (acima).
3. As env vars vêm do próprio resource Worker (defina `DATABASE_URL_SYNC`,
   `COFRE_KEY`, `SIGCON_CONCURRENCY`, `TG_SKIP_ENRICH`, e — se usar Service Token —
   `PACTHA_API_URL`, `PACTHA_SERVICE_TOKEN` uma vez no Worker).
4. Para rodar sob demanda: botão **Run now** na Scheduled Task. **Não dispare os três
   tenants ao mesmo tempo.**
5. Ao criar uma task nova, **escolha um horário que não colida com as dos outros dois
   tenants**.

## Monitoramento

Logs de ingestão ficam na tabela `ingestion_log` — **do banco daquele tenant**.
Query útil:

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

Para abrir o `psql` do tenant:

```bash
ssh -i ~/.ssh/coolify_localhost root@54.232.208.118
docker exec -it tox59kvmkrb0ywmeaty3t02a psql -U pactha -d pactha   # freitas
docker exec -it p434vbj35siee57shlsyzuc2 psql -U pactha -d pactha   # trust
docker exec -it iogvjlnkpqlugja9j76rktl1 psql -U pactha -d pactha   # montesiao-mg
```
