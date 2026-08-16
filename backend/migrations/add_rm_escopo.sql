-- RM COMPLETO (todos os anos) x RM ANUAL: coexistem por um `escopo`.
--
-- Ate aqui havia UM RM por (municipio_id, data_referencia). O RM "completo"
-- (padrao Freitas, todos os anos, 4 partes por estagio) precisa coexistir com os
-- anuais SEM colidir na data — a data_referencia dele e so a data de EMISSAO.
-- Resolvemos com uma coluna `escopo` ('anual'|'completo') e uma unique TRIPLA
-- (municipio_id, data_referencia, escopo) no lugar da dupla.
--
-- Idempotente. NAO toca em nenhuma linha existente: todas nascem 'anual' (default),
-- que e exatamente o que ja eram.
ALTER TABLE rm_relatorios
    ADD COLUMN IF NOT EXISTS escopo VARCHAR(12) NOT NULL DEFAULT 'anual';

-- Derruba a unique ANTIGA (municipio_id, data_referencia) — seja qual for o nome
-- auto-gerado da constraint — para que a data possa repetir entre 'anual' e
-- 'completo'. So mexe em unique de EXATAMENTE essas duas colunas.
DO $$
DECLARE cname text;
BEGIN
  SELECT c.conname INTO cname
  FROM pg_constraint c
  WHERE c.conrelid = 'rm_relatorios'::regclass
    AND c.contype = 'u'
    AND c.conkey = ARRAY[
      (SELECT attnum FROM pg_attribute WHERE attrelid='rm_relatorios'::regclass AND attname='municipio_id'),
      (SELECT attnum FROM pg_attribute WHERE attrelid='rm_relatorios'::regclass AND attname='data_referencia')
    ]::smallint[]
  LIMIT 1;
  IF cname IS NOT NULL THEN
    EXECUTE format('ALTER TABLE rm_relatorios DROP CONSTRAINT %I', cname);
  END IF;
END $$;

-- A nova unique TRIPLA. E tambem o alvo do ON CONFLICT (municipio_id,
-- data_referencia, escopo) do endpoint de criacao (routers/rm.py).
CREATE UNIQUE INDEX IF NOT EXISTS ux_rm_mun_data_escopo
    ON rm_relatorios (municipio_id, data_referencia, escopo);
