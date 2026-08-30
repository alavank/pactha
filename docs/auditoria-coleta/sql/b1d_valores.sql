\echo === detalhe jsonb (rotulos originais) de 2 propostas divergentes ===
SELECT numero_proposta, valor_global, valor_repasse, valor_contrapartida, modalidade, to_char(detalhe_atualizado_em,'MM-DD HH24:MI') AS det_em,
       (SELECT string_agg(k||'='||left(detalhe->>k,40), ' ; ') FROM jsonb_object_keys(detalhe) k WHERE k ILIKE '%valor%' OR k ILIKE '%repasse%' OR k ILIKE '%contrapartida%' OR k ILIKE '%global%') AS campos_valor
FROM transferegov_propostas WHERE municipio_id=1 AND numero_proposta IN ('059522/2021','000002/2016','010215/2016');
\echo === padrao na carteira ativa: global == repasse+contrapartida? ===
SELECT CASE WHEN valor_global IS NULL OR valor_repasse IS NULL THEN 'nulo'
            WHEN abs(valor_global - (valor_repasse+COALESCE(valor_contrapartida,0))) < 0.05 THEN 'consistente (global=repasse+contrap)'
            WHEN abs(valor_repasse - COALESCE(valor_contrapartida,0)) < 0.05 AND valor_contrapartida > 0 THEN 'REPASSE==CONTRAPARTIDA (deslocado)'
            ELSE 'outro' END AS padrao, count(*) AS n, count(DISTINCT p.municipio_id) AS municipios,
       count(*) FILTER (WHERE p.modalidade ILIKE 'Termo%') AS termos, count(*) FILTER (WHERE p.modalidade ILIKE 'Conv%') AS convenios, count(*) FILTER (WHERE p.codigo_instrumento IS NOT NULL) AS com_instr
FROM transferegov_propostas p JOIN municipios m ON m.id=p.municipio_id AND m.active GROUP BY 1 ORDER BY 2 DESC;
\echo === deslocados: por hora do detalhe (quem escreveu por ultimo) ===
SELECT to_char(detalhe_atualizado_em,'MM-DD HH24') AS det_hora, count(*) FILTER (WHERE abs(valor_repasse - COALESCE(valor_contrapartida,0)) < 0.05 AND valor_contrapartida > 0) AS deslocados, count(*) AS total
FROM transferegov_propostas p JOIN municipios m ON m.id=p.municipio_id AND m.active GROUP BY 1 ORDER BY 1 DESC LIMIT 14;
\echo === RM 51: valores do item 932836 e de mais 3 ===
SELECT i->>'numero' AS numero, i->>'valor_global' AS vg, i->>'valor_repasse' AS vr, i->>'valor_contrapartida' AS vc, i->>'valor_a_desembolsar' AS a_desemb
FROM rm_relatorios r, jsonb_array_elements(r.conteudo->'partes') p, jsonb_array_elements(p->'secoes') s, jsonb_array_elements(s->'grupos') g, jsonb_array_elements(g->'itens') i
WHERE r.id=51 AND i->>'fonte'='voluntaria' ORDER BY (i->>'numero') LIMIT 6;
\echo === status_changes recentes para propostas de Araujos (o que a trigger viu) ===
SELECT to_char(changed_at,'MM-DD HH24:MI') AS quando, ref, left(status_anterior,40) AS de, left(status_novo,40) AS para FROM status_changes WHERE municipio_id=1 AND tabela='transferegov_propostas' ORDER BY changed_at DESC LIMIT 8;
