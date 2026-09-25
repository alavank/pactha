-- CGU / Portal da Transparência — os RECURSOS RECEBIDOS POR PASTA (24/09/2026).
--
-- Coletor: `ingestion/cgu_transferencias.py` (armadilhas no cabeçalho). Todo
-- dinheiro que a União transfere ao município e aos fundos dele, mês a mês, por
-- órgão, programa e ação: fundo a fundo da saúde, FNDE, FNAS, PNAB, Defesa Civil,
-- FPM, FUNDEB, royalties. A classificação por PASTA e por FAVORECIDO não é
-- gravada — é feita na leitura (`services/transferencias_pasta.py`).
--
-- Duas tabelas, novas e só com FK para `municipios`:
--
-- 1. `cgu_transferencias` — uma linha do arquivo da CGU por linha. SEM chave
--    natural: o mesmo (ação, favorecido) aparece em várias linhas no mesmo mês (o
--    PAB de Monte Sião em 08/2026 são três). O (município, mês) é trocado inteiro
--    a cada carga, numa transação.
-- 2. `cgu_transferencias_carga` — o que já entrou: (município, mês), quantas
--    linhas, o total, se o mês JÁ ESTAVA FECHADO quando foi lido (o mês corrente
--    é parcial e as constitucionais — FPM, FUNDEB — só entram depois que ele
--    fecha) e de onde saiu o código SIAFI do município (o arquivo não tem IBGE).

CREATE TABLE IF NOT EXISTS cgu_transferencias (
    id                        BIGSERIAL PRIMARY KEY,
    municipio_id              INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    -- 1º dia do mês ("ANO / MÊS" do arquivo). Não há data do pagamento.
    mes                       DATE NOT NULL,
    -- "Constitucionais e Royalties" | "Legais, Voluntárias e Específicas"
    tipo_transferencia        VARCHAR(80),
    tipo_favorecido           VARCHAR(80),
    uf                        VARCHAR(2),
    -- NULO quando a linha entrou pelo CNPJ do favorecido e veio sem município.
    siafi_municipio           VARCHAR(8),
    orgao_codigo              VARCHAR(10),
    orgao_nome                TEXT,
    ug_codigo                 VARCHAR(10),
    ug_nome                   TEXT,
    funcao_codigo             VARCHAR(4),
    funcao_nome               TEXT,
    subfuncao_codigo          VARCHAR(6),
    subfuncao_nome            TEXT,
    programa_codigo           VARCHAR(10),
    programa_nome             TEXT,
    acao_codigo               VARCHAR(10),
    acao_nome                 TEXT,
    linguagem_cidada          TEXT,
    grupo_despesa             TEXT,
    modalidade                TEXT,
    elemento                  TEXT,
    plano_orcamentario_codigo VARCHAR(20),
    plano_orcamentario        TEXT,
    localizador               TEXT,
    -- CNPJ só com dígitos; o nome como a CGU publica (sem acento).
    favorecido_doc            VARCHAR(20),
    favorecido_nome           TEXT,
    valor                     NUMERIC(18, 2) NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_cgu_transferencias_mun_mes
    ON cgu_transferencias (municipio_id, mes);

CREATE TABLE IF NOT EXISTS cgu_transferencias_carga (
    municipio_id     INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    mes              DATE NOT NULL,
    linhas           INTEGER NOT NULL,
    total            NUMERIC(18, 2) NOT NULL,
    -- FALSE = lido enquanto o mês corria: parcial, e sem as constitucionais.
    mes_fechado      BOOLEAN NOT NULL,
    siafi_municipio  VARCHAR(8),
    -- cauc_situacao | tabela_tesouro | cnpj_prefeitura
    siafi_origem     VARCHAR(20),
    carregado_em     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (municipio_id, mes)
);
