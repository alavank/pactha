-- CGU / Portal da Transparência — os convênios do Executivo federal, pela planilha.
--
-- Coletor: `ingestion/cgu_convenios.py` (armadilhas no cabeçalho). O que esta
-- fonte tem e o TransfereGov não: as TRANSFERÊNCIAS LEGAIS da Defesa Civil (Lei
-- 12.340 — ações de resposta e recuperação) e o histórico anterior a 2009 (SIAFI).
-- Medido em 22/09/2026: Nova Palma com 8 instrumentos vigentes só aqui (R$ 22,9
-- mi, um de R$ 14,4 mi ainda sem nada liberado); Santa Maria com 16 (R$ 187 mi).
--
-- Três tabelas, todas novas e só com FK para `municipios`:
--
-- 1. `cgu_convenios` — um instrumento por linha. Chave (município, número,
--    documento do convenente): o número se repete no país (6 casos).
--    `municipal = false` é o convenente que NÃO é a prefeitura nem órgão/fundo
--    municipal (hospital, APAE, UFSM): fica, marcado, e fora dos totais — regra
--    do dono. `no_transferegov` NULO = "não deu para conferir", nunca "não".
-- 2. `cgu_convenios_ob` — as ordens bancárias de cada instrumento. SEM chave
--    natural: o par (convênio, OB) se repete 850 vezes na planilha; a lista do
--    município é trocada inteira a cada carga.
-- 3. `cgu_convenios_carga` — qual arquivo (AAAAMMDD) já entrou em cada município,
--    e o código SIAFI dele (a planilha não tem IBGE). Arquivo igual = nada a
--    baixar: a planilha não é diária (a de 11/09 ainda era a mais nova em 22/09).

CREATE TABLE IF NOT EXISTS cgu_convenios (
    id                      BIGSERIAL PRIMARY KEY,
    municipio_id            INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    numero                  VARCHAR(40) NOT NULL,
    numero_original         TEXT,
    numero_processo         TEXT,
    situacao                VARCHAR(60),
    objeto                  TEXT,
    orgao_superior_codigo   VARCHAR(10),
    orgao_superior          TEXT,
    orgao_concedente_codigo VARCHAR(10),
    orgao_concedente        TEXT,
    ug_concedente_codigo    VARCHAR(10),
    ug_concedente           TEXT,
    convenente_doc          VARCHAR(20) NOT NULL,
    convenente_nome         TEXT,
    tipo_convenente         VARCHAR(80),
    municipal               BOOLEAN NOT NULL,
    -- CONVENIO, CONTRATO DE REPASSE, TRANSFERENCIA LEGAL, TERMO DE COMPROMISSO...
    tipo_instrumento        VARCHAR(60),
    valor                   NUMERIC(18, 2),
    valor_liberado          NUMERIC(18, 2),
    valor_contrapartida     NUMERIC(18, 2),
    data_publicacao         DATE,
    data_inicio_vigencia    DATE,
    data_final_vigencia     DATE,
    data_ultima_liberacao   DATE,
    valor_ultima_liberacao  NUMERIC(18, 2),
    no_transferegov         BOOLEAN,
    arquivo                 VARCHAR(8) NOT NULL,
    atualizado_em           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (municipio_id, numero, convenente_doc)
);

CREATE INDEX IF NOT EXISTS ix_cgu_convenios_mun_vigencia
    ON cgu_convenios (municipio_id, data_final_vigencia DESC);

CREATE TABLE IF NOT EXISTS cgu_convenios_ob (
    id              BIGSERIAL PRIMARY KEY,
    municipio_id    INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    numero          VARCHAR(40) NOT NULL,
    ordem_bancaria  VARCHAR(40) NOT NULL,
    data_emissao    DATE,
    valor           NUMERIC(18, 2)
);

CREATE INDEX IF NOT EXISTS ix_cgu_convenios_ob_mun_numero
    ON cgu_convenios_ob (municipio_id, numero);

CREATE TABLE IF NOT EXISTS cgu_convenios_carga (
    municipio_id     INTEGER PRIMARY KEY REFERENCES municipios(id) ON DELETE CASCADE,
    arquivo          VARCHAR(8) NOT NULL,
    siafi_municipio  VARCHAR(8),
    instrumentos     INTEGER,
    ordens_bancarias INTEGER,
    carregado_em     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
