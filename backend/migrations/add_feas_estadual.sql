-- FEAS — o cofinanciamento ESTADUAL da assistência social (26/09/2026,
-- `ingestion/feas_estadual.py`; armadilhas no cabeçalho do coletor).
--
-- Cada pagamento do Fundo Estadual de Assistência Social ao município — ao fundo
-- municipal (Piso Mineiro, Piso Gaúcho) ou à prefeitura (emendas e programas do
-- FEAS) —, lido da despesa aberta do Estado: MG pelo pacote `despesa` do
-- dados.mg.gov.br (UE 1480004 SEDESE/FEAS/SUBAS), RS pelo `{ano}-despesa-do-estado`
-- do dados.rs.gov.br (UO 2178).
--
-- Duas tabelas novas, FK só para `municipios`. Não há chave natural confiável
-- (a mesma OB pode ter várias linhas): o período é TROCADO inteiro por município —
-- o ano em MG (um arquivo por ano), o mês no RS (um arquivo por mês).

CREATE TABLE IF NOT EXISTS feas_pagamento (
    id              BIGSERIAL PRIMARY KEY,
    municipio_id    INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    uf              VARCHAR(2) NOT NULL,
    ano             SMALLINT NOT NULL,
    mes             SMALLINT,
    data            DATE,
    documento       TEXT,                       -- nº da OB (MG) / do pagamento (RS)
    favorecido_cnpj VARCHAR(14) NOT NULL,       -- o fundo municipal OU a prefeitura
    favorecido_nome TEXT,
    unidade         TEXT,                       -- "1480004 - SEDESE/FEAS/SUBAS" | "2178 - Fundo..."
    acao            TEXT,                       -- "4431 PISO MINEIRO DE ASSISTENCIA SOCIAL"
    modalidade      TEXT,                       -- RS: 40 (a municípios) | 41 (fundo a fundo)
    valor           NUMERIC(18, 2) NOT NULL,    -- estorno entra negativo
    arquivo         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_feas_pagamento_mun
    ON feas_pagamento (municipio_id, uf, ano, mes);

-- O que já foi lido, por recurso do CKAN (MG: "ft_despesa_2026"; RS: "202607"):
-- a versão (`last_modified`) e a assinatura dos CNPJs procurados. Recurso igual
-- para o mesmo conjunto de CNPJs não é baixado de novo.
CREATE TABLE IF NOT EXISTS feas_carga (
    uf              VARCHAR(2) NOT NULL,
    recurso         TEXT NOT NULL,
    versao          TEXT NOT NULL,
    alvos           TEXT NOT NULL,
    linhas          INTEGER NOT NULL DEFAULT 0,
    lido_em         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (uf, recurso)
);
