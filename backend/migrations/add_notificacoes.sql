-- Tabela de notificacoes push (eventos relevantes detectados pelos scrapers).
-- Quando o scraper SIGCON detecta delta (novo convenio, status mudou, valor
-- alterado, nova emenda etc), insere um registro aqui.
-- O frontend faz GET /api/notificacoes pra mostrar badge contador + dropdown.

CREATE TABLE IF NOT EXISTS notificacoes (
    id SERIAL PRIMARY KEY,
    tipo VARCHAR(50) NOT NULL,           -- 'sigcon_novo', 'sigcon_status_mudou', 'sigcon_valor', 'emenda_nova', etc
    municipio_id INTEGER REFERENCES municipios(id) ON DELETE CASCADE,
    convenio_estadual_id INTEGER REFERENCES convenios_estadual(id) ON DELETE SET NULL,
    convenio_federal_id INTEGER REFERENCES convenios_federal(id) ON DELETE SET NULL,
    titulo TEXT NOT NULL,                -- "Novo convenio SEINFRA R$ 1M" / "Status mudou: Plano Autorizado -> Vigente"
    mensagem TEXT,                       -- detalhes
    severidade VARCHAR(20) DEFAULT 'info', -- info/success/warning/critical
    payload JSONB,                       -- dados estruturados (old_value, new_value, etc)
    lida BOOLEAN DEFAULT false,
    lida_em TIMESTAMPTZ,
    lida_por_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_notif_mun ON notificacoes(municipio_id, lida, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_notif_lida ON notificacoes(lida, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_notif_tipo ON notificacoes(tipo);
