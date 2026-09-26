-- FNAS (Fundo Nacional de Assistência Social, MDS) — o dinheiro da ASSISTÊNCIA
-- SOCIAL no fundo municipal (26/09/2026, `ingestion/fnas_suas.py`; armadilhas no
-- cabeçalho do coletor).
--
-- Fonte: o painel "Repasses Fundo a Fundo" do MDS (paineis.mds.gov.br, Qlik
-- Sense), que abre sessão ANÔNIMA pelo websocket do engine — três apps:
--   * Saldos — o saldo de CADA CONTA do fundo, mês a mês, desde 2011 (conta
--     corrente, poupança, fundos, CDB/RDB). Nenhuma outra fonte pública tem: a
--     CGU dá o total repassado no mês, o SUASWeb exige hCaptcha;
--   * Repasses — cada ordem bancária do FNAS ao fundo: competência, bloco, piso,
--     programa, número da OB, data e a conta onde caiu;
--   * Emendas — o repasse que veio por emenda, com o PARLAMENTAR e o partido.
--
-- Quatro tabelas novas, FK só para `municipios`. Texto que vem do painel (nome de
-- bloco, grupo, tipo de emenda, partido) é TEXT: o GRUPO2 estourou VARCHAR(60) na
-- 1ª carga contra Postgres real. Largura fixa só em código (conta, agência, OB).

-- 1. Saldo por conta e mês. O painel publica UMA linha por (conta, mês) —
--    medido em 26/09/2026: nenhuma conta de Monte Sião, Nova Palma ou Santa
--    Maria em 2026 tem duas. Conta e agência vêm com zeros à esquerda em
--    quantidade variável ("000000197475" e "0000197475" são a mesma): gravadas
--    SEM os zeros, que é como casam com a conta do repasse.
CREATE TABLE IF NOT EXISTS fnas_saldo_conta (
    id              BIGSERIAL PRIMARY KEY,
    municipio_id    INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    ano_mes         INTEGER NOT NULL,           -- 202608
    cnpj            VARCHAR(14) NOT NULL,
    tipo_entidade   TEXT,                       -- FUNDO MUNICIPAL | PREFEITURA
    agencia         VARCHAR(12) NOT NULL,
    conta           VARCHAR(20) NOT NULL,
    bloco           TEXT,                       -- "BL PSB FNAS", "PROGRAMAS"...
    tipo_conta      TEXT,                       -- o nome da conta (bloco ou programa)
    monitorado      BOOLEAN,                    -- ST_MONITORAMENTO_SALDO = 'S'
    vl_conta_corrente NUMERIC(18, 2) NOT NULL DEFAULT 0,
    vl_poupanca     NUMERIC(18, 2) NOT NULL DEFAULT 0,
    vl_fundos       NUMERIC(18, 2) NOT NULL DEFAULT 0,
    vl_cdb_rdb      NUMERIC(18, 2) NOT NULL DEFAULT 0,
    vl_total        NUMERIC(18, 2) NOT NULL,
    UNIQUE (municipio_id, ano_mes, cnpj, agencia, conta)
);

CREATE INDEX IF NOT EXISTS ix_fnas_saldo_conta_mun_mes
    ON fnas_saldo_conta (municipio_id, ano_mes DESC);

-- 2. Cada repasse (OB) do FNAS ao município. `processo_entidade` é a chave do
--    painel (CO_PROCESSO_ENTIDADE): 1.594.570 valores distintos em 1.594.570
--    linhas no app dos últimos 4 anos.
CREATE TABLE IF NOT EXISTS fnas_repasse (
    id              BIGSERIAL PRIMARY KEY,
    municipio_id    INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    processo_entidade BIGINT NOT NULL,
    ano             SMALLINT NOT NULL,          -- ano de COMPETÊNCIA (NU_ANO_EXERCICIO)
    mes             SMALLINT,                   -- mês de competência
    cnpj            VARCHAR(14),
    bloco           TEXT,                       -- DS_TIPO_PROGRAMA
    grupo           TEXT,                       -- GRUPO2: BLOCO PSB, IGD-PBF...
    piso            TEXT,                       -- DS_PISO_PAI
    programa        TEXT,                       -- NO_PROGRAMA_RESUMIDO
    tipo_execucao   TEXT,                       -- SERVICO | GESTAO | PROGRAMAS | SIGTV
    ob              VARCHAR(20),
    dt_ob           DATE,                       -- DT_CRIACAO_SIAFI
    agencia         VARCHAR(12),
    conta           VARCHAR(20),
    processo        VARCHAR(30),
    valor           NUMERIC(18, 2) NOT NULL,
    UNIQUE (municipio_id, processo_entidade)
);

CREATE INDEX IF NOT EXISTS ix_fnas_repasse_mun_ano
    ON fnas_repasse (municipio_id, ano DESC, mes DESC);

-- 3. As emendas (o app de emendas do painel). ⚠️ A chave do painel se repete em
--    4 das 24.667 linhas nacionais (dois autores no mesmo processo): a linha é
--    (processo, parlamentar).
CREATE TABLE IF NOT EXISTS fnas_emenda (
    id              BIGSERIAL PRIMARY KEY,
    municipio_id    INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    processo_entidade BIGINT NOT NULL,
    parlamentar     TEXT NOT NULL,
    partido         TEXT,
    tipo_emenda     TEXT,
    programa        TEXT,                       -- DS_PROGRAMA_FUNDO
    ano             SMALLINT,
    mes             SMALLINT,
    ob              VARCHAR(20),
    dt_ob           DATE,
    agencia         VARCHAR(12),
    conta           VARCHAR(20),
    gnd             TEXT,                       -- 3 custeio, 4 investimento
    processo        VARCHAR(30),
    valor           NUMERIC(18, 2) NOT NULL,
    UNIQUE (municipio_id, processo_entidade, parlamentar)
);

-- 4. O que já foi lido, por município e app. `historico` = a carga completa (desde
--    2008/2011) já foi feita; sem ela, a próxima rodada lê tudo de novo. `painel_em`
--    é a DH_CARGA do app — a data em que o MDS recarregou o painel.
CREATE TABLE IF NOT EXISTS fnas_carga (
    municipio_id    INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    app             VARCHAR(10) NOT NULL,       -- saldo | repasse | emenda
    historico       BOOLEAN NOT NULL DEFAULT FALSE,
    linhas          INTEGER NOT NULL DEFAULT 0,
    painel_em       TIMESTAMP,
    lido_em         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (municipio_id, app)
);
