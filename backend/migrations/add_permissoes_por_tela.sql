-- ===========================================================================
-- PERMISSAO POR TELA — a traducao das concessoes antigas (05/09/2026)
-- ===========================================================================
--
-- O QUE MUDOU, E POR QUE ESTE ARQUIVO EXISTE
-- ------------------------------------------
-- Ate 05/09/2026 duas chaves governavam dezessete telas do menu:
--
--     transferegov.*  ->  as 8 telas do grupo FEDERAIS (Radar, Em execução,
--                         Especiais, PAC, Voluntárias, Rejeitadas, Encerradas,
--                         CNPJ)
--     convenios.*     ->  as 10 telas do grupo ESTADUAIS (Convênios, Emendas,
--                         Repasses, Cofinanciamento, Monitoramento, Consulta
--                         Popular, Programas do Estado, Plano Rio Grande,
--                         Emendas RS, TCE-RS)
--
-- O administrador marcava «Transfere Gov» e concedia SETE telas sem saber que
-- estava concedendo sete. O pedido do dono foi granularidade Modulo › Tela ›
-- Acao — «em Federais posso liberar Em execução e não PAC» —, entao cada folha
-- do menu virou tela e chave proprias.
--
-- ⚠️⚠️ ESTE E O ARQUIVO DE MAIOR RISCO DO INCREMENTO, e o motivo e o deploy:
-- `AUTHZ_MODO` passou a ser `bloqueio` por DEFAULT no MESMO deploy (decisao do
-- dono, depois de a consequencia ter sido posta na mesa). Ou seja: a partir
-- deste boot, caixinha desmarcada RECUSA de verdade. Uma linha esquecida aqui
-- nao e "um detalhe a acertar depois" — e alguem trancado fora amanha de manha,
-- em cinco prefeituras ao mesmo tempo.
--
-- Por isso as tres regras abaixo, e cada uma tem o seu porque:
--
--   1. RENOMEAR TELA VALE PARA TODOS. Quem tinha a tela `transferegov` ganha as
--      oito; quem tinha `convenios` ganha as dez. Isso NAO e conceder — e
--      traduzir o mesmo acesso para o vocabulario novo. Sem isto, todo mundo
--      perde os dois maiores grupos do menu no deploy.
--
--   2. DERIVAR `user_permissoes` DE `user_telas` SO PARA QUEM TEM ZERO LINHA.
--      Esta e a regra que mais custou a escolher, e a assimetria e deliberada:
--        · quem JA TEM linha foi configurado de proposito por alguem, e
--          acrescentar caixinha desfaria uma restricao que o administrador
--          escolheu — afrouxar em silencio e o pior dos dois erros;
--        · quem NAO TEM nenhuma nunca foi configurado, e ate ontem isso nao
--          fazia falta (em `AUTHZ_MODO=aviso` as caixinhas so registravam).
--          Com `bloqueio`, essa pessoa perderia TUDO no deploy.
--      Preservar o acesso de hoje e o contrato de uma migration; apertar e
--      trabalho do administrador na tela nova, com a arvore na frente dele.
--
--   3. ADMIN ATIVO GANHA `usuarios.*` E A TELA `usuarios` — ANTI-LOCKOUT.
--      `routers/users.py::_require_admin` deixou de olhar o papel e virou
--      `_exige_tela_usuarios` (o proprio docstring dele previa o dia). Sem esta
--      regra, um administrador sem a caixinha marcada se trancaria fora da
--      UNICA tela que conserta o problema — e nao haveria caminho de volta sem
--      acesso ao banco.
--
-- ⚠️ IDEMPOTENTE E GUARDADA. As tres partes rodam UMA VEZ por banco (marca em
-- `migration_backfills`), como o backfill de `add_permissoes_por_acao.sql`.
-- Rodar de novo re-concederia o que o administrador tivesse retirado no
-- meio-tempo, que e a mesma classe de erro da regra 2.
--
-- ⚠️ A SEMENTE DAS CHAVES NAO ESTA AQUI: ela vive em
-- `add_permissoes_por_acao.sql`, que roda a CADA boot com DO NOTHING e por isso
-- e quem torna as chaves novas GRAVAVEIS nos cinco bancos. Aqui so se traduz
-- concessao. As duas coisas separadas de proposito — a FK precisa existir antes
-- de qualquer INSERT em `user_permissoes`, e por isso este arquivo entra DEPOIS
-- daquele em `MIGRATION_FILES` (guardado por
-- `tests/test_migrations_ordem_tabela.py`).
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 1. AS TELAS: `transferegov` -> 8, `convenios` -> 10
-- ---------------------------------------------------------------------------
-- ⚠️ AS ANTIGAS NAO SAO APAGADAS. `user_telas` nao tem FK e uma linha
-- `transferegov` sobrando e inerte (nenhuma rota pergunta por ela) — enquanto
-- apagar seria irreversivel se algo desse errado no deploy. Sobra sujeira
-- legivel em vez de risco.
WITH marca AS (
    INSERT INTO migration_backfills (nome)
    VALUES ('add_permissoes_por_tela:telas_dos_grupos')
    ON CONFLICT (nome) DO NOTHING
    RETURNING nome
), mapa(antiga, nova) AS (
    VALUES
        ('transferegov'::text, 'transferegov_radar'::text),
        ('transferegov', 'transferegov_geral'),
        ('transferegov', 'transferegov_especiais'),
        ('transferegov', 'transferegov_pac'),
        ('transferegov', 'transferegov_voluntarias'),
        ('transferegov', 'transferegov_rejeitadas'),
        ('transferegov', 'transferegov_encerradas'),
        ('transferegov', 'transferegov_cnpj'),
        -- `convenios` e `emendas` ja existiam como tela e continuam valendo:
        -- so as OITO que estavam escondidas dentro de `convenios` entram aqui.
        ('convenios', 'repasses'),
        ('convenios', 'cofinanciamento'),
        ('convenios', 'monitoramento'),
        ('convenios', 'consulta_popular'),
        ('convenios', 'programas_rs'),
        ('convenios', 'funrigs'),
        ('convenios', 'emendas_rs'),
        ('convenios', 'tce_rs'),
        -- A aba Telemetria declarava `tela: "auditoria"` em
        -- `lib/configuracoes.ts` — a chave de OUTRA coisa. Quem tinha a trilha
        -- ja via a telemetria, entao traduzir preserva o acesso de hoje; separar
        -- as duas dali para a frente e decisao do administrador.
        ('auditoria', 'telemetria')
)
INSERT INTO user_telas (user_id, tela)
SELECT ut.user_id, m.nova
  FROM marca, user_telas ut
  JOIN mapa m ON m.antiga = ut.tela
 ON CONFLICT DO NOTHING;


