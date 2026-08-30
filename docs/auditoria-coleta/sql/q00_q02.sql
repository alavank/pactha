\echo === Q00: ambiente ===
SELECT version();
SELECT current_setting('TimeZone') AS tz, now() AS agora_utc, now() AT TIME ZONE 'America/Sao_Paulo' AS agora_brt;
\echo === Q00: tamanhos ===
SELECT relname, n_live_tup, pg_size_pretty(pg_total_relation_size(relid)) AS tamanho
FROM pg_stat_user_tables
WHERE relname IN ('ingestion_log','transferegov_propostas','scraper_municipio_coleta','convenios_estadual',
                  'cagec_situacao','cauc_situacao','emendas_estaduais','municipios','cofre_senhas','rm_relatorios','audit_log') ORDER BY 1;
\echo === Q00: indices ===
SELECT tablename, indexname, indexdef FROM pg_indexes
WHERE tablename IN ('ingestion_log','transferegov_propostas','scraper_municipio_coleta','convenios_estadual') ORDER BY 1,2;
\echo === Q00: schema ===
\d ingestion_log
\d scraper_municipio_coleta
\d transferegov_propostas
\d municipios
\d convenios_estadual
\d cagec_situacao
\d cauc_situacao
\d emendas_estaduais
\d rm_relatorios
\d audit_log
\d simec_termos
SELECT column_name, data_type, character_maximum_length FROM information_schema.columns
WHERE table_name='cofre_senhas' AND column_name <> 'senha_hash' ORDER BY ordinal_position;
\echo === Q01: carteira ===
SELECT uf, active, count(*) AS n FROM municipios GROUP BY 1,2 ORDER BY 1,2;
SELECT id, nome, uf, ibge_code, (cnpj IS NOT NULL) AS tem_cnpj, (fns_code IS NOT NULL) AS tem_fns,
       row_number() OVER (ORDER BY nome) AS pos_alfa FROM municipios WHERE active ORDER BY nome;
SELECT id, nome, uf, ibge_code FROM municipios WHERE NOT active ORDER BY nome;
SELECT fonte, count(*) AS n, count(DISTINCT municipio_id) AS municipios FROM convenios_estadual GROUP BY 1 ORDER BY 1;
\echo === Q02: inventario ingestion_log ===
SELECT source, count(*) AS n,
       to_char(min(COALESCE(finished_at,started_at)) AT TIME ZONE 'America/Sao_Paulo','YYYY-MM-DD') AS primeira_brt,
       to_char(max(COALESCE(finished_at,started_at)) AT TIME ZONE 'America/Sao_Paulo','YYYY-MM-DD HH24:MI') AS ultima_brt
FROM ingestion_log GROUP BY 1 ORDER BY 1;
SELECT source, status, count(*) AS n FROM ingestion_log
WHERE COALESCE(finished_at,started_at) >= now() - interval '30 days' GROUP BY 1,2 ORDER BY 1,2;
SELECT source, count(*) AS n,
       count(*) FILTER (WHERE finished_at IS NULL) AS sem_finished,
       count(*) FILTER (WHERE status='running') AS running,
       round(avg(EXTRACT(epoch FROM finished_at-started_at))::numeric) AS dur_media_s,
       max(EXTRACT(epoch FROM finished_at-started_at)) AS dur_max_s
FROM ingestion_log WHERE COALESCE(finished_at,started_at) >= now() - interval '30 days' GROUP BY 1 ORDER BY 1;
