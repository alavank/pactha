-- id_proposta_siconv: ID interno da proposta no SICONV (idProposta), usado para
-- casar com o open data siconv_emenda (ID_PROPOSTA -> NOME_PARLAMENTAR).
-- O scraper passa a guardar esse id (vem da URL de detalhe ?idProposta=NNN);
-- o backfill (siconv_emenda_backfill.py) preenche o parlamentar a partir dele.
ALTER TABLE transferegov_propostas ADD COLUMN IF NOT EXISTS id_proposta_siconv TEXT;
CREATE INDEX IF NOT EXISTS idx_tgprop_id_proposta_siconv ON transferegov_propostas (id_proposta_siconv);
