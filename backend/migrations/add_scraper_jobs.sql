-- Fila de jobs de scraping on-demand (ex.: refresh SIGCON disparado pela UI).
-- Substitui o antigo gatilho on-demand que disparava um redeploy remoto via API da plataforma.
-- O Worker (Scheduled Task no Coolify) consome via ingestion/run_queue_sigcon.py.
-- Idempotente (roda no boot da API via services/startup.py).
CREATE TABLE IF NOT EXISTS scraper_jobs (
    id           BIGSERIAL   PRIMARY KEY,
    tipo         TEXT        NOT NULL,
    status       TEXT        NOT NULL DEFAULT 'pending',  -- pending | running | done | error
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,
    error        TEXT
);

-- Acelera o claim/dedup (buscar pending/running por tipo).
CREATE INDEX IF NOT EXISTS idx_scraper_jobs_tipo_status
    ON scraper_jobs (tipo, status);