-- ---------------------------------------------------------------------------
-- 2. AS TELAS DE ADMINISTRACAO que passaram a ser tela de verdade
-- ---------------------------------------------------------------------------
-- Usuarios, Status dos Dados e Parametros eram governadas pelo PAPEL `admin`.
-- Agora sao telas, e quem era administrador tem de continuar entrando nelas.
--
-- ⚠️ ESTA E A METADE ANTI-LOCKOUT DA REGRA 3. A outra metade (as caixinhas de
-- acao) vem na parte 4.
WITH marca AS (
    INSERT INTO migration_backfills (nome)
    VALUES ('add_permissoes_por_tela:telas_de_administracao')
    ON CONFLICT (nome) DO NOTHING
    RETURNING nome
), telas(tela) AS (
    VALUES ('usuarios'::text), ('frescor'), ('parametros')
)
INSERT INTO user_telas (user_id, tela)
SELECT u.id, t.tela
  FROM marca, users u
 CROSS JOIN telas t
 WHERE u.role = 'admin'
   AND u.active
   -- Quiosque nao e pessoa: o `viewer` do link publico de TV nunca administra
   -- nada, e o guard de `ehQuiosque` o barra de qualquer forma.
   AND COALESCE(u.kiosk, FALSE) = FALSE
 ON CONFLICT DO NOTHING;


