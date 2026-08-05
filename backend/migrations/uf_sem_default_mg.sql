-- Municipio criado sem UF nascia 'MG' (default da coluna) e todo filtro por
-- estado passava a mentir: o coletor do CAGEC ganhava um alvo falso, o
-- Acordo FES casava divida por nome, o FNS consultava a UF errada. A UF
-- passa a ser decisao de quem provisiona (o canal control agora a exige).
--
-- DROP DEFAULT e idempotente: rodar a cada boot (como o runner faz) e no-op
-- quando o default ja saiu. Nao toca nos VALORES existentes — os 61
-- municipios dos tres tenants ja foram conferidos contra o IBGE.
ALTER TABLE municipios ALTER COLUMN uf DROP DEFAULT;

-- PURGA: o coletor do CAGEC passou a visitar so municipio de MG, entao a
-- limpeza que rodava dentro do loop (_limpar_sumidos) nunca mais alcanca os
-- demais — e uma linha coletada no tempo em que o portal mineiro recebia
-- CNPJ de fora (casamento por nome podia trazer a entidade errada) ficaria
-- CONGELADA, alimentando o medidor da Visao Geral para sempre.
DELETE FROM cagec_situacao cs
USING municipios m
WHERE m.id = cs.municipio_id
  AND upper(coalesce(m.uf, '')) <> 'MG';
