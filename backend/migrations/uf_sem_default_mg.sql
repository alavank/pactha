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
--
-- ⚠️ A PURGA E POR FONTE, NAO POR UF — e a diferenca entre as duas linhas
-- abaixo e o que permite o CHE gaucho existir. Ate 08/2026 esta migration
-- apagava TODA linha de municipio fora de MG, a CADA BOOT da API. Como
-- `cagec_situacao` passou a guardar tambem o cadastro estadual de OUTROS
-- estados (`add_cadastro_estadual_rs.sql`), a regra antiga apagaria o CHE do
-- Rio Grande do Sul toda vez que a API subisse, e o coletor o recriaria horas
-- depois: a tela piscando entre "aguardando coleta" e dado real, sem erro em
-- lugar nenhum e sem ninguem entender por que.
--
-- O que a purga precisa remover continua sendo o mesmo: linha do coletor
-- MINEIRO em municipio que nao e de Minas. O `coalesce` preserva o
-- comportamento historico para as linhas legadas (fonte NULL = coletadas
-- quando so existia o CAGEC).
DELETE FROM cagec_situacao cs
USING municipios m
WHERE m.id = cs.municipio_id
  AND upper(coalesce(m.uf, '')) <> 'MG'
  AND coalesce(cs.fonte, 'CAGEC-MG') = 'CAGEC-MG';
