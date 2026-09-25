-- LIBERAÇÕES DO FNDE com o FAVORECIDO (24/09/2026) — `ingestion/fnde_liberacoes.py`.
--
-- Até aqui `simec_par_liberacoes` só recebia o relatório do SIMEC, que mostra UM
-- CNPJ (o da prefeitura) e só o ano corrente. A consulta de liberações do FNDE
-- (`pls/simad`) lista TODA entidade do município — prefeitura, secretaria de
-- educação, fundos, caixas escolares — e qualquer ano de 2000 em diante. Três
-- coisas mudam na tabela:
--
-- 1. QUEM RECEBEU: `cnpj_favorecido`, `favorecido`, `tipo_favorecido` (as chaves de
--    `services/liberacoes_fnde.TIPOS`, as mesmas da CGU) e `fonte` ('simec' |
--    'fnde_simad').
--    ⚠️ Os DEFAULTs são o que toda linha antiga É: veio do SIMEC, que só lê a
--    prefeitura. Então linha antiga = `tipo_favorecido 'prefeitura'`, `fonte
--    'simec'` — e a soma de todo leitor, que agora filtra pelo tipo, não muda para
--    o que já existia. ADD COLUMN com DEFAULT constante não reescreve a tabela.
--
-- 2. A CHAVE ÚNICA GANHA O CNPJ. Medido em 24/09/2026: a MESMA OB, na MESMA data,
--    paga VÁRIAS caixas escolares (o PDDE sai numa OB de lista) — em Monte Sião a
--    OB 007948 de 30/04/2026 paga 6 caixas e a 008849 de 08/05/2026 paga 7; 2025 e
--    Nova Palma repetem o padrão. Na chave antiga (municipio_id, programa,
--    dt_pgto, ob) as seis virariam UMA linha, sobrescrita em silêncio. (cnpj, programa, data, OB) não repete em
--    nenhum dos 4 recortes medidos (2 municípios x 2025/2026, 335 liberações).
--    `cnpj_favorecido` é NOT NULL DEFAULT '' de propósito: NULL é distinto de NULL
--    numa UNIQUE, e a linha sem CNPJ duplicaria a cada rodada.
--
-- 3. O CNPJ das linhas antigas: o da prefeitura (`municipios.cnpj`), que é o que o
--    SIMEC mostra. Sem ele (tenant que não cadastrou), fica '' — e o coletor novo
--    apaga a linha do SIMEC quando grava a MESMA liberação (data + OB) da
--    prefeitura vinda do simad (`fnde_liberacoes._SQL_SUPERA_SIMEC`).
--
-- Idempotente: ADD COLUMN IF NOT EXISTS; o backfill só toca linha com CNPJ vazio;
-- a unique nova é superconjunto da antiga (não pode falhar num banco que já
-- respeita a antiga); a antiga é achada pelas COLUNAS, seja qual for o nome.
-- ⚠️ DDL em tabela que o coletor escreve: deployar FORA da janela de coleta
-- (depois das 10:00 UTC) ou com as coletas pausadas — skill `migrations`, regra 6.

ALTER TABLE simec_par_liberacoes ADD COLUMN IF NOT EXISTS cnpj_favorecido TEXT NOT NULL DEFAULT '';
ALTER TABLE simec_par_liberacoes ADD COLUMN IF NOT EXISTS favorecido TEXT;
ALTER TABLE simec_par_liberacoes ADD COLUMN IF NOT EXISTS tipo_favorecido TEXT NOT NULL DEFAULT 'prefeitura';
ALTER TABLE simec_par_liberacoes ADD COLUMN IF NOT EXISTS fonte TEXT NOT NULL DEFAULT 'simec';

UPDATE simec_par_liberacoes AS l
   SET cnpj_favorecido = m.cnpj
  FROM municipios AS m
 WHERE m.id = l.municipio_id
   AND l.cnpj_favorecido = ''
   AND l.fonte = 'simec'
   AND m.cnpj ~ '^[0-9]{14}$';

-- A chave nova. É também o alvo do ON CONFLICT dos dois coletores.
CREATE UNIQUE INDEX IF NOT EXISTS ux_simec_lib_favorecido
    ON simec_par_liberacoes (municipio_id, cnpj_favorecido, programa, dt_pgto, ob);

-- Derruba a UNIQUE antiga (municipio_id, programa, dt_pgto, ob) — só ela, achada
-- pelas colunas (o nome auto-gerado é `simec_par_liberacoes_municipio_id_programa_dt_pgto_ob_key`).
DO $$
DECLARE cname text;
BEGIN
  SELECT c.conname INTO cname
  FROM pg_constraint c
  WHERE c.conrelid = 'simec_par_liberacoes'::regclass
    AND c.contype = 'u'
    AND c.conkey = ARRAY[
      (SELECT attnum FROM pg_attribute WHERE attrelid = 'simec_par_liberacoes'::regclass AND attname = 'municipio_id'),
      (SELECT attnum FROM pg_attribute WHERE attrelid = 'simec_par_liberacoes'::regclass AND attname = 'programa'),
      (SELECT attnum FROM pg_attribute WHERE attrelid = 'simec_par_liberacoes'::regclass AND attname = 'dt_pgto'),
      (SELECT attnum FROM pg_attribute WHERE attrelid = 'simec_par_liberacoes'::regclass AND attname = 'ob')
    ]::smallint[]
  LIMIT 1;
  IF cname IS NOT NULL THEN
    EXECUTE format('ALTER TABLE simec_par_liberacoes DROP CONSTRAINT %I', cname);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_simec_lib_mun_tipo ON simec_par_liberacoes (municipio_id, tipo_favorecido);

-- O que o simad já respondeu por (município, ano): a data de "fechamento" que o
-- FNDE carimba em toda página (a tela mostra), quantas entidades a lista trouxe e
-- se o ano foi lido INTEIRO. É também o estado da carga inicial: ano passado com
-- `completo` não é relido (o corrente e o anterior são, toda noite).
CREATE TABLE IF NOT EXISTS fnde_liberacoes_carga (
    municipio_id   INT NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    ano            INT NOT NULL,
    fechamento     DATE,
    n_entidades    INT NOT NULL DEFAULT 0,
    n_liberacoes   INT NOT NULL DEFAULT 0,
    completo       BOOLEAN NOT NULL DEFAULT false,
    erro           TEXT,
    atualizado_em  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (municipio_id, ano)
);
