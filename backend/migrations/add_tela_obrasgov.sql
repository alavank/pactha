-- A tela de Obras Federais chega a quem já acompanha obra.
--
-- 04/09/2026, junto com o grupo OBRAS do menu. O mesmo defeito do
-- `add_tela_investsus.sql` aconteceria sem este arquivo: a tela e a rota
-- existem, mas **tela nova não nasce concedida a ninguém** — e o item do menu é
-- filtrado por `user_telas`. O resultado observado em 17/08 foi o próprio dono
-- abrir o menu e não achar a tela nova (só o super-admin, que passa por tudo,
-- a via).
--
-- Quem tem `sismob` ganha `obrasgov`. O SISMOB é a tela vizinha da mesma pasta,
-- e é literalmente a mesma pessoa: quem acompanha a obra de saúde do município
-- é quem precisa ver a obra de mobilidade, de habitação e a reconstrução da
-- Defesa Civil — que é o que esta tela acrescenta. Casa com a permissão, que
-- herda de `convenios` pela mesma chave (add_permissoes_por_acao.sql).
--
-- ATENÇÃO ao NOT EXISTS: o runner roda TODOS os arquivos a cada boot. Sem a
-- guarda, o backfill devolveria a tela a quem um admin tivesse revogado. Com
-- ela, só roda enquanto NINGUÉM tiver `obrasgov` — concessão única, revogação
-- respeitada dali em diante.
INSERT INTO user_telas (user_id, tela)
SELECT user_id, 'obrasgov' FROM user_telas
WHERE tela = 'sismob'
  AND NOT EXISTS (SELECT 1 FROM user_telas WHERE tela = 'obrasgov')
ON CONFLICT DO NOTHING;
