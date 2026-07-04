-- Acordo FES — divida do Fundo Estadual de Saude de MG (SES-MG) com os credores
-- da saude (fundos municipais de saude, hospitais, Santas Casas, consorcios).
-- Fonte: espelho Excel publico do Painel do Acordo FES (saude.mg.gov.br/acordofes).
-- Agregado por credor (CNPJ + razao social). municipio_id preenchido quando o
-- credor e o "FUNDO MUNICIPAL DE SAUDE DE <municipio nosso>".
CREATE TABLE IF NOT EXISTS acordofes_credor (
    id              SERIAL PRIMARY KEY,
    cnpj            VARCHAR(14),
    razao_social    TEXT,
    municipio_id    INT REFERENCES municipios(id),
    divida_inicial  NUMERIC(18, 2) DEFAULT 0,
    total_pago      NUMERIC(18, 2) DEFAULT 0,
    divida_atual    NUMERIC(18, 2) DEFAULT 0,
    valor_retirado  NUMERIC(18, 2) DEFAULT 0,
    pago_fora       NUMERIC(18, 2) DEFAULT 0,
    n_empenhos      INT DEFAULT 0,
    atualizado_em   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_acordofes_cnpj ON acordofes_credor (cnpj);
CREATE INDEX IF NOT EXISTS ix_acordofes_municipio ON acordofes_credor (municipio_id);
