-- Codigo FNS (6 digitos) por municipio, p/ des-hardcodar run_fns_local.py.
-- Idempotente (roda no boot via services/startup.py).
ALTER TABLE municipios ADD COLUMN IF NOT EXISTS fns_code VARCHAR(6);
