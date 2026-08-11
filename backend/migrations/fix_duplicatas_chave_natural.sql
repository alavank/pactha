-- ⭐ DUPLICATAS: a chave de identidade estava errada em duas tabelas.
--
-- Achado em 11/08/2026 pelo dono, olhando a tela: a MESMA emenda (nº 157912,
-- R$ 9,2 mi, Fábio Avelar / Nova Serrana) aparecia DUAS vezes. Medido depois nos
-- três clientes: no freitas eram 195 linhas fantasma em `emendas_estaduais`,
-- inflando o total em R$ 74.702.744,03 (+34%) — e 7 linhas em
-- `convenios_estadual`, inflando R$ 1.563.275,67.
--
-- ⚠️ AS DUAS CAUSAS SÃO A MESMA DOENÇA: um campo que DESCREVE o registro entrou
-- na chave que o IDENTIFICA.
--
--   1. EMENDAS — o unique era (nr_indicacao, ano). Só que `ano` não é atributo
--      da indicação: o SIGCON não devolve essa coluna. É o ANO DO FILTRO que o
--      coletor escolhe no dropdown ao varrer 2022→2026. A mesma indicação
--      devolvida sob dois filtros não conflitava e virava linha nova. Prova de
--      que é duplicata e não histórico: nas 190 indicações repetidas, ZERO têm
--      valor, status ou município divergente entre os "anos" — são cópias
--      idênticas.
--
--   2. CONVÊNIOS — a chave era `nr_sigcon`, que MUDA de valor durante a vida do
--      convênio: enquanto está em celebração vale o nº do plano; quando é
--      assinado, passa a valer o nº SIAFI. Chave que muda não é chave — o
--      upsert não encontrava a linha antiga e inseria uma segunda. A chave certa
--      é `nr_proposta`, que nasce no cadastramento, nunca muda e está preenchido
--      em 100% das linhas (contra 58% do SIAFI).
--
-- Esta migration roda no boot de TODOS os tenants (decisão do dono: "isso tem
-- que ser corrigido e ser padrão para todos e para os próximos"). Ela é
-- IDEMPOTENTE: onde já está limpo, não apaga nada; onde a constraint já está
-- certa, não faz nada. Trust e Monte Sião hoje têm ZERO duplicata — e passam a
-- ter a trava que impede o problema de nascer lá.

-- =========================================================================
-- 1. EMENDAS ESTADUAIS
-- =========================================================================

-- 1.1 Backup só se houver o que deduplicar (e só uma vez).
DO $$
DECLARE n bigint;
BEGIN
    SELECT count(*) INTO n FROM (
        SELECT ROW_NUMBER() OVER (PARTITION BY municipio_id, nr_indicacao
                                  ORDER BY ano ASC, updated_at DESC, id ASC) rn
        FROM emendas_estaduais
        WHERE nr_indicacao IS NOT NULL AND btrim(nr_indicacao) <> ''
    ) t WHERE rn > 1;
    IF n > 0 AND to_regclass('public.emendas_estaduais_bkp_dup') IS NULL THEN
        EXECUTE 'CREATE TABLE emendas_estaduais_bkp_dup AS SELECT * FROM emendas_estaduais';
        RAISE NOTICE 'emendas: backup criado, % linha(s) duplicada(s) a remover', n;
    END IF;
END $$;

-- 1.2 Dedupe. SOBREVIVE A DE MENOR `ano` — que é o ano em que a fonte reportou
--     a indicação pela primeira vez, e portanto o correto. (As duas regras
--     candidatas — menor ano e mais recente — coincidiram em 190 de 190 grupos,
--     então a escolha é robusta; e como as linhas são idênticas, nada de dado
--     bom se perde.)
WITH ranked AS (
    SELECT id, ROW_NUMBER() OVER (PARTITION BY municipio_id, nr_indicacao
                                  ORDER BY ano ASC, updated_at DESC, id ASC) rn
    FROM emendas_estaduais
    WHERE nr_indicacao IS NOT NULL AND btrim(nr_indicacao) <> ''
)
DELETE FROM emendas_estaduais e USING ranked r
 WHERE e.id = r.id AND r.rn > 1;

-- 1.3 A chave certa. Só troca depois do dedupe — o ADD CONSTRAINT é a própria
--     validação: se sobrasse duplicata, ele falharia e a transação inteira
--     voltaria atrás.
ALTER TABLE emendas_estaduais DROP CONSTRAINT IF EXISTS uq_emendas_estaduais_nr_ano;
DROP INDEX IF EXISTS uq_emendas_estaduais_nr_ano;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'uq_emendas_estaduais_mun_nr') THEN
        ALTER TABLE emendas_estaduais
          ADD CONSTRAINT uq_emendas_estaduais_mun_nr UNIQUE (municipio_id, nr_indicacao);
    END IF;
