-- A-3 (auditoria 11/09) — PREPARADA, NÃO REGISTRADA em MIGRATION_FILES ainda.
--
-- Adiciona rastreabilidade de início/heartbeat ao ingestion_log, para o watchdog
-- detectar job que começou e morreu antes do finished_at. Idempotente e
-- retrocompatível: só ADICIONA colunas anuláveis; nenhuma leitura atual quebra
-- (o /api/status/ingestao e o control/ingestion leem source/status/records/
-- finished_at, que continuam iguais).
--
-- ⚠️ Só entra em vigor quando (a) for adicionada a MIGRATION_FILES em
-- services/startup.py e (b) os coletores adotarem services/ingest_heartbeat.py.
-- Enquanto não registrada, este arquivo é inerte (migrations só rodam se listadas).
-- Ver docs/CHECKLIST_CORRECOES_AUDITORIA.md.

ALTER TABLE ingestion_log ADD COLUMN IF NOT EXISTS started_at   TIMESTAMPTZ;
ALTER TABLE ingestion_log ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;

-- Índice para o watchdog achar rápido linhas 'running' com heartbeat velho.
CREATE INDEX IF NOT EXISTS ix_ingestion_log_running
    ON ingestion_log (source, heartbeat_at)
    WHERE status = 'running';
