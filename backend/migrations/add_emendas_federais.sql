-- Emendas parlamentares FEDERAIS: a carteira do município e a execução dela.
--
-- ⭐ O BURACO QUE ISTO FECHA. O PACTHA não tinha tela de emenda federal. Ela
-- aparecia de raspão em dois lugares — como Transferência Especial na tela
-- «Especiais» e como selo `TE` na lista de Convênios — e sempre pelo mesmo
-- caminho: a emenda que virou PROPOSTA. Medido em 06/09/2026 no dump
-- `siconv_emenda.zip`: **45% das emendas de Nova Palma e 43% das de Monte Sião
-- têm `ID_PROPOSTA` VAZIO**. Quase metade da carteira era invisível, e só o
-- filtro por CNPJ do beneficiário a alcança.
--
-- ⚠️⚠️ NOMES NOVOS DE PROPÓSITO, e a lista de nomes queimados é longa.
-- `drop_lean_tables.sql` — que continua em MIGRATION_FILES, ACIMA desta —
-- derruba a cada boot, nos cinco tenants: `emendas`, `convenios_federal`,
-- `emendas_camara`, `sancoes_ceis`, `programas_federais`, `oportunidades`,
-- `desembolsos`. O cabeçalho dele diz que tudo o que é
-- federal/transferegov/portal-transparencia vai embora. Reusar qualquer um
-- desses nomes apagaria a tabela em TODO deploy, e o sintoma seria "as emendas
-- federais esvaziaram sozinhas de novo". É o mesmo motivo que obrigou o
-- `add_programas_captacao.sql` a estrear com nome novo (ver o comentário dele
-- em services/startup.py). `tests/test_emendas_federais_migration.py` crava isso.
--
-- ⚠️⚠️ DOIS "VALORES", DUAS PERGUNTAS — e confundi-los é o erro caro aqui:
--
--   carteira.valor_repasse_emenda .. quanto DESTA emenda foi para ESTE
--                                    beneficiário. Responde "quanto o município
--                                    recebeu". Vem do dump SICONV.
--   cgu.valor_pago ................. quanto da emenda INTEIRA a União já pagou.
--                                    Responde "a emenda andou". Vem da CGU e é
--                                    NACIONAL.
--
-- Uma emenda de bancada de R$ 30 mi que passou por Nova Palma com R$ 250 mil
-- traria R$ 30 mi pelo segundo campo. É por isso que `emendas_federais_cgu` NÃO
-- TEM `municipio_id`: sem a coluna, o `SUM(valor_pago) GROUP BY municipio_id`
-- que produziria esse número é impossível de escrever por acidente. A guarda é
-- o schema, não a disciplina de quem escreve a query.
--
-- ⚠️ E `localidadeDoGasto` É NOME, NUNCA CHAVE. Guardamos o texto porque ele
-- informa, mas a atribuição ao município é feita SÓ por CNPJ do beneficiário —
-- diretriz do dono (04/09/2026), depois de casar por nome ter trazido 379 obras
-- da UFSM como se fossem da prefeitura de Santa Maria.

