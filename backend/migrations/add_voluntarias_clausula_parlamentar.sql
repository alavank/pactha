-- Novos campos das Voluntarias para o RM:
--   situacao_contratacao         Ex: "Em Andamento" / "Clausula Suspensiva" / "Conta Pendente de Regularizacao"
--   clausula_suspensiva_dt_prevista  Data prevista para resolucao (quando aplicavel)
--   clausula_suspensiva_motivo   Motivo da clausula suspensiva (texto curto)
--   parlamentar                  Parlamentar responsavel pela indicacao
ALTER TABLE transferegov_propostas ADD COLUMN IF NOT EXISTS situacao_contratacao TEXT;
ALTER TABLE transferegov_propostas ADD COLUMN IF NOT EXISTS clausula_suspensiva_dt_prevista DATE;
ALTER TABLE transferegov_propostas ADD COLUMN IF NOT EXISTS clausula_suspensiva_motivo TEXT;
ALTER TABLE transferegov_propostas ADD COLUMN IF NOT EXISTS parlamentar TEXT;
