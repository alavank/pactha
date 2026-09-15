-- VOLUNTARIAS: a ARVORE da proposta pelos dumps de Discricionarias e Legais
-- (15/09/2026). Coletor: `ingestion/transferegov_arvore.py`.
--
-- Os 65 zips de `api-publica.transferegov.gestao.gov.br/downloads/dadosgov/`
-- trazem, por proposta, o que o PACTHA buscava RASPANDO o portal — parte atras
-- de sessao gov.br (morta 297 h em 720 h) — e muito que nao buscava de lugar
-- nenhum: aditivos, prorrogacoes, pagamentos com o fornecedor e a nota, plano
-- de trabalho, justificativas, medicoes, contrapartida, rendimento.
--
-- ONDE CADA COISA MORA:
--   `transferegov_propostas.arvore` — o que e PEQUENO por proposta: o convenio
--     inteiro, emendas + apoiadores, indicadores, historico de situacao,
--     projeto basico, justificativas, metas -> etapas, plano de aplicacao,
--     cronograma, obras/medicoes, CIPI (e o elo com o Obras.gov), empenhos,
--     desembolsos, tributos, aditivos, prorrogacoes, solicitacoes, contrapartida,
--     rendimento, desbloqueio, e o `_resumo` calculado pelo coletor. Linhas
--     CRUAS da fonte, pelos nomes das colunas do CSV (campo vazio omitido).
--   tres TABELAS para as listas GRANDES (medido em 15/09/2026, carteira do
--   tamanho da Trust): ate 12.868 pagamentos, 12.912 documentos de liquidacao e
--   11.333 licitacoes NUM SO convenio. No JSONB da proposta isso seria um modal
--   de megabytes; aqui a tela pagina.
--   `tg_propostas_canceladas` — as canceladas vem num arquivo PROPRIO, que o
--     PACTHA nunca leu, e a regra de categoria das telas nao conhece o status
--     (cairia em Voluntarias ativas). Ficam separadas.
--
-- `ops_obs_aberto` tem o MESMO formato do `ops_obs` raspado; os leitores usam
-- COALESCE(aberto, raspado): o dump manda, a raspagem vira reserva.
--
-- ⚠️ NULO SIGNIFICA "AINDA NAO COLHIDO", nunca "nao ha". O coletor so troca uma
-- secao quando TODOS os arquivos dela foram lidos inteiros.
ALTER TABLE transferegov_propostas
    ADD COLUMN IF NOT EXISTS arvore                 JSONB,
    ADD COLUMN IF NOT EXISTS arvore_atualizado_em   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ops_obs_aberto         JSONB;

CREATE INDEX IF NOT EXISTS ix_tg_propostas_id_siconv_mun
    ON transferegov_propostas (municipio_id, id_proposta_siconv);

CREATE TABLE IF NOT EXISTS tg_licitacoes (
    id              BIGSERIAL PRIMARY KEY,
    municipio_id    INTEGER NOT NULL REFERENCES municipios(id),
    id_licitacao    TEXT NOT NULL,
    id_proposta     TEXT NOT NULL,
    nr_convenio     TEXT,
    numero          TEXT,
    modalidade      TEXT,
    status          TEXT,
    data_publicacao TEXT,
    valor           NUMERIC(18, 2),
    dados           JSONB,
    contratos       JSONB,
    itens           JSONB,
    atualizado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tg_licitacoes ON tg_licitacoes (municipio_id, id_licitacao);
CREATE INDEX IF NOT EXISTS ix_tg_licitacoes_proposta ON tg_licitacoes (municipio_id, id_proposta);

CREATE TABLE IF NOT EXISTS tg_pagamentos (
    id              BIGSERIAL PRIMARY KEY,
    municipio_id    INTEGER NOT NULL REFERENCES municipios(id),
    nr_mov_fin      TEXT NOT NULL,
    id_proposta     TEXT NOT NULL,
    nr_convenio     TEXT,
    data_pagamento  TEXT,
    fornecedor_doc  TEXT,
    fornecedor_nome TEXT,
    tipo            TEXT,
    id_dl           TEXT,
    valor           NUMERIC(18, 2),
    dados           JSONB,
    favorecidos     JSONB,
    atualizado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tg_pagamentos ON tg_pagamentos (municipio_id, nr_mov_fin);
CREATE INDEX IF NOT EXISTS ix_tg_pagamentos_proposta ON tg_pagamentos (municipio_id, id_proposta);

CREATE TABLE IF NOT EXISTS tg_documentos_liquidacao (
    id              BIGSERIAL PRIMARY KEY,
    municipio_id    INTEGER NOT NULL REFERENCES municipios(id),
    id_dl           TEXT NOT NULL,
    id_proposta     TEXT NOT NULL,
    id_licitacao    TEXT,
    id_contrato     TEXT,
    data_emissao    TEXT,
    numero          TEXT,
    descricao       TEXT,
    razao_social    TEXT,
    valor           NUMERIC(18, 2),
    status          TEXT,
    dados           JSONB,
    itens           JSONB,
    atualizado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tg_documentos_liquidacao ON tg_documentos_liquidacao (municipio_id, id_dl);
CREATE INDEX IF NOT EXISTS ix_tg_documentos_liquidacao_proposta ON tg_documentos_liquidacao (municipio_id, id_proposta);

CREATE TABLE IF NOT EXISTS tg_propostas_canceladas (
    id                BIGSERIAL PRIMARY KEY,
    municipio_id      INTEGER NOT NULL REFERENCES municipios(id),
    id_proposta       TEXT NOT NULL,
    numero_proposta   TEXT,
    proponente        TEXT,
    natureza_juridica TEXT,
    municipal         BOOLEAN,
    objeto            TEXT,
    orgao             TEXT,
    valor_global      NUMERIC(18, 2),
    dados             JSONB,
    atualizado_em     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tg_propostas_canceladas ON tg_propostas_canceladas (municipio_id, id_proposta);