END $$;

-- =========================================================================
-- 2. CONVÊNIOS ESTADUAIS (só as linhas do SIGCON-MG — a tabela é compartilhada
--    com FNS e GConv-ES, que têm identidade própria e não entram nisto)
-- =========================================================================

-- 2.1 O scraper nunca gravou a COLUNA `nr_proposta` (o número só existia dentro
--     do raw_data). Sem este backfill a chave nova nasceria vazia e não
--     protegeria nada.
UPDATE convenios_estadual
   SET nr_proposta = nullif(btrim(raw_data->>'nr_proposta'), '')
 WHERE fonte = 'SIGCON-MG'
   AND (nr_proposta IS NULL OR btrim(nr_proposta) = '')
   AND nullif(btrim(raw_data->>'nr_proposta'), '') IS NOT NULL;

-- 2.2 Backup só quando houver duplicata.
DO $$
DECLARE n bigint;
BEGIN
    SELECT count(*) INTO n FROM (
        SELECT ROW_NUMBER() OVER (PARTITION BY municipio_id, nr_proposta
                                  ORDER BY (nullif(nr_siafi,'') IS NOT NULL) DESC,
                                           (situacao = 'Em vigor') DESC,
                                           updated_at DESC, id DESC) rn
        FROM convenios_estadual
        WHERE fonte = 'SIGCON-MG' AND nr_proposta IS NOT NULL AND btrim(nr_proposta) <> ''
    ) t WHERE rn > 1;
    IF n > 0 AND to_regclass('public.convenios_estadual_bkp_dup') IS NULL THEN
        EXECUTE 'CREATE TABLE convenios_estadual_bkp_dup AS '
                'SELECT * FROM convenios_estadual WHERE fonte = ''SIGCON-MG''';
        RAISE NOTICE 'convenios: backup criado, % linha(s) duplicada(s) a remover', n;
    END IF;
END $$;

-- 2.3 Dedupe. SOBREVIVE quem tem nº SIAFI (o convênio celebrado, que é o estado
--     mais avançado); empate → quem está "Em vigor"; empate → o mais recente.
--     Medido: as 7 linhas que saem no freitas estão todas em fases anteriores
--     (Análise, Assinatura, Publicação, Cadastramento) e NENHUM convênio
--     "Em vigor" é afetado.
WITH ranked AS (
    SELECT id, ROW_NUMBER() OVER (PARTITION BY municipio_id, nr_proposta
                                  ORDER BY (nullif(nr_siafi,'') IS NOT NULL) DESC,
                                           (situacao = 'Em vigor') DESC,
                                           updated_at DESC, id DESC) rn
    FROM convenios_estadual
    WHERE fonte = 'SIGCON-MG' AND nr_proposta IS NOT NULL AND btrim(nr_proposta) <> ''
)
DELETE FROM convenios_estadual c USING ranked r
 WHERE c.id = r.id AND r.rn > 1;

-- 2.4 A trava. Índice PARCIAL: vale só para o SIGCON-MG e só onde há número de
--     proposta — as linhas de FNS/GConv-ES seguem com a identidade delas.
--     ⚠️ Índice parcial exige repetir o predicado no ON CONFLICT do coletor
--     (armadilha que já travou o SIGCON por 24 dias, calada, em outra ocasião).
CREATE UNIQUE INDEX IF NOT EXISTS ux_convenios_sigcon_mun_proposta
    ON convenios_estadual (municipio_id, nr_proposta)
 WHERE fonte = 'SIGCON-MG' AND nr_proposta IS NOT NULL AND btrim(nr_proposta) <> '';
