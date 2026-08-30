\echo === c07a: tasks do worker Freitas ===
SELECT id, uuid, name FROM applications WHERE uuid='s49c3b58lysqq0tpelneg3g3';
SELECT st.id, st.name, st.frequency, st.timeout, st.enabled, left(st.command,255) AS cmd
FROM scheduled_tasks st JOIN applications a ON a.id=st.application_id
WHERE a.uuid='s49c3b58lysqq0tpelneg3g3' ORDER BY st.name;
\echo === c07b: duracao real 30d por task x status ===
SELECT st.name, e.status, count(*) AS n,
       round(avg(COALESCE(e.duration, EXTRACT(epoch FROM e.updated_at-e.created_at)))::numeric) AS avg_s,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY COALESCE(e.duration, EXTRACT(epoch FROM e.updated_at-e.created_at))::float8)::numeric) AS med_s,
       max(COALESCE(e.duration, EXTRACT(epoch FROM e.updated_at-e.created_at)))::int AS max_s,
       st.timeout AS teto_task_s,
       count(*) FILTER (WHERE COALESCE(e.duration, EXTRACT(epoch FROM e.updated_at-e.created_at)) >= st.timeout - 5) AS bateu_teto,
       count(*) FILTER (WHERE e.message ILIKE '%rc=124%' OR e.error_details ILIKE '%124%') AS msg_timeout,
       count(*) FILTER (WHERE e.message ILIKE '%rc=99%' OR e.message ILIKE '%ja rodando%' OR e.message ILIKE '%pulou%') AS msg_lock_pulou,
       count(*) FILTER (WHERE e.message IS NULL OR length(e.message) < 20) AS msg_vazia
FROM scheduled_task_executions e
JOIN scheduled_tasks st ON st.id=e.scheduled_task_id
JOIN applications a ON a.id=st.application_id
WHERE a.uuid='s49c3b58lysqq0tpelneg3g3' AND e.created_at >= now() - interval '30 days'
GROUP BY 1,2, st.timeout ORDER BY 1,2;
\echo === c07c: execucoes TransfereGov (diaria + lote), duracao vs teto ===
SELECT st.name, e.id, e.status,
       to_char(e.created_at - interval '3 hours','MM-DD HH24:MI') AS inicio_brt,
       COALESCE(e.duration, EXTRACT(epoch FROM e.updated_at-e.created_at))::int AS dur_s, st.timeout AS teto_task_s,
       CASE WHEN e.status='running' AND e.created_at < now()-interval '2 hours' THEN 'RUNNING-ORFA'
            WHEN COALESCE(e.duration, EXTRACT(epoch FROM e.updated_at-e.created_at)) >= 3000 THEN 'PERTO-DO-TETO' END AS alerta,
       left(regexp_replace(e.message, E'[\\r\\n]+', ' | ', 'g'), 120) AS msg_inicio,
       right(regexp_replace(e.message, E'[\\r\\n]+', ' | ', 'g'), 160) AS msg_fim
FROM scheduled_task_executions e JOIN scheduled_tasks st ON st.id=e.scheduled_task_id
JOIN applications a ON a.id=st.application_id
WHERE a.uuid='s49c3b58lysqq0tpelneg3g3' AND st.name ILIKE '%transferegov%' AND st.name NOT ILIKE '%lote%' AND e.created_at >= now() - interval '30 days'
ORDER BY st.name, e.created_at DESC;
\echo === c07d: execucoes por dia x task ===
SELECT to_char(date_trunc('day', e.created_at - interval '3 hours'),'YYYY-MM-DD') AS dia_brt, st.name,
       count(*) AS execs, count(*) FILTER (WHERE e.status='success') AS ok,
       count(*) FILTER (WHERE e.status='failed') AS failed, count(*) FILTER (WHERE e.status='running') AS running
FROM scheduled_task_executions e JOIN scheduled_tasks st ON st.id=e.scheduled_task_id
JOIN applications a ON a.id=st.application_id
WHERE a.uuid='s49c3b58lysqq0tpelneg3g3' AND e.created_at >= now() - interval '30 days'
GROUP BY 1,2 ORDER BY 2,1;
\echo === c10a: estado da sessao pela task govbr (horas acumuladas) ===
WITH ex AS (
  SELECT e.created_at, st.name,
         CASE WHEN e.message ILIKE '%RECONECTADO%' THEN 'viva'
              WHEN e.message ILIKE '%SSO expirou%' OR e.message ILIKE '%RE-CAPTURA%' THEN 'morta'
              WHEN e.message ILIKE '%sem sessao govbr%' THEN 'sem_sessao'
              WHEN e.status <> 'success' THEN 'falhou_task' ELSE 'indeterminado' END AS estado
  FROM scheduled_task_executions e JOIN scheduled_tasks st ON st.id=e.scheduled_task_id JOIN applications a ON a.id=st.application_id
  WHERE a.uuid='s49c3b58lysqq0tpelneg3g3' AND (st.name ILIKE '%govbr%' OR st.name ILIKE '%keepalive%') AND e.created_at >= now() - interval '30 days'),
