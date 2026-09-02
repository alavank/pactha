-- =====================================================================
-- Incremento 6 — ALCANCE POR LINHA (Row-Level), por USUARIO e por MODULO.
--
-- A regra do dono, palavra por palavra:
--
--   "Escopo (Editar somente os dele): e uma regra de nivel de linha. O
--    sistema valida se o ID do usuario logado e o mesmo criador do
--    registro. Se for, ele deixa editar; se nao for, o botao some ou fica
--    bloqueado. Essas regras seriam configuradas no painel de
--    administracao no modulo de usuarios, e isso aconteceria POR MODULO."
--
-- E a decisao dele sobre o alcance: **vale SO PARA ESCRITA** (editar e
-- excluir). A pessoa continua VENDO a lista inteira do municipio.
--
-- Este arquivo entrega DUAS tabelas e NENHUMA concessao:
--   1. `escopo_recursos` — a tabela-CATALOGO dos modulos que aceitam
--      alcance (a chave estrangeira que mata o typo silencioso);
--   2. `user_escopos`     — o alcance escolhido, por usuario e por modulo.
--
-- ---------------------------------------------------------------------
-- ⚠️⚠️ POR QUE NAO HA BACKFILL AQUI — leia antes de acrescentar um.
-- ---------------------------------------------------------------------
-- A promessa e a de sempre: NINGUEM pode perder a capacidade de editar no
-- deploy. Ela e cumprida da forma mais forte possivel — este arquivo NAO
-- ESCREVE UMA UNICA LINHA por usuario. AUSENCIA DE LINHA E `todos`, que e
-- exatamente o comportamento de hoje, e o codigo le assim em tres lugares
-- (services/auth.py::_carregar_escopos, services/authz.py::escopo_de e o
-- DEFAULT da coluna abaixo).
--
-- Materializar um `'todos'` para cada usuario x modulo pareceria mais
-- explicito e seria PIOR: criaria uma segunda fonte de verdade para a
-- mesma pergunta ("o que significa nao ter linha?"), que continuaria
-- existindo de qualquer jeito — todo usuario CRIADO DEPOIS deste deploy
-- nasce sem linha nenhuma. Duas respostas para uma pergunta so e como as
-- duas divergem.
--
-- ⚠️ CONSEQUENCIA PARA QUEM MEXER AQUI DEPOIS: no dia em que este arquivo
-- precisar escrever em `user_escopos`, esse INSERT TEM de cruzar
-- `migration_backfills` (o "ja aplicada" que este runner nao tem), com o
-- padrao `WITH marca AS (INSERT ... ON CONFLICT DO NOTHING RETURNING nome)`
-- de add_role_vira_rotulo.sql. Sem isso o boot seguinte DESFAZ o que o
-- administrador configurou ontem — o runner (services/startup.py) roda
-- TODO arquivo da lista a CADA boot e engole erro. O teste
-- `tests/test_escopo_migration.py::test_a_migration_nao_escreve_linha_de_usuario`
-- quebra se alguem acrescentar um INSERT aqui sem a marca.
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1. A TABELA-CATALOGO — o banco como ULTIMA LINHA DE DEFESA.
-- ---------------------------------------------------------------------
-- Mesma cicatriz de `user_telas`, que aceita QUALQUER string: um typo
-- (`gestaoo`) grava sem reclamar e nao vale nada. Aqui o typo seria pior
-- do que inofensivo — ele seria uma restricao que o administrador JURA
-- ter configurado e que nunca se aplica, ou seja o usuario continua
-- editando o registro dos outros. Falha SILENCIOSA de permissao, na
-- direcao que abre.
--
-- Com a FK de `user_escopos.recurso` apontando para ca, chave invalida
-- deixa de ser gravavel: o INSERT falha, alto e claro.
--
-- `tabela` e `coluna_dono` sao repetidos aqui como CONTEXTO para quem
-- abrir o banco (a autoridade continua sendo
-- `services/permissoes.py::ESCOPO_RECURSOS`, que e o que o codigo le e a
-- API serve). O teste tests/test_escopo_migration.py compara os dois,
-- campo por campo: recurso novo entra nos DOIS lugares ou o teste quebra.
CREATE TABLE IF NOT EXISTS escopo_recursos (
    recurso     TEXT PRIMARY KEY,
    -- Onde mora a linha e qual coluna guarda o criador. Recurso cuja
    -- tabela nao tenha essa coluna NAO pode entrar: o alcance viraria uma
    -- opcao na tela que nao faz nada.
    tabela      TEXT NOT NULL,
    coluna_dono TEXT NOT NULL,
    criado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ---------------------------------------------------------------------
-- 2. O ALCANCE — uma linha por usuario, por modulo.
-- ---------------------------------------------------------------------
-- ⚠️ POR QUE UMA TABELA PROPRIA, E NAO UMA COLUNA `escopo` EM
-- `user_permissoes` (que era a sugestao obvia):
--
--   a) `user_permissoes` e apagada e reinserida conforme o administrador
--      marca e desmarca caixinhas (routers/permissoes.py::_gravar_concessao
--      remove a linha de quem perdeu a permissao). Com o alcance morando
--      la, DESMARCAR e REMARCAR «Editar» apagaria a restricao junto e a
--      pessoa voltaria calada para `todos`. Restricao de seguranca que
--      some como efeito colateral de um clique em outra caixinha e o pior
--      tipo de defeito: ninguem ve, e ele abre.
--
--   b) o dono pediu POR MODULO, e `user_permissoes` e POR CHAVE. Uma
--      coluna la permitiria `gestao.editar = proprios` com
--      `gestao.excluir = todos` — dois valores para uma escolha que a
--      tela desenha como UM radio. O dia em que os dois divergissem, a
--      tela mostraria um e o servidor obedeceria o outro.
--
-- ON DELETE CASCADE no usuario: apagou a pessoa, some a configuracao.
-- ON DELETE RESTRICT no catalogo: tirar um modulo do catalogo com gente
-- configurada tem de DOER — sem o RESTRICT, um DELETE numa manutencao
-- levaria junto, em cascata e em silencio, todas as restricoes ativas
-- (e a direcao da perda e a que ABRE o sistema).
--
-- O CHECK e a terceira trava do vocabulario (as outras duas sao o
-- `_validar_escopos` do router e a normalizacao do Python): valor fora de
-- 'todos'/'proprios' nao entra de jeito nenhum, venha de onde vier.
CREATE TABLE IF NOT EXISTS user_escopos (
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recurso      TEXT NOT NULL REFERENCES escopo_recursos(recurso)
                      ON UPDATE CASCADE ON DELETE RESTRICT,
    -- DEFAULT 'todos' e a mesma promessa da ausencia de linha: o valor que
    -- NAO restringe ninguem.
    escopo       TEXT NOT NULL DEFAULT 'todos'
                      CHECK (escopo IN ('todos', 'proprios')),
    definido_em  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Quem configurou (NULL = o sistema). A trilha de auditoria continua
    -- sendo a fonte oficial do "quem, quando e o que mudou"
    -- (usuarios.conceder, com valor-antes/valor-depois); esta coluna e a
    -- resposta barata para "de onde veio esta linha?".
    definido_por INTEGER REFERENCES users(id) ON DELETE SET NULL,
    PRIMARY KEY (user_id, recurso)
);

