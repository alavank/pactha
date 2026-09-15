-- GESTAO DE PARCERIAS pela API oficial INTEIRA (15/09/2026): a arvore de cada
-- proposta e as emendas indicadas ao municipio.
--
-- `detalhe` guarda, por proposta, as rotas de
-- `api-publica.transferegov.gestao.gov.br/parcerias` penduradas nela: metas com
-- etapas e itens, cronograma de desembolso, analise (texto do parecer),
-- indicadores de resultado, e — por parceria celebrada — a CONTA (saldo em conta
-- corrente e em investimento, classificacao de ingresso), o extrato, os
-- pagamentos da conta a terceiros (OPP), os empenhos e documento habil -> ordem
-- de pagamento (a OB). Resposta CRUA da fonte, pelos nomes que ela manda, mais
-- um `_resumo` calculado pelo coletor (`ingestion/parcerias.execucao_da_arvore`).
--
-- JSONB na linha do pai, pelo mesmo desenho de `transferegov_te.detalhe`
-- (add_te_detalhe.sql): a arvore e lida INTEIRA, sempre de uma proposta so.
--
-- ⚠️ NULO SIGNIFICA "AINDA NAO COLHIDO", nunca "a proposta nao tem nada". O
-- coletor so grava arvore completa: consulta sem resposta = nada gravado.
--
-- `nu_externo` e o numero da proposta no SISTEMA DE ORIGEM — para a saude, o
-- `nuProposta` do FNS (conferido: 12240183000126003 abre a mesma proposta de Nova
-- Palma no ConsultaFNS). Em coluna, e com indice, para o cruzamento com as
-- propostas FNS (`convenios_estadual`) nao precisar de requisicao nenhuma.
ALTER TABLE parcerias_propostas
    ADD COLUMN IF NOT EXISTS detalhe               JSONB,
    ADD COLUMN IF NOT EXISTS detalhe_atualizado_em TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS nu_externo            TEXT;

-- Linhas gravadas antes desta coluna: o `nu_externo` ja estava no raw_data
-- (`_parceria`), entao nao precisa esperar a proxima rodada. Idempotente pelo
-- `IS NULL`.
UPDATE parcerias_propostas
   SET nu_externo = raw_data->'_parceria'->>'nu_externo'
 WHERE nu_externo IS NULL
   AND raw_data->'_parceria'->>'nu_externo' IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_parcerias_propostas_nu_externo
    ON parcerias_propostas (nu_externo) WHERE nu_externo IS NOT NULL;

-- A fila da arvore: os mais velhos primeiro.
CREATE INDEX IF NOT EXISTS ix_parcerias_propostas_detalhe_fila
    ON parcerias_propostas (detalhe_atualizado_em NULLS FIRST);

-- EMENDAS INDICADAS AO MUNICIPIO (`/beneficiario_emenda_parlamentar`). Chegam
-- ANTES da proposta: e a emenda que o parlamentar ja destinou ao fundo ou a
-- prefeitura, com GND3/GND4 e as indicacoes de apoiador, exista proposta ou nao.
-- E a pergunta "tem dinheiro indicado para nos que ainda nao foi usado?", que
-- nenhuma tela respondia.
--
-- Uma linha por (municipio, registro da fonte). O coletor troca o conjunto do
-- municipio inteiro quando a consulta volta completa — indicacao retirada na
-- fonte some daqui tambem.
CREATE TABLE IF NOT EXISTS parcerias_emendas_indicadas (
    id                     BIGSERIAL PRIMARY KEY,
    municipio_id           INTEGER NOT NULL REFERENCES municipios(id),
    id_beneficiario_emenda BIGINT NOT NULL,
    id_programa            BIGINT,
    cnpj_beneficiario      VARCHAR(14),
    nome_beneficiario      TEXT,
    natureza_juridica      TEXT,
    ano_emenda             INTEGER,
    numero_emenda          TEXT,
    parlamentar            TEXT,
    tipo_emenda            TEXT,
    valor_gnd3             NUMERIC(18, 2),
    valor_gnd4             NUMERIC(18, 2),
    valor_total            NUMERIC(18, 2),
    indicacoes             JSONB,
    raw_data               JSONB,
    atualizado_em          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_parcerias_emendas_indicadas
    ON parcerias_emendas_indicadas (municipio_id, id_beneficiario_emenda);
CREATE INDEX IF NOT EXISTS ix_parcerias_emendas_indicadas_emenda
    ON parcerias_emendas_indicadas (numero_emenda);
