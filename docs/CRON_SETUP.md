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

| Task | Freitas | Trust | Monte Sião |
|------|---------|-------|------------|
| `sigcon` | `0 0,6,12,18 * * *` | `0 2,8,14,20 * * *` | `0 4,10,16,22 * * *` |
| `transferegov` | `0 2 * * *` | `0 10 * * *` | `0 18 * * *` |
| `fns` | `30 5 * * *` | `30 6 * * *` | `30 7 * * *` |
| `govbr-renew` | `5 * * * *` | `25 * * * *` | `45 * * * *` |
| `queue-sigcon` | `0,30 * * * *` | `10,40 * * * *` | `20,50 * * * *` |
| `painel-alertas` | `45 */2 * * *` | `15 */2 * * *` | `15 */2 * * *` |
| `cagec` | `0 10,15,19,23 * * *` | `48 10,15,19,23 * * *` | `46 10,15,19,23 * * *` |
| `cauc-manha` | `25 10-14 * * *` | `27 10-14 * * *` | `29 10-14 * * *` |
| `gconv-es` | — | `40 10,15,19,23 * * *` | — |
| `transfvol-go` | — | `42 10,15,19,23 * * *` | — |
| `cofin-ses-go` | — | `44 10,15,19,23 * * *` | — |
| `tcm-go` | — | `45 10 * * *` | — |

> 🕐 **TODOS OS HORÁRIOS ACIMA SÃO UTC.** O host, o `instance_timezone` do
> Coolify e o PHP do container estão em `Etc/UTC`; **Brasília é UTC−3**. Isto já
> custou caro: um `cagec` marcado para "07:00" rodava às **04:00 da manhã** para
> o cliente. Ao combinar horário com alguém, converta antes de escrever o cron.
> As faixas do CAGEC (10/15/19/23 UTC) são **07h, 12h, 16h e 20h de Brasília**.
> Dentro de cada faixa: Freitas `:00`–`:34`, Monte Sião `:46`, Trust `:48`–`:57`.
> O 15h virou 16h porque o SIGCON da Freitas ocupa 15:00–15:50 BRT.

**Duração real medida** (de `scheduled_task_executions`, 7 dias — e **não** de
`ingestion_log`, cujo `started_at` é NULL e faz toda média sair 0):

| | `sigcon` | `cagec` | `transferegov` |
|---|---|---|---|
| Freitas (41 municípios) | **43 min** (máx 50) | 18 min (máx 45) | 24 min |
| Trust (19, sendo 7 de MG) | 1,8 min | 5,5 min | 28 min |
| Monte Sião (1) | 6,3 min | 1,2 min | 7,6 min |

⚠️ **O `cagec` da Freitas tem DOIS tetos e os dois precisam caber**: o do job
runner do Coolify (coluna `scheduled_tasks.timeout`, hoje 3000s) e o
`timeout -k 30 N` do próprio comando (2700s). Subir só um não resolve — e um job
morto pelo runner **não deixa linha em `ingestion_log`**, porque o log só é
escrito no fim do script. Foi assim que a Freitas passou nove dias sem coletar,
sem erro em lugar nenhum, só com a data velha na tela. O reaper mata em 3600s,
que é o teto de tudo isso.

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

# portal-transparencia (emendas parlamentares federais) — 06/09/2026
flock -n /tmp/portal_transparencia.lock timeout -k 30 1520 \
  python -u ingestion/portal_transparencia.py \
  || echo "[aviso] portal-transparencia rc=$? (1=ja rodando, 124=timeout)"
