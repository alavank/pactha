-- SES-MG: pagamentos do Fundo Estadual de Saúde aos Fundos Municipais por
-- RESOLUÇÃO SES — o fundo a fundo estadual da saúde de Minas (24/09/2026,
-- `ingestion/ses_mg_resolucoes.py`). Painel público
-- pagamentoderesolucoes.saude.mg.gov.br (Pagamentos Orçamentários e Restos a Pagar).
--
-- ⭐ O QUE FALTAVA. De saúde estadual em MG a plataforma tinha a DÍVIDA (Acordo FES,
-- `acordofes_credor`) e a emenda por Resolução SES INDICADA (`emendas_estaduais`,
-- pelo CSV da SEGOV). O dinheiro ORDINÁRIO que o Estado paga todo mês ao Fundo
-- Municipal — incentivo da APS, CBAF, farmácia, promoção da saúde — não estava em
-- lugar nenhum. Monte Sião em 2026: 26 OBs, R$ 4.440.015,08, das quais R$ 431.951,08
-- ordinárias e R$ 4.008.064,00 de emenda.
--
-- ⚠️ `categoria` SEPARA O QUE OUTRA TELA JÁ CONTA. 'emenda' (UPG 666/675) é a
-- mesma emenda que Emendas parlamentares › Estaduais (MG) já soma pela indicação:
-- fica aqui À PARTE e nunca entra no total ordinário. 'acordo_fes' (UPG 948) é a
-- recomposição do Acordo FES. 'emenda_federal' (UPG 650) é emenda federal que
-- passa pelo fundo estadual.
--
-- ⚠️ `do_municipio` É A VERDADE, NÃO O NOME. A busca da fonte é pelo NOME do
-- município e devolve todo credor sediado nele (consórcio, hospital). Só é do
-- município o CNPJ conferido (prefeitura, fundo que o FNS lista pelo IBGE, ou o
-- cadastro da Receita com o IBGE do município e natureza jurídica municipal). O
-- resto fica gravado e FORA das contas.

CREATE TABLE IF NOT EXISTS ses_mg_pagamentos (
    id                   BIGSERIAL PRIMARY KEY,
    municipio_id         INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    tipo                 VARCHAR(12) NOT NULL,       -- 'orcamentario' | 'restos'
    id_fonte             BIGINT NOT NULL,            -- o id do "Visualizar" da fonte
    ano_pagamento        SMALLINT NOT NULL,          -- o ano consultado (data_pgto)
    ano_empenho          SMALLINT,                   -- restos: o da fonte; orçamentário: o do pagamento
    categoria            VARCHAR(20) NOT NULL,       -- ordinario | emenda | emenda_federal | acordo_fes
    cod_atividade        VARCHAR(10),
    atividade            TEXT,
    cod_fonte            VARCHAR(10),
    cod_upg              VARCHAR(10),
    upg                  TEXT,
    num_empenho          VARCHAR(20),
    num_ob               VARCHAR(20),                -- "Nº de Documento de Pagamento" (vazio nos restos)
    data_pagamento       DATE,
    valor                NUMERIC(16, 2) NOT NULL,
    valor_nao_processado NUMERIC(16, 2),             -- só restos a pagar
    valor_processado     NUMERIC(16, 2),             -- só restos a pagar
    banco                VARCHAR(10),
    agencia              VARCHAR(10),
    conta                VARCHAR(20),                -- como a fonte escreve: com o dígito colado
    situacao             VARCHAR(100),
    cnpj_credor          VARCHAR(14) NOT NULL,
    razao_credor         TEXT,
    do_municipio         BOOLEAN NOT NULL,
    conferido_por        VARCHAR(20),                -- prefeitura | fns | receita (NULL = não é)
    resolucao            VARCHAR(20),                -- "10900/2026"
    atualizado_em        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tipo, id_fonte)
);
CREATE INDEX IF NOT EXISTS ix_ses_mg_pagamentos_mun_ano
    ON ses_mg_pagamentos (municipio_id, ano_pagamento);

-- O que foi lido INTEIRO, por (município, tipo, ano). É o que separa "zero
-- pagamento" de "nunca consultado", ordena o rodízio (quem está há mais tempo sem
-- conferir vai primeiro) e diz à tela de quando é o dado.
CREATE TABLE IF NOT EXISTS ses_mg_cobertura (
    municipio_id         INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    tipo                 VARCHAR(12) NOT NULL,
    ano                  SMALLINT NOT NULL,
    nome_consultado      VARCHAR(120) NOT NULL,
    n_linhas             INTEGER NOT NULL,
    total                NUMERIC(18, 2) NOT NULL,
    fonte_atualizada_em  TIMESTAMP,                  -- "Última atualização" da página inicial
    coletado_em          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (municipio_id, tipo, ano)
);

-- Cadastro da Receita (BrasilAPI / minhareceita) de cada CNPJ credor que não é o
-- da prefeitura nem um fundo que o FNS lista — consultado UMA vez e guardado. Sem
-- FK: é cadastro de CNPJ, não de município.
CREATE TABLE IF NOT EXISTS ses_mg_credores (
    cnpj                 VARCHAR(14) PRIMARY KEY,
    razao_social         TEXT,
    ibge                 VARCHAR(7),
    uf                   VARCHAR(2),
    natureza_codigo      INTEGER,
    natureza             TEXT,
    situacao             TEXT,
    fonte                VARCHAR(40),
    consultado_em        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Acordo FES POR EMPENHO (dos credores casados a um município do tenant), gravado
-- por `ingestion/acordofes_ingest.py` junto do agregado `acordofes_credor`. É a
-- chave CONFIÁVEL (CNPJ, ano do empenho, nº do empenho) que diz qual pagamento de
-- restos a pagar da SES-MG é de um empenho que está na dívida do Acordo — sem ela,
-- a Res. 6949/2019 paga em 2026 pareceria dinheiro novo.
CREATE TABLE IF NOT EXISTS acordofes_empenho (
    id                   BIGSERIAL PRIMARY KEY,
    municipio_id         INTEGER REFERENCES municipios(id) ON DELETE CASCADE,
    cnpj                 VARCHAR(14) NOT NULL,
    ano_empenho          SMALLINT NOT NULL,
    num_empenho          VARCHAR(20) NOT NULL,
    resolucao            VARCHAR(20),
    divida_inicial       NUMERIC(16, 2),
    total_pago           NUMERIC(16, 2),
    divida_atual         NUMERIC(16, 2),
    valor_retirado       NUMERIC(16, 2),
    pago_fora            NUMERIC(16, 2)
);
CREATE INDEX IF NOT EXISTS ix_acordofes_empenho_chave
    ON acordofes_empenho (cnpj, ano_empenho, num_empenho);
