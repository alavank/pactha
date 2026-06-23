-- Módulo "Geração de Documentos" — documentos preenchidos na plataforma
-- (1º tipo: plano_sustentabilidade). dados = JSONB com o formulário.
CREATE TABLE IF NOT EXISTS documentos_gerados (
    id            SERIAL PRIMARY KEY,
    municipio_id  INT,
    tipo          TEXT NOT NULL DEFAULT 'plano_sustentabilidade',
    titulo        TEXT,
    dados         JSONB NOT NULL DEFAULT '{}'::jsonb,
    status        TEXT DEFAULT 'rascunho',
    criado_por    INT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_documentos_mun ON documentos_gerados (municipio_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS ix_documentos_tipo ON documentos_gerados (tipo);
