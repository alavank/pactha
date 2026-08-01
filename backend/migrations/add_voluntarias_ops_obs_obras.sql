-- OPs/OBs (Execução Concedente -> Listagem de Repasses): valores de repasse/
-- desembolso + ordens bancárias (GERCOMP). E OBRAS (Acompanhamento de Obras /
-- medicao): lotes/CTEF + submetas + contrato + ART/RRT. Ambos JSONB.
ALTER TABLE transferegov_propostas
    ADD COLUMN IF NOT EXISTS ops_obs JSONB,
    ADD COLUMN IF NOT EXISTS obras JSONB;
