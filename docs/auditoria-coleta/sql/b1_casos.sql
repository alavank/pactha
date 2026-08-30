\echo === B1a: Araujos e IBGEs suspeitos ===
SELECT id, nome, ibge_code, uf, active, cnpj, fns_code FROM municipios WHERE nome ILIKE 'ara%' OR ibge_code IN ('3103900','3104502');
\echo === B1b: creche em todas as tabelas com objeto (Araujos id=1) ===
SELECT 'convenios_estadual' AS t, id, fonte, ano, left(situacao,40) AS situacao, dt_vigencia_atual, dt_vigencia_final, nr_sigcon, nr_proposta, left(objeto,140) AS objeto, to_char(updated_at,'MM-DD') AS upd
FROM convenios_estadual WHERE municipio_id=1 AND (objeto ILIKE '%creche%' OR objeto ILIKE '%CMEI%' OR objeto ILIKE '%infantil%') ORDER BY ano;
SELECT 'transferegov_propostas' AS t, id, numero_proposta, codigo_instrumento, left(situacao,50) AS situacao, dt_fim_vigencia, valor_global, left(objeto,140) AS objeto, to_char(detalhe_atualizado_em,'MM-DD') AS det, (obras IS NOT NULL) AS tem_obras
FROM transferegov_propostas WHERE municipio_id=1 AND (objeto ILIKE '%creche%' OR objeto ILIKE '%CMEI%' OR objeto ILIKE '%infantil%' OR objeto ILIKE '%escola%');
SELECT 'transferegov_pac' AS t, id, left(situacao,50) AS situacao, left(objeto,140) AS objeto FROM transferegov_pac WHERE municipio_id=1 AND (objeto ILIKE '%creche%' OR objeto ILIKE '%infantil%');
SELECT 'simec_termos' AS t, id, tipo_documento, tipo_objeto, quantidade_obra, dt_vigencia, valor_termo, to_char(updated_at,'MM-DD') AS upd FROM simec_termos WHERE municipio_id=1;
SELECT 'simec_par_liberacoes' AS t, count(*) AS n, max(dt_pgto) AS ult_pgto FROM simec_par_liberacoes WHERE municipio_id=1;
SELECT 'sismob_obras' AS t, count(*) AS n FROM sismob_obras WHERE municipio_id=1;
SELECT 'transferegov_te' AS t, count(*) AS n, string_agg(left(objeto,60), ' | ') AS objetos FROM transferegov_te WHERE municipio_id=1;
\echo === B1c: creche em QUALQUER municipio ativo (caso o relato seja de outro) ===
SELECT m.nome, 'convenios_estadual' AS t, c.ano, left(c.situacao,30) AS sit, left(c.objeto,100) AS objeto FROM convenios_estadual c JOIN municipios m ON m.id=c.municipio_id WHERE m.active AND c.objeto ILIKE '%creche%' ORDER BY 1 LIMIT 40;
SELECT m.nome, 'transferegov_propostas' AS t, p.numero_proposta, left(p.situacao,30) AS sit, left(p.objeto,100) AS objeto FROM transferegov_propostas p JOIN municipios m ON m.id=p.municipio_id WHERE m.active AND p.objeto ILIKE '%creche%' ORDER BY 1 LIMIT 40;
\echo === B2a: exportacoes do RM (14 dias) ===
SELECT to_char(created_at AT TIME ZONE 'America/Sao_Paulo','MM-DD HH24:MI') AS quando, user_email, municipio_id, details->>'variante' AS variante, details->>'formato' AS formato, left(details->>'arquivo',60) AS arquivo
FROM audit_log WHERE action='export.rm' AND created_at >= now()-interval '14 days' ORDER BY created_at DESC LIMIT 60;
SELECT details->>'variante' AS variante, count(*) FROM audit_log WHERE action='export.rm' GROUP BY 1 ORDER BY 2 DESC;
\echo === B2b: RMs existentes (todos) ===
SELECT r.id, m.nome, r.data_referencia, r.anos, r.fontes, r.estagio, r.status, to_char(r.created_at AT TIME ZONE 'America/Sao_Paulo','MM-DD HH24:MI') AS criado, to_char(r.updated_at AT TIME ZONE 'America/Sao_Paulo','MM-DD HH24:MI') AS atualizado,
       jsonb_array_length(r.conteudo->'partes') AS partes,
       (SELECT string_agg((p->>'ordem')||':'||left(p->>'titulo',28), ' ; ') FROM jsonb_array_elements(r.conteudo->'partes') p) AS titulos
FROM rm_relatorios r JOIN municipios m ON m.id=r.municipio_id ORDER BY r.updated_at DESC;
\echo === B2c: detalhe SIGCON lido por convenio (efeito do #319) ===
SELECT m.nome, count(*) AS n,
       count(*) FILTER (WHERE c.dt_assinatura IS NULL) AS sem_assin,
       count(*) FILTER (WHERE c.dt_vigencia_atual IS NULL AND c.dt_vigencia_final IS NULL) AS sem_vig,
       count(*) FILTER (WHERE c.valor_contrapartida IS NULL) AS sem_contrap,
       count(*) FILTER (WHERE c.raw_data ? 'responsaveis') AS com_resp,
       count(*) FILTER (WHERE c.raw_data ? 'prestacao_contas_status') AS com_pc,
       count(*) FILTER (WHERE c.raw_data ? 'detalhes' OR c.raw_data ? 'detalhe') AS com_detalhe_raw,
       to_char(max(c.updated_at) AT TIME ZONE 'America/Sao_Paulo','MM-DD HH24:MI') AS max_upd
FROM convenios_estadual c JOIN municipios m ON m.id=c.municipio_id WHERE c.fonte='SIGCON-MG' AND m.active GROUP BY 1 ORDER BY 2 DESC;
SELECT jsonb_object_keys(raw_data) AS k, count(*) FROM convenios_estadual WHERE municipio_id=1 AND fonte='SIGCON-MG' GROUP BY 1 ORDER BY 2 DESC LIMIT 40;
\echo === B2d: credenciais SIGCON por municipio ativo MG (sem coluna cifrada) ===
SELECT m.nome, count(cs.id) AS creds, string_agg(DISTINCT left(cs.sistema,25), ',') AS sistemas, to_char(max(cs.updated_at),'MM-DD') AS upd
FROM municipios m LEFT JOIN cofre_senhas cs ON cs.municipio_id=m.id AND (cs.sistema ILIKE 'SIGCON%' OR cs.automation_key='sigcon')
WHERE m.active AND upper(m.uf)='MG' GROUP BY 1 ORDER BY creds, 1;
\echo === B2e: convenios_estadual SIGCON por municipio ativo (tem dado?) ===
SELECT m.nome, count(c.id) FILTER (WHERE c.fonte='SIGCON-MG') AS sigcon, count(c.id) FILTER (WHERE c.fonte='FNS') AS fns, (SELECT count(*) FROM emendas_estaduais e WHERE e.municipio_id=m.id) AS emendas
FROM municipios m LEFT JOIN convenios_estadual c ON c.municipio_id=m.id WHERE m.active GROUP BY m.id, m.nome ORDER BY sigcon, m.nome;
