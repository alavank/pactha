-- DEPLOY 2 DE DOIS — derruba a identidade ANTIGA do RM.
--
-- ⚠️⚠️ SO PODE SUBIR DEPOIS QUE `add_rm_fontes_indice.sql` ESTIVER EM PRODUCAO NOS
-- QUATRO TENANTS (Freitas, Trust, Monte Siao/MG, Santa Maria/RS). Ele NAO e o par
-- daquele no mesmo PR: registrar os dois na mesma lista faz o boot rodar os dois
-- de uma vez, o indice antigo cai enquanto o container antigo ainda esta no ar, e
-- todo POST /api/rm daquele container morre com 42P10 ate ele sair — que e
-- exatamente a janela que a divisao em dois deploys existe para fechar.
--
-- O QUE MUDA A PARTIR DAQUI: enquanto `ux_rm_mun_anos` existia, o RM completo e o
-- RM filtrado por consultas NAO conseguiam coexistir no mesmo escopo de anos (os
-- dois tem o mesmo (municipio_id, anos), e o segundo levava 23505 — traduzido em
-- 409 pelo router). Depois deste DROP, coexistem.
--
-- O QUE SOBRA sobre a tabela:
--   ux_rm_mun_anos_fontes  UNIQUE (municipio_id, anos, fontes)  <- a identidade
--   ix_rm_mun_data         (municipio_id, data_referencia DESC) <- so leitura
-- Consulta por (municipio_id, anos) continua servida pelo PREFIXO do indice novo,
-- entao nenhuma leitura perde plano.
--
-- ⚠️ PORTA DE MAO UNICA. Depois do primeiro par completo+filtrado do mesmo
-- periodo, voltar a imagem anterior deixa `POST /api/rm` morto com 42P10 naquele
-- tenant, permanentemente: recriar `ux_rm_mun_anos` falharia por duplicata, e a
-- unica saida seria APAGAR RM de usuario. A volta so e barata enquanto ninguem
-- tiver usado o recurso.
--
-- ⚠️ O GUARD NAO E ENFEITE, e ele nao estava no plano original.
--
-- Um `DROP INDEX IF EXISTS ux_rm_mun_anos;` solto derruba a identidade ANTIGA sem
-- perguntar se a NOVA chegou. Se `add_rm_fontes_indice.sql` tiver falhado neste
-- tenant — e o runner de services/startup.py ENGOLE erro de migration, registrando
-- em log e seguindo o boot — a tabela ficaria SEM NENHUM indice unico util e todo
-- `ON CONFLICT (municipio_id, anos, fontes)` morreria com 42P10. O tenant perderia
-- a geracao de RM inteira, e o log do boot diria que estava tudo certo.
--
-- Com o guard, o pior caso vira um NO-OP: o indice antigo fica de pe, a geracao
-- continua funcionando como no deploy 1, e o proximo boot tenta de novo assim que
-- o indice novo existir. Trocar uma falha permanente e silenciosa por "continua
-- como estava" e o unico desenho aceitavel para uma porta de mao unica.
DO $$
BEGIN
    IF to_regclass('public.ux_rm_mun_anos_fontes') IS NOT NULL THEN
        DROP INDEX IF EXISTS ux_rm_mun_anos;
    ELSE
        RAISE WARNING 'ux_rm_mun_anos_fontes ausente: o indice antigo NAO foi '
                      'derrubado. O RM completo e o filtrado ainda nao coexistem '
                      'neste tenant. Conferir add_rm_fontes_indice.sql.';
    END IF;
END $$;
