-- A tela de Parcerias chega a quem já acompanha instrumento federal.
--
-- 07/09/2026, junto com a fonte (`add_parcerias.sql`). O mesmo defeito que o
-- `add_tela_obrasgov.sql` e o `add_tela_investsus.sql` já documentam
-- aconteceria sem este arquivo: a tela e a rota existem, mas **tela nova não
-- nasce concedida a ninguém** — e o item do menu é filtrado por `user_telas`. O
-- resultado observado em 17/08 foi o próprio dono abrir o menu e não achar a
-- tela nova (só o super-admin, que passa por tudo, a via).
--
-- ⭐ Quem tem `convenios` ganha `parcerias`, e a escolha da chave de origem é
-- deliberada. Esta tela mostra a emenda de saúde que virou instrumento — é
-- literalmente a mesma pessoa que hoje acompanha convênio, não quem acompanha
-- obra. Por isso não herda de `sismob`, como a de Obras Federais herdou.
--
-- ⚠️ E ELA CONCEDE A TELA **E** A AÇÃO, ao contrário de `add_tela_obrasgov.sql`.
-- `permissoes_efetivas()` resolve a partir de `user_permissoes`, e os blocos que
-- derivariam a permissão a partir de um papel têm guarda em
-- `migration_backfills` e já dispararam. Só a tela daria menu visível e 403 no
-- clique — que é o defeito que `add_tela_emendas_federais.sql` teve de
-- consertar depois.
--
-- ATENÇÃO ao NOT EXISTS: o runner roda TODOS os arquivos a cada boot. Sem a
-- guarda, o backfill devolveria a tela a quem um admin tivesse revogado. Com
-- ela, só roda enquanto NINGUÉM tiver `parcerias` — concessão única, revogação
-- respeitada dali em diante.

INSERT INTO user_telas (user_id, tela)
SELECT user_id, 'parcerias' FROM user_telas
WHERE tela = 'convenios'
  AND NOT EXISTS (SELECT 1 FROM user_telas WHERE tela = 'parcerias')
ON CONFLICT DO NOTHING;

-- A ação, pelo mesmo critério e com a mesma guarda.
INSERT INTO user_permissoes (user_id, permissao)
SELECT DISTINCT up.user_id, 'parcerias.ver'
  FROM user_permissoes up
 WHERE up.permissao = 'convenios.ver'
   AND EXISTS (SELECT 1 FROM permissoes_catalogo
                WHERE chave = 'parcerias.ver')
   AND NOT EXISTS (SELECT 1 FROM user_permissoes
                    WHERE permissao = 'parcerias.ver')
ON CONFLICT DO NOTHING;
