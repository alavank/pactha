-- FUNDO A FUNDO da saude: o repasse que o FNS faz ao Fundo Municipal, por
-- BLOCO e por GRUPO de financiamento.
--
-- E a maior transferencia federal recorrente da saude, e ate 02/09/2026 a
-- plataforma nao via nada dela. O que ja existia era `convenios_estadual` com
-- fonte='FNS', que guarda a PROPOSTA (o extraordinario). Isto aqui e o
-- ORDINARIO — o dinheiro que sustenta a rede todo mes.
--
-- Medido no primeiro teste, Monte Siao/MG em 2026: R$ 8.553.475,09, sendo
-- R$ 3,44 mi de Atencao Primaria e R$ 2,51 mi de Atencao Especializada. Para
-- comparar: o municipio inteiro tem R$ 32,3 mi de repasse ESTADUAL acumulado
-- em toda a historia que a plataforma acompanha.
--
-- FONTE: consultafns.saude.gov.br/recursos/consulta-consolidada/repasse-bloco
-- PUBLICA, sem login. A resposta e hierarquica (bloco -> grupo) e esta tabela
-- ACHATA essa arvore: uma linha por (bloco, grupo).
--
-- ⚠️ A CHAVE NATURAL INCLUI O ANO. O portal responde por ano-calendario e o
-- valor de um ano em curso CRESCE a cada competencia paga. Sem o ano na chave,
-- a coleta de 2026 sobrescreveria a de 2025 e a serie historica morreria na
-- primeira rodada.
--
-- ⚠️ `vl_desconto` NAO e enfeite: o portal desconta glosa do bruto, e foi
-- medido diferente de zero logo no primeiro municipio testado (R$ 12.980 em
-- Media e Alta Complexidade). Guardar so o liquido esconderia a glosa, que e
-- exatamente o tipo de coisa que o gestor precisa ver.
--
-- ⚠️ Colunas de valor ANULAVEIS e sem DEFAULT: NULL = "nao coletado", 0 =
-- "coletado e e zero". A diferenca ja custou caro neste projeto.
--
-- Idempotente e aditiva.

CREATE TABLE IF NOT EXISTS fns_repasse_faf (
    id             SERIAL PRIMARY KEY,
    municipio_id   INTEGER NOT NULL REFERENCES municipios(id),
    ano            INTEGER NOT NULL,
    tipo_repasse   VARCHAR(1)  NOT NULL DEFAULT 'M',   -- M=Municipal, E=Estadual
    bloco_codigo   INTEGER     NOT NULL,
    bloco_nome     VARCHAR(180),
    grupo_codigo   INTEGER     NOT NULL,
    grupo_nome     VARCHAR(180),
    vl_total       NUMERIC(16,2),
    vl_desconto    NUMERIC(16,2),
    vl_liquido     NUMERIC(16,2),
    raw_data       JSONB,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

-- A identidade da linha. `grupo_codigo` = 0 fica reservado para o TOTAL do
-- bloco, quando o portal devolve bloco sem detalhamento de grupo.
CREATE UNIQUE INDEX IF NOT EXISTS ux_fns_faf_chave
    ON fns_repasse_faf (municipio_id, ano, tipo_repasse, bloco_codigo, grupo_codigo);

-- A consulta que o produto faz: "quanto este municipio recebeu neste ano".
CREATE INDEX IF NOT EXISTS idx_fns_faf_mun_ano
    ON fns_repasse_faf (municipio_id, ano);
