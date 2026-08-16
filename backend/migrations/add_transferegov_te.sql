-- Transferencia Especial / Emenda Pix (FEDERAL) persistida.
--
-- A API "especiais" (especiais.transferegov...) rate-limita forte: coletar MG
-- inteiro (~8773 planos) ao vivo numa request web e inviavel. Entao um coletor no
-- worker (ingestion/transferegov_te.py) pagina DEVAGAR e faz upsert aqui; o RM
-- (rm_builder) e a tela (routers/transferegov.buscar) leem desta tabela — rapido e
-- completo, sem depender da API ao vivo. Ver memory te-emenda-pix-especiais.
-- Idempotente. Chave natural: planoAcaoId da API.
CREATE TABLE IF NOT EXISTS transferegov_te (
    plano_acao_id     BIGINT PRIMARY KEY,
    municipio_id      INTEGER REFERENCES municipios(id),
    uf                VARCHAR(2),
    codigo            VARCHAR(40),
    emenda            VARCHAR(200),
    parlamentar       VARCHAR(200),
    objeto            TEXT,
    situacao          VARCHAR(80),
    situacao_trabalho VARCHAR(80),
    valor_total       NUMERIC(16,2),
    valor_investimento NUMERIC(16,2),
    valor_custeio     NUMERIC(16,2),
    beneficiario_nome VARCHAR(300),
    beneficiario_cnpj VARCHAR(20),
    programa_codigo   VARCHAR(30),
    raw_data          JSONB,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_te_municipio ON transferegov_te(municipio_id);
CREATE INDEX IF NOT EXISTS idx_te_uf ON transferegov_te(uf);
CREATE INDEX IF NOT EXISTS idx_te_benef ON transferegov_te(beneficiario_nome);
