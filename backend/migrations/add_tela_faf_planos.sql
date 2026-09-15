-- A tela de Planos de Ação (Fundo a Fundo) chega a quem já acompanha convênio.
--
-- 07/09/2026, junto com o router. O mesmo defeito que `add_tela_obrasgov.sql` e
-- `add_tela_parcerias.sql` já documentam aconteceria sem este arquivo: a tela e
-- a rota existem, mas **tela nova não nasce concedida a ninguém** — e o item do
-- menu é filtrado por `user_telas`. O resultado observado em 17/08 foi o próprio
-- dono abrir o menu e não achar a tela nova.
--
-- ⭐ Quem tem `convenios` ganha `faf_planos`, e a escolha da chave de origem é
-- deliberada. Esta tela mostra o plano que justifica um repasse federal — é a
-- mesma pessoa que acompanha instrumento federal, não quem acompanha obra. Por
-- isso não herda de `sismob`, como a de Obras Federais herdou.
--
-- ⚠️ E ELA CONCEDE A TELA **E** A AÇÃO. `permissoes_efetivas()` resolve a partir
-- de `user_permissoes`, e os blocos que derivariam a permissão a partir de um
-- papel têm guarda em `migration_backfills` e já dispararam. Só a tela daria
-- menu visível e 403 no clique — o defeito que `add_tela_emendas_federais.sql`
-- teve de consertar depois.
--
-- ATENÇÃO ao NOT EXISTS: o arquivo roda de novo sempre que é editado (até
-- 15/09/2026 o runner rodava TODOS os arquivos a cada boot). Sem a
-- guarda, o backfill devolveria a tela a quem um admin tivesse revogado. Com
-- ela, só roda enquanto NINGUÉM tiver `faf_planos` — concessão única, revogação
-- respeitada dali em diante.

INSERT INTO user_telas (user_id, tela)
SELECT user_id, 'faf_planos' FROM user_telas
WHERE tela = 'convenios'
  AND NOT EXISTS (SELECT 1 FROM user_telas WHERE tela = 'faf_planos')
ON CONFLICT DO NOTHING;

-- A ação, pelo mesmo critério e com a mesma guarda.
INSERT INTO user_permissoes (user_id, permissao)
SELECT DISTINCT up.user_id, 'faf_planos.ver'
  FROM user_permissoes up
 WHERE up.permissao = 'convenios.ver'
   AND EXISTS (SELECT 1 FROM permissoes_catalogo
                WHERE chave = 'faf_planos.ver')
   AND NOT EXISTS (SELECT 1 FROM user_permissoes
                    WHERE permissao = 'faf_planos.ver')
ON CONFLICT DO NOTHING;
