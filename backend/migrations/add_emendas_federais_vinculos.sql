-- Emendas federais: o que chegou A ESTE MUNICÍPIO e o convênio que a emenda gerou
-- aqui — os outros dois arquivos de `EmendasParlamentares.zip` da CGU (24/09/2026,
-- `ingestion/portal_transparencia.py::execucao_planilha`).
--
-- ⭐ O NÚMERO QUE A TELA NÃO TINHA. `emendas_federais_cgu` é o agregado da emenda
-- INTEIRA, nacional — somá-lo por município deu R$ 4 bi em Nova Palma (ver
-- routers/emendas_federais.py). `_PorFavorecido.csv` diz quem recebeu, em qual
-- município e em qual mês: filtrado pelo município do cliente, é "quanto desta
-- emenda foi pago AQUI", e esse SIM se soma.
--
-- ⚠️ COM `municipio_id`, ao contrário do agregado: cada linha JÁ é do município
-- (casado por nome IGUAL + UF — nunca por "contém"). Linha de favorecido de outro
-- município não é gravada: uma emenda individual se espalha (a mesma de 2015 gerou
-- convênios em Nova Palma, Tapera e Caçapava do Sul).

CREATE TABLE IF NOT EXISTS emendas_federais_favorecidos (
    id                  BIGSERIAL PRIMARY KEY,
    municipio_id        INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    codigo_emenda       VARCHAR(12) NOT NULL,
    ano_mes             VARCHAR(6) NOT NULL,        -- "202606", como a fonte
    favorecido_doc      VARCHAR(20) NOT NULL,       -- CNPJ (ou CPF mascarado, como vier)
    favorecido          TEXT,
    natureza_juridica   TEXT,
    tipo_favorecido     TEXT,
    valor               NUMERIC(18, 2),
    atualizado_em       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (municipio_id, codigo_emenda, ano_mes, favorecido_doc)
);
CREATE INDEX IF NOT EXISTS ix_emendas_federais_favorecidos_cod
    ON emendas_federais_favorecidos (municipio_id, codigo_emenda);

CREATE TABLE IF NOT EXISTS emendas_federais_convenios (
    id                  BIGSERIAL PRIMARY KEY,
    municipio_id        INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    codigo_emenda       VARCHAR(12) NOT NULL,
    numero_convenio     VARCHAR(30) NOT NULL,       -- o número SIAFI/TransfereGov
    convenente          TEXT,
    objeto              TEXT,
    valor               NUMERIC(18, 2),
    data_publicacao     DATE,
    funcao              TEXT,
    subfuncao           TEXT,
    atualizado_em       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (municipio_id, codigo_emenda, numero_convenio)
);
CREATE INDEX IF NOT EXISTS ix_emendas_federais_convenios_cod
    ON emendas_federais_convenios (municipio_id, codigo_emenda);
