\echo === Q08a: municipio ativo x fonte (scraper_municipio_coleta), piores primeiro ===
WITH m AS (SELECT id, nome, row_number() OVER (ORDER BY nome) AS pos_alfa FROM municipios WHERE active)
SELECT m.pos_alfa, m.nome, f.fonte,
       to_char(sc.ultima_coleta_em AT TIME ZONE 'America/Sao_Paulo','MM-DD HH24:MI') AS ultima_coleta_brt,
       round((EXTRACT(epoch FROM now()-sc.ultima_coleta_em)/86400)::numeric,1) AS dias_desde_carimbo,
       sc.tentativas,
       to_char(sc.ultimo_erro_em AT TIME ZONE 'America/Sao_Paulo','MM-DD HH24:MI') AS ultimo_erro_brt,
       CASE WHEN sc.municipio_id IS NULL THEN 'NUNCA' WHEN COALESCE(sc.tentativas,0)=0 THEN 'bom' ELSE 'carimbo-em-erro' END AS qualidade,
       sc.detalhe_pagina, left(regexp_replace(sc.ultimo_erro,'\s+',' ','g'),160) AS ultimo_erro
FROM m CROSS JOIN (VALUES ('sigcon'),('sigcon_emendas'),('cagec'),('transferegov'),('simec_termos')) AS f(fonte)
LEFT JOIN scraper_municipio_coleta sc ON sc.municipio_id=m.id AND sc.fonte=f.fonte
ORDER BY f.fonte, (sc.municipio_id IS NULL) DESC, COALESCE(sc.tentativas,0) DESC, sc.ultima_coleta_em ASC NULLS FIRST, m.nome;
\echo === Q08b: resumo por fonte vs STALENESS_MUNICIPIO_H ===
WITH m AS (SELECT id FROM municipios WHERE active), lim(fonte, h) AS (VALUES ('sigcon',48),('transferegov',36),('cagec',48))
SELECT f.fonte, lim.h AS teto_h, count(*) AS ativos, count(sc.municipio_id) AS com_linha,
       count(*) FILTER (WHERE COALESCE(sc.tentativas,0)=0 AND sc.ultima_coleta_em IS NOT NULL) AS bons,
       count(*) FILTER (WHERE COALESCE(sc.tentativas,0)>0) AS em_erro,
       count(*) FILTER (WHERE sc.municipio_id IS NULL) AS nunca,
       count(*) FILTER (WHERE sc.tentativas=0 AND sc.ultima_coleta_em < now()-make_interval(hours=>lim.h)) AS bons_mas_velhos,
       round((EXTRACT(epoch FROM percentile_cont(0.5) WITHIN GROUP (ORDER BY now()-sc.ultima_coleta_em))/3600)::numeric,1) AS med_h,
       round((EXTRACT(epoch FROM max(now()-sc.ultima_coleta_em))/3600)::numeric,1) AS max_h
FROM m CROSS JOIN (VALUES ('sigcon'),('sigcon_emendas'),('cagec'),('transferegov'),('simec_termos')) AS f(fonte)
LEFT JOIN lim ON lim.fonte=f.fonte
LEFT JOIN scraper_municipio_coleta sc ON sc.municipio_id=m.id AND sc.fonte=f.fonte
GROUP BY 1,2 ORDER BY 1;
\echo === Q08c: semantica empirica do carimbo ===
SELECT fonte, count(*) AS n,
       count(*) FILTER (WHERE ultimo_erro_em > ultima_coleta_em) AS erro_apos_carimbo,
       count(*) FILTER (WHERE tentativas>0 AND ultimo_erro_em = ultima_coleta_em) AS carimbo_no_erro,
       count(*) FILTER (WHERE ultima_coleta_em IS NULL) AS sem_carimbo
FROM scraper_municipio_coleta GROUP BY 1 ORDER BY 1;
\echo === Q08d: terco alfabetico x atraso ===
WITH m AS (SELECT id, nome, row_number() OVER (ORDER BY nome) AS pos_alfa, ntile(3) OVER (ORDER BY nome) AS terco FROM municipios WHERE active)
SELECT sc.fonte, m.terco, count(*) AS n,
       round(avg(EXTRACT(epoch FROM now()-sc.ultima_coleta_em)/86400)::numeric,2) AS media_dias,
       round(max(EXTRACT(epoch FROM now()-sc.ultima_coleta_em)/86400)::numeric,2) AS max_dias,
       round(avg(sc.tentativas)::numeric,2) AS media_tentativas
