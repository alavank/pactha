-- Registros do Sistema de Monitoramento de Convênios — Decreto Estadual (RS)
-- nº 56.939/2023.
--
-- ⚠️ POR QUE UMA TABELA, E NÃO UMA COLUNA `ultimo_monitoramento_em` em
-- `convenios_estadual`. A obrigação é POR CONVÊNIO POR MÊS, e o alarme é "2
-- meses consecutivos sem registro". Um timestamp responde *quando foi a última
-- vez*; ele não responde **quais meses faltam**, que é a única pergunta que
-- importa aqui. E a exceção de calamidade (120 dias) precisa PULAR meses, não
-- deslocar um timestamp.
--
-- ⚠️ E a informação que decide o alarme — a AUSÊNCIA — não existe como linha
-- em lugar nenhum. Ela é calculada em `services/monitoramento_rs.py` a partir da
-- vigência do convênio contra o que está aqui. Esta tabela guarda só o que o
-- Estado confirma ter recebido.
--
-- ⚠️ A LINHA SIGNIFICA "REGISTRADO", JAMAIS "EM ORDEM". O portal aceita o
-- registro mensal; se o conteúdo dele satisfaz o concedente é outra história,
-- que só a análise da CAGE responde. Confundir as duas coisas faria a tela dizer
-- "em dia" para quem está prestes a ter a parcela suspensa por outro motivo.

CREATE TABLE IF NOT EXISTS monitoramento_convenios (
    id              SERIAL PRIMARY KEY,
    municipio_id    INTEGER NOT NULL REFERENCES municipios(id),
    -- Nullable de propósito: o registro pode chegar do portal ANTES de sabermos
    -- casá-lo com a linha de `convenios_estadual` (que vem do dump da CAGE, com
    -- outra chave). Guardar sem o vínculo é melhor que descartar.
    convenio_id     INTEGER REFERENCES convenios_estadual(id),
    fonte           VARCHAR(40) NOT NULL,      -- 'FPE-RS'
    -- Número do convênio no FPE — a identidade do lado do Estado.
    chave           TEXT NOT NULL,
    competencia     VARCHAR(7) NOT NULL,       -- 'AAAA-MM'
    status_execucao VARCHAR(40),               -- licitando | contratando | executando
    perc_fisico     NUMERIC(5,2),
    tem_fotos       BOOLEAN,
    registrado_em   DATE,
    registrado_por  TEXT,
    raw_data        JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- A identidade do registro: uma competência por convênio por fonte. É o que
-- permite ao coletor reprocessar o mês inteiro sem duplicar.
CREATE UNIQUE INDEX IF NOT EXISTS ux_monit_conv
    ON monitoramento_convenios (fonte, chave, competencia);
-- A consulta da tela e do alerta: "o que este município registrou, do mais
-- recente para trás".
CREATE INDEX IF NOT EXISTS ix_monit_conv_mun
    ON monitoramento_convenios (municipio_id, competencia DESC);
