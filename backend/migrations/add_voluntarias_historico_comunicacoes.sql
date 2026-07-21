-- Histórico de Comunicações + Documentos do Quadro Resumo (Projeto Básico /
-- Documentos Orçamentários do TransfereGov "mandatárias").
-- Traz o andamento REAL da análise: eventos (análise iniciada, laudo emitido,
-- aceite, SPA concluída...), com SITUAÇÃO e CONSIDERAÇÕES do concedente, além
-- dos Termos de Notificação enviados. Exige sessão gov.br (área /private/).
ALTER TABLE transferegov_propostas
    ADD COLUMN IF NOT EXISTS historico_comunicacoes JSONB,
    ADD COLUMN IF NOT EXISTS documentos_quadro_resumo JSONB,
    ADD COLUMN IF NOT EXISTS historico_atualizado_em TIMESTAMPTZ;
