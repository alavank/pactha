-- PAGAMENTOS da Transferencia Especial (Emenda Pix) no plano de acao.
--
-- Origem: os dois endpoints PUBLICOS da mesma base que o coletor ja usa,
-- descobertos no bundle da SPA de especiais (main.js -> getPublicUrlDocumentoHabil
-- / getPublicUrlOpob; chunks 527 e 32), e CONFERIDOS AO VIVO no plano 91573:
--   /api/public/documentos-habeis/plano-acao/resumido/{planoAcaoId}  (a grade
--     "Lista de Documentos Habeis": empenho, minuta, DH, valor, situacao, OP)
--   /api/public/opob/{opObId}  (ordem bancaria, ordenador, gestor financeiro e o
--     HISTORICO DE EVENTOS DE PAGAMENTO)
--
-- O JSONB e gravado no MESMO formato do `transferegov_propostas.ops_obs` das
-- voluntarias (chaves valor_desembolsado / valor_a_desembolsar /
-- data_ultimo_desembolso / obs[].data_emissao_ob|valor|numero_ob|situacao), de
-- proposito: assim o RM reusa services/rm_builder._desembolso_ops_obs e
-- _ano_pagamento_ops_obs nas duas fontes, sem parser novo e sem as duas
-- divergirem de formato com o tempo. E `rm_pdf._desembolso_destaque` — que ja e
-- generico sobre o dict do item — passa a imprimir a caixa da TE de graca.
--
-- `pagamentos_atualizado_em` e o skip incremental (espelha ops_obs_atualizado_em):
-- carimba MESMO quando o plano nao tem documento habil, senao os ~30% de planos
-- sem DH consumiriam a rodada inteira todo dia.
--
-- ⚠️ NULO SIGNIFICA "NAO MEDIDO", nao "nao ha pagamento". O RM so escreve
-- PENDENTE DE DESEMBOLSO quando ha medida — mesma disciplina de _nes_resumo.
-- Idempotente (ADD COLUMN IF NOT EXISTS), roda nos 4 bancos.
ALTER TABLE transferegov_te
    ADD COLUMN IF NOT EXISTS pagamentos               JSONB,
    ADD COLUMN IF NOT EXISTS pagamentos_atualizado_em TIMESTAMPTZ;

-- A fila do coletor de pagamentos: carteira + vencidos primeiro.
CREATE INDEX IF NOT EXISTS idx_te_pgto_fila
    ON transferegov_te (pagamentos_atualizado_em NULLS FIRST)
    WHERE municipio_id IS NOT NULL;
