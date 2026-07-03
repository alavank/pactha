-- Base federal SICONV/TransfereGov (Brasil inteiro) p/ consulta por CNPJ.
-- Fonte: dados abertos repositorio.dados.gov.br/seges/detru (proposta + convenio).
-- Nivel PROPOSTA (cobre toda a atividade da entidade); enriquecida com o
-- convenio celebrado (via id_proposta) quando existe.
CREATE TABLE IF NOT EXISTS siconv_federal (
    id_proposta       BIGINT PRIMARY KEY,
    cnpj              VARCHAR(14),
    proponente        TEXT,
    uf                VARCHAR(2),
    municipio         TEXT,
    nr_proposta       VARCHAR(40),
    ano               INT,
    situacao          TEXT,
    objeto            TEXT,
    vl_global         NUMERIC(18, 2),
    vl_repasse        NUMERIC(18, 2),
    nr_convenio       VARCHAR(40),
    situacao_convenio TEXT,
    vl_desembolsado   NUMERIC(18, 2),
    dt_assinatura     DATE,
    dt_fim_vigencia   DATE,
    atualizado_em     TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_siconv_federal_cnpj ON siconv_federal (cnpj);