```

### portal-transparencia — a fonte nova (emendas federais)

**Task PROPRIA, e nao pendurada no `run_all()` dos dados abertos.** O perfil da fonte
convida (dado aberto, leve, idempotente, auto-limitada), mas [`INFRA.md`](../INFRA.md) §5
e explicito: **nos dois tenants do RS nao ha `sigcon`** — e e ele que chama o
`run_dadosabertos_cron.run_all()`. Nova Palma e Santa Maria nunca coletariam, e Nova
Palma e justamente um dos dois municipios onde a chave da CGU foi ligada. Some-se o
desconto do `SIGCON_BUDGET_SECONDS` e o precedente do PR #259 (fonte coletando 2x/dia).

**Lock proprio** (`/tmp/portal_transparencia.lock`) e nao o `/tmp/scraper.lock`
compartilhado: e `httpx` puro, sem login e sem navegador, entao nao disputa a fila do
Chromium. Mesmo argumento do `simec-termos` e do `obrasgov`.

**Margens** (regra de ouro do INFRA.md): orcamento interno `PT_ORCAMENTO_S=1400` →
`timeout -k 30 **1520**` → coluna `timeout` da Scheduled Task = **1640** (interno + 120).
Mexer num sem o outro faz o Coolify matar primeiro e **descartar o stdout** — a task
nunca teria logado nada em tenant nenhum, que foi o que aconteceu em 17/08.

**Escada (UTC), passo de 30 min:** freitas `35 3 * * *` · trust `5 4 * * *` ·
montesiao `35 4 * * *` · santamaria `5 5 * * *` · **novapalma `35 5 * * *`**.

- Tudo dentro de **03:00–05:59 UTC = 00:00–02:59 BRT**, que e a janela de **700 req/min**
  da CGU (fora dela sao 400).
- ⚠️ O passo de 30 min e **maior que o orcamento de 23 min** de proposito: a cota da CGU
  e **por CHAVE**, e a chave e a mesma nos tenants que a tem. Dois workers nunca podem
  bater no mesmo token ao mesmo tempo.
- Os minutos `:35`/`:05` evitam o `transferegov-lote` (`:00`), o `sigcon` (`:25`) e o
  `cagec` (`:50-58`).

⚠️ **Antes de criar, confira a coluna VERTICAL de cada worker**
(`GET /applications/<worker_uuid>/scheduled-tasks`, que e a fonte de verdade — nao este
arquivo). A escada do `obrasgov` foi desenhada *entre tenants* e ninguem a conferiu
contra as tasks `03:xx` que cada worker ja tinha; o freitas nasceu no mesmo minuto do
`transferegov-lote`.

⚠️ **A chave (`PORTAL_TRANSPARENCIA_API_KEY`) vai no WORKER**, nao na API, e so em
`novapalma-rs` e `montesiao-mg`. Sem ela a task ainda vale a pena: a **carteira** de
emendas sai do dump aberto e roda nos cinco.

- `run_sigcon_cron.py` já roda também as fontes de **dados abertos**
  (`run_dadosabertos_cron.run_all()`: CAUC, Acordo FES, SISMOB e SIMEC-PAR) e o
  backfill CKAN. Elas não têm task própria de propósito — o SISMOB se auto-limita a
  1×/dia dentro do próprio `ingest()` (`SISMOB_MIN_INTERVAL_H`).
  ⚠️ Consequência para quem for acrescentar a próxima: essas fontes **não têm
  `timeout` próprio** — herdam o `timeout -k 30 3000` da task `sigcon` e gastam do
  orçamento dele (`SIGCON_BUDGET_SECONDS`, do qual o tempo é descontado). Fonte
  nova aqui dentro precisa de orçamento interno CURTO, não dos 25 min de quem tem
  task própria.
  ⚠️ **Os Termos de Compromisso do SIMEC NÃO estão aqui**: têm task própria
  (`simec-termos`, 06:10, lock `/tmp/simec_termos.lock`, timeout 1700) nos 4
  workers. O PR #259 chegou a pendurá-los no `run_all()` sem saber que a task já
  existia, e a fonte passou a coletar duas vezes por dia; foi desfeito. Antes de
  pendurar QUALQUER fonte aqui, confira as tasks reais no Coolify — elas são a
  fonte de verdade, não este documento.
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
