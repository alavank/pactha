-- TCE-RS pelo PORTAL — o mesmo Tribunal, por um host que responde.
--
-- O `dados.tce.rs.gov.br` (CKAN) devolve 403 ao IP da VPS desde 17/08/2026,
-- medido quatro vezes. O `portal.tce.rs.gov.br` é OUTRO host, com API sem
-- autenticação, e entrega o MESMO acervo: 866 licitações e 1.202 contratos de
-- Nova Palma (2007-2026) contra as 864 e 1.201 do CKAN — a diferença são dois
-- contratos registrados depois. Não é um subconjunto do dump bloqueado; é o
-- dump, mais o que o CSV não tinha.
--
-- ⚠️ O QUE ESTA MIGRATION NÃO CRIA: `tce_rs_licitacoes` e `tce_rs_contratos`.
-- Elas já existem (`add_tce_rs.sql`) e são as MESMAS — a chave natural do
-- LicitaCon é a mesma pelos dois caminhos, então os dois coletores fazem UPSERT
-- na mesma linha em vez de duplicá-la. O que entra aqui são as colunas que só o
-- portal traz, e três tabelas de coisas que o CKAN não tem.
--
-- ⚠️⚠️ E DUAS COLUNAS SÓ O CKAN TRAZ: `vl_licitacao` e `vl_homologado`. A API do
-- portal NÃO publica valor de licitação em endpoint nenhum (conferido no
-- Swagger, nos 15 campos da lista e nos 27 do detalhe). Por isso o UPSERT do
-- coletor do portal não menciona esses dois campos — se o CKAN um dia for
-- liberado e preencher, a rodada do portal NÃO os apaga. Valor de CONTRATO o
-- portal tem, e melhor: inicial E atual, que o CSV não separava.

-- ---------------------------------------------------------------------------
-- 1. As colunas que só o portal traz
-- ---------------------------------------------------------------------------
ALTER TABLE tce_rs_licitacoes ADD COLUMN IF NOT EXISTS tp_situacao VARCHAR(4);
ALTER TABLE tce_rs_licitacoes ADD COLUMN IF NOT EXISTS ds_situacao TEXT;
-- WEB = registrado direto no LicitaCon Web · VAL = veio por remessa do
-- e-Validador. Não é curiosidade técnica: decide se a data da remessa é do
-- município ou do Tribunal (ver a tabela `tce_rs_remessas`, abaixo).
ALTER TABLE tce_rs_licitacoes ADD COLUMN IF NOT EXISTS aplic_origem VARCHAR(8);
ALTER TABLE tce_rs_licitacoes ADD COLUMN IF NOT EXISTS incluido_na_fonte TIMESTAMP;
ALTER TABLE tce_rs_licitacoes ADD COLUMN IF NOT EXISTS atualizado_na_fonte TIMESTAMP;

ALTER TABLE tce_rs_contratos ADD COLUMN IF NOT EXISTS tp_situacao VARCHAR(4);
ALTER TABLE tce_rs_contratos ADD COLUMN IF NOT EXISTS ds_situacao TEXT;
ALTER TABLE tce_rs_contratos ADD COLUMN IF NOT EXISTS aplic_origem VARCHAR(8);
-- O NOME do contratado. O CSV do CKAN só trazia o documento (`nr_documento`), e
-- CNPJ sem razão social não é legível numa tela de gestor.
ALTER TABLE tce_rs_contratos ADD COLUMN IF NOT EXISTS nm_contratado TEXT;
-- ⚠️ DOIS VALORES, e a diferença é o aditivo: `vl_contrato` recebe o VALOR
-- INICIAL (é o que o CSV do CKAN gravava ali, e é o que a tela já soma) e
-- `vl_atual` é o valor depois de acréscimos, supressões, reajustes e
-- reequilíbrios. Guardar só um deles esconderia exatamente o que o Tribunal
-- fiscaliza.
ALTER TABLE tce_rs_contratos ADD COLUMN IF NOT EXISTS vl_atual NUMERIC(18,2);
ALTER TABLE tce_rs_contratos ADD COLUMN IF NOT EXISTS licitacao_origem TEXT;
ALTER TABLE tce_rs_contratos ADD COLUMN IF NOT EXISTS incluido_na_fonte TIMESTAMP;
ALTER TABLE tce_rs_contratos ADD COLUMN IF NOT EXISTS atualizado_na_fonte TIMESTAMP;
-- ⚠️ A COLUNA QUE FAZ O JOB CABER NA JANELA. O valor do contrato só existe no
-- endpoint de DETALHE, que é UMA requisição por contrato — Santa Maria tem
-- 6.213. Aqui fica a VERSÃO da fonte que o detalhe guardado reflete: recebe uma
-- cópia do `DATA_ATUALIZACAO` que veio na lista no momento em que o detalhe foi
-- buscado. A pendência é então `detalhe_da_versao IS DISTINCT FROM
-- atualizado_na_fonte`, e o coletor gasta seu orçamento de tempo só nela — a
-- primeira carga se completa em algumas noites em vez de estourar o timeout
-- todas elas.
--
-- ⚠️ Guarda a VERSÃO e não a HORA DA BUSCA de propósito: comparar "quando
-- olhei" (TIMESTAMPTZ, UTC) com "quando a fonte mudou" (TIMESTAMP sem fuso, em
-- horário de Brasília) erra por três horas duas vezes por dia — e o erro é
-- silencioso, ora rebuscando tudo, ora nunca rebuscando nada.
ALTER TABLE tce_rs_contratos ADD COLUMN IF NOT EXISTS detalhe_da_versao TIMESTAMP;
ALTER TABLE tce_rs_licitacoes ADD COLUMN IF NOT EXISTS detalhe_da_versao TIMESTAMP;

