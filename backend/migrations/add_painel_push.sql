-- Painel Executivo do prefeito — tabelas PROPRIAS do painel.
-- O app painel/ e read-only nas tabelas do PACTHA; SO escreve nestas.
-- Idempotente (CREATE TABLE IF NOT EXISTS), roda no boot via startup.py.

-- Inscricoes de Web Push (VAPID) por usuario/municipio. UNIQUE por endpoint.
CREATE TABLE IF NOT EXISTS painel_push_subscriptions (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER REFERENCES users(id),      -- prefeito (nullable p/ kiosk)
    municipio_id  INTEGER NOT NULL REFERENCES municipios(id),
    endpoint      TEXT NOT NULL UNIQUE,
    p256dh        TEXT NOT NULL,
    auth          TEXT NOT NULL,
    ua            TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    last_ok_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_painel_push_municipio ON painel_push_subscriptions(municipio_id);

-- Preferencias de notificacao do prefeito (o que ele quer receber).
CREATE TABLE IF NOT EXISTS painel_preferencias (
    user_id          INTEGER PRIMARY KEY REFERENCES users(id),
    cauc_vencendo    BOOLEAN DEFAULT TRUE,
    nova_emenda      BOOLEAN DEFAULT TRUE,
    prazo_prestacao  BOOLEAN DEFAULT TRUE,
    mudanca_status   BOOLEAN DEFAULT TRUE,
    vigencia_60d     BOOLEAN DEFAULT TRUE,
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Dedupe do cron de alertas: nao reenvia o mesmo alerta (municipio+regra+ref).
CREATE TABLE IF NOT EXISTS painel_alertas_enviados (
    id           SERIAL PRIMARY KEY,
    municipio_id INTEGER NOT NULL,
    regra        TEXT NOT NULL,
    ref          TEXT NOT NULL,
    enviado_em   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (municipio_id, regra, ref)
);

-- Cache da narrativa IA (Haiku): regenerar so quando os numeros mudam (input_hash).
-- ano=0 representa "todos os anos" (a coluna faz parte da PK, nao pode ser NULL).
CREATE TABLE IF NOT EXISTS painel_narrativa_cache (
    municipio_id INTEGER NOT NULL,
    ano          INTEGER NOT NULL DEFAULT 0,
    kind         TEXT NOT NULL DEFAULT 'resumo',
    texto        TEXT,
    input_hash   TEXT,
    gerado_em    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (municipio_id, ano, kind)
);
