\echo === Q06a: transferegov status 30d ===
SELECT source, status, count(*) AS n,
       min(records_inserted) AS min_ins, round(avg(records_inserted)) AS avg_ins, max(records_inserted) AS max_ins,
       sum(records_processed) AS municipios_tentados,
       count(*) FILTER (WHERE COALESCE(records_processed,0)=0) AS rodadas_sem_municipio
FROM ingestion_log
WHERE source IN ('transferegov_voluntarias','transferegov_lote','transferegov_opendata','transferegov_pac')
  AND COALESCE(finished_at,started_at) >= now() - interval '30 days'
GROUP BY 1,2 ORDER BY 1,2;
\echo === Q06b: classes de error_message ===
SELECT source, status,
       CASE WHEN error_message IS NULL THEN '(sem mensagem)'
            WHEN error_message ILIKE '%com erro%' AND error_message ILIKE '%paginacao incompleta%' THEN 'erro municipio + paginacao incompleta'
            WHEN error_message ILIKE '%paginacao incompleta%' THEN 'paginacao incompleta'
            WHEN error_message ILIKE '%municipio(s) com erro%' THEN 'municipio com erro'
            WHEN error_message ILIKE '%guarda de completude%' THEN 'guarda de completude (opendata abortou sem gravar)'
            WHEN error_message ILIKE '%orcamento%' THEN 'orcamento'
            ELSE 'outro' END AS classe,
       count(*) AS n, min(left(regexp_replace(error_message,'\s+',' ','g'),200)) AS exemplo
FROM ingestion_log
WHERE source IN ('transferegov_voluntarias','transferegov_lote','transferegov_opendata','transferegov_pac')
  AND COALESCE(finished_at,started_at) >= now() - interval '30 days'
GROUP BY 1,2,3 ORDER BY 1,2,4 DESC;
\echo === Q06c: municipios com erro ===
SELECT source, trim(nome) AS municipio, count(*) AS vezes
FROM ingestion_log, LATERAL regexp_split_to_table(substring(error_message FROM 'com erro: ([^;]+)'), ',') AS nome
WHERE source IN ('transferegov_voluntarias','transferegov_lote')
  AND COALESCE(finished_at,started_at) >= now() - interval '30 days' AND error_message ILIKE '%com erro%'
GROUP BY 1,2 ORDER BY 3 DESC, 2;
\echo === Q06d: por dia ===
SELECT to_char(date_trunc('day', COALESCE(finished_at,started_at) AT TIME ZONE 'America/Sao_Paulo'),'YYYY-MM-DD') AS dia_brt,
       count(*) FILTER (WHERE source='transferegov_lote') AS lote,
       count(*) FILTER (WHERE source='transferegov_lote' AND status='success') AS lote_ok,
       count(*) FILTER (WHERE source='transferegov_lote' AND status='success' AND COALESCE(records_processed,0)=0) AS lote_sucesso_vazio,
       sum(records_processed) FILTER (WHERE source='transferegov_lote') AS lote_municipios,
       sum(records_inserted)  FILTER (WHERE source='transferegov_lote') AS lote_propostas,
       count(*) FILTER (WHERE source='transferegov_voluntarias') AS diario,
       string_agg(status, ',') FILTER (WHERE source='transferegov_voluntarias') AS diario_status,
       count(*) FILTER (WHERE source='transferegov_opendata') AS opendata,
       string_agg(status, ',') FILTER (WHERE source='transferegov_opendata') AS opendata_status
FROM ingestion_log
WHERE source IN ('transferegov_voluntarias','transferegov_lote','transferegov_opendata')
  AND COALESCE(finished_at,started_at) >= now() - interval '30 days'
GROUP BY 1 ORDER BY 1;
\echo === Q06e: rodizio TG orcamento esgotado ===
SELECT m.nome, sc.tentativas,
       to_char(sc.ultima_coleta_em AT TIME ZONE 'America/Sao_Paulo','MM-DD HH24:MI') AS ultima_brt,
       left(sc.ultimo_erro,160) AS ultimo_erro
FROM scraper_municipio_coleta sc JOIN municipios m ON m.id=sc.municipio_id
WHERE sc.fonte='transferegov' AND sc.ultimo_erro ILIKE 'parcial: orcamento%'
ORDER BY sc.tentativas DESC, m.nome;
\echo === ultimas 40 linhas do log ===
SELECT id, source, status, records_processed AS proc, records_inserted AS ins, records_updated AS upd,
       to_char(COALESCE(finished_at,started_at) AT TIME ZONE 'America/Sao_Paulo','MM-DD HH24:MI') AS fim_brt,
       left(regexp_replace(error_message,'\s+',' ','g'),140) AS msg
FROM ingestion_log ORDER BY id DESC LIMIT 40;
