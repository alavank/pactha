-- Emendas estaduais de MG: o OBJETO e a FASE DO PLANO de cada indicação (25/09/2026).
--
-- A Transferência Especial estadual (TE-MG) não vira convênio: a tela só mostrava o
-- objeto do convênio ligado, então a TE aparecia sem dizer para que é o dinheiro. O
-- CSV da SEGOV no dados.mg.gov.br (emendas_mg.py) traz o título do plano de trabalho
-- ("CONSTRUÇÃO DA COBERTURA DA QUADRA...") e a fase do instrumento (ANÁLISE TÉCNICA,
-- ADEQUAÇÃO, VIGENTE...) — ADEQUAÇÃO é a prefeitura que precisa corrigir o plano.
--
-- Idempotente; nas duas tabelas de add_emendas_estaduais_execucao.sql, que vem antes.
ALTER TABLE emendas_estaduais ADD COLUMN IF NOT EXISTS objeto TEXT;
ALTER TABLE emendas_estaduais ADD COLUMN IF NOT EXISTS fase_plano VARCHAR(80);
ALTER TABLE emendas_estaduais_outros ADD COLUMN IF NOT EXISTS objeto TEXT;
ALTER TABLE emendas_estaduais_outros ADD COLUMN IF NOT EXISTS fase_plano VARCHAR(80);
