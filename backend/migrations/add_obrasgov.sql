-- Obras.gov.br / CIPI — as obras federais que não são de saúde nem de educação.
--
-- O SISMOB cobre saúde, o SIMEC cobre educação, e o resto — mobilidade,
-- saneamento, habitação, segurança — não aparecia em lugar nenhum. O Cadastro
-- Integrado de Projetos de Investimento traz todas, com situação, datas
-- previstas e efetivas, valor por origem de recurso, tomador e executor.
--
-- ⚠️ O MUNICÍPIO NÃO VEM DA FONTE. A API não tem filtro territorial (medido:
-- `codigoIbge` é ignorado e devolve obra de outro estado com HTTP 200), e o
-- projeto raramente diz onde fica — de 397 projetos do RS, só 96 tinham CEP ou
-- endereço. O vínculo é feito por **CNPJ do tomador ou executor**, e por isso
-- `municipio_id` aqui é uma inferência NOSSA, não um campo do Governo Federal.
-- Ver `ingestion/obrasgov.py`.
--
-- ⚠️ E UMA OBRA PODE PERTENCER A MAIS DE UM MUNICÍPIO da carteira (consórcio,
-- obra intermunicipal). A chave é `id_unico` — global, como a fonte a define —,
-- então nesse caso a última gravação vence e `municipio_id` fica com um deles.
-- É a escolha certa enquanto os tenants têm um município cada; num tenant de
-- assessoria com carteira grande, isto vira uma tabela de ligação. Registrado
-- aqui para que a troca seja uma decisão, e não uma descoberta.

CREATE TABLE IF NOT EXISTS obrasgov_projetos (
    id                SERIAL PRIMARY KEY,
    municipio_id      INTEGER NOT NULL REFERENCES municipios(id),
    -- "53409.43-83" — o identificador do CIPI, e a chave natural.
    id_unico          VARCHAR(40) NOT NULL,
    nome              TEXT,
    descricao         TEXT,
    -- A fonte separa os três, e eles dizem coisas diferentes: `funcao_social` é
    -- para quem serve, `meta_global` é o que entrega.
    funcao_social     TEXT,
    meta_global       TEXT,
    natureza          VARCHAR(40),      -- Obra · Serviço · ...
    especie           VARCHAR(40),      -- Construção · Reforma · Ampliação
    situacao          VARCHAR(60),      -- Cadastrada · Em execução · Concluída
    uf                VARCHAR(2),
    cep               VARCHAR(12),
    endereco          TEXT,
    -- ⚠️ PREVISTA x EFETIVA, e é a diferença que denuncia obra parada. A
    -- efetiva vem nula enquanto não acontece — nulo aqui é "ainda não", nunca
    -- zero nem a data prevista repetida.
    data_inicial_prevista  DATE,
    data_final_prevista    DATE,
    data_inicial_efetiva   DATE,
    data_final_efetiva     DATE,
    data_situacao          DATE,
    data_cadastro          DATE,
    populacao_beneficiada  INTEGER,
    empregos_gerados       INTEGER,
    -- Soma das fontes de recurso. A API traz uma linha por origem (Federal,
    -- Estadual, Municipal); `origens_recurso` guarda quais são.
    valor_investimento_previsto NUMERIC(18,2),
    origens_recurso   TEXT[],
    eixos             TEXT[],
    tipos             TEXT[],
    tomadores         TEXT[],
    executores        TEXT[],
    repassadores      TEXT[],
    raw_data          JSONB,
    atualizado_em     TIMESTAMPTZ DEFAULT NOW()
);

-- ⚠️ SEM o UNIQUE em `id_unico` sozinho (15/09/2026). A chave natural virou
-- (municipio_id, id_unico) em `add_obrasgov_territorio_e_detalhe.sql`, que cria
-- `ux_obrasgov_projetos_mun` e DERRUBA `ux_obrasgov_projetos`. Com a linha aqui,
-- todo boot recriava o indice que a migration seguinte apagava — e nos tenants
-- com a mesma obra em dois municipios (freitas, trust, bgk) o CREATE falhava
-- com "duplicate key", o que o runner antigo rotulava "ja aplicada (skip)".
CREATE INDEX IF NOT EXISTS ix_obrasgov_projetos_mun
    ON obrasgov_projetos (municipio_id, situacao);
