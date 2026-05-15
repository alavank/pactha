-- Tabela de Emendas Parlamentares Estaduais (SIGCON-MG / Pesquisar Emendas Por Convenente).
-- Diferente da tabela `emendas` (federal, vinculada a convenios_federal por id_proposta),
-- esta guarda indicacoes parlamentares ESTADUAIS de MG por municipio convenente.

CREATE TABLE IF NOT EXISTS emendas_estaduais (
    id SERIAL PRIMARY KEY,
    municipio_id INTEGER REFERENCES municipios(id) ON DELETE CASCADE,
    nr_indicacao VARCHAR(50),
    nome_responsavel VARCHAR(300),
    tipo_indicacao VARCHAR(100),
    uo_codigo VARCHAR(20),
    uo_sigla VARCHAR(50),
    cnpj_beneficiario VARCHAR(20),
    beneficiario VARCHAR(300),
    grupo_despesa VARCHAR(200),
    tipo_atendimento VARCHAR(300),
    valor_indicacao NUMERIC(15,2),
    status_indicacao VARCHAR(50),
    ano INTEGER,
    parlamentar_id INTEGER REFERENCES parlamentares(id) ON DELETE SET NULL,
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- UNIQUE TOTAL (nao parcial) pra ON CONFLICT funcionar.
-- Drop + recreate caso exista a versao antiga partial.
DROP INDEX IF EXISTS ux_emendas_estaduais_nr_ano;
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_emendas_estaduais_nr_ano'
    ) THEN
        ALTER TABLE emendas_estaduais ADD CONSTRAINT uq_emendas_estaduais_nr_ano
            UNIQUE (nr_indicacao, ano);
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS ix_emendas_estaduais_mun ON emendas_estaduais(municipio_id);
CREATE INDEX IF NOT EXISTS ix_emendas_estaduais_ano ON emendas_estaduais(ano);
CREATE INDEX IF NOT EXISTS ix_emendas_estaduais_parl ON emendas_estaduais(parlamentar_id);