FROM m JOIN scraper_municipio_coleta sc ON sc.municipio_id=m.id GROUP BY 1,2 ORDER BY 1,2;
SELECT sc.fonte, round(corr(m.pos_alfa::float8, (EXTRACT(epoch FROM now()-sc.ultima_coleta_em)/86400)::float8)::numeric,2) AS corr_pos_x_dias,
       round(corr(m.pos_alfa::float8, sc.tentativas::float8)::numeric,2) AS corr_pos_x_tentativas
FROM (SELECT id, row_number() OVER (ORDER BY nome) AS pos_alfa FROM municipios WHERE active) m
JOIN scraper_municipio_coleta sc ON sc.municipio_id=m.id GROUP BY 1 ORDER BY 1;
\echo === Q09a: carimbos das tabelas de dados por municipio ativo ===
WITH m AS (SELECT id, nome, uf, row_number() OVER (ORDER BY nome) AS pos_alfa FROM municipios WHERE active),
tg AS (SELECT municipio_id, count(*) AS n_prop, max(updated_at) AS upd, max(detalhe_atualizado_em) AS det,
              max(historico_atualizado_em) AS hist, max(ops_obs_atualizado_em) AS ops FROM transferegov_propostas GROUP BY 1),
ce AS (SELECT municipio_id,
              count(*) FILTER (WHERE fonte='SIGCON-MG') AS n_sigcon, max(updated_at) FILTER (WHERE fonte='SIGCON-MG') AS upd_sigcon,
              count(*) FILTER (WHERE fonte='FNS') AS n_fns, max(updated_at) FILTER (WHERE fonte='FNS') AS upd_fns
       FROM convenios_estadual GROUP BY 1),
ee AS (SELECT municipio_id, count(*) AS n, max(updated_at) AS upd FROM emendas_estaduais GROUP BY 1),
cg AS (SELECT municipio_id, max(atualizado_em) AS atualizado_em, max(data_pesquisa) AS data_pesquisa, bool_and(regular) AS regular FROM cagec_situacao GROUP BY 1)
SELECT m.pos_alfa, m.nome, tg.n_prop,
       round((EXTRACT(epoch FROM now()-tg.upd)/86400)::numeric,1)  AS d_tg_upd,
       round((EXTRACT(epoch FROM now()-tg.det)/86400)::numeric,1)  AS d_tg_det,
       round((EXTRACT(epoch FROM now()-tg.hist)/86400)::numeric,1) AS d_tg_hist,
       round((EXTRACT(epoch FROM now()-tg.ops)/86400)::numeric,1)  AS d_tg_ops,
       ce.n_sigcon, round((EXTRACT(epoch FROM now()-ce.upd_sigcon)/86400)::numeric,1) AS d_sigcon,
       ce.n_fns, round((EXTRACT(epoch FROM now()-ce.upd_fns)/86400)::numeric,1) AS d_fns,
       round((EXTRACT(epoch FROM now()-cg.atualizado_em)/86400)::numeric,1) AS d_cagec, cg.data_pesquisa AS cagec_pesq, cg.regular AS cagec_reg,
       round((EXTRACT(epoch FROM now()-ca.atualizado_em)/86400)::numeric,1) AS d_cauc, ca.data_pesquisa AS cauc_pesq,
       ee.n AS n_em_est, round((EXTRACT(epoch FROM now()-ee.upd)/86400)::numeric,1) AS d_em_est
FROM m LEFT JOIN tg ON tg.municipio_id=m.id LEFT JOIN ce ON ce.municipio_id=m.id
LEFT JOIN cg ON cg.municipio_id=m.id LEFT JOIN cauc_situacao ca ON ca.municipio_id=m.id LEFT JOIN ee ON ee.municipio_id=m.id
ORDER BY m.pos_alfa;
\echo === Q09c: terco alfabetico x idade do detalhe/historico ===
SELECT terco, count(*) AS n, round(avg(d_det)::numeric,1) AS media_d_det, round(max(d_det)::numeric,1) AS max_d_det,
       round(avg(d_hist)::numeric,1) AS media_d_hist, count(*) FILTER (WHERE d_det IS NULL) AS sem_detalhe
FROM (SELECT m.terco, EXTRACT(epoch FROM now()-max(p.detalhe_atualizado_em))/86400 AS d_det,
             EXTRACT(epoch FROM now()-max(p.historico_atualizado_em))/86400 AS d_hist
      FROM (SELECT id, ntile(3) OVER (ORDER BY nome) AS terco FROM municipios WHERE active) m
      LEFT JOIN transferegov_propostas p ON p.municipio_id=m.id GROUP BY m.id, m.terco) x
