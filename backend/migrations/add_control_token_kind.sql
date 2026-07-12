-- Control-plane token (Console Alavank): terceiro tipo de principal, distinto do
-- JWT de usuario e do service token de scraper. A coluna `kind` discrimina:
--   'scraper' (default, tokens dos scrapers) | 'control' (token do Console).
ALTER TABLE service_tokens ADD COLUMN IF NOT EXISTS kind TEXT DEFAULT 'scraper';
