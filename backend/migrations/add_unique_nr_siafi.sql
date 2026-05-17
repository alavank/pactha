-- Unique index em convenios_estadual.nr_siafi para prevenir duplicacao
-- entre scraper Playwright (nr_sigcon=siafi numerico) e CKAN bulk
-- (nr_sigcon=instrumento XXXXXXXXXX/YYYY).
--
-- ATENCAO: requer que duplicatas pre-existentes ja tenham sido deduplicadas.
-- A migration eh idempotente (IF NOT EXISTS) e parcial (so quando nr_siafi nao nulo).

CREATE UNIQUE INDEX IF NOT EXISTS ux_convenios_estadual_nr_siafi
  ON convenios_estadual(nr_siafi)
  WHERE nr_siafi IS NOT NULL AND nr_siafi != '';