GROUP BY 1 ORDER BY 1;
SELECT round(corr(pos_alfa::float8, d_det::float8)::numeric,2) AS corr_pos_x_dias_detalhe
FROM (SELECT m.pos_alfa, EXTRACT(epoch FROM now()-max(p.detalhe_atualizado_em))/86400 AS d_det
      FROM (SELECT id, row_number() OVER (ORDER BY nome) AS pos_alfa FROM municipios WHERE active) m
      JOIN transferegov_propostas p ON p.municipio_id=m.id GROUP BY 1) t;
\echo === Q10: sessoes gov.br no Cofre (sem coluna cifrada) ===
SELECT id, municipio_id, sistema, automation_key, categoria, length(senha_hash) AS len_cifrado,
       to_char(created_at AT TIME ZONE 'America/Sao_Paulo','YYYY-MM-DD HH24:MI') AS criado_brt,
       to_char(updated_at AT TIME ZONE 'America/Sao_Paulo','YYYY-MM-DD HH24:MI') AS atualizado_brt,
       round((EXTRACT(epoch FROM now()-updated_at)/3600)::numeric,1) AS h_desde_update, left(observacao,200) AS observacao
FROM cofre_senhas WHERE length(senha_hash) > 1000 OR automation_key IN ('govbr','siconv_legado') ORDER BY updated_at DESC;
\echo === Q10b: credenciais por automation_key/sistema (contagem) ===
SELECT automation_key, left(sistema,40) AS sistema, count(*) AS n, count(DISTINCT municipio_id) AS municipios FROM cofre_senhas GROUP BY 1,2 ORDER BY 1,2;
\echo === Q11a: por municipio ativo — carimbos de detalhe/historico/ops ===
SELECT m.nome, count(p.id) AS n,
       count(*) FILTER (WHERE p.codigo_instrumento IS NOT NULL) AS com_instr,
       count(*) FILTER (WHERE p.detalhe_atualizado_em IS NULL) AS det_null,
       round((EXTRACT(epoch FROM percentile_cont(0.5) WITHIN GROUP (ORDER BY now()-p.detalhe_atualizado_em))/86400)::numeric,1) AS det_med_dias,
       count(*) FILTER (WHERE p.detalhe IS NOT NULL AND p.detalhe_atualizado_em IS NULL) AS det_valor_sem_carimbo,
       count(*) FILTER (WHERE p.historico_comunicacoes IS NOT NULL) AS hist_com_valor,
       count(*) FILTER (WHERE p.historico_comunicacoes IS NOT NULL AND p.historico_atualizado_em IS NULL) AS hist_valor_sem_carimbo,
       count(*) FILTER (WHERE p.historico_comunicacoes IS NOT NULL AND p.historico_atualizado_em < now()-interval '30 days') AS hist_valor_velho_30d,
       round((EXTRACT(epoch FROM percentile_cont(0.5) WITHIN GROUP (ORDER BY now()-p.historico_atualizado_em))/86400)::numeric,1) AS hist_med_dias,
       count(*) FILTER (WHERE p.ops_obs_atualizado_em IS NULL) AS ops_null,
       count(*) FILTER (WHERE p.clausula_suspensiva_motivo IS NOT NULL) AS com_clausula,
       count(*) FILTER (WHERE p.situacao_contratacao_detalhe IS NOT NULL) AS com_claus_det,
       count(*) FILTER (WHERE p.projeto_basico IS NOT NULL) AS com_pb,
       count(*) FILTER (WHERE p.notas_empenho IS NOT NULL) AS com_ne,
       count(*) FILTER (WHERE p.parlamentar IS NOT NULL) AS com_parl,
       to_char(max(p.updated_at) AT TIME ZONE 'America/Sao_Paulo','MM-DD HH24:MI') AS max_upd_brt
FROM municipios m LEFT JOIN transferegov_propostas p ON p.municipio_id=m.id
WHERE m.active GROUP BY m.nome ORDER BY n DESC NULLS LAST;
\echo === Q11b: histograma de idade dos carimbos (carteira ativa) ===
SELECT c.carimbo, CASE WHEN c.ts IS NULL THEN '0 NULL' WHEN c.ts >= now()-interval '1 day' THEN '1 <1d'
       WHEN c.ts >= now()-interval '7 days' THEN '2 1-7d' WHEN c.ts >= now()-interval '30 days' THEN '3 7-30d' ELSE '4 >30d' END AS faixa, count(*)
