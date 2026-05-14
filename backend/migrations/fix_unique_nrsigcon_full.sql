-- Corrige UNIQUE INDEX de nr_sigcon: era parcial (WHERE nr_sigcon IS NOT NULL),
-- agora total. Permite ON CONFLICT (nr_sigcon) sem precisar de WHERE clause.
-- Idempotente: drop+recreate (sem WHERE).

DROP INDEX IF EXISTS ix_convenios_estadual_nrsigcon;

-- Garante nr_sigcon NOT NULL antes (quaisquer NULL viram SIGCON-{id})
UPDATE convenios_estadual SET nr_sigcon = 'SIGCON-AUTO-' || id WHERE nr_sigcon IS NULL;

-- Recria UNIQUE total (case-insensitive sem acentos nao precisa - nr_sigcon eh codigo numerico)
CREATE UNIQUE INDEX ix_convenios_estadual_nrsigcon
ON convenios_estadual (nr_sigcon);
