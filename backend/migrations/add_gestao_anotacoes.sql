-- Modulo Gestao Interna: anotacoes paralelas aos dados oficiais.
-- Permite ao usuario marcar status personalizado (ex: "prestacao enviada
-- fisicamente"), protocolo, data, observacoes e anexar arquivos (PDF/imagem)
-- a QUALQUER item de convenio/proposta/plano, SEM alterar os dados brutos
-- vindos dos scrapers.
CREATE TABLE IF NOT EXISTS gestao_anotacoes (
    id              SERIAL PRIMARY KEY,
    municipio_id    INT NOT NULL,
    fonte           TEXT NOT NULL,    -- 'sigcon' | 'voluntaria' | 'plano_acao' | 'fns' | 'simec' | 'emenda' | 'rm'
    fonte_ref       TEXT NOT NULL,    -- numero ou id do registro original
    numero_referencia TEXT,           -- label para exibicao (ex: "1481000677/2026" ou "9317999")
    status_interno  TEXT,             -- predefinido (ver router) OU "Outro"
    status_custom   TEXT,             -- quando status_interno = "Outro"
    protocolo       TEXT,
    data_protocolo  DATE,
    observacoes     TEXT,
    anexos          JSONB NOT NULL DEFAULT '[]'::jsonb,  -- [{nome, mime, dados_b64, tamanho}]
    criado_por      INT,              -- users.id
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_gestao_mun ON gestao_anotacoes (municipio_id);
CREATE INDEX IF NOT EXISTS ix_gestao_item ON gestao_anotacoes (fonte, fonte_ref);
CREATE INDEX IF NOT EXISTS ix_gestao_status ON gestao_anotacoes (status_interno);
