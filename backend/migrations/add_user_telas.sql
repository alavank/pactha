-- Permissao por tela/modulo por usuario.
-- Admin = ve todas. Nao-admin = ve apenas as telas atribuidas aqui.
CREATE TABLE IF NOT EXISTS user_telas (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tela VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, tela)
);
CREATE INDEX IF NOT EXISTS idx_user_telas_user ON user_telas(user_id);