-- --------------------------------------------------------------- carteira --
-- Uma linha por LINHA DO DUMP (proposta × emenda) atribuída a um município
-- nosso. NÃO depende da chave da CGU: sai do siconv_emenda.zip, que é aberto —
-- e é isto que faz a tela nascer útil nos três tenants sem chave.
CREATE TABLE IF NOT EXISTS emendas_federais_carteira (
    id                     SERIAL PRIMARY KEY,
    municipio_id           INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    -- ⚠️ AS TRÊS COLUNAS DA CHAVE SÃO `NOT NULL DEFAULT ''`, e isso não é
    -- estilo. No Postgres NULL nunca colide com NULL num índice único: com
    -- `nr_emenda` nulo o ON CONFLICT jamais casaria e cada rodada inseriria de
    -- novo as 7.059 linhas que vêm sem número. A tabela cresceria, ninguém
    -- perceberia, e a tela duplicaria.
    id_proposta            VARCHAR(20)  NOT NULL DEFAULT '',
    cod_programa_emenda    VARCHAR(20)  NOT NULL DEFAULT '',
    nr_emenda              VARCHAR(20)  NOT NULL DEFAULT '',
    -- Ano lido das posições 5:9 de COD_PROGRAMA_EMENDA, que tem 13 dígitos =
    -- órgão SIAFI (5) + ano (4) + sequencial (4). NULL quando o campo não vem
    -- com os 13.
    ano                    SMALLINT,
    -- Os 12 dígitos que a CGU chama de `codigoEmenda` (ano + NR_EMENDA).
    -- NULLABLE de propósito: NR_EMENDA vem vazio em 7.059 das 298.114 linhas do
    -- dump, com 4 dígitos em 444 e com 9 em uma. Essas linhas CONTINUAM VALENDO
    -- — têm parlamentar, valor e beneficiário —, só nunca entram na fila da CGU.
    codigo_emenda          VARCHAR(12),
    -- ⭐ TRUE quando a CGU devolveu este mesmo código de volta. É o que separa
    -- "nós derivamos" de "o Governo confirmou", e é o que permite parar de
    -- derivar: código confirmado uma vez vira dado, não hipótese.
    codigo_confirmado      BOOLEAN NOT NULL DEFAULT FALSE,
    -- CNPJ do BENEFICIARIO_EMENDA, só dígitos. Vem com 14 em 298.107 das
    -- 298.114 linhas; 7 chegam com 13 (zero à esquerda comido pelo CSV) e são
    -- completadas na ingestão.
    beneficiario_cnpj      VARCHAR(14) NOT NULL DEFAULT '',
    beneficiario_nome      VARCHAR(300),
    -- COMO este CNPJ foi reconhecido como do município: 'prefeitura'
    -- (municipios.cnpj), 'sismob' ou 'pac'. Guardar isto é o que permite
    -- auditar a atribuição sem reabrir o coletor.
    vinculo                VARCHAR(20),
    -- TRUE quando o CNPJ é o da própria prefeitura. É o que a tela usa para
    -- separar "do município" de "de entidade do município" (hospital, APAE,
    -- fundo) — os dois aparecem, e somá-los sem dizer prometeria ao gestor um
    -- caixa que não é dele.
    e_prefeitura           BOOLEAN NOT NULL DEFAULT FALSE,
    parlamentar            VARCHAR(200),
    -- INDIVIDUAL 239.097 · COMISSAO 25.005 · RELATOR GERAL 13.792 ·
    -- BANCADA 9.566 · vazio 10.654 (medido no dump de 06/09/2026). ⚠️ Vazio é
    -- "não informado", nunca um valor — não preencher com COALESCE.
    tipo_parlamentar       VARCHAR(20),
    impositiva             BOOLEAN,
    qualif_proponente      VARCHAR(120),
    orgao_siafi            VARCHAR(5),
    valor_repasse_proposta NUMERIC(18,2),
    valor_repasse_emenda   NUMERIC(18,2),
    raw_data               JSONB,
    -- ⚠️ `visto_em` E NÃO `atualizado_em`: é o carimbo da RODADA, e é dele que
    -- o monitor de frescor lê. A emenda de 2011 não muda mais — um carimbo de
    -- "última alteração" congelaria e a linha do painel envelheceria sozinha
    -- com o coletor rodando todo dia. Mesmo desenho de `programas_captacao`.
    visto_em               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    criado_em              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ⚠️ A CHAVE É A LINHA DO DUMP, não a emenda. A relação emenda↔proposta é N:M
-- (medido: até 4 propostas por emenda nos dois municípios de teste), então
-- chavear por `codigo_emenda` sozinho apagaria propostas em silêncio. O
-- `municipio_id` entra porque a mesma linha pode ser atribuída a dois
-- municípios da carteira por CNPJs diferentes.
CREATE UNIQUE INDEX IF NOT EXISTS ux_emendas_federais_carteira
    ON emendas_federais_carteira
       (municipio_id, id_proposta, cod_programa_emenda, nr_emenda, beneficiario_cnpj);
CREATE INDEX IF NOT EXISTS ix_emendas_federais_carteira_mun
    ON emendas_federais_carteira (municipio_id, ano DESC);
CREATE INDEX IF NOT EXISTS ix_emendas_federais_carteira_codigo
    ON emendas_federais_carteira (codigo_emenda)
    WHERE codigo_emenda IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_emendas_federais_carteira_autor
    ON emendas_federais_carteira (parlamentar);

-- -------------------------------------------------------------- agregado ---
-- O que a CGU sabe sobre a emenda. FATO NACIONAL: sem municipio_id, de
-- propósito (ver o cabeçalho). Os valores chegam da API como STRING e são
-- convertidos aqui para NUMERIC — nulo continua nulo, nunca vira zero.
CREATE TABLE IF NOT EXISTS emendas_federais_cgu (
    id                    SERIAL PRIMARY KEY,
    codigo_emenda         VARCHAR(12) NOT NULL,
    ano                   SMALLINT,
    tipo_emenda           VARCHAR(60),
    autor                 VARCHAR(20),
    nome_autor            VARCHAR(200),
    numero_emenda         VARCHAR(20),
    -- ⚠️ TEXTO INFORMATIVO, NUNCA CHAVE DE MUNICÍPIO. Ver o cabeçalho.
    -- NOT NULL DEFAULT '' porque entra na chave natural.
    localidade_gasto      TEXT NOT NULL DEFAULT '',
    funcao                TEXT NOT NULL DEFAULT '',
    subfuncao             TEXT NOT NULL DEFAULT '',
    valor_empenhado       NUMERIC(18,2),
    valor_liquidado       NUMERIC(18,2),
    valor_pago            NUMERIC(18,2),
    valor_resto_inscrito  NUMERIC(18,2),
    valor_resto_cancelado NUMERIC(18,2),
    valor_resto_pago      NUMERIC(18,2),
    raw_data              JSONB,
    visto_em              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    criado_em             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ⚠️ A CHAVE NÃO É SÓ O CÓDIGO. O `ConsultaEmendasDTO` traz `localidadeDoGasto`,
-- `funcao` e `subfuncao`, que VARIAM dentro da mesma emenda — se a API devolver
-- quatro linhas por código e a chave fosse só `codigo_emenda`, três seriam
-- sobrescritas e o valor gravado seria o da última página, em silêncio. Se a
-- medição do dia 1 mostrar que é sempre uma linha por código, esta chave
-- degenera sem custo nenhum.
CREATE UNIQUE INDEX IF NOT EXISTS ux_emendas_federais_cgu
    ON emendas_federais_cgu (codigo_emenda, localidade_gasto, funcao, subfuncao);
CREATE INDEX IF NOT EXISTS ix_emendas_federais_cgu_codigo
    ON emendas_federais_cgu (codigo_emenda);

-- ------------------------------------------------------------ documentos ---
-- A linha do tempo da execução: quando foi empenhada, liquidada, paga.
--
-- ⚠️ NENHUMA COLUNA DE DINHEIRO, e isso é a fonte, não esquecimento: o
-- `DocumentoRelacionadoEmendaDTO` NÃO traz valor. Ele responde QUANDO e EM QUE
-- FASE, jamais QUANTO. Uma coluna de valor aqui convidaria a tela a somar
-- documentos como se fossem pagamentos.
--
-- ⚠️ E SEM `municipio_id`, pelo mesmo motivo do agregado: o documento é da
-- emenda inteira, e uma emenda pode atender vários municípios. Carimbar um
-- município aqui seria inventar um vínculo que a fonte não afirma.
CREATE TABLE IF NOT EXISTS emendas_federais_documentos (
    id                        SERIAL PRIMARY KEY,
    codigo_emenda             VARCHAR(12) NOT NULL,
    documento_id              BIGINT NOT NULL,
    data                      DATE,
    -- Empenho · Liquidação · Pagamento. ⚠️ TEXT e não VARCHAR(n): é vocabulário
    -- de fonte externa, e o Governo renomeia categoria sem avisar — uma
    -- categoria de 41 caracteres numa VARCHAR(40) abortou a carga inteira do
    -- santamaria no obrasgov (ver add_obrasgov_taxonomias_text.sql).
    fase                      TEXT,
    codigo_documento          VARCHAR(60),
    codigo_documento_resumido VARCHAR(40),
    especie_tipo              TEXT,
    tipo_emenda               TEXT,
    raw_data                  JSONB,
    visto_em                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    criado_em                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_emendas_federais_documentos
    ON emendas_federais_documentos (codigo_emenda, documento_id);
CREATE INDEX IF NOT EXISTS ix_emendas_federais_doc_codigo
    ON emendas_federais_documentos (codigo_emenda, fase);

-- ---------------------------------------------------------------- rodízio ---
-- O livro-caixa da fase CGU: o que já foi perguntado, quando, e o que voltou.
--
-- ⚠️ SEM ESTA TABELA A COTA VAZA. Um código que a CGU NÃO conhece não deixa
-- linha em nenhuma das duas tabelas acima — e a rodada seguinte o pergunta de
-- novo, para sempre. Com ~2.400 códigos no tenant maior, isso é o orçamento
-- inteiro de uma noite gasto em nada, toda noite.
--
-- É também o que permite a rodada CONTINUAR DE ONDE PAROU entre madrugadas: a
-- primeira carga de um tenant grande leva três noites e isso NÃO é defeito —
-- mesmo desenho do `tce_rs_portal`. Precedente da forma: `scraper_municipio_coleta`.
CREATE TABLE IF NOT EXISTS emendas_federais_consulta (
    codigo_emenda  VARCHAR(12) PRIMARY KEY,
    -- 'siconv' (derivado do dump) ou 'transferegov_te' (o código já vem PRONTO
    -- no `codigoEmendaFormatado`, no formato '202341760002-Nome do Parlamentar').
    -- ⭐ Os da TE são o GRUPO DE CONTROLE do dia 1: foram formatados pelo próprio
    -- Governo, então uma resposta vazia neles acusa a chave ou o endpoint, e
    -- nunca a nossa derivação.
    origem         VARCHAR(20) NOT NULL DEFAULT 'siconv',
    ano            SMALLINT,
    consultado_em  TIMESTAMPTZ,
    agregados_em   TIMESTAMPTZ,
    documentos_em  TIMESTAMPTZ,
    -- ⚠️ TRÊS ESTADOS, NUNCA DOIS. NULL = nunca perguntamos; FALSE = perguntamos
    -- e a CGU não conhece o código; TRUE = achou. Um valor zero na tabela do
    -- agregado é a CGU AFIRMANDO zero — coisa diferente das outras duas, e
    -- confundi-las é a única forma de a tela mentir com números certos.
    achou_agregado BOOLEAN,
    n_documentos   INTEGER,
    tentativas     SMALLINT NOT NULL DEFAULT 0,
    ultimo_erro    TEXT,
    criado_em      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- O rodízio: nunca consultado primeiro, depois o mais velho.
CREATE INDEX IF NOT EXISTS ix_emendas_federais_consulta_rodizio
    ON emendas_federais_consulta (consultado_em NULLS FIRST);
CREATE INDEX IF NOT EXISTS ix_emendas_federais_consulta_ano
    ON emendas_federais_consulta (ano DESC);
