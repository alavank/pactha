-- Uso único REAL do token SSO (compartilhado entre workers, ao contrário do revoke in-memory).
-- O aceitador insere o jti; UNIQUE impede replay. Idempotente (roda no boot).
CREATE TABLE IF NOT EXISTS sso_used_jti (
    jti      VARCHAR(64) PRIMARY KEY,
    used_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
