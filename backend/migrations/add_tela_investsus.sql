-- A tela InvestSUS chega a quem ja cuida da saude.
--
-- O #243 criou a tela e a rota, mas o item do menu e filtrado por `user_telas`
-- — e tela nova nao nasce concedida a ninguem. Resultado observado em 17/08: o
-- proprio dono do produto abriu o menu SAUDE e o InvestSUS nao estava la (so o
-- super-admin, que passa por tudo, o via).
--
-- Mesmo desenho do add_bi_tela.sql ("quem tem bi ganha bi_tela"): quem tem a
-- tela `fns` ganha `investsus`. O FNS e a tela vizinha da mesma pasta — quem
-- acompanha a proposta do Fundo Nacional de Saude e exatamente quem precisa ver
-- o repasse que ela vira. E casa com a permissao, que ja herda de `consultas`
-- (add_permissoes_por_acao.sql).
--
-- ATENCAO ao NOT EXISTS: o runner roda TODOS os arquivos a cada boot. Sem a
-- guarda, o backfill devolveria a tela a quem um admin tivesse revogado. Com
-- ela, so roda enquanto NINGUEM tiver `investsus` — concessao unica, revogacao
-- respeitada dali em diante.
INSERT INTO user_telas (user_id, tela)
SELECT user_id, 'investsus' FROM user_telas
WHERE tela = 'fns'
  AND NOT EXISTS (SELECT 1 FROM user_telas WHERE tela = 'investsus')
ON CONFLICT DO NOTHING;
