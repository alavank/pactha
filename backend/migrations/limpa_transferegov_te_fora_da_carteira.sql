-- Remove de `transferegov_te` os planos de UF que o tenant nao acompanha.
--
-- ⚠️ SAO SOBRA DE UM BUG, nao dado legitimo. O coletor tinha `TE_UF` com default
-- "MG" (`ingestion/transferegov_te.py`), e nenhum dos 4 tenants define essa
-- variavel — entao TODO tenant baixava Minas Gerais inteiro (~8773 planos). No
-- Freitas e no Monte Siao dava certo por coincidencia: sao de MG. No Trust
-- (ES/GO/MG/TO) e no Santa Maria (RS) o beneficiario nunca casava com municipio
-- da carteira, e as linhas entravam com `municipio_id` NULL.
--
-- Essas linhas sao INVISIVEIS para o produto: tanto `routers/transferegov` como
-- `services/rm_builder` leem com `WHERE municipio_id = :m`. Ou seja, nao havia
-- tela errada — havia disco gasto e, muito pior, as Transferencias Especiais dos
-- municipios REAIS desses dois tenants nunca coletadas. O coletor corrigido
-- passa a percorrer as UFs da carteira; esta migration limpa o que ficou.
--
-- Idempotente: na segunda vez nao encontra mais nada.

DO $$
DECLARE
    n_ufs int;
    apagadas int;
BEGIN
    -- ⚠️ GUARDA CONTRA APAGAR TUDO. Se a carteira estiver vazia ou sem UF
    -- preenchida, o NOT IN abaixo casaria com TODAS as linhas. Banco recem
    -- criado, seed ainda por rodar, restore pela metade: o custo de errar aqui e
    -- perder a coleta inteira, e o de nao agir e adiar uma limpeza. Nao age.
    SELECT count(DISTINCT upper(uf)) INTO n_ufs
      FROM municipios WHERE uf IS NOT NULL AND btrim(uf) <> '';

    IF n_ufs = 0 THEN
        RAISE NOTICE 'transferegov_te: carteira sem UF definida — limpeza PULADA';
        RETURN;
    END IF;

    DELETE FROM transferegov_te
     WHERE upper(coalesce(uf, '')) NOT IN (
            SELECT upper(uf) FROM municipios
             WHERE uf IS NOT NULL AND btrim(uf) <> '')
       -- Cinto de seguranca: so o que nunca casou com municipio nenhum. Uma
       -- linha COM municipio_id foi util a alguma tela, e divergencia de UF ali
       -- seria outro problema — que apagar esconderia em vez de resolver.
       AND municipio_id IS NULL;

    GET DIAGNOSTICS apagadas = ROW_COUNT;
    IF apagadas > 0 THEN
        RAISE NOTICE 'transferegov_te: % linha(s) de UF fora da carteira removidas', apagadas;
    END IF;
END $$;
