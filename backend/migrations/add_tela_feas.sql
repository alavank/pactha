-- A tela «Assistência social — Estado (FEAS)» chega a quem administra os usuários
-- do cliente (26/09/2026).
--
-- Tela nova não nasce concedida a ninguém (o defeito de 17/08: item filtrado por
-- `user_telas`, só o super-admin via). Mesmo desenho de `add_tela_fnas.sql`: a
-- concessão inicial vai para quem pode conceder (`usuarios.conceder`), e dali o
-- administrador repassa a quem quiser na tela de Usuários.
--
-- ⚠️ TELA E AÇÃO, as duas: ter a tela não concede a chave
-- (`permissoes_efetivas()` lê só `user_permissoes`), e sem a chave o menu abre e
-- o clique dá 403. Ver `add_tela_emendas_federais.sql`.
--
-- ⚠️ CADA INSERT TEM A SUA GUARDA (NOT EXISTS da própria chave): o arquivo roda
-- de novo quando é editado, e a guarda faz dele uma concessão única — quem um
-- administrador revogar depois não ganha de volta.

INSERT INTO user_telas (user_id, tela)
SELECT user_id, 'feas' FROM user_permissoes
WHERE permissao = 'usuarios.conceder'
  AND NOT EXISTS (SELECT 1 FROM user_telas WHERE tela = 'feas')
ON CONFLICT DO NOTHING;

INSERT INTO user_permissoes (user_id, permissao)
SELECT user_id, 'feas.ver' FROM user_permissoes
WHERE permissao = 'usuarios.conceder'
  AND EXISTS (SELECT 1 FROM permissoes_catalogo WHERE chave = 'feas.ver')
  AND NOT EXISTS (SELECT 1 FROM user_permissoes WHERE permissao = 'feas.ver')
ON CONFLICT DO NOTHING;
