\echo === RM 51: item 932836 (creche) — campos ===
SELECT p->>'ordem' AS parte, i->>'numero' AS numero, i->>'situacao_atual' AS sit, i->>'situacao_contratacao' AS sit_contr, i->>'clausula_motivo' AS claus, left(i->>'projeto_basico',120) AS pb, left(i->>'obra',160) AS obra, left(i->>'nes',160) AS nes, i->>'valor_empenhado' AS empenhado, i->>'valor_desembolsado' AS desemb, i->>'processo_execucao_qtd' AS pe_qtd, left(i->>'processo_execucao_lista',160) AS pe_lista, i->>'parlamentar' AS parl
FROM rm_relatorios r, jsonb_array_elements(r.conteudo->'partes') p, jsonb_array_elements(p->'secoes') s, jsonb_array_elements(s->'grupos') g, jsonb_array_elements(g->'itens') i
WHERE r.id=51 AND (i->>'numero' ILIKE '%932836%' OR i->>'numero' ILIKE '%059522%' OR i->>'numero' ILIKE '%23400.002301%');
\echo === banco: proposta 059522/2021 de Araujos — o que esta preenchido ===
SELECT id, numero_proposta, codigo_instrumento, situacao, situacao_siafi, situacao_contratacao, clausula_suspensiva_dt_prevista, left(clausula_suspensiva_motivo,80) AS claus_motivo,
       (situacao_contratacao_detalhe IS NOT NULL) AS tem_claus_det, (projeto_basico IS NOT NULL) AS tem_pb, left(projeto_basico::text,200) AS pb,
       (notas_empenho IS NOT NULL) AS tem_ne, left(notas_empenho::text,160) AS ne, (ops_obs IS NOT NULL) AS tem_ops, left(ops_obs::text,160) AS ops, (obras IS NOT NULL) AS tem_obras,
       processo_execucao_qtd, left(processo_execucao::text,160) AS pe, (historico_comunicacoes IS NOT NULL) AS tem_hist, historico_atualizado_em, detalhe_atualizado_em, ops_obs_atualizado_em, updated_at, parlamentar, programa, valor_global, dt_fim_vigencia
FROM transferegov_propostas WHERE municipio_id=1 AND numero_proposta='059522/2021';
\echo === banco: simec_termos 6 raw ===
SELECT id, processo, nr_documento, tipo_documento, tipo_objeto, dt_validacao, periodo_pagamento, vigencia_txt, dt_vigencia, valor_termo, left(raw_data::text,300) AS raw FROM simec_termos WHERE id=6;
\echo === log de mudancas de status (trigger log_status_change) para a proposta 18 ===
SELECT table_name, column_name FROM information_schema.columns WHERE table_name ILIKE '%status_change%' OR table_name ILIKE '%status_log%' ORDER BY 1,2 LIMIT 30;
\echo === RMs de Araujos: quando cada um foi (re)populado vs #317 (29/08 10:49) e #319 (29/08 19:43) ===
SELECT id, to_char(created_at AT TIME ZONE 'America/Sao_Paulo','MM-DD HH24:MI') AS criado, to_char(updated_at AT TIME ZONE 'America/Sao_Paulo','MM-DD HH24:MI') AS atualizado, anos, fontes, estagio,
  (SELECT count(*) FROM jsonb_array_elements(conteudo->'partes') p, jsonb_array_elements(p->'secoes') s, jsonb_array_elements(s->'grupos') g, jsonb_array_elements(g->'itens') i WHERE i->>'numero' ILIKE '%932836%') AS tem_creche
FROM rm_relatorios WHERE municipio_id=1 ORDER BY updated_at DESC;
\echo === auditoria: acoes sobre RM de Araujos 27-29/08 (criacao/auto-popular/export) por usuario ===
SELECT to_char(created_at AT TIME ZONE 'America/Sao_Paulo','MM-DD HH24:MI') AS quando, user_email, action, target_id, left(details::text,120) AS det FROM audit_log WHERE municipio_id=1 AND action ILIKE '%rm%' AND created_at >= '2026-08-27' ORDER BY created_at;
