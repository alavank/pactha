-- ===========================================================================
-- O PERFIL «Prefeito» SAI DO CARDAPIO (05/09/2026)
-- ===========================================================================
--
-- Decisao do dono, palavra por palavra: "eu nao quero mais a opçao prefeito
-- ativada e quando for cadastrar qq usuario o campo de rotulo aparece vazio e
-- pode ser selecionado ou administrador ou usuario".
--
-- POR QUE UMA MIGRATION, E NAO SO TIRAR DA LISTA DO CODIGO
-- -------------------------------------------------------
-- Desde 11/08/2026 os perfis sao CADASTRAVEIS por cliente (`parametros`, tipo
-- `perfil_usuario`), e a lista de `frontend/.../usuarios/page.tsx::ROLES` virou
-- SEMENTE — ela so vale enquanto a chamada a API nao voltou. «Prefeito» esta
-- gravado em `parametros` nos cinco bancos, semeado por `add_parametros.sql`.
-- Tirar so do codigo deixaria o rotulo aparecendo no seletor de todo cliente.
--
-- ⚠️ DESATIVA, NAO APAGA. Duas razoes, e a segunda e a que decide:
--   1. `parametros.ativo = FALSE` e exatamente o mecanismo que o cliente ja usa
--      para tirar um rotulo do cardapio sem perder o historico — e o mesmo que
--      `analyst` e `viewer` receberam quando sairam da lista de escolha.
--   2. ⚠️ CONTA QUE JA TEM `role = 'prefeito'` CONTINUA VALENDO. Se a linha
--      fosse apagada, a tela mostraria a CHAVE CRUA ("prefeito") no lugar do
--      rotulo — que e exatamente o defeito que a lista fixa em codigo ja teve
--      uma vez com "analyst". Inativo significa "nao aparece para escolher, mas
--      sei traduzir quem ja tem".
--
-- ⚠️ O PAPEL NAO ERA A TRAVA, e por isso desativa-lo nao afrouxa nada. Ate a
-- vespera, escolher «Prefeito» semeava `users.somente_leitura = TRUE`; essa
-- trava foi REMOVIDA no mesmo deploy (ver `services/auth.py`), e o que ela fazia
-- agora se faz desmarcando as caixinhas de escrita de cada tela. Ninguem ganha
-- nem perde acesso por causa desta migration — ela mexe num ROTULO.
--
-- Idempotente: `UPDATE ... WHERE ativo` nao faz nada na segunda vez, e nao ha
-- guard em `migration_backfills` de proposito — se alguem reativar o rotulo no
-- banco a mao, o proximo boot volta a desativa-lo, que e o comportamento
-- desejado enquanto a decisao do dono for esta.
-- ===========================================================================

UPDATE parametros
   SET ativo = FALSE
 WHERE tipo = 'perfil_usuario'
   AND valor = 'prefeito'
   AND ativo;
