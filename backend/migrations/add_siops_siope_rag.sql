-- Obrigações de SAÚDE e EDUCAÇÃO que travam repasse (24/09/2026,
-- `ingestion/siops_siope.py`): o detalhe que falta aos itens 3.2.3, 3.2.4, 5.1 e
-- 5.2 do CAUC, e os instrumentos de planejamento do SUS (Plano, PAS, RDQA, RAG).
--
-- O CAUC só diz "!" ou uma data de validade. Ele não diz QUAL bimestre falta,
-- nem o percentual aplicado, nem se o município já entregou e o Tesouro ainda
-- não atualizou — foi assim que Nova Palma/RS, com o 4º bimestre do SIOPS
-- homologado em 23/09/2026, recebeu "vence em 6 dias" do PACTHA.
--
-- Tabelas novas, só com FK para `municipios`. Nada aqui altera tabela existente.

-- ---------------------------------------------------------------------------
-- 1. Um bimestre de SIOPS (saúde, Anexo 12 do RREO) ou SIOPE (educação, Anexo 8)
-- ---------------------------------------------------------------------------
-- ⚠️ SÓ EXISTE LINHA PARA BIMESTRE ENCERRADO E PARA O QUE A FONTE PROVOU.
-- `entregue = false` só é gravado quando a fonte respondeu por aquele UF e
-- período e o município não estava lá (SIOPS: fora da lista de homologados;
-- SIOPE: fora da declaração da UF). Resposta vazia ou erro da fonte NÃO vira
-- "não entregue" — vira ausência de linha e rodada `partial`.
--
-- O percentual do bimestre é ACUMULADO no ano e PARCIAL: o mínimo (15% saúde,
-- 25% educação) só se apura no 6º bimestre. `pct_aplicado` guarda o que a fonte
-- publicou; a regra de cor mora em `services/saude_educacao.py`.
CREATE TABLE IF NOT EXISTS saude_educacao_bimestre (
    id              BIGSERIAL PRIMARY KEY,
    municipio_id    INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    sistema         VARCHAR(5) NOT NULL CHECK (sistema IN ('SIOPS', 'SIOPE')),
    ano             SMALLINT NOT NULL,
    bimestre        SMALLINT NOT NULL CHECK (bimestre BETWEEN 1 AND 6),
    entregue        BOOLEAN NOT NULL,
    -- SIOPS: data da HOMOLOGAÇÃO (lista do siops.datasus.gov.br);
    -- SIOPE: DAT_DECL (data da declaração). NULL = a fonte provou a entrega
    -- (o indicador existe) mas não deu a data.
    data_entrega    DATE,
    recibo          VARCHAR(30),                -- SIOPE: NUM_RECI
    pct_aplicado    NUMERIC(7, 2),              -- SIOPS 3.2 (ASPS) / SIOPE 1.1 (MDE)
    pct_minimo      NUMERIC(5, 2),              -- 15 / 25 (o mínimo ANUAL)
    numerador       NUMERIC(18, 2),             -- SIOPS: despesa ASPS com recurso próprio
    denominador     NUMERIC(18, 2),             -- SIOPS: receita de impostos e transferências
    indicadores     JSONB,                      -- os demais indicadores que a fonte publica
    atualizado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (municipio_id, sistema, ano, bimestre)
);

CREATE INDEX IF NOT EXISTS ix_saude_educacao_bimestre_mun
    ON saude_educacao_bimestre (municipio_id, sistema, ano DESC, bimestre DESC);

-- ---------------------------------------------------------------------------
-- 2. Instrumentos de planejamento do SUS (DigiSUS Gestor — Módulo Planejamento)
-- ---------------------------------------------------------------------------
-- Uma linha por município × instrumento × ano. `instrumento`: PLANO, PAS, RDQA1,
-- RDQA2, RDQA3, RAG. No PLANO o `ano` é o PRIMEIRO do quadriênio (2026 para
-- 2026-2029) e `periodo` guarda o texto. `situacao` é a palavra LITERAL da fonte
-- ("Em Análise no Conselho de Saúde", "Avaliado"...), para conferir contra o
-- DigiSUS; a classificação (concluído / no conselho / pendente) é do serviço.
CREATE TABLE IF NOT EXISTS sus_instrumentos_planejamento (
    id              BIGSERIAL PRIMARY KEY,
    municipio_id    INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    instrumento     VARCHAR(10) NOT NULL,
    ano             SMALLINT NOT NULL,
    periodo         VARCHAR(20),
    situacao        TEXT NOT NULL,
    fase            SMALLINT,                   -- código da fase no DigiSUS (2 = 2022-2025, 9 = 2026-2029)
    atualizado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (municipio_id, instrumento, ano)
);

CREATE INDEX IF NOT EXISTS ix_sus_instrumentos_mun
    ON sus_instrumentos_planejamento (municipio_id, ano DESC);
