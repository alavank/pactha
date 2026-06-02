-- SIMEC PAR (consulta publica MEC) - relatorio publico por municipio.
-- Idempotente: CREATE TABLE IF NOT EXISTS + indices uteis.

-- Resumo por dimensao do PAR (4 dimensoes, contagem de indicadores por score)
CREATE TABLE IF NOT EXISTS simec_par_dimensoes (
    id            SERIAL PRIMARY KEY,
    municipio_id  INT NOT NULL,
    dimensao      TEXT NOT NULL,
    score_4       INT DEFAULT 0,
    score_3       INT DEFAULT 0,
    score_2       INT DEFAULT 0,
    score_1       INT DEFAULT 0,
    score_na      INT DEFAULT 0,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (municipio_id, dimensao)
);

-- Liberacoes de recursos do MEC para o municipio (PNAE/PNATE/QUOTA/etc)
CREATE TABLE IF NOT EXISTS simec_par_liberacoes (
    id             SERIAL PRIMARY KEY,
    municipio_id   INT NOT NULL,
    programa       TEXT NOT NULL,        -- sigla ex: 'PNATE', 'QUOTA'
    programa_full  TEXT,                  -- nome completo "PNATE - PROGRAMA..."
    dt_pgto        DATE,
    ob             TEXT,                  -- ordem bancaria (codigo)
    valor          NUMERIC,
    parcela        TEXT,
    descricao      TEXT,                  -- coluna 'Programa' detalhada
    banco          TEXT,
    agencia        TEXT,
    conta          TEXT,
    ano            INT,
    raw            JSONB,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (municipio_id, programa, dt_pgto, ob)
);

CREATE INDEX IF NOT EXISTS ix_simec_lib_mun_ano ON simec_par_liberacoes (municipio_id, ano DESC);
CREATE INDEX IF NOT EXISTS ix_simec_lib_programa ON simec_par_liberacoes (programa);
