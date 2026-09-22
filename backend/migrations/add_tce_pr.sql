-- TCE-PR — o que o município do Paraná declarou ao Tribunal (SIM-AM), pelo PIT.
--
-- Fonte: `https://pit.tce.pr.gov.br/Arquivos/{ANO}_PIT_TodosArquivos.zip`, o
-- "Download de Dados" do Portal Informação para Todos. Um zip por exercício
-- (2013 em diante), com um zip por município e tema dentro
-- (`2026_411295_Convenio.zip`...), e XML com atributos dentro de cada um.
--
-- Medido em Juranda/PR (22/09/2026): 2 convênios, 6 obras e 126 licitações só em
-- 2026, e 6.089 empenhos cuja FONTE DE RECURSO nomeia o convênio que os paga
-- ("SECID Convênio 1748/2025 Pavimentação Pedras Irreg."). É a única fonte do
-- PACTHA que diz quanto do dinheiro de cada convênio estadual a prefeitura já
-- empenhou, liquidou e pagou.
--
-- ⚠️ O CÓDIGO DO MUNICÍPIO NO PIT TEM SEIS DÍGITOS: é o IBGE sem o dígito
-- verificador (Juranda = 411295, IBGE 4112959). Não há coluna nova em
-- `municipios` para isso: o coletor corta `ibge_code`.
--
-- ⚠️ CADA ARQUIVO ANUAL TRAZ SÓ O QUE NASCEU NAQUELE ANO, e nada se repete entre
-- arquivos (medido em 2013/2017/2021/2025/2026, nas quatro tabelas abaixo). Por
-- isso a chave de "o que é deste arquivo" é (município, ano) — o coletor
-- substitui o ano inteiro de uma vez, e um registro que a fonte retirou sai.
--
-- ⚠️ E O MUNICÍPIO É MAIS DE UMA ENTIDADE: prefeitura (`id_pessoa` 12356 em
-- Juranda), Câmara (9872), e onde houver, autarquias e fundos. Mesma separação
-- do TCE-RS; a tela filtra por `id_pessoa`.