-- ---------------------------------------------------------------------------
-- 3. AS ACOES DAS TELAS NOVAS, para quem JA TINHA a concessao antiga
-- ---------------------------------------------------------------------------
-- Quem tinha `transferegov.ver` ganha `<tela>.ver` das oito federais; quem
-- tinha `transferegov.exportar` ganha `<tela>.exportar` das que exportam. Idem
-- para `convenios.*` nas oito estaduais.
--
-- ⚠️ VALE PARA TODOS, e nao so para quem tem zero linha (que e a regra 2 da
-- parte 4). A diferenca: aqui nao se esta CONCEDENDO nada — a pessoa ja tinha
-- exatamente este acesso ontem, sob outro nome. Nao traduzir seria RETIRAR.
WITH marca AS (
    INSERT INTO migration_backfills (nome)
    VALUES ('add_permissoes_por_tela:traduz_acoes_dos_grupos')
    ON CONFLICT (nome) DO NOTHING
    RETURNING nome
), mapa(antiga, nova) AS (
    VALUES
        -- FEDERAIS — `ver`
        ('transferegov.ver'::text, 'transferegov_radar.ver'::text),
        ('transferegov.ver', 'transferegov_geral.ver'),
        ('transferegov.ver', 'transferegov_especiais.ver'),
        ('transferegov.ver', 'transferegov_pac.ver'),
        ('transferegov.ver', 'transferegov_voluntarias.ver'),
        ('transferegov.ver', 'transferegov_rejeitadas.ver'),
        ('transferegov.ver', 'transferegov_encerradas.ver'),
        ('transferegov.ver', 'transferegov_cnpj.ver'),
        -- FEDERAIS — `exportar` (so as cinco que tem rota de PDF)
        ('transferegov.exportar', 'transferegov_geral.exportar'),
        ('transferegov.exportar', 'transferegov_especiais.exportar'),
        ('transferegov.exportar', 'transferegov_voluntarias.exportar'),
        ('transferegov.exportar', 'transferegov_rejeitadas.exportar'),
        ('transferegov.exportar', 'transferegov_encerradas.exportar'),
        -- ESTADUAIS — as oito que sairam de dentro de `convenios`. So `ver`:
        -- nenhuma delas tem rota de exportacao nem de coleta hoje.
        ('convenios.ver', 'repasses.ver'),
        ('convenios.ver', 'cofinanciamento.ver'),
        ('convenios.ver', 'monitoramento.ver'),
        ('convenios.ver', 'consulta_popular.ver'),
        ('convenios.ver', 'programas_rs.ver'),
        ('convenios.ver', 'funrigs.ver'),
        ('convenios.ver', 'emendas_rs.ver'),
        ('convenios.ver', 'tce_rs.ver'),
        -- Parametros: quem editava PESSOAS editava as LISTAS (a aba pegava
        -- carona em `usuarios.*`). Traduzir preserva o acesso de hoje.
        ('usuarios.ver', 'parametros.ver'),
        ('usuarios.editar', 'parametros.editar')
)
INSERT INTO user_permissoes (user_id, permissao, concedido_por)
SELECT up.user_id, m.nova, NULL
  FROM marca, user_permissoes up
  JOIN mapa m ON m.antiga = up.permissao
 ON CONFLICT DO NOTHING;


