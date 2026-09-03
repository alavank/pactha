-- SICONFI / Tesouro Nacional — o que o município entregou e quanto ele aguenta.
--
-- Duas perguntas que o produto não sabia responder, e que decidem convênio:
--
--   1. "As contas estão em dia no Tesouro?" O CAUC já diz REGULAR ou IRREGULAR
--      nas obrigações 3.1.2 / 3.2.2 / 3.3, mas não diz **o quê** nem **quando**.
--      `siconfi_entregas` traz o extrato: cada entregável, cada período, a data
--      em que foi enviado e por qual forma. É a diferença entre "irregular na
--      obrigação 3.2.2" e "faltou o RREO do 4º bimestre".
--
--   2. "O município pode contrair crédito com garantia da União?" É a CAPAG, a
--      nota que o Tesouro publica de A+ a D. Nova Palma é **A+** (dívida
--      consolidada de R$ 682 mil sobre RCL de R$ 41,5 milhões, posição de
--      06/2026). Isso é porta de captação aberta que o gestor pode não saber
--      que tem — e o inverso, um C ou D, explica por que um pleito não anda.
--
-- ⚠️ A PREFEITURA E A CÂMARA DIVIDEM O MESMO `cod_ibge` NO SICONFI, e o extrato
-- devolve as duas misturadas — a Câmara vem primeiro. O que separa é o texto de
-- `instituicao` ("Prefeitura Municipal de X" x "Câmara de Vereadores de X").
-- Guardar as duas faria a tela cobrar da prefeitura uma MSC que é da Câmara.
-- Mesma armadilha do `tce_orgao_codigo` (PM 53100 x CM 53101) e do CHE.
--
-- ⚠️ `entregavel` É TEXTO DA FONTE, e ele varia com o PORTE do município:
-- Nova Palma entrega "Relatório Resumido de Execução Orçamentária Simplificado"
-- (bimestral) e "Relatório de Gestão Fiscal Simplificado" (semestral); Santa
-- Maria entrega as versões plenas, com outra periodicidade. Não normalize para
-- "RREO": o gestor procura o nome que está no recibo do Tesouro, e a palavra
-- "Simplificado" é o que explica por que a periodicidade dele é diferente da do
-- vizinho.

CREATE TABLE IF NOT EXISTS siconfi_entregas (
    id               SERIAL PRIMARY KEY,
    municipio_id     INTEGER NOT NULL REFERENCES municipios(id),
    exercicio        INTEGER NOT NULL,
    -- 'Relatório Resumido de Execução Orçamentária Simplificado', 'MSC
    -- Agregada', 'Balanço Anual (DCA)'... literal da fonte.
    entregavel       VARCHAR(120) NOT NULL,
    periodo          SMALLINT NOT NULL,
    -- M mensal · B bimestral · Q quadrimestral · S semestral · A anual.
    periodicidade    VARCHAR(2),
    -- ⚠️ VEM NULO com muita frequência, inclusive em entrega que ACONTECEU (as
    -- 22 linhas de Nova Palma em 2025 têm `status_relatorio` nulo e
    -- `data_status` preenchido). Quem prova a entrega é a DATA, não o status.
    status_relatorio TEXT,
    data_status      TIMESTAMPTZ,
    forma_envio      VARCHAR(30),
    instituicao      TEXT,
    raw_data         JSONB,
    atualizado_em    TIMESTAMPTZ DEFAULT NOW()
);

-- A identidade da entrega. `periodicidade` fica FORA da chave de propósito: ela
-- descreve o entregável, não o identifica, e um ente que mude de porte (e por
-- isso de periodicidade) duplicaria o histórico inteiro.
CREATE UNIQUE INDEX IF NOT EXISTS ux_siconfi_entregas
    ON siconfi_entregas (municipio_id, exercicio, entregavel, periodo);
CREATE INDEX IF NOT EXISTS ix_siconfi_entregas_mun
    ON siconfi_entregas (municipio_id, exercicio DESC);


CREATE TABLE IF NOT EXISTS siconfi_capag (
    id                  SERIAL PRIMARY KEY,
    municipio_id        INTEGER NOT NULL REFERENCES municipios(id),
    -- O ano da planilha publicada (2026 na posição de junho/2026).
    exercicio           INTEGER NOT NULL,
    -- A data da posição, que o Tesouro põe no NOME do recurso ("Capag
    -- Municípios 2026 - 01/06/2026"). Sem ela, duas revisões do mesmo ano
    -- ficariam indistinguíveis e a tela não saberia de quando é a nota.
    posicao             DATE,
    -- 'A+', 'A', 'B+', 'B', 'C', 'D'.
    nota                VARCHAR(4),
    -- Indicador 1 = endividamento (DC/RCL) · 2 = poupança corrente ·
    -- 3 = liquidez. Cada um com a sua nota parcial.
    ind_endividamento   NUMERIC(20,12),
    nota_endividamento  VARCHAR(2),
    ind_poupanca        NUMERIC(20,12),
    nota_poupanca       VARCHAR(2),
    ind_liquidez        NUMERIC(20,12),
    nota_liquidez       VARCHAR(2),
    icf                 VARCHAR(12),
    observacao          TEXT,
    raw_data            JSONB,
    atualizado_em       TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_siconfi_capag
    ON siconfi_capag (municipio_id, exercicio);
