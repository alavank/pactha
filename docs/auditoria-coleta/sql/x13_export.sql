SELECT m.ibge_code, m.nome, p.numero_proposta, p.id_proposta_siconv, p.codigo_instrumento,
       p.situacao, p.situacao_siafi, p.modalidade,
       p.valor_global, p.valor_repasse, p.valor_contrapartida, p.valor_emenda,
       p.parlamentar, p.dt_proposta, p.dt_fim_vigencia,
       p.updated_at, p.detalhe_atualizado_em, p.historico_atualizado_em
FROM transferegov_propostas p JOIN municipios m ON m.id=p.municipio_id
WHERE m.ibge_code IN ('3113206','3104205','3103900','3169109','3107406')
ORDER BY m.ibge_code, p.numero_proposta;
