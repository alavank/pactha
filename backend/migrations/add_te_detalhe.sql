-- A ARVORE DO PLANO da Transferencia Especial (Emenda Pix) pela API OFICIAL,
-- e a DATA EM QUE CADA FONTE SE ATUALIZOU (14/09/2026).
--
-- `detalhe` guarda, por plano de acao, os outros 21 recursos de
-- `api-publica.transferegov.gestao.gov.br/especiais` pendurados nele: plano de
-- trabalho (vigencia, pareceres, historico), executores (metas, finalidades),
-- empenhos -> documentos habeis -> OP/OB, a conta (saldo e extrato com
-- favorecido), relatorios de gestao (com QUEM RECEBEU o dinheiro do municipio),
-- devolucoes e o historico do plano. Resposta CRUA da fonte, pelos nomes que
-- ela manda — ver `ingestion/transferegov_te.arvore_do_plano`.
--
-- JSONB NA LINHA DO PAI, e nao uma tabela por recurso, pelo mesmo desenho das
-- irmas (`pagamentos` aqui, `relatorios_gestao` no faf_planos_acao): a arvore
-- e lida INTEIRA, sempre de um plano so, pela tela de detalhe.
--
-- ⚠️ NULO SIGNIFICA "AINDA NAO COLHIDO", nunca "o plano nao tem nada". O
-- coletor so grava arvore completa: consulta sem resposta = nada gravado.
--
-- `detalhe_atualizado_em` e a fila (os mais velhos primeiro), no molde de
-- `pagamentos_atualizado_em` (add_te_pagamentos.sql).
ALTER TABLE transferegov_te
    ADD COLUMN IF NOT EXISTS detalhe               JSONB,
    ADD COLUMN IF NOT EXISTS detalhe_atualizado_em TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_te_detalhe_fila
    ON transferegov_te (detalhe_atualizado_em NULLS FIRST)
    WHERE municipio_id IS NOT NULL;

-- QUANDO A PROPRIA FONTE FOI ATUALIZADA — outra coisa que a hora da nossa
-- coleta. As quatro APIs novas do TransfereGov expoem `/data-atualizacao`;
-- coletar as 3h nao significa que a fonte mudou as 3h, e fonte que parou de se
-- atualizar continuava parecendo em dia no Frescor. Uma linha por fonte, com
-- chave de texto: a primeira e `transferegov_especiais`, e as proximas APIs
-- entram aqui sem migration nova.
CREATE TABLE IF NOT EXISTS fonte_atualizacao (
    fonte         TEXT PRIMARY KEY,
    data_fonte    TIMESTAMPTZ,
    consultado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
