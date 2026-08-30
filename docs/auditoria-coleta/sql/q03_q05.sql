\echo === Q03: frescor por fonte vs catalogo ===
WITH cat(source, horas, uf) AS (VALUES
  ('transferegov_opendata',30,NULL),('transferegov_voluntarias',30,NULL),('transferegov_pac',30,NULL),
  ('fns',30,NULL),('cauc',12,NULL),('acordofes',12,NULL),('simec_par',12,NULL),('simec_termos',30,NULL),
  ('siconv_convenio_backfill',30,NULL),('sismob',30,NULL),('transferegov_lote',6,NULL),
  ('sigcon_scraper',18,'MG'),('cagec',30,'MG'),('acordofes',12,'MG'),
  ('gconv_es',30,'ES'),('transfvol_go',30,'GO'),('cofin_ses_go',30,'GO'),('tcm_go',30,'GO'),
  ('che_rs',30,'RS'),('convenios_rs',30,'RS'),('fpe_rs',54,'RS'),('consulta_popular_rs',192,'RS')),
ufs AS (SELECT DISTINCT upper(uf) AS uf FROM municipios WHERE active AND uf IS NOT NULL),
cat_t AS (SELECT source, min(horas) AS horas FROM cat WHERE uf IS NULL OR uf IN (SELECT uf FROM ufs) GROUP BY 1),
lg AS (SELECT source, status, COALESCE(finished_at,started_at) AS ts, records_processed, records_inserted, error_message FROM ingestion_log),
ult AS (SELECT DISTINCT ON (source) source, ts AS ultima_ts, status AS ultimo_status, records_processed AS ult_proc,
               records_inserted AS ult_ins, left(regexp_replace(error_message,'\s+',' ','g'),120) AS ult_msg
        FROM lg ORDER BY source, ts DESC),
suc AS (SELECT source, max(ts) FILTER (WHERE status IN ('success','ok')) AS ultimo_sucesso,
               max(ts) FILTER (WHERE status IN ('success','ok','partial','parcial')) AS ultimo_sucesso_ou_parcial
        FROM lg GROUP BY 1),
n30 AS (SELECT source,
               count(*) FILTER (WHERE status IN ('success','ok')) AS ok30,
               count(*) FILTER (WHERE status IN ('partial','parcial')) AS parcial30,
               count(*) FILTER (WHERE status IN ('error','erro','failed')) AS erro30,
               count(*) FILTER (WHERE status NOT IN ('success','ok','partial','parcial','error','erro','failed')) AS outro30,
               count(*) AS total30
        FROM lg WHERE ts >= now() - interval '30 days' GROUP BY 1)
SELECT s.source, c.horas AS frescor_h,
       to_char(suc.ultimo_sucesso AT TIME ZONE 'America/Sao_Paulo','MM-DD HH24:MI') AS ult_sucesso_brt,
       round((EXTRACT(epoch FROM now()-suc.ultimo_sucesso)/3600)::numeric,1) AS h_desde_sucesso,
       CASE WHEN c.horas IS NULL THEN 'sem-catalogo'
            WHEN suc.ultimo_sucesso IS NULL THEN 'NUNCA'
            WHEN now()-suc.ultimo_sucesso > make_interval(hours => c.horas) THEN 'SIM' ELSE 'nao' END AS atrasada,
       round((EXTRACT(epoch FROM now()-suc.ultimo_sucesso_ou_parcial)/3600)::numeric,1) AS h_desde_suc_ou_parcial,
       to_char(ult.ultima_ts AT TIME ZONE 'America/Sao_Paulo','MM-DD HH24:MI') AS ult_qualquer_brt,
       ult.ultimo_status, ult.ult_proc, ult.ult_ins,
       COALESCE(n30.ok30,0) AS ok30, COALESCE(n30.parcial30,0) AS parcial30, COALESCE(n30.erro30,0) AS erro30,
       COALESCE(n30.outro30,0) AS outro30, COALESCE(n30.total30,0) AS total30, ult.ult_msg
FROM (SELECT source FROM cat_t UNION SELECT source FROM ult) s
LEFT JOIN cat_t c USING (source) LEFT JOIN ult USING (source) LEFT JOIN suc USING (source) LEFT JOIN n30 USING (source)
ORDER BY (c.horas IS NULL), atrasada DESC, s.source;
\echo === Q04: serie diaria 30d ===
SELECT source,
       to_char(date_trunc('day', COALESCE(finished_at,started_at) AT TIME ZONE 'America/Sao_Paulo'),'YYYY-MM-DD') AS dia_brt,
       count(*) AS rodadas,
       count(*) FILTER (WHERE status IN ('success','ok')) AS ok,
       count(*) FILTER (WHERE status IN ('partial','parcial')) AS parcial,
       count(*) FILTER (WHERE status IN ('error','erro','failed')) AS erro,
       sum(COALESCE(records_processed,0)) AS processed,
       sum(COALESCE(records_inserted,0)+COALESCE(records_updated,0)) AS ins_upd,
       max(COALESCE(records_inserted,0)+COALESCE(records_updated,0)) AS ins_upd_max_rodada
FROM ingestion_log
WHERE COALESCE(finished_at,started_at) >= now() - interval '30 days'
GROUP BY 1,2 ORDER BY 1,2;
\echo === Q05: quedas >25% vs mediana das 5 anteriores ===
WITH r AS (
  SELECT id, source, COALESCE(finished_at,started_at) AS ts, status,
         COALESCE(records_inserted,0)+COALESCE(records_updated,0) AS n, records_processed AS proc
  FROM ingestion_log
  WHERE COALESCE(finished_at,started_at) >= now() - interval '45 days'
    AND status IN ('success','ok','partial','parcial')),
w AS (SELECT r.*, array_agg(n) OVER (PARTITION BY source ORDER BY ts, id ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS prev5 FROM r),
m AS (SELECT w.*, cardinality(prev5) AS n_prev,
             (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY t.x) FROM unnest(prev5) AS t(x)) AS med5 FROM w)
SELECT source, to_char(ts AT TIME ZONE 'America/Sao_Paulo','MM-DD HH24:MI') AS ts_brt, status, n, proc, n_prev,
       round(med5::numeric,1) AS med5,
       round((100*(1 - n/NULLIF(med5,0)))::numeric) AS queda_pct,
       CASE WHEN source IN ('transferegov_lote','sigcon_scraper','cagec') THEN 'RODIZIO: variacao esperada'
            ELSE 'comparavel' END AS regime
FROM m
WHERE ts >= now() - interval '30 days' AND n_prev >= 3 AND med5 > 0 AND n < 0.75*med5
ORDER BY source, ts;