FROM transferegov_propostas p JOIN municipios m ON m.id=p.municipio_id AND m.active
CROSS JOIN LATERAL (VALUES ('detalhe',p.detalhe_atualizado_em),('historico',p.historico_atualizado_em),('ops_obs',p.ops_obs_atualizado_em)) AS c(carimbo, ts)
GROUP BY 1,2 ORDER BY 1,2;
\echo === Q11c: propostas vivas com detalhe >30d ou nunca lido (top 60) ===
SELECT m.nome, p.numero_proposta, left(p.situacao,50) AS situacao, p.codigo_instrumento,
       round((EXTRACT(epoch FROM now()-p.detalhe_atualizado_em)/86400)::numeric) AS d_det,
       round((EXTRACT(epoch FROM now()-p.historico_atualizado_em)/86400)::numeric) AS d_hist,
       (p.historico_comunicacoes IS NOT NULL) AS tem_hist, to_char(p.updated_at AT TIME ZONE 'America/Sao_Paulo','MM-DD') AS upd
FROM transferegov_propostas p JOIN municipios m ON m.id=p.municipio_id AND m.active
WHERE (p.situacao ILIKE '%execu%' OR p.situacao ILIKE '%an_lise%' OR p.situacao ILIKE '%aprovad%')
  AND (p.detalhe_atualizado_em IS NULL OR p.detalhe_atualizado_em < now()-interval '30 days')
ORDER BY p.detalhe_atualizado_em NULLS FIRST, m.nome LIMIT 60;
SELECT count(*) AS vivas_det_velho_ou_nulo FROM transferegov_propostas p JOIN municipios m ON m.id=p.municipio_id AND m.active
WHERE (p.situacao ILIKE '%execu%' OR p.situacao ILIKE '%an_lise%' OR p.situacao ILIKE '%aprovad%')
  AND (p.detalhe_atualizado_em IS NULL OR p.detalhe_atualizado_em < now()-interval '30 days');
\echo === Q11d: propostas em municipios inativos ===
SELECT m.active, count(*) AS propostas, count(DISTINCT p.municipio_id) AS municipios FROM transferegov_propostas p JOIN municipios m ON m.id=p.municipio_id GROUP BY 1;
\echo === Q12: candidatos a reconciliacao ===
WITH m AS (SELECT id, nome, ibge_code, row_number() OVER (ORDER BY nome) AS pos_alfa, count(*) OVER () AS n_at FROM municipios WHERE active),
sc AS (SELECT municipio_id, max(CASE WHEN fonte='transferegov' THEN tentativas END) AS tg_tent,
              max(CASE WHEN fonte='transferegov' THEN EXTRACT(epoch FROM now()-ultima_coleta_em)/86400 END) AS tg_dias,
              max(CASE WHEN fonte='sigcon' THEN tentativas END) AS sig_tent,
              max(CASE WHEN fonte='sigcon' THEN EXTRACT(epoch FROM now()-ultima_coleta_em)/86400 END) AS sig_dias
       FROM scraper_municipio_coleta GROUP BY 1),
tg AS (SELECT municipio_id, count(*) AS n_prop, count(*) FILTER (WHERE detalhe_atualizado_em IS NULL) AS det_null,
              EXTRACT(epoch FROM percentile_cont(0.5) WITHIN GROUP (ORDER BY now()-detalhe_atualizado_em))/86400 AS det_med_dias
       FROM transferegov_propostas GROUP BY 1)
SELECT m.pos_alfa, m.nome, m.ibge_code, tg.n_prop, tg.det_null, sc.tg_tent, round(sc.tg_dias::numeric,1) AS tg_dias,
       round(tg.det_med_dias::numeric,1) AS det_med_dias, sc.sig_tent, round(sc.sig_dias::numeric,1) AS sig_dias,
       concat_ws(',', CASE WHEN m.pos_alfa = m.n_at THEN 'FIM-ALFABETO' END,
                      CASE WHEN tg.n_prop = max(tg.n_prop) OVER () THEN 'MAIS-PESADO' END,
                      CASE WHEN m.nome ILIKE 'bom despacho%' THEN 'BOM-DESPACHO' END) AS marcas,
       row_number() OVER (ORDER BY COALESCE(sc.tg_tent,0) DESC, COALESCE(tg.det_med_dias,9999) DESC, COALESCE(sc.tg_dias,9999) DESC) AS rank_pior
FROM m LEFT JOIN sc ON sc.municipio_id=m.id LEFT JOIN tg ON tg.municipio_id=m.id ORDER BY rank_pior;
