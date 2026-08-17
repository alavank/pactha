-- Consulta Popular / COREDEs — o mecanismo de participação que NÃO existe em Minas.
--
-- Desde 1998, a população vota por região (28 Conselhos Regionais de
-- Desenvolvimento) quais projetos entram na LOA estadual. Os mais votados viram,
-- na prática, convênio com município. Nenhum concorrente que atende só MG tem
-- isso — e o dado é público, publicado pela SPGG em planilha por COREDE.
--
-- ⭐ POR QUE ISTO VENDE, e o exemplo que provou. Na edição 2026/2027, o COREDE
-- Central elegeu duas demandas (R$ 2,23 milhões no total). Santa Maria votou:
-- 153 votos na primeira, 141 na segunda — e ficou **DESCLASSIFICADA nas duas**,
-- por não atingir o mínimo de mobilização. Ou seja: a cidade ficou de fora de
-- um recurso da própria região, e isso não aparece em lugar nenhum do sistema
-- financeiro dela. É informação que muda comportamento no ano seguinte, que é
-- exatamente o que um painel de captação deveria fazer.
--
-- ⚠️ UMA LINHA POR DEMANDA DO COREDE, com a participação do município ao lado.
-- Não é "uma linha por município": o objeto é a DEMANDA (ela tem valor, órgão e
-- votação regional própria), e o município entra como o desempenho dele naquela
-- demanda. Modelar ao contrário obrigaria a repetir valor e órgão em toda linha
-- e a somar errado no primeiro relatório.

CREATE TABLE IF NOT EXISTS consulta_popular_rs (
    id                SERIAL PRIMARY KEY,
    municipio_id      INTEGER NOT NULL REFERENCES municipios(id),
    corede            VARCHAR(60) NOT NULL,
    -- A edição como o Estado a nomeia: '2026/2027'. Texto e não ano, porque a
    -- consulta é bienal no nome e o gestor procura por esse rótulo.
    edicao            VARCHAR(16) NOT NULL,
    -- Ordem da demanda na cédula ('1', '2', ...). Faz parte da identidade
    -- porque o TEXTO da demanda é longo e o Estado o reescreve entre planilhas.
    demanda_ordem     VARCHAR(8) NOT NULL,
    demanda           TEXT,
    orgao             TEXT,
    votos_corede      INTEGER,
    classificada      BOOLEAN,
    valor             NUMERIC(18,2),
    -- O desempenho DESTE município na demanda.
    votos_municipio   INTEGER,
    status_municipio  TEXT,          -- 'Classificado' | 'Desclassificado'
    raw_data          JSONB,
    atualizado_em     TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_consulta_popular_rs
    ON consulta_popular_rs (municipio_id, edicao, demanda_ordem);
CREATE INDEX IF NOT EXISTS ix_consulta_popular_rs_mun
    ON consulta_popular_rs (municipio_id, edicao DESC);
