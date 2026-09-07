-- Remove de `transferegov_te` os planos atribuidos ao municipio ERRADO pelo
-- casamento por nome que o coletor usava ate 06/09/2026.
--
-- ⚠️ SAO SOBRA DE UM BUG ESTRUTURAL, e nao dado legitimo. O coletor antigo
-- (`ingestion/transferegov_te.py`, funcao `_casa_municipio`) decidia de que
-- municipio era o plano procurando o NOME do municipio DENTRO do nome do
-- beneficiario:
--
--     'MUNICIPIO DE NOVA SERRANA' contem 'SERRANA'  ->  creditado a Serrana
--
-- A contaminacao estava medida antes desta limpeza: 628 de 890 linhas do tenant
-- trust tinham `beneficiario_cnpj` divergente do CNPJ do municipio a que a linha
-- fora atribuida. Diferente da sobra que `limpa_transferegov_te_fora_da_carteira`
-- apagou — aquelas eram linhas com `municipio_id` NULO, invisiveis ao produto —,
-- ESTAS aparecem na tela e no Relatorio de Monitoramento do municipio errado.
--
-- O coletor novo entra por CNPJ (`municipios.cnpj` -> `id_beneficiario` -> planos
-- daquele beneficiario), entao o vinculo passa a ser exato. Ele tambem CORRIGE
-- sozinho, no primeiro upsert, toda linha cujo beneficiario esteja na carteira:
-- a PK e `plano_acao_id` e os ids sao os mesmos nas duas fontes. O que ele nao
-- alcanca — e o que esta migration apaga — sao os planos de municipios FORA da
-- carteira que foram creditados a alguem DE dentro: como nenhuma rodada futura
-- os visita, ficariam para sempre na tela de quem nao e dono deles.
--
-- ⚠️ SO APAGA COM PROVA DOS DOIS LADOS. Exige `beneficiario_cnpj` na linha E
-- `municipios.cnpj` no municipio: sem os dois nao ha como afirmar divergencia, e
-- "nao sei" nunca pode virar DELETE. Onde o CNPJ do municipio ainda esta vazio a
-- linha fica como esta — `ingestion/siconfi.py` preenche esse campo sozinho a
-- partir do cadastro do Tesouro, e a proxima rodada desta migration resolve.
--
-- ⚠️ E RESPEITA `municipio_entidades`. A Transferencia Especial vai ao ente
-- federativo (498 beneficiarios do RS conferidos em 06/09/2026: todos
-- municipios, nenhum fundo), mas se um dia o beneficiario for um fundo do
-- proprio municipio, o CNPJ dele esta cadastrado la — e a linha e legitima.
--
-- Idempotente: na segunda vez nao encontra mais nada.

DO $$
DECLARE
    apagadas int;
BEGIN
    DELETE FROM transferegov_te te
     WHERE te.municipio_id IS NOT NULL
       -- Os dois CNPJs tem de existir para a comparacao significar algo.
       AND coalesce(regexp_replace(coalesce(te.beneficiario_cnpj, ''), '\D', '', 'g'), '') <> ''
       AND EXISTS (
            SELECT 1 FROM municipios m
             WHERE m.id = te.municipio_id
               AND coalesce(regexp_replace(coalesce(m.cnpj, ''), '\D', '', 'g'), '') <> '')
       -- Nao e o CNPJ da prefeitura a que a linha foi atribuida...
       AND NOT EXISTS (
            SELECT 1 FROM municipios m
             WHERE m.id = te.municipio_id
               AND regexp_replace(coalesce(m.cnpj, ''), '\D', '', 'g')
                 = regexp_replace(te.beneficiario_cnpj, '\D', '', 'g'))
       -- ...nem de uma entidade daquele municipio (fundo, hospital, autarquia).
       AND NOT EXISTS (
            SELECT 1 FROM municipio_entidades e
             WHERE e.municipio_id = te.municipio_id
               AND regexp_replace(coalesce(e.cnpj, ''), '\D', '', 'g')
                 = regexp_replace(te.beneficiario_cnpj, '\D', '', 'g'));

    GET DIAGNOSTICS apagadas = ROW_COUNT;
    IF apagadas > 0 THEN
        RAISE NOTICE 'transferegov_te: % linha(s) com vinculo de municipio falso removidas', apagadas;
    END IF;
END $$;
