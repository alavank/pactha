-- Detalhe generico da Situacao de Contratacao Atual (qualquer tipo de detalhe,
-- nao so Clausula Suspensiva). O scraper segue o botao "Detalhar..." da linha
-- e captura todos os pares label/valor da pagina de detalhe.
ALTER TABLE transferegov_propostas ADD COLUMN IF NOT EXISTS situacao_contratacao_detalhe JSONB;
