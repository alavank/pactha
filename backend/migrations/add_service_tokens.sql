-- Migration: service_tokens + automation_key no cofre

CREATE TABLE IF NOT EXISTS service_tokens (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    token_hash VARCHAR(255) NOT NULL,
    token_prefix VARCHAR(12),
    scopes JSONB DEFAULT '[]',
    description TEXT,
    active BOOLEAN DEFAULT TRUE,
    last_used_at TIMESTAMPTZ,
    last_used_ip VARCHAR(64),
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by_user_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_service_tokens_hash ON service_tokens(token_hash);

ALTER TABLE cofre_senhas ADD COLUMN IF NOT EXISTS automation_key VARCHAR(50);
CREATE INDEX IF NOT EXISTS idx_cofre_automation ON cofre_senhas(automation_key);
