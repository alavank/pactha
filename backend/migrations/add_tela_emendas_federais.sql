-- A tela de Emendas Federais chega a quem já acompanha instrumento federal.
--
-- 06/09/2026, junto com a nona folha do grupo FEDERAIS. Sem este arquivo
-- acontece o defeito de 17/08 outra vez: a tela e a rota existem, mas **tela
-- nova não nasce concedida a ninguém** — e o item do menu é filtrado por
-- `user_telas`. O resultado observado naquele dia foi o próprio dono abrir o
-- menu e não achar a tela nova (só o super-admin, que passa por tudo, a via).
--
-- ⚠️⚠️ E ELE CONCEDE AS DUAS COISAS, ao contrário de `add_tela_obrasgov.sql` e
-- `add_tela_investsus.sql`. Aqueles concedem só `user_telas`, e o comentário
-- deles afirma que a ação "já herda de convenios/consultas
-- (add_permissoes_por_acao.sql)". **Essa herança não alcança os cinco tenants no
-- ar**, por três motivos que se somam:
--
--   1. `services/permissoes.py::permissoes_efetivas()` resolve EXCLUSIVAMENTE de
--      `user_permissoes` — ter a tela não concede a chave;
--   2. o bloco de compatibilidade de `add_permissoes_por_acao.sql` está guardado
--      por `migration_backfills` e **já disparou**, então alcança só banco novo;
--   3. a parte 4 de `add_permissoes_por_tela.sql` deriva de `user_telas` apenas
--      para quem tem ZERO linha em `user_permissoes`, e também já disparou.
--
-- Ou seja: repetir o padrão daqueles arquivos daria menu visível e **403 no
-- clique**, com `AUTHZ_MODO=bloqueio`. (Vale conferir se `obrasgov` e
-- `investsus` estão nessa situação hoje — é o mesmo par de INSERTs, em PR
-- próprio.)
--
-- A VIZINHA É «Federais — Especiais», e não «Parlamentares». Três razões:
--   1. é onde a emenda federal aparece HOJE (a Transferência Especial), então é
--      literalmente a mesma pessoa que precisa da tela nova;
--   2. é do MESMO grupo do menu (FEDERAIS) — a mesma analogia que fez
--      `sismob -> obrasgov` na pasta OBRAS;
--   3. «Parlamentares» é tela de agregação cross-fonte, fora do grupo: quem a
--      tem não necessariamente acompanha instrumento federal, e herdar dela
--      concederia a gente que não pediu.
--
-- ATENÇÃO ao NOT EXISTS: o runner roda TODOS os arquivos a cada boot. Sem a
-- guarda, o backfill devolveria o acesso a quem um admin tivesse revogado. Com
-- ela, só roda enquanto NINGUÉM tiver — concessão única, revogação respeitada
-- dali em diante.
--
-- ⚠️ E AS DUAS GUARDAS SÃO INDEPENDENTES de propósito: revogar a TELA de uma
-- pessoa não pode travar o backfill da AÇÃO das outras, e vice-versa.

-- 1. A TELA (o item do menu).
INSERT INTO user_telas (user_id, tela)
SELECT user_id, 'emendas_federais' FROM user_telas
WHERE tela = 'transferegov_especiais'
  AND NOT EXISTS (SELECT 1 FROM user_telas WHERE tela = 'emendas_federais')
ON CONFLICT DO NOTHING;

-- 2. A AÇÃO (o que a rota cobra). Sem esta, a pessoa vê o item, clica e toma
-- 403 — e a mensagem do 403 não diz qual caixinha falta.
--
-- ⚠️ Espelha a concessão de `ver` da tela VIZINHA, e não de `user_telas`: quem
-- tem a tela mas NÃO tem `transferegov_especiais.ver` foi restringido de
-- propósito por alguém, e conceder aqui desfaria essa escolha.
INSERT INTO user_permissoes (user_id, permissao)
SELECT user_id, 'emendas_federais.ver' FROM user_permissoes
WHERE permissao = 'transferegov_especiais.ver'
  AND NOT EXISTS (SELECT 1 FROM user_permissoes
                   WHERE permissao = 'emendas_federais.ver')
ON CONFLICT DO NOTHING;