-- A leitura quente e "o alcance DESTE usuario" (uma vez por requisicao,
-- em load_user_scopes), ja coberta pela chave primaria. Este indice serve
-- a pergunta inversa — "quem esta restrito na Gestao Interna?" — que e a
-- que o controle interno faz numa revisao de acesso.
CREATE INDEX IF NOT EXISTS idx_user_escopos_recurso
    ON user_escopos (recurso);


-- ---------------------------------------------------------------------
-- 3. SEMENTE DO CATALOGO — a cada boot, SEM marca.
-- ---------------------------------------------------------------------
-- Roda sempre de proposito, exatamente como a semente de
-- `permissoes_catalogo`: declarar que um modulo ACEITA alcance nao
-- restringe ninguem, e e o que faz um modulo novo passar a ser
-- configuravel num tenant que ja esta no ar, sem migration nova.
--
-- `DO NOTHING` e nao `DO UPDATE`: linha que ja esta la fica como esta.
-- Modulo que sumir do Python NAO e apagado daqui — apagar quebraria a FK
-- de quem ja tem alcance configurado nele. Ele fica inerte: o codigo so
-- olha para `services/permissoes.py::ESCOPO_RECURSOS`, entao a linha orfa
-- nao vale nada enquanto alguem nao a remover a mao.
INSERT INTO escopo_recursos (recurso, tabela, coluna_dono) VALUES
    ('gestao', 'gestao_anotacoes', 'criado_por'),
    ('agendamentos', 'agendamentos', 'criado_por'),
    ('rm', 'rm_relatorios', 'criado_por'),
    ('documentos', 'documentos_gerados', 'criado_por')
ON CONFLICT (recurso) DO NOTHING;
