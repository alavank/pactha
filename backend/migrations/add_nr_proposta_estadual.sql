-- Adiciona campos especificos de exibicao SIGCON-MG: nr_proposta, nr_plano_trabalho,
-- qt_alteracoes (Quantidade de Alteracoes Concluidas) e dt_assinatura.
-- Idempotente.

ALTER TABLE convenios_estadual ADD COLUMN IF NOT EXISTS nr_proposta VARCHAR(50);
ALTER TABLE convenios_estadual ADD COLUMN IF NOT EXISTS nr_plano_trabalho VARCHAR(50);
ALTER TABLE convenios_estadual ADD COLUMN IF NOT EXISTS qt_alteracoes INTEGER DEFAULT 0;
ALTER TABLE convenios_estadual ADD COLUMN IF NOT EXISTS dt_assinatura DATE;

CREATE INDEX IF NOT EXISTS ix_convenios_estadual_nr_proposta
ON convenios_estadual (nr_proposta) WHERE nr_proposta IS NOT NULL;
