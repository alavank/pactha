-- Integração Telegram: vincula chat_id ao user_id PACTA.
-- chat_id Telegram pode ter ate 19 digitos (BIGINT seguro).

CREATE TABLE IF NOT EXISTS telegram_users (
    id              SERIAL PRIMARY KEY,
    chat_id         BIGINT NOT NULL UNIQUE,
    user_id         INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    municipio_id    INT REFERENCES municipios(id) ON DELETE SET NULL,
    telegram_user   VARCHAR(255),  -- @handle ou nome
    historico       JSONB NOT NULL DEFAULT '[]'::jsonb,  -- ultimas N msgs p/ contexto
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_telegram_users_user ON telegram_users(user_id);
CREATE INDEX IF NOT EXISTS idx_telegram_users_chat ON telegram_users(chat_id);

-- Codigos de vinculacao (expiram em 10 min, descartados apos uso)
CREATE TABLE IF NOT EXISTS telegram_link_codes (
    codigo          VARCHAR(12) PRIMARY KEY,
    user_id         INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at      TIMESTAMPTZ NOT NULL,
    used_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_telegram_codes_expires ON telegram_link_codes(expires_at);
