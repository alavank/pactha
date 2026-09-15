-- RM por SELEÇÃO de anos: um único relatório cujo ESCOPO são os anos escolhidos.
--
-- Novo modelo (substitui o par 'anual'|'completo'): a geração é UMA só — o
-- usuário seleciona os anos e gera UM relatório com eles juntos. Seleção vazia
-- (Todos) = o COMPLETO (todos os anos). O escopo vira a coluna `anos` (INT[]),
-- sempre ORDENADA e sem repetição (normalizada no router), e a identidade do
-- relatório passa a ser (municipio_id, anos).
--
-- Idempotente. Backfill preserva os RMs existentes: os anuais viram [ano da
-- data_referencia]; um eventual 'completo' vira {} (todos).
ALTER TABLE rm_relatorios
    ADD COLUMN IF NOT EXISTS anos INT[] NOT NULL DEFAULT '{}';

-- Backfill (só onde ainda está no default vazio):
UPDATE rm_relatorios
   SET anos = ARRAY[EXTRACT(YEAR FROM data_referencia)::int]
 WHERE anos = '{}' AND escopo = 'anual' AND data_referencia IS NOT NULL;
UPDATE rm_relatorios
   SET anos = '{}'
 WHERE escopo = 'completo';

-- Troca a chave: de (municipio, data, escopo) para (municipio, anos).
-- ux_rm_mun_data_escopo foi criada como UNIQUE INDEX (ver add_rm_escopo.sql).
DROP INDEX IF EXISTS ux_rm_mun_data_escopo;

-- ⚠️⚠️ O CREATE ABAIXO SÓ RODA SE A IDENTIDADE NOVA AINDA NÃO EXISTIR.
--
-- Este arquivo rodava a CADA BOOT (até 15/09/2026 o runner de services/startup.py
-- não guardava "já aplicada"; hoje roda de novo quando é editado, e banco novo
-- roda tudo), e `IF NOT EXISTS` só protege enquanto o índice EXISTE. Depois que
-- `drop_rm_unique_anos.sql` o derruba, este CREATE volta a tentar recriá-lo — e
-- no primeiro dia em que um RM FILTRADO por consultas conviver com o COMPLETO do
-- mesmo período, ele passa a falhar com "could not create unique index ... is
-- duplicated".
--
-- E aí o estrago é triplo e silencioso:
--   1. o runner classifica o erro por SUBSTRING e "duplicat" cai no filtro que
--      loga "ja aplicada (skip)" — ninguém vê problema nenhum no log;
--   2. o arquivo inteiro é UM `cur.execute()`, ou seja, UMA transação: a falha
--      aborta também o ALTER e os dois UPDATE acima;
--   3. isso passa a acontecer em TODO boot, nos QUATRO tenants, para sempre.
--
-- O guard é a condição inversa: enquanto a identidade nova
-- (`ux_rm_mun_anos_fontes`) não existir, a antiga é recriada como sempre foi;
-- assim que ela existir, este bloco vira no-op. ⚠️ TEM DE ESTAR EM PRODUÇÃO
-- ANTES do deploy que derruba `ux_rm_mun_anos`.
DO $$
BEGIN
    IF to_regclass('public.ux_rm_mun_anos_fontes') IS NULL THEN
        CREATE UNIQUE INDEX IF NOT EXISTS ux_rm_mun_anos
            ON rm_relatorios (municipio_id, anos);
    END IF;
END $$;
