-- O CONSOLIDADO chega a quem administra os usuários do cliente (18/09/2026).
--
-- Tela nova não nasce concedida a ninguém (o defeito de 17/08: item filtrado por
-- `user_telas`, só o super-admin via). E a decisão do dono foi "permissão
-- própria: o admin do cliente marca quem vê" — mas ninguém concede o que não
-- tem (`routers/users.py`, anti-escalonamento). Então a concessão inicial vai
-- para quem pode conceder (`usuarios.conceder`), e dali o administrador repassa
-- a quem quiser na tela de Usuários.
--
-- ⚠️ TELA E AÇÕES, as duas: ter a tela não concede a chave
-- (`permissoes_efetivas()` lê só `user_permissoes`), e sem a chave o menu abre
-- e o clique dá 403. Ver o mesmo raciocínio em `add_tela_emendas_federais.sql`.
--
-- ⚠️ CADA INSERT TEM A SUA GUARDA (NOT EXISTS da própria chave): o arquivo roda
-- de novo quando é editado, e a guarda faz dele uma concessão única — quem um
-- administrador revogar depois não ganha de volta. Guardas independentes para
-- revogar a tela de alguém não travar a ação dos outros.
--
-- Tenant de um município só (Monte Sião, Santa Maria, Nova Palma) recebe também;
-- o item do menu some lá pelo layout (carteira de um município não tem o que
-- pôr lado a lado).

INSERT INTO user_telas (user_id, tela)
SELECT user_id, 'consolidado' FROM user_permissoes
WHERE permissao = 'usuarios.conceder'
  AND NOT EXISTS (SELECT 1 FROM user_telas WHERE tela = 'consolidado')
ON CONFLICT DO NOTHING;

INSERT INTO user_permissoes (user_id, permissao)
SELECT user_id, 'consolidado.ver' FROM user_permissoes
WHERE permissao = 'usuarios.conceder'
  AND NOT EXISTS (SELECT 1 FROM user_permissoes WHERE permissao = 'consolidado.ver')
ON CONFLICT DO NOTHING;

INSERT INTO user_permissoes (user_id, permissao)
SELECT user_id, 'consolidado.exportar' FROM user_permissoes
WHERE permissao = 'usuarios.conceder'
  AND NOT EXISTS (SELECT 1 FROM user_permissoes WHERE permissao = 'consolidado.exportar')
ON CONFLICT DO NOTHING;
