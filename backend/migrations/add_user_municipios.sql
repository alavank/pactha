-- Acesso por municipio por usuario (multi-tenant).
-- Admin = ve todos. Nao-admin = ve apenas os municipios atribuidos aqui.
CREATE TABLE IF NOT EXISTS user_municipios (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    municipio_id INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, municipio_id)
);
CREATE INDEX IF NOT EXISTS idx_user_municipios_user ON user_municipios(user_id);
