-- RM por SELEÇÃO de anos: um único relatório cujo ESCOPO são os anos escolhidos.
--
-- Novo modelo (substitui o par 'anual'|'completo'): a geração é UMA só — o
-- usuário seleciona os anos e gera UM relatório com eles juntos. Seleção vazia
-- (Todos) = o COMPLETO (todos os anos). O escopo vira a coluna `anos` (INT[]),
-- sempre ORDENADA e sem repetição (normalizada no router), e a identidade do
-- relatório passa a ser (municipio_id, anos).
--
-- Idempotente. Backfill preserva os RMs existentes: os anuais viram [ano da
-- data_referencia]; um eventual 'completo' vira {} (todos).
ALTER TABLE rm_relatorios
    ADD COLUMN IF NOT EXISTS anos INT[] NOT NULL DEFAULT '{}';

-- Backfill (só onde ainda está no default vazio):
UPDATE rm_relatorios
   SET anos = ARRAY[EXTRACT(YEAR FROM data_referencia)::int]
 WHERE anos = '{}' AND escopo = 'anual' AND data_referencia IS NOT NULL;
UPDATE rm_relatorios
   SET anos = '{}'
 WHERE escopo = 'completo';

-- Troca a chave: de (municipio, data, escopo) para (municipio, anos).
-- ux_rm_mun_data_escopo foi criada como UNIQUE INDEX (ver add_rm_escopo.sql).
DROP INDEX IF EXISTS ux_rm_mun_data_escopo;
CREATE UNIQUE INDEX IF NOT EXISTS ux_rm_mun_anos
    ON rm_relatorios (municipio_id, anos);