seq AS (SELECT created_at, name, estado, lead(created_at) OVER (PARTITION BY name ORDER BY created_at) AS prox FROM ex)
SELECT name, estado, count(*) AS execs, round((sum(EXTRACT(epoch FROM COALESCE(prox, now())-created_at))/3600)::numeric,1) AS horas_acumuladas
FROM seq GROUP BY 1,2 ORDER BY 1,2;
\echo === c10b: episodios de sessao ===
WITH ex AS (
  SELECT e.created_at, st.name,
         CASE WHEN e.message ILIKE '%RECONECTADO%' THEN 'viva'
              WHEN e.message ILIKE '%SSO expirou%' OR e.message ILIKE '%RE-CAPTURA%' THEN 'morta'
              WHEN e.message ILIKE '%sem sessao govbr%' THEN 'sem_sessao' ELSE 'outro' END AS estado
  FROM scheduled_task_executions e JOIN scheduled_tasks st ON st.id=e.scheduled_task_id JOIN applications a ON a.id=st.application_id
  WHERE a.uuid='s49c3b58lysqq0tpelneg3g3' AND st.name ILIKE '%govbr%' AND e.created_at >= now() - interval '30 days'),
t AS (SELECT created_at, name, estado, lag(estado) OVER (PARTITION BY name ORDER BY created_at) AS prev FROM ex),
ep AS (SELECT created_at, name, estado, lead(created_at) OVER (PARTITION BY name ORDER BY created_at) AS fim FROM t WHERE estado IS DISTINCT FROM prev)
SELECT name, to_char(created_at - interval '3 hours','MM-DD HH24:MI') AS inicio_brt, estado,
       round((EXTRACT(epoch FROM COALESCE(fim,now())-created_at)/3600)::numeric,1) AS horas FROM ep ORDER BY name, created_at;
\echo === c10c: auth status da rodada diaria transferegov ===
SELECT to_char(e.created_at - interval '3 hours','MM-DD HH24:MI') AS inicio_brt, e.status,
       substring(e.message FROM 'auth status: [^\n]{0,80}') AS auth_status,
       (e.message ILIKE '%pulando auth%') AS pulou_auth, (e.message ILIKE '%sem sessao gov.br valida%') AS guest_only,
       (e.message ILIKE '%contexto AUTH criado%') AS auth_criado,
       (e.message ILIKE '%enrich via HTTP%') AS http_enrich,
       (e.message ILIKE '%SKIP_ENRICH%' OR e.message ILIKE '%pulando enrich%' OR e.message ILIKE '%sem enrich%') AS skip_enrich
FROM scheduled_task_executions e JOIN scheduled_tasks st ON st.id=e.scheduled_task_id JOIN applications a ON a.id=st.application_id
WHERE a.uuid='s49c3b58lysqq0tpelneg3g3' AND st.name ILIKE '%transferegov%' AND e.created_at >= now() - interval '30 days'
ORDER BY e.created_at DESC LIMIT 80;
\echo === c10d: mensagens (flatten) das tasks de interesse — 30d ===
SELECT e.id, to_char(e.created_at - interval '3 hours','YYYY-MM-DD HH24:MI') AS inicio_brt, st.name, e.status,
       COALESCE(e.duration, EXTRACT(epoch FROM e.updated_at-e.created_at))::int AS dur_s,
       regexp_replace(e.message, E'[\\r\\n]+', ' | ', 'g') AS msg
FROM scheduled_task_executions e JOIN scheduled_tasks st ON st.id=e.scheduled_task_id JOIN applications a ON a.id=st.application_id
WHERE a.uuid='s49c3b58lysqq0tpelneg3g3' AND (st.name ILIKE '%transferegov%' OR st.name ILIKE '%govbr%' OR st.name ILIKE '%keepalive%' OR st.name ILIKE '%sigcon%' OR st.name ILIKE '%cagec%' OR st.name ILIKE '%watchdog%')
  AND e.created_at >= now() - interval '30 days' ORDER BY e.created_at;
