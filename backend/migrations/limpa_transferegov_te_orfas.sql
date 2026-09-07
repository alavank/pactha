-- Remove de `transferegov_te` os planos que nunca pertenceram a municipio nenhum
-- da carteira — 40.707 linhas nos cinco tenants, 97,8% da tabela (medido em
-- 07/09/2026).
--
-- ⚠️ SAO O RESIDUO DE UM MODELO DE COLETA QUE ACABOU. Ate 06/09/2026 o coletor
-- baixava a UF INTEIRA e depois tentava adivinhar, por semelhanca de nome, de
-- que municipio era cada plano. O que nao casava entrava com `municipio_id`
-- NULO e ficava. Medido por tenant, antes desta limpeza:
--
--     freitas       8.771 linhas ->    565 vinculadas,  8.206 orfas  (94%)
--     trust        13.181 linhas ->    278 vinculadas, 12.903 orfas  (98%)
--     montesiao     8.771 linhas ->     20 vinculadas,  8.751 orfas  (99,8%)
--     santamaria    5.337 linhas ->     41 vinculadas,  5.296 orfas  (99,2%)
--     novapalma     5.554 linhas ->      3 vinculadas,  5.551 orfas  (99,9%)
--
-- ⭐ POR QUE AGORA, E NAO ANTES. Enquanto a coleta era por UF, essas linhas
-- tinham uma funcao teorica: se um municipio vizinho entrasse na carteira, o
-- plano dele ja estaria baixado. O coletor novo entra por CNPJ, municipio a
-- municipio (`ingestion/transferegov_te.run_municipios`) — ele nunca mais visita
-- essas linhas, e municipio novo na carteira tem os planos dele buscados em DUAS
-- requisicoes. Elas deixaram de ser reserva e viraram peso morto.
--
-- Elas sempre foram invisiveis ao produto: `routers/transferegov.buscar` e
-- `services/rm_builder` leem os dois com `WHERE municipio_id = :m`. Nao ha tela
-- que mude, nem relatorio que perca linha. O que se ganha e uma tabela ~45x
-- menor, e o fim da duvida recorrente de "por que a TE tem 13 mil linhas se o
-- tenant tem 20 municipios".
--
-- ⚠️ GUARDA CONTRA APAGAR TUDO, e ela e o coracao desta migration. Num banco
-- onde o coletor ainda nao rodou — tenant novo, restore pela metade, primeiro
-- boot — TODA linha estaria com `municipio_id` nulo, e este DELETE limparia a
-- tabela inteira. Por isso so age quando ja existe vinculo: se nenhuma linha
-- tem municipio, o estado nao e "sobra para limpar", e sim "coleta que ainda nao
-- aconteceu". Mesma doutrina do `n_ufs = 0` em
-- `limpa_transferegov_te_fora_da_carteira.sql`.
--
-- Idempotente: na segunda vez nao encontra mais nada.

DO $$
DECLARE
    vinculadas int;
    apagadas int;
BEGIN
    SELECT count(*) INTO vinculadas
      FROM transferegov_te WHERE municipio_id IS NOT NULL;

    IF vinculadas = 0 THEN
        RAISE NOTICE 'transferegov_te: nenhuma linha vinculada a municipio — '
                     'limpeza PULADA (coleta ainda nao rodou neste banco)';
        RETURN;
    END IF;

    DELETE FROM transferegov_te WHERE municipio_id IS NULL;

    GET DIAGNOSTICS apagadas = ROW_COUNT;
    IF apagadas > 0 THEN
        RAISE NOTICE 'transferegov_te: % linha(s) orfa(s) removidas (% vinculada(s) mantidas)',
                     apagadas, vinculadas;
    END IF;
END $$;
