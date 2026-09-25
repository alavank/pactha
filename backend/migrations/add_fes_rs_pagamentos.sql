-- Repasses do FUNDO ESTADUAL DE SAÚDE do RS (SES-RS) aos municípios e às
-- entidades de saúde — as planilhas "GERAL PAGOS em <MÊS> Programas Municipais e
-- INCENTIVOS" de saude.rs.gov.br/pagamentos-mes (24/09/2026,
-- `ingestion/fes_rs.py`).
--
-- Uma linha por linha da planilha: um PAGAMENTO (valor_pago > 0) ou uma RETENÇÃO
-- (valor_retido > 0, com o motivo) — a fonte publica as duas em linhas separadas
-- do mesmo empenho, e é assim que ficam.
--
-- ⚠️ `fundo_municipal` SEPARA AS CONTAS. Na mesma planilha, sob o código do
-- município, vêm o Fundo Municipal de Saúde (o dinheiro da PREFEITURA) e os
-- hospitais/clínicas sediados nele (ASSISTIR, MAC, SUS Gaúcho vão direto ao
-- hospital). Todo total "do município" filtra `fundo_municipal`; o resto é
-- mostrado à parte, fora da soma — o mesmo critério de `convenios_estadual_outros`.
--
-- ⚠️ SEM CHAVE NATURAL. Nº de empenho + data + valor repete (dois pagamentos
-- iguais no mesmo dia são normais). A carga é por (município, ano, mês): apaga e
-- insere na mesma transação, e só com o arquivo do mês lido inteiro.

CREATE TABLE IF NOT EXISTS fes_rs_pagamentos (
    id               BIGSERIAL PRIMARY KEY,
    municipio_id     INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    ano              SMALLINT NOT NULL,          -- ano/mês do PAGAMENTO (o do arquivo)
    mes              SMALLINT NOT NULL,
    cod_municipio_rs SMALLINT NOT NULL,          -- código ESTADUAL da SES/CAGE (não é IBGE)
    crs              VARCHAR(10),                -- Coordenadoria Regional de Saúde
    credor           TEXT NOT NULL,
    cod_credor       VARCHAR(20) NOT NULL,       -- código CAGE do credor
    fundo_municipal  BOOLEAN NOT NULL,
    cod_projeto      VARCHAR(10),
    projeto          TEXT,
    cod_subprojeto   VARCHAR(10),
    subprojeto       TEXT,
    cod_modalidade   VARCHAR(4),
    modalidade       TEXT,
    cod_recurso      VARCHAR(10),
    recurso          TEXT,
    fonte_recurso    VARCHAR(20),                -- 'ESTADUAL' | 'FEDERAL' (MAC federal repassado pelo Estado)
    competencia_ano  SMALLINT,
    competencia_mes  SMALLINT,
    nr_empenho       VARCHAR(20),
    data_pagamento   DATE,
    valor_pago       NUMERIC(18, 2) NOT NULL DEFAULT 0,
    valor_retido     NUMERIC(18, 2) NOT NULL DEFAULT 0,
    cod_retencao     VARCHAR(10),
    motivo_retencao  TEXT,
    -- 'desconto' (CONASEMS, multa de auditoria, restituição...) | 'tributo'
    -- (ISSQN, IRRF do prestador) | 'judicial' | 'consignado' | 'outra'
    tipo_retencao    VARCHAR(20),
    documento        VARCHAR(40),                -- "Doc Credor" (nº da portaria/documento)
    nr_liquidacao    VARCHAR(20),
    processo_empenho VARCHAR(30),
    processo_liquidacao VARCHAR(30),
    historico        TEXT,                       -- cita a portaria/Res. CIB
    atualizado_em    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_fes_rs_pag_mun_ano_mes
    ON fes_rs_pagamentos (municipio_id, ano, mes);

-- O arquivo de cada mês que já foi carregado: o hash decide se a rodada de hoje
-- precisa reler (a SES republica o ano inteiro todo dia, com nome novo, e quase
-- todos os meses vêm byte a byte iguais).
CREATE TABLE IF NOT EXISTS fes_rs_arquivos (
    ano           SMALLINT NOT NULL,
    mes           SMALLINT NOT NULL,
    url           TEXT NOT NULL,
    sha256        VARCHAR(64) NOT NULL,
    -- Os municípios (IBGE) e a versão do leitor com que o arquivo foi lido:
    -- município novo no tenant ou leitor novo obrigam a reler o mesmo arquivo.
    assinatura    TEXT NOT NULL,
    publicado_em  TIMESTAMP,                     -- do prefixo do nome (aaaamm/ddhhmmss), hora de Brasília
    pago_ate      DATE,                          -- a última data de pagamento do arquivo
    linhas        INTEGER NOT NULL,
    total_pago    NUMERIC(18, 2) NOT NULL,       -- linha TOTAIS do arquivo (o Estado inteiro)
    total_retido  NUMERIC(18, 2) NOT NULL,
    lido_em       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ano, mes)
);
