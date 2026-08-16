-- valor_emenda: soma dos repasses de emenda parlamentar da proposta (do CSV
-- siconv_emenda, coluna VALOR_REPASSE_EMENDA). Uma proposta pode ter varias.
--
-- Os outros dois valores que o dono pediu sao DERIVADOS (nao viram coluna):
--   valor_voluntario = valor_repasse - valor_emenda  (parte discricionaria)
--   valor_proponente = valor_contrapartida           (ja existe)
-- Validado 16/08/2026: p/ propostas 100% de emenda, valor_emenda == valor_repasse.
ALTER TABLE transferegov_propostas
    ADD COLUMN IF NOT EXISTS valor_emenda NUMERIC;
