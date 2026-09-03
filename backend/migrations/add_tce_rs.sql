-- TCE-RS / LicitaCon — o que o município comprou e com quem contratou.
--
-- Nova Palma tem **864 licitações e 1.201 contratos** publicados (2016-2026), e
-- só em 2026 são 96 contratos somando **R$ 19,1 milhões** — numa prefeitura de
-- 5,6 mil habitantes. O maior deles é a "construção de 25 casas de alvenaria"
-- (R$ 3,64 mi). Nada disso aparecia no sistema.
--
-- Por que isto importa num produto de convênios: o convênio federal ou estadual
-- termina numa licitação e num contrato, e é aí que o prazo escorre. A execução
-- que o TransfereGov mostra pelo lado do repasse, o LicitaCon mostra pelo lado
-- da compra — e é o lado que o TCE fiscaliza.
--
-- ⚠️ O CÓDIGO DO ÓRGÃO NÃO É O IBGE. É o código do TCE-RS: Nova Palma = 53100,
-- Santa Maria = 56900. E a Câmara Municipal tem código próprio (53101 / 56901)
-- e **não é o cliente** — a mesma separação prefeitura/câmara que o SICONFI e o
-- CHE exigem. Ele vive em `municipios.tce_orgao_codigo`
-- (add_municipio_identificadores.sql).

CREATE TABLE IF NOT EXISTS tce_rs_licitacoes (
    id                SERIAL PRIMARY KEY,
    municipio_id      INTEGER NOT NULL REFERENCES municipios(id),
    cd_orgao          VARCHAR(10) NOT NULL,
    nm_orgao          TEXT,
    -- A CHAVE DO LICITACON. São quatro campos, e nenhum sobra: o número
    -- reinicia a cada ano e a cada modalidade, então (nr, ano) sozinho colide
    -- entre um pregão e uma concorrência do mesmo número.
    nr_licitacao      VARCHAR(20) NOT NULL,
    ano_licitacao     INTEGER NOT NULL,
    cd_tipo_modalidade VARCHAR(10) NOT NULL,
    nr_processo       VARCHAR(20),
    ano_processo      INTEGER,
    tp_objeto         VARCHAR(10),
    -- Fase atual (ADH = adjudicada/homologada, etc). É o que diz se a licitação
    -- ainda anda ou já virou contrato.
    cd_tipo_fase_atual VARCHAR(10),
    ds_objeto         TEXT,
    -- ⚠️ DOIS VALORES, e a diferença é o que interessa: `vl_licitacao` é o
    -- estimado e `vl_homologado` é o que de fato saiu. Guardar só um deles
    -- apagaria a economia (ou o estouro) do certame.
    vl_licitacao      NUMERIC(18,2),
    vl_homologado     NUMERIC(18,2),
    dt_abertura       DATE,
    dt_homologacao    DATE,
    dt_adjudicacao    DATE,
    -- CNPJ/CPF do vencedor, quando a licitação já tem um.
    tp_documento_vencedor VARCHAR(4),
    nr_documento_vencedor VARCHAR(20),
    link_licitacon    TEXT,
    raw_data          JSONB,
    atualizado_em     TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_tce_rs_licitacoes
    ON tce_rs_licitacoes (cd_orgao, nr_licitacao, ano_licitacao, cd_tipo_modalidade);
CREATE INDEX IF NOT EXISTS ix_tce_rs_licitacoes_mun
    ON tce_rs_licitacoes (municipio_id, ano_licitacao DESC);


CREATE TABLE IF NOT EXISTS tce_rs_contratos (
    id                SERIAL PRIMARY KEY,
    municipio_id      INTEGER NOT NULL REFERENCES municipios(id),
    cd_orgao          VARCHAR(10) NOT NULL,
    nm_orgao          TEXT,
    nr_contrato       VARCHAR(20) NOT NULL,
    ano_contrato      INTEGER NOT NULL,
    -- C = contrato · outros valores para ata, termo etc. Entra na chave porque
    -- o número é sequencial POR TIPO: existe contrato 15 e ata 15 no mesmo ano.
    tp_instrumento    VARCHAR(4) NOT NULL,
    -- A licitação que originou (pode ser vazia: contrato por dispensa).
    nr_licitacao      VARCHAR(20),
    ano_licitacao     INTEGER,
    cd_tipo_modalidade VARCHAR(10),
    nr_processo       VARCHAR(20),
    ano_processo      INTEGER,
    -- O CONTRATADO. `tp_documento` = J (CNPJ) ou F (CPF); o número vem SEM
    -- máscara e SEM zeros à esquerda perdidos.
    tp_documento      VARCHAR(4),
    nr_documento      VARCHAR(20),
    ds_objeto         TEXT,
    vl_contrato       NUMERIC(18,2),
    dt_assinatura     DATE,
    dt_inicio_vigencia DATE,
    dt_final_vigencia  DATE,
    nr_dias_prazo     INTEGER,
    link_licitacon    TEXT,
    raw_data          JSONB,
    atualizado_em     TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_tce_rs_contratos
    ON tce_rs_contratos (cd_orgao, nr_contrato, ano_contrato, tp_instrumento);
CREATE INDEX IF NOT EXISTS ix_tce_rs_contratos_mun
    ON tce_rs_contratos (municipio_id, ano_contrato DESC);
CREATE INDEX IF NOT EXISTS ix_tce_rs_contratos_vigencia
    ON tce_rs_contratos (municipio_id, dt_final_vigencia);


-- CACHE HTTP CONDICIONAL — infraestrutura, não uma tabela do TCE.
--
-- ⚠️ ESTE REPO NÃO TINHA HTTP CONDICIONAL EM LUGAR NENHUM. A auditoria de
-- 29/08/2026 mediu: zero ocorrências de ETag / If-None-Match / If-Modified-Since
-- em 44 coletores; o único cache é por IDADE DE ARQUIVO em disco
-- (`TRANSFEREGOV_CACHE_HORAS`), que rebaixa o dump inteiro mesmo quando nada
-- mudou. O TCE-RS serve `ETag` e `Last-Modified` corretos, então é aqui que a
-- peça nasce — e ela é genérica de propósito: qualquer coletor que baixe
-- arquivo grande pode usá-la depois (o CAUC e o Acordo FES baixam 10-14×/dia
-- hoje).
--
-- A chave é a URL, e não a fonte: um mesmo coletor baixa vários arquivos (um
-- por órgão, um por ano) e cada um tem o seu selo.
CREATE TABLE IF NOT EXISTS fonte_http_cache (
    url            TEXT PRIMARY KEY,
    fonte          VARCHAR(40) NOT NULL,
    etag           TEXT,
    last_modified  TEXT,
    -- Tamanho e hash do conteúdo, para o caso de o servidor não mandar
    -- validador nenhum — aí o "mudou?" ainda pode ser respondido, só que
    -- depois do download.
    tamanho        BIGINT,
    sha256         VARCHAR(64),
    -- Quando o servidor respondeu 304 pela última vez. Separado de
    -- `atualizado_em` porque "conferi e não mudou" não é "baixei de novo".
    conferido_em   TIMESTAMPTZ,
    atualizado_em  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_fonte_http_cache_fonte ON fonte_http_cache (fonte);