CREATE INDEX IF NOT EXISTS ix_tce_rs_contratos_detalhe
    ON tce_rs_contratos (municipio_id, detalhe_da_versao NULLS FIRST);
CREATE INDEX IF NOT EXISTS ix_tce_rs_licitacoes_detalhe
    ON tce_rs_licitacoes (municipio_id, detalhe_da_versao NULLS FIRST);


-- ---------------------------------------------------------------------------
-- 2. REMESSAS — e o que elas de fato dizem
-- ---------------------------------------------------------------------------
-- ⚠️⚠️ LEIA ANTES DE MOSTRAR ISTO COMO "O MUNICÍPIO ENTREGOU EM DIA".
--
-- A remessa do tipo **LicitaCon WEB** NÃO é entrega do município: é a carga
-- noturna do próprio Tribunal. Medido em 03/09/2026 contra a fonte: nove órgãos
-- de OITO tipos diferentes (prefeitura, autarquia, fundação, consórcio, empresa
-- pública, sociedade anônima, associação, sociedade limitada) têm, no mesmo
-- período, a MESMA data e o mesmo horário — 2026/7 em todos eles é 10/08/2026
-- entre 05:12 e 05:19. Nova Palma e Santa Maria coincidem nos 19 meses medidos.
-- Um município que atrasasse teria a mesma data de um que não atrasou.
--
-- A remessa do tipo **e-Validador** é envio de verdade: as quatro de Nova Palma
-- em agosto/2025 são de 15, 22, 27 e 29/08, e nenhum outro órgão tem essas
-- datas. Só que o município que registra direto no LicitaCon Web não envia
-- nenhuma — e Nova Palma parou de enviar em 2026.
--
-- O que esta tabela serve, então: dizer POR QUAL VIA o município opera, se o
-- período foi consolidado, e quem é o responsável cadastrado. Pontualidade se
-- mede por outro caminho — a defasagem entre `dt_assinatura` e
-- `incluido_na_fonte` do contrato (medida: mediana de 1 dia em Nova Palma e 5
-- em Santa Maria, nenhum acima de 30 — os dois estão em dia).
CREATE TABLE IF NOT EXISTS tce_rs_remessas (
    id                SERIAL PRIMARY KEY,
    municipio_id      INTEGER NOT NULL REFERENCES municipios(id),
    cd_orgao          VARCHAR(10) NOT NULL,
    ano_exercicio     INTEGER NOT NULL,
    periodo_mes       INTEGER NOT NULL,
    -- "LicitaCon WEB" (carga do TCE) ou "e-Validador - LicitaCon" (envio do
    -- órgão). É a coluna que decide como ler `dt_recebimento`.
    tipo_remessa      TEXT NOT NULL,
    -- Recibo de Validação e Entrega. É o identificador da remessa e o que a
    -- torna única dentro do período.
    cod_barras_rve    VARCHAR(32) NOT NULL,
    dt_recebimento    TIMESTAMP,
    cd_situacao       VARCHAR(4),
    ds_situacao       TEXT,
    nome_responsavel  TEXT,
    cargo_responsavel TEXT,
    raw_data          JSONB,
    atualizado_em     TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_tce_rs_remessas
    ON tce_rs_remessas (cd_orgao, ano_exercicio, periodo_mes, cod_barras_rve);
CREATE INDEX IF NOT EXISTS ix_tce_rs_remessas_mun
    ON tce_rs_remessas (municipio_id, ano_exercicio DESC, periodo_mes DESC);


-- ---------------------------------------------------------------------------
-- 3. LICITACON OBRAS — a obra que o convênio pagou, com medição e saldo
-- ---------------------------------------------------------------------------
-- Sistema instituído pela Resolução TCE-RS 1.176/2023 e obrigatório para órgão
-- municipal desde 08/01/2024. É a fonte que faltava do lado da EXECUÇÃO: o
-- TransfereGov mostra o repasse, o LicitaCon mostra o contrato, e esta mostra
-- se a obra andou — percentual medido, saldo, paralisação e previsão de
-- reinício.
--
-- ⚠️ ZERO OBRA É RESULTADO LEGÍTIMO, e não falha de coleta: Santa Maria tem 120,
-- Nova Palma tem 0. O sistema é de 2024 e município pequeno pode não ter obra
-- sujeita a registro. Mesma disciplina do SISMOB — a ausência é gravada como
-- rodada bem-sucedida com zero linha, nunca como erro.
CREATE TABLE IF NOT EXISTS tce_rs_obras (
    id                SERIAL PRIMARY KEY,
    municipio_id      INTEGER NOT NULL REFERENCES municipios(id),
    -- Identificador da obra no sistema do TCE. É global (não reinicia por
    -- órgão nem por ano), então sozinho já é a chave natural.
    id_obra           INTEGER NOT NULL,
    cd_orgao          VARCHAR(10) NOT NULL,
    nm_orgao          TEXT,
    ds_objeto         TEXT,
    endereco          TEXT,
    bairro            TEXT,
    ds_tipo_obra      TEXT,
    tp_situacao_obra  VARCHAR(8),
    ds_situacao_obra  TEXT,
    -- O ELO COM O CONTRATO. Os três campos são a chave de `tce_rs_contratos`,
    -- e é por eles que a obra encontra a licitação, o objeto e o contratado.
    nr_contrato       INTEGER,
    ano_contrato      INTEGER,
    tp_instrumento    VARCHAR(4),
    nm_contratado     TEXT,
    nr_doc_contratado VARCHAR(20),
    dt_inicio_vigencia DATE,
    dt_fim_vigencia    DATE,
    vl_inicial        NUMERIC(18,2),
    vl_atual          NUMERIC(18,2),
    vl_total_medido   NUMERIC(18,2),
    vl_saldo          NUMERIC(18,2),
    -- ⚠️ DOIS PERCENTUAIS, e eles DIVERGEM: na obra 436 de Santa Maria o
    -- financeiro está em 90,6% e o físico (`pc_executado`) em 0,0 — o órgão
    -- mede o pagamento e não alimenta o avanço físico. Mostrar um pelo outro
    -- inventaria execução que ninguém declarou.
    pc_financeiro_exec NUMERIC(9,4),
    pc_executado       NUMERIC(9,4),
    dt_evento_paralisacao DATE,
    ds_motivo_paralisacao TEXT,
    dt_previsao_reinicio  DATE,
    qt_medicoes       INTEGER,
    dt_ultima_medicao DATE,
    qt_termos_aditivos INTEGER,
    raw_data          JSONB,
    atualizado_em     TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_tce_rs_obras ON tce_rs_obras (id_obra);
CREATE INDEX IF NOT EXISTS ix_tce_rs_obras_mun
    ON tce_rs_obras (municipio_id, tp_situacao_obra);
CREATE INDEX IF NOT EXISTS ix_tce_rs_obras_contrato
    ON tce_rs_obras (cd_orgao, nr_contrato, ano_contrato, tp_instrumento);


-- ---------------------------------------------------------------------------
-- 4. ORIGEM DO RECURSO — por que esta tabela é a razão de todo o resto
-- ---------------------------------------------------------------------------
-- É aqui que a obra encontra o CONVÊNIO que a pagou. Exemplo real, obra 436 de
-- Santa Maria: tipo "Convênio/Repasse Federal", fonte "Ministério da Integração
-- e do Desenvolvimento Regional", processo 59053.018691/2024-19,
-- R$ 2.431.396,74, contrapartida zero. Em nenhuma outra fonte do PACTHA esse
-- vínculo é declarado pelo próprio município ao órgão de controle.
--
-- Uma obra pode ter várias origens (federal + estadual + tesouro), e por isso é
-- tabela e não coluna.
CREATE TABLE IF NOT EXISTS tce_rs_obras_recursos (
    id                SERIAL PRIMARY KEY,
    municipio_id      INTEGER NOT NULL REFERENCES municipios(id),
    id_obra           INTEGER NOT NULL,
    id_origem_recurso INTEGER NOT NULL,
    -- FDL = Convênio/Repasse Federal · e há os equivalentes estadual e próprio.
    cod_tp_recurso    VARCHAR(8),
    ds_tp_recurso     TEXT,
    ds_fonte_recurso  TEXT,
    -- O número do convênio ou do processo, como o município o declarou. Texto
    -- livre de propósito: vem "Processo 59053.018691/2024-19" numa obra e o
    -- número puro em outra, e normalizar aqui apagaria o que a fonte disse.
    ds_convenio_contrato TEXT,
    data_recurso      DATE,
    vl_recurso        NUMERIC(18,2),
    vl_contrapartida  NUMERIC(18,2),
    raw_data          JSONB,
    atualizado_em     TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_tce_rs_obras_recursos
    ON tce_rs_obras_recursos (id_obra, id_origem_recurso);
CREATE INDEX IF NOT EXISTS ix_tce_rs_obras_recursos_mun
    ON tce_rs_obras_recursos (municipio_id, cod_tp_recurso);
