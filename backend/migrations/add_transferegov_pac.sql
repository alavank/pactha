-- Selecao PAC / Novo PAC (TransfereGov, Acesso Livre guest) por municipio.
-- Fonte: discricionarias.transferegov.../voluntarias/propostapac/listarPropostaPac.jsf
-- Idempotente. Chave: (municipio_id, numero_proposta).
CREATE TABLE IF NOT EXISTS transferegov_pac (
    id                  SERIAL PRIMARY KEY,
    municipio_id        INTEGER NOT NULL REFERENCES municipios(id),
    numero_proposta     VARCHAR(30) NOT NULL,
    programa            VARCHAR(400),
    programa_codigo     VARCHAR(30),
    proponente          VARCHAR(300),
    cnpj                VARCHAR(20),
    situacao            VARCHAR(120),
    valor_repasse       NUMERIC(16,2),
    valor_contrapartida NUMERIC(16,2),
    valor_total         NUMERIC(16,2),
    emenda_parlamentar  VARCHAR(300),
    qualificacao        VARCHAR(300),
    objeto              TEXT,
    justificativa       TEXT,
    detalhe_url         TEXT,
    raw_data            JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pac_mun_prop ON transferegov_pac(municipio_id, numero_proposta);
CREATE INDEX IF NOT EXISTS idx_pac_municipio ON transferegov_pac(municipio_id);
CREATE INDEX IF NOT EXISTS idx_pac_parlamentar ON transferegov_pac(emenda_parlamentar);
