\echo === RM: chaves do JSON ===
SELECT id, (SELECT string_agg(k, ',') FROM jsonb_object_keys(conteudo->'partes'->0) k) AS chaves_parte FROM rm_relatorios WHERE id IN (51,95) ;
SELECT id, (SELECT string_agg(k, ',') FROM jsonb_object_keys(conteudo->'partes'->0->'secoes'->0) k) AS chaves_secao FROM rm_relatorios WHERE id IN (51,95);
SELECT id, (SELECT string_agg(k, ',') FROM jsonb_object_keys(conteudo->'partes'->0->'secoes'->0->'grupos'->0) k) AS chaves_grupo FROM rm_relatorios WHERE id IN (51,95);
SELECT id, (SELECT string_agg(k, ',') FROM jsonb_object_keys(conteudo->'partes'->0->'secoes'->0->'grupos'->0->'itens'->0) k) AS chaves_item FROM rm_relatorios WHERE id IN (51,95);
\echo === RM: itens por parte/secao/fonte (Araujos 51 e 95, Nova Serrana 50, Araujos 90) ===
SELECT r.id, p->>'ordem' AS parte, left(s->>'titulo',45) AS secao, i->>'fonte' AS fonte, count(*) AS itens
FROM rm_relatorios r, jsonb_array_elements(r.conteudo->'partes') p, jsonb_array_elements(p->'secoes') s, jsonb_array_elements(s->'grupos') g, jsonb_array_elements(g->'itens') i
WHERE r.id IN (51,95,50,90) GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;
\echo === RM 51 (Araujos, todas as fontes): itens estaduais e a creche ===
SELECT p->>'ordem' AS parte, i->>'fonte' AS fonte, left(i->>'numero',22) AS numero, left(i->>'objeto',80) AS objeto, i->>'status' AS status, i->>'ano' AS ano
FROM rm_relatorios r, jsonb_array_elements(r.conteudo->'partes') p, jsonb_array_elements(p->'secoes') s, jsonb_array_elements(s->'grupos') g, jsonb_array_elements(g->'itens') i
WHERE r.id=51 AND (i->>'fonte' IN ('sigcon','emenda_estadual','simec_termo','simec') OR i->>'objeto' ILIKE '%creche%' OR i->>'numero' ILIKE '%059522%' OR i->>'numero' ILIKE '%932836%')
ORDER BY 1,2,3;
\echo === RM 51: contagem total de itens por fonte ===
SELECT i->>'fonte' AS fonte, count(*) FROM rm_relatorios r, jsonb_array_elements(r.conteudo->'partes') p, jsonb_array_elements(p->'secoes') s, jsonb_array_elements(s->'grupos') g, jsonb_array_elements(g->'itens') i WHERE r.id=51 GROUP BY 1 ORDER BY 2 DESC;
\echo === Araujos: convenios SIGCON no banco vs no RM 51 ===
SELECT c.nr_sigcon, c.nr_proposta, c.ano, left(c.situacao,30) AS situacao, c.dt_vigencia_atual, c.dt_vigencia_final, c.valor_total, left(c.objeto,60) AS objeto
FROM convenios_estadual c WHERE c.municipio_id=1 AND c.fonte='SIGCON-MG' ORDER BY c.ano, c.nr_sigcon;
\echo === Araujos: emendas estaduais no banco ===
SELECT nr_indicacao, ano, left(nome_responsavel,25) AS resp, left(beneficiario,30) AS benef, left(tipo_atendimento,40) AS tipo, valor_indicacao, status_indicacao FROM emendas_estaduais WHERE municipio_id=1 ORDER BY ano, nr_indicacao;
