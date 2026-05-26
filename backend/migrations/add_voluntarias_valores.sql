-- Valores monetarios das Transferencias Voluntarias (TransfereGov/SICONV).
-- Capturados pelo scraper a partir da tela de detalhe (Valor Global/Repasse/Contrapartida).
-- Idempotente: ADD COLUMN IF NOT EXISTS.
ALTER TABLE transferegov_propostas ADD COLUMN IF NOT EXISTS valor_global NUMERIC;
ALTER TABLE transferegov_propostas ADD COLUMN IF NOT EXISTS valor_repasse NUMERIC;
ALTER TABLE transferegov_propostas ADD COLUMN IF NOT EXISTS valor_contrapartida NUMERIC;
