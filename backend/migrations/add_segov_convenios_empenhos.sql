-- Empenhos e PAGAMENTOS do Estado de MG por convenio, do DADO ABERTO da SEGOV.
--
-- Fonte: dataset CKAN `portal_convenios_saida` (dados.mg.gov.br, SEGOV, semanal):
--   pagamento{ano}.csv    empenhos do exercicio: numero, data de registro, credor,
--                         UO, elemento/item, fonte, valor EMPENHADO, LIQUIDADO e
--                         PAGO (valor_pago_financeiro)
--   pagamentorp{ano}.csv  restos a pagar: liquidado, pago processado e nao processado
-- Os dois chegam CHAVEADOS pelo nº SIAFI do convenio (`contratoconvenio_saida`).
-- ⚠️ A auditoria de 11/09/2026 mediu 100% de juncao desse campo com o
-- `convenios_saida.numero_siafi` do MESMO dataset (SEGOV x SEGOV); a juncao
-- com o `nr_siafi` que o scraper grava em `convenios_estadual` e hipotese ate
-- a primeira carga (o coletor loga "N de M convenios com SIAFI casaram").
--
-- ⚠️ POR QUE ISTO EXISTE, se ja ha `transparencia_mg_empenhos`. Aquela tabela e
-- alimentada pelo Portal da Transparencia (Joomla), que RECUSA o IP do
-- datacenter (403) e nao tem task — em producao ela esta vazia e a caixa de
-- desembolso dos estaduais nunca enche. O CSV da SEGOV responde de qualquer IP
-- com UA de navegador. Ele nao traz DATA do pagamento, nº da OB nem situacao da
-- ordem — traz o QUANTO (empenhado/liquidado/pago) por nota de empenho, e e
-- isso que o RM passa a mostrar. O Joomla continua sendo a fonte do detalhe da
-- OB quando (se) responder: o RM prefere ele e cai para esta tabela na falta.
--
-- ⚠️ TABELA PROPRIA, e nao linha em `transparencia_mg_empenhos`: a chave
-- primaria de la e o `id_empenho` INTERNO do Joomla, que o CSV nao tem. Inventar
-- um id para caber la misturaria duas identidades na mesma coluna.
--
-- ⚠️ SO ENTRA LINHA QUE CASOU COM UM CONVENIO NOSSO (por SIAFI). O CSV e do
-- Estado inteiro; guardar tudo seria 5 mil linhas/ano por tenant sem municipio
-- para pendurar. Convenio raspado DEPOIS ganha seus empenhos na rodada seguinte
-- (o upsert re-vincula `convenio_id` a cada carga).
--
-- `ON DELETE SET NULL` em convenio_id e obrigatorio, nao estilo:
-- `fix_duplicatas_chave_natural.sql` faz DELETE em convenios_estadual a cada boot.
CREATE TABLE IF NOT EXISTS segov_convenios_empenhos (
    id              BIGSERIAL PRIMARY KEY,
    municipio_id    INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    convenio_id     INTEGER REFERENCES convenios_estadual(id) ON DELETE SET NULL,
    -- `contratoconvenio_saida` do CSV = nº SIAFI do convenio.
    nr_siafi        VARCHAR(30) NOT NULL,
    -- De qual arquivo veio: o ano do nome (pagamento2026 -> 2026) e o tipo
    -- ('pg' = pagamento{ano}, 'rp' = pagamentorp{ano}).
    ano_arquivo     INTEGER NOT NULL,
    tipo            VARCHAR(2) NOT NULL,
    numero_empenho  VARCHAR(40) NOT NULL,
    dt_empenho      DATE,                -- data_registro_doc_empenho
    credor_nome     TEXT,
    credor_doc      VARCHAR(20),         -- cnpj_cpf_credor_formatado, como veio
    uo_sigla        VARCHAR(30),
    uo_nome         TEXT,
    fonte_recurso   TEXT,
    -- ⚠️ NULO = a coluna NAO EXISTE naquele arquivo (restos a pagar nao traz
    -- empenhado), nunca "zero". Zero e "0,0" no CSV e chega como 0.
    vr_empenhado    NUMERIC(18, 2),
    vr_liquidado    NUMERIC(18, 2),
    -- pagamento{ano}: valor_pago_financeiro; restos a pagar: processado + nao processado.
    vr_pago         NUMERIC(18, 2),
    raw_data        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Identidade DA FONTE: a mesma NE aparece a cada carga semanal com o pago
-- crescendo; e por aqui que o upsert a reconhece. A UO entra porque o numero
-- do empenho e sequencial POR unidade orcamentaria.
CREATE UNIQUE INDEX IF NOT EXISTS ux_segov_emp_chave
    ON segov_convenios_empenhos (nr_siafi, ano_arquivo, tipo, numero_empenho, COALESCE(uo_sigla, ''));
CREATE INDEX IF NOT EXISTS ix_segov_emp_mun
    ON segov_convenios_empenhos (municipio_id);
CREATE INDEX IF NOT EXISTS ix_segov_emp_conv
    ON segov_convenios_empenhos (convenio_id) WHERE convenio_id IS NOT NULL;