-- ---------------------------------------------------------------------------
-- 1. Convênios que a entidade registrou no SIM-AM
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tce_pr_convenios (
    id                SERIAL PRIMARY KEY,
    municipio_id      INTEGER NOT NULL REFERENCES municipios(id),
    -- Identificador do TCE: global, não reinicia por ano nem por entidade.
    id_convenio       BIGINT NOT NULL,
    ano               INTEGER NOT NULL,
    id_pessoa         BIGINT,
    nm_entidade       TEXT,
    nr_convenio       VARCHAR(40),
    nr_termo          VARCHAR(40),
    dt_celebracao     DATE,
    -- ⚠️ A SITUAÇÃO É A DO ARQUIVO DAQUELE ANO. Os zips de exercícios antigos
    -- são congelados (o de 2021 não muda desde 09/2023): um convênio de 2017
    -- "Em Andamento" pode ter terminado depois. A tela diz isso.
    situacao          TEXT,
    -- Federal / Estadual / Municipal — quem repassa.
    esfera            TEXT,
    vl_convenio       NUMERIC(18,2),
    vl_recurso_proprio NUMERIC(18,2),
    dt_inicio_vigencia DATE,
    dt_fim_vigencia    DATE,
    ds_objeto         TEXT,
    ds_fonte_receita  TEXT,
    ds_plano_padrao_fonte TEXT,
    dt_envio          TIMESTAMP,
    raw_data          JSONB,
    atualizado_em     TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tce_pr_convenios ON tce_pr_convenios (id_convenio);
CREATE INDEX IF NOT EXISTS ix_tce_pr_convenios_mun ON tce_pr_convenios (municipio_id, ano DESC);

-- ---------------------------------------------------------------------------
-- 2. Obras ("intervenções" no SIM-AM)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tce_pr_obras (
    id                SERIAL PRIMARY KEY,
    municipio_id      INTEGER NOT NULL REFERENCES municipios(id),
    id_intervencao    BIGINT NOT NULL,
    ano               INTEGER NOT NULL,
    id_pessoa         BIGINT,
    nm_entidade       TEXT,
    cd_intervencao    VARCHAR(20),
    -- ⚠️ O NOME DA OBRA COSTUMA CITAR O CONVÊNIO que a paga ("... R$ 14.852.000,
    -- CONVÊNIO 745 ... FEA"). É texto livre do município, guardado como veio.
    nm_intervencao    TEXT,
    vl_intervencao    NUMERIC(18,2),
    dt_inicio         DATE,
    prazo_dias        INTEGER,
    situacao          TEXT,
    regime            TEXT,
    dt_ultima_medicao DATE,
    -- Os bens/endereços da obra (`IntervencaoBem`), com a coordenada em texto
    -- como o TCE publica ("24°25'18.0 Sul, 52°50'38.4 Oeste").
    bens              JSONB,
    raw_data          JSONB,
    atualizado_em     TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tce_pr_obras ON tce_pr_obras (id_intervencao);
CREATE INDEX IF NOT EXISTS ix_tce_pr_obras_mun ON tce_pr_obras (municipio_id, ano DESC);

-- ---------------------------------------------------------------------------
-- 3. Licitações
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tce_pr_licitacoes (
    id                SERIAL PRIMARY KEY,
    municipio_id      INTEGER NOT NULL REFERENCES municipios(id),
    id_licitacao      BIGINT NOT NULL,
    ano               INTEGER NOT NULL,
    id_pessoa         BIGINT,
    nm_entidade       TEXT,
    modalidade        TEXT,
    nr_licitacao      VARCHAR(40),
    dt_abertura       DATE,
    -- Valor ESTIMADO do edital. O homologado sai por item em `LicitacaoVencedor`
    -- e não é somado aqui.
    vl_licitacao      NUMERIC(18,2),
    situacao          TEXT,
    classificacao     TEXT,
    ds_objeto         TEXT,
    raw_data          JSONB,
    atualizado_em     TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tce_pr_licitacoes ON tce_pr_licitacoes (id_licitacao);
CREATE INDEX IF NOT EXISTS ix_tce_pr_licitacoes_mun ON tce_pr_licitacoes (municipio_id, ano DESC);

-- ---------------------------------------------------------------------------
-- 4. Contratos e aditivos
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tce_pr_contratos (
    id                SERIAL PRIMARY KEY,
    municipio_id      INTEGER NOT NULL REFERENCES municipios(id),
    id_contrato       BIGINT NOT NULL,
    ano               INTEGER NOT NULL,
    id_pessoa         BIGINT,
    nm_entidade       TEXT,
    nr_contrato       VARCHAR(40),
    tipo_ato          TEXT,
    nm_contratado     TEXT,
    -- ⚠️ CPF VEM MASCARADO PELA FONTE ("***.449.***-**"); CNPJ vem inteiro.
    nr_doc_contratado VARCHAR(20),
    vl_contrato       NUMERIC(18,2),
    dt_assinatura     DATE,
    dt_inicio         DATE,
    dt_fim            DATE,
    ds_objeto         TEXT,
    raw_data          JSONB,
    atualizado_em     TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tce_pr_contratos ON tce_pr_contratos (id_contrato);
CREATE INDEX IF NOT EXISTS ix_tce_pr_contratos_mun ON tce_pr_contratos (municipio_id, ano DESC);

-- ⚠️ O ADITIVO MORA NO ARQUIVO DO ANO DO ADITIVO, não no do contrato: o de 2026
-- aditiva contratos de 2023. E um mesmo número de aditivo aparece em dois
-- arquivos quando mexe em valor E prazo (aditivo 6 do contrato 2279893 está em
-- `ContratoAditivo` e em `ContratoAditivoPrazo`) — por isso `arquivo` é chave.
CREATE TABLE IF NOT EXISTS tce_pr_contratos_aditivos (
    id                SERIAL PRIMARY KEY,
    municipio_id      INTEGER NOT NULL REFERENCES municipios(id),
    ano               INTEGER NOT NULL,
    id_contrato       BIGINT NOT NULL,
    -- valor | prazo | rescisao
    arquivo           VARCHAR(12) NOT NULL,
    nr_aditivo        VARCHAR(20) NOT NULL,
    ano_aditivo       INTEGER NOT NULL,
    tipo              TEXT,
    operacao          TEXT,
    vl_aditivo        NUMERIC(18,2),
    -- Valor do contrato DEPOIS do aditivo, como a entidade declarou.
    vl_atualizado     NUMERIC(18,2),
    -- Nova data de fim, nos aditivos de prazo.
    dt_fim            DATE,
    dt_aditivo        DATE,
    motivo            TEXT,
    raw_data          JSONB,
    atualizado_em     TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tce_pr_contratos_aditivos
    ON tce_pr_contratos_aditivos (id_contrato, arquivo, ano_aditivo, nr_aditivo);
CREATE INDEX IF NOT EXISTS ix_tce_pr_contratos_aditivos_mun
    ON tce_pr_contratos_aditivos (municipio_id, ano);

-- ---------------------------------------------------------------------------
-- 5. Despesa por FONTE DE RECURSO — o dinheiro do convênio sendo gasto
-- ---------------------------------------------------------------------------
-- Agregado dos empenhos do exercício (`Empenho.xml`), por entidade e fonte. Não
-- guarda empenho a empenho de propósito: são 15 mil linhas/ano num município de
-- 7 mil habitantes, e a pergunta da tela é "quanto deste convênio já saiu".
--
-- ⚠️ OS TRÊS VALORES SÃO OS DA NOTA DE EMPENHO (`vlEmpenho`, `vlLiquidacao`,
-- `vlPagamento`), como o município os informa. Somar as liquidações do arquivo
-- próprio dá um número um pouco diferente (34,19 mi contra 33,49 mi em Juranda
-- 2026) porque conta estornos e liquidações de restos a pagar. Não misturar.
CREATE TABLE IF NOT EXISTS tce_pr_despesa_fonte (
    id                SERIAL PRIMARY KEY,
    municipio_id      INTEGER NOT NULL REFERENCES municipios(id),
    ano               INTEGER NOT NULL,
    id_pessoa         BIGINT NOT NULL,
    nm_entidade       TEXT,
    -- A fonte que o MUNICÍPIO criou (ex.: 824 "SECID Convênio 1748/2025 ...").
    cd_fonte          VARCHAR(20) NOT NULL,
    ds_fonte          TEXT NOT NULL,
    -- O plano padrão do TCE em que ela se encaixa ("Transferências Voluntárias
    -- Públicas Estaduais"). É o que permite separar convênio de recurso livre
    -- sem ler o texto que cada município escreve como quer.
    ds_plano_padrao   TEXT,
    qt_empenhos       INTEGER NOT NULL DEFAULT 0,
    vl_empenhado      NUMERIC(18,2),
    vl_liquidado      NUMERIC(18,2),
    vl_pago           NUMERIC(18,2),
    atualizado_em     TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tce_pr_despesa_fonte
    ON tce_pr_despesa_fonte (municipio_id, ano, id_pessoa, cd_fonte, ds_fonte);

-- ---------------------------------------------------------------------------
-- 6. O que cada ano do arquivo disse — referência e último envio
-- ---------------------------------------------------------------------------
-- ⚠️ O DADO TEM ATRASO, e a tela precisa dizer de quanto. `DataReferencia`
-- (2026/09) é a geração do arquivo; `ultimoEnvioSIMAMNesteExercicio` (2026/06)
-- é o último MÊS que a entidade entregou ao TCE. Em 22/09/2026, Juranda estava
-- três meses atrás — e isso é o prazo normal do SIM-AM, não falha nossa.
CREATE TABLE IF NOT EXISTS tce_pr_arquivos (
    municipio_id      INTEGER NOT NULL REFERENCES municipios(id),
    ano               INTEGER NOT NULL,
    etag              TEXT,
    last_modified     TEXT,
    referencia        VARCHAR(10),
    ultimo_envio      VARCHAR(10),
    contagens         JSONB,
    atualizado_em     TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (municipio_id, ano)
);