-- ---------------------------------------------------------------------------
-- 4. ⭐⭐ O BACKFILL QUE IMPEDE O APAGAO — so para quem tem ZERO caixinha
-- ---------------------------------------------------------------------------
-- Ate a vespera, `AUTHZ_MODO` era `aviso`: as caixinhas de acao NAO barravam
-- nada, e quem impedia a escrita era a tela e a trava de conta «somente
-- leitura». Consequencia pratica: existem contas em producao com telas e ZERO
-- linha em `user_permissoes`, que funcionavam perfeitamente. Com `bloqueio`
-- ligado no mesmo deploy, essas contas perderiam TUDO — inclusive a leitura.
--
-- A regra: para cada tela que a pessoa TEM, conceder as acoes daquela tela.
-- Preserva exatamente o acesso de hoje (com a tela, hoje ela faz tudo naquela
-- tela) e nao mexe em quem ja foi configurado.
--
-- ⚠️ SO QUEM TEM ZERO LINHA. Quem tem uma linha sequer foi configurado de
-- proposito, e acrescentar caixinha ali desfaria a restricao que alguem
-- escolheu — ver a regra 2 no cabecalho.
--
-- ⚠️ AS INERTES FICAM DE FORA: `gestao.exportar`, `cauc.exportar` e as demais
-- de `services/permissoes.py::PERMISSOES_INERTES` nao abrem rota nenhuma e a
-- arvore da tela nem as desenha. Conceder seria encher `user_permissoes` de
-- linha que nao governa nada.
WITH marca AS (
    INSERT INTO migration_backfills (nome)
    VALUES ('add_permissoes_por_tela:acoes_de_quem_nao_tinha_nenhuma')
    ON CONFLICT (nome) DO NOTHING
    RETURNING nome
), sem_caixinha AS (
    SELECT u.id
      FROM users u
     WHERE u.active
       AND COALESCE(u.kiosk, FALSE) = FALSE
       -- Super-admin nao entra: a funcao pura ja devolve o catalogo inteiro
       -- para ele, e desenhar 96 caixinhas marcadas para o dono da plataforma
       -- sugeriria que alguem poderia desmarca-las.
       AND COALESCE(u.super_admin, FALSE) = FALSE
       AND NOT EXISTS (SELECT 1 FROM user_permissoes up WHERE up.user_id = u.id)
)
INSERT INTO user_permissoes (user_id, permissao, concedido_por)
SELECT s.id, pc.permissao, NULL
  FROM marca, sem_caixinha s
  JOIN user_telas ut ON ut.user_id = s.id
  -- A tela de cada permissao esta no PREFIXO da chave: `rm.editar` -> `rm`.
  -- Vale para todas menos as que o catalogo aponta para outra tela (`bi.tela`,
  -- `bi.link`) — e as duas sao inertes ou de tela propria, entao a juncao por
  -- prefixo acerta o conjunto inteiro.
  JOIN permissoes_catalogo pc
    ON pc.permissao LIKE ut.tela || '.%'
   AND position('.' in substr(pc.permissao, length(ut.tela) + 2)) = 0
 WHERE pc.permissao NOT IN (
        'acordofes.exportar', 'bi.exportar', 'bi.tela', 'cauc.exportar',
        'fns.exportar', 'frescor.exportar', 'gestao.exportar',
        'simec.exportar', 'sismob.exportar')
 ON CONFLICT DO NOTHING;


-- ---------------------------------------------------------------------------
-- 5. ANTI-LOCKOUT: `usuarios.*` para todo administrador ativo
-- ---------------------------------------------------------------------------
-- ⚠️ ESTA E A LINHA QUE IMPEDE O PIOR CENARIO DO DEPLOY. `_exige_tela_usuarios`
-- substituiu o gate por papel em `routers/users.py`, e as rotas de la cobram
-- `usuarios.<acao>` de verdade agora. Um administrador que caisse fora da regra
-- 4 (porque JA tinha alguma caixinha, mas nenhuma de `usuarios`) ficaria sem a
-- tela que conserta o problema — e sem caminho de volta fora do banco.
--
-- Roda DEPOIS da parte 4 de proposito: la o conjunto e derivado das telas, aqui
-- e uma garantia incondicional para quem administra.
WITH marca AS (
    INSERT INTO migration_backfills (nome)
    VALUES ('add_permissoes_por_tela:antilockout_admin')
    ON CONFLICT (nome) DO NOTHING
    RETURNING nome
), chaves(permissao) AS (
    VALUES ('usuarios.ver'::text), ('usuarios.criar'), ('usuarios.editar'),
           ('usuarios.excluir'), ('usuarios.conceder'),
           ('usuarios.resetar_senha')
)
INSERT INTO user_permissoes (user_id, permissao, concedido_por)
SELECT u.id, c.permissao, NULL
  FROM marca, users u
 CROSS JOIN chaves c
 WHERE u.role = 'admin'
   AND u.active
   AND COALESCE(u.kiosk, FALSE) = FALSE
   AND COALESCE(u.super_admin, FALSE) = FALSE
 ON CONFLICT DO NOTHING;
