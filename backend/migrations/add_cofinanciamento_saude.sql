-- COFINANCIAMENTO ESTADUAL DA SAÚDE — o dinheiro que o Estado repassa ao fundo
-- municipal, e o que o município deixa de receber por desempenho.
--
-- ⚠️ POR QUE UMA TABELA E NÃO DUAS. São duas bases com esquemas diferentes
-- (Atenção Primária e Vigilância em Saúde), mas a pergunta do gestor é uma só:
-- "quanto da saúde estadual eu tenho, e o que está travado?". `tipo` separa a
-- origem; os campos comuns servem às duas e os específicos ficam em `raw_data`.
--
-- O QUE FAZ ISTO VALER: na Atenção Primária existe TETO e existe VALOR A
-- RECEBER, e a diferença entre os dois é dinheiro perdido por indicador de
-- desempenho (ISF). Na Vigilância existe parcela com pagamento NÃO liberado.
-- Os dois são alerta acionável — não é relatório, é o que o gestor pode
-- reverter.

CREATE TABLE IF NOT EXISTS cofinanciamento_saude (
    id            SERIAL PRIMARY KEY,
    municipio_id  INTEGER NOT NULL REFERENCES municipios(id),
    fonte         VARCHAR(40) NOT NULL,   -- 'SES-GO'
    -- 'atencao_primaria' | 'vigilancia'
    tipo          VARCHAR(40) NOT NULL,
    chave         TEXT NOT NULL,
    -- "2026/Q1" na Atenção Primária; "programa N · parcela M" na Vigilância.
    competencia   VARCHAR(60),
    programa      VARCHAR(300),
    -- Teto pactuado (só Atenção Primária).
    valor_teto    NUMERIC(18,2),
    -- O que o município efetivamente recebe/recebeu.
    valor         NUMERIC(18,2),
    -- % do teto a receber, e o indicador que o determinou (ISF).
    perc_receber  NUMERIC(7,2),
    indicador     NUMERIC(9,2),
    -- Vigilância: a parcela está liberada para pagamento?
    liberado      BOOLEAN,
    -- Atenção Primária: o quadrimestre já fechou? (aberto ainda pode mudar)
    fechado       BOOLEAN,
    data_ref      DATE,
    ano           INTEGER,
    raw_data      JSONB,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_cofin_saude_fonte_chave
    ON cofinanciamento_saude(fonte, chave);
CREATE INDEX IF NOT EXISTS ix_cofin_saude_mun
    ON cofinanciamento_saude(municipio_id, tipo, ano DESC);
