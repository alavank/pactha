-- =====================================================================
-- Incremento 5 — PERMISSAO POR ACAO (`recurso.acao`), por USUARIO.
--
-- Ate aqui a permissao era BINARIA: ou a pessoa via a tela, ou nao via.
-- Quem via `rm` criava, editava, apagava e exportava. A regra do dono e
-- outra — "algumas pessoas so vao VER, outras EDITAR, e isso POR USUARIO";
-- e os SUPER-ADMIN "tem tudo, fazem tudo... sao tipo ROOT".
--
-- Este arquivo entrega TRES coisas, nesta ordem:
--   1. a tabela-CATALOGO (`permissoes_catalogo`), semeada com as chaves;
--   2. a tabela de CONCESSAO (`user_permissoes`), com CHAVE ESTRANGEIRA
--      para o catalogo;
--   3. o BACKFILL de compatibilidade — ninguem pode perder acesso no
--      deploy.
--
-- ⚠️ O RISCO DESTE ARQUIVO E O APAGAO, e ele e o mesmo do Incremento 4:
-- no instante em que o codigo passar a exigir `rm.excluir`, quem nao tiver
-- linha em `user_permissoes` perde a funcao. Por isso o backfill traduz o
-- acesso que existe HOJE (telas + papel) para as chaves novas, e o arquivo
-- inteiro e UMA transacao (o runner faz um `cur.execute(arquivo)` e so
-- entao `commit()`): ou entra tudo, ou nao entra nada — nunca "tabela nova
-- sem as permissoes dentro".
--
-- ⚠️ E O RUNNER RODA TUDO A CADA BOOT, E ENGOLE ERRO. Para DDL idempotente
-- isso e inofensivo; para BACKFILL nao e — um `INSERT ... ON CONFLICT DO
-- NOTHING` de permissao que rode a cada boot DEVOLVE o acesso que o
-- administrador REVOGOU ontem. O registro `migration_backfills` (criado
-- pelo Incremento 4) e o "ja aplicada" que este runner nao tem, e o
-- backfill abaixo depende dele. Ver o cabecalho de add_role_vira_rotulo.sql
-- para o mecanismo do `WITH marca AS (INSERT ... RETURNING)`.
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1. A TABELA-CATALOGO — o banco como ULTIMA LINHA DE DEFESA.
-- ---------------------------------------------------------------------
-- Ela existe por causa de um defeito que ja esta no ar: `user_telas`
-- aceita QUALQUER string. Um typo (`documentoss`) grava sem reclamar,
-- volta na leitura, aparece marcado na tela de Usuarios como se fosse um
-- acesso concedido — e nao concede nada. E uma falha SILENCIOSA de
-- permissao: o administrador jura que deu acesso, a pessoa jura que nao
-- tem, e nao ha erro em lugar nenhum para investigar.
--
-- Com a chave estrangeira de `user_permissoes` apontando para ca, chave
-- invalida deixa de ser gravavel: o INSERT falha, alto e claro, no momento
-- em que alguem tenta.
--
-- ⚠️ A AUTORIDADE DO CONTEUDO CONTINUA SENDO O PYTHON
-- (`services/permissoes.py::CATALOGO`), que e quem a API serve e o
-- frontend consome. Esta tabela guarda so o que a FK precisa (a chave) mais
-- dois campos de contexto (secao e se e acao de escrita) para quem abrir o
-- banco entender o que esta lendo. Os ROTULOS e as DESCRICOES nao sao
-- copiados para ca de proposito: texto duplicado diverge, e o unico jeito
-- de nunca divergir e existir num lugar so.
--
-- O teste `tests/test_permissoes_catalogo.py` compara a semente abaixo com
-- o catalogo do Python, chave por chave. Permissao nova entra nos DOIS
-- lugares ou o teste quebra.
CREATE TABLE IF NOT EXISTS permissoes_catalogo (
    chave       TEXT PRIMARY KEY,
    secao       TEXT NOT NULL,
    -- escrita: o guard de somente-leitura (services/auth.py) barra esta
    -- acao? E pergunta sobre o METODO HTTP, nao sobre o nome do verbo —
    -- por isso `ai.exportar` e TRUE (o endpoint e POST) e `bi.link` e
    -- FALSE (o prefixo esta em READONLY_WRITE_ALLOW).
    escrita     BOOLEAN NOT NULL DEFAULT FALSE,
    criado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ---------------------------------------------------------------------
-- 2. A CONCESSAO — uma linha por permissao, por usuario.
-- ---------------------------------------------------------------------
-- ON DELETE CASCADE no usuario: apagou a pessoa, some a permissao dela.
-- ON DELETE RESTRICT no catalogo: tirar uma permissao do catalogo com
-- gente usando tem de DOER. Sem o RESTRICT, um `DELETE FROM
-- permissoes_catalogo` numa manutencao levaria junto, em cascata e em
-- silencio, o acesso de todo mundo aquela funcao.
--
-- `concedido_por` guarda QUEM concedeu (NULL = o sistema, isto e, este
-- backfill). A trilha de auditoria continua sendo a fonte oficial do
-- "quem, quando e o que mudou" (services/audit.py::registrar_critico);
-- esta coluna e a resposta barata para "de onde veio esta linha?" sem
-- precisar cruzar a trilha inteira.
CREATE TABLE IF NOT EXISTS user_permissoes (
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    permissao     TEXT NOT NULL REFERENCES permissoes_catalogo(chave)
                       ON UPDATE CASCADE ON DELETE RESTRICT,
    concedido_em  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    concedido_por INTEGER REFERENCES users(id) ON DELETE SET NULL,
    PRIMARY KEY (user_id, permissao)
);

-- A leitura quente e "as permissoes DESTE usuario", ja coberta pela chave
-- primaria. Este indice serve a pergunta inversa — "quem tem
-- `cofre.revelar`?" — que e a que o controle interno faz numa auditoria.
CREATE INDEX IF NOT EXISTS idx_user_permissoes_permissao
    ON user_permissoes (permissao);


-- ---------------------------------------------------------------------
-- 3. SEMENTE DO CATALOGO — a cada boot, sem marca.
-- ---------------------------------------------------------------------
-- Roda sempre de proposito, ao contrario do backfill: nao concede nada a
-- ninguem (so declara que a chave EXISTE) e e o que faz uma permissao nova
-- passar a ser gravavel no tenant que ja esta no ar, sem migration nova.
--
-- `DO NOTHING` e nao `DO UPDATE`: chave que ja esta la fica como esta.
-- Chave que sumir do Python NAO e apagada daqui — apagar quebraria a FK de
-- quem ainda a tem concedida. Ela fica inerte: a funcao pura
-- (`permissoes_efetivas`) descarta chave fora do catalogo do Python, entao
-- a concessao orfa nao vale nada enquanto alguem nao a remover a mao.
INSERT INTO permissoes_catalogo (chave, secao, escrita) VALUES
    ('gestao.ver', 'trabalho', FALSE),
    ('gestao.criar', 'trabalho', TRUE),
    ('gestao.editar', 'trabalho', TRUE),
    ('gestao.excluir', 'trabalho', TRUE),
    ('gestao.exportar', 'trabalho', FALSE),
    ('gestao.anexo_baixar', 'trabalho', FALSE),
    ('rm.ver', 'trabalho', FALSE),
    ('rm.criar', 'trabalho', TRUE),
    ('rm.editar', 'trabalho', TRUE),
    ('rm.excluir', 'trabalho', TRUE),
    ('rm.exportar', 'trabalho', FALSE),
    ('documentos.ver', 'trabalho', FALSE),
    ('documentos.criar', 'trabalho', TRUE),
    ('documentos.editar', 'trabalho', TRUE),
    ('documentos.excluir', 'trabalho', TRUE),
    ('documentos.exportar', 'trabalho', FALSE),
    ('convenios.ver', 'convenios', FALSE),
    ('convenios.exportar', 'convenios', FALSE),
    ('convenios.atualizar', 'convenios', TRUE),
    ('transferegov.ver', 'convenios', FALSE),
    ('transferegov.exportar', 'convenios', FALSE),
    ('transferegov.atualizar', 'convenios', TRUE),
    ('cauc.ver', 'convenios', FALSE),
    ('cauc.exportar', 'convenios', FALSE),
    ('cauc.atualizar', 'convenios', TRUE),
    ('sismob.ver', 'convenios', FALSE),
    ('sismob.exportar', 'convenios', FALSE),
    ('sismob.atualizar', 'convenios', TRUE),
    ('acordofes.ver', 'convenios', FALSE),
    ('acordofes.exportar', 'convenios', FALSE),
    ('acordofes.atualizar', 'convenios', TRUE),
    ('emendas.ver', 'consultas', FALSE),
    ('emendas.exportar', 'consultas', FALSE),
    ('fns.ver', 'consultas', FALSE),
    ('fns.exportar', 'consultas', FALSE),
    -- InvestSUS entrou depois, junto do grupo SAUDE do menu. Herda de
    -- 'consultas' como o FNS, que e a tela vizinha: quem ja podia ver o Fundo
    -- Nacional de Saude passa a ver os repasses do InvestSUS sem concessao nova.
    -- So `ver`: a fonte e fechada e nao ha coletor, entao `exportar`/`atualizar`
    -- nao teriam rota para governar (ver o comentario em services/permissoes.py).
    ('investsus.ver', 'consultas', FALSE),
    ('simec.ver', 'consultas', FALSE),
    ('simec.exportar', 'consultas', FALSE),
    ('parlamentares.ver', 'consultas', FALSE),
    ('parlamentares.exportar', 'consultas', FALSE),
    ('dou.ver', 'consultas', FALSE),
    ('dou.exportar', 'consultas', FALSE),
    ('frescor.ver', 'consultas', FALSE),
    ('frescor.exportar', 'consultas', FALSE),
    ('bi.ver', 'bi', FALSE),
    ('bi.exportar', 'bi', FALSE),
    ('bi.tela', 'bi', FALSE),
    ('bi.link', 'bi', FALSE),
    ('ai.usar', 'ia', TRUE),
    ('ai.exportar', 'ia', TRUE),
    ('cofre.ver', 'cofre', FALSE),
    ('cofre.criar', 'cofre', TRUE),
    ('cofre.editar', 'cofre', TRUE),
    ('cofre.excluir', 'cofre', TRUE),
    ('cofre.revelar', 'cofre', FALSE),
    ('sessoes.ver', 'cofre', FALSE),
    ('sessoes.capturar', 'cofre', TRUE),
    ('usuarios.ver', 'usuarios', FALSE),
    ('usuarios.criar', 'usuarios', TRUE),
    ('usuarios.editar', 'usuarios', TRUE),
    ('usuarios.excluir', 'usuarios', TRUE),
    ('usuarios.conceder', 'usuarios', TRUE),
    -- Incremento 7 (modelos de permissao). Entra NESTA semente, e nao numa
    -- migration propria, porque e aqui que mora a tabela-catalogo que serve de
    -- chave estrangeira — e porque esta semente roda a CADA boot, que e o que
    -- faz a chave nova virar gravavel num tenant que ja esta no ar.
    ('usuarios.modelos', 'usuarios', TRUE),
    ('usuarios.resetar_senha', 'usuarios', TRUE),
    ('telegram.vincular', 'telegram', TRUE),
    ('telegram.administrar', 'telegram', TRUE),
    ('auditoria.ver', 'auditoria', FALSE),
    ('auditoria.exportar', 'auditoria', FALSE),
    -- Telemetria de uso: navegacao e presenca. Separada da Auditoria de
    -- proposito — a trilha guarda ato consequente e serve de prova; esta guarda
    -- navegacao e serve para entender o uso.
    ('uso.ver', 'auditoria', FALSE)
ON CONFLICT (chave) DO NOTHING;


-- ---------------------------------------------------------------------
-- 4. ⭐ BACKFILL DE COMPATIBILIDADE — UMA VEZ NA VIDA DO BANCO.
-- ---------------------------------------------------------------------
-- A regra, palavra por palavra: "quem tem a tela X hoje recebe X.ver e
-- X.exportar; os verbos de ESCRITA so para quem e `admin` hoje".
--
-- O mapa abaixo e essa regra escrita como dado, e cada linha e uma
-- traducao do que o sistema JA FAZ hoje — nao do que seria bonito:
--
--   * `gestao.anexo_baixar` entra com as de LEITURA porque hoje quem abre
--     a Gestao Interna baixa o anexo (GET, sem gate proprio). Deixa-lo de
--     fora tiraria um acesso que a pessoa tem.
--
--   * `cofre.revelar` e o CRUD do Cofre so para admin, e nao para quem tem
--     a tela: hoje `routers/cofre.py` exige `role == 'admin'` em revelar,
--     criar, editar e excluir — a tela `cofre` sozinha da apenas a
--     listagem mascarada. A traducao preserva exatamente isso.
--
--   * `usuarios.*` e `frescor.*` nao tem tela correspondente (a tela de
--     Usuarios e o monitor de frescor sempre foram `role == 'admin'`),
--     entao a linha vem com tela NULL e exige_admin.
--
--   * `ai.usar`, `ai.exportar` e `telegram.vincular` sao acoes de ESCRITA
--     (o endpoint e POST) e ainda assim NAO exigem admin: hoje quem abre a
--     tela da IA conversa e exporta, e quem abre o Telegram liga o PROPRIO
--     celular. Sao os tres casos em que "ninguem pode perder acesso no
--     deploy" vence a simetria da regra — e sao os tres unicos, travados
--     por teste (tests/test_permissoes_migration.py).
--
--   * `auditoria.exportar` acompanha `auditoria.ver` porque hoje a mesma
--     tela exporta. E o CSV entrega IP e quem revelou qual senha — e a
--     primeira caixinha que o dono deve revisar depois do deploy. Tirar
--     acesso e decisao do administrador na tela de Usuarios, nunca efeito
--     colateral de um deploy.
--
-- QUEM FICA DE FORA, e por que:
--   * usuario INATIVO — nao passa nem pelo login (`get_current_user`
--     recusa `not user.active`); conceder para ele seria acesso dormente
--     aparecendo na tela sem ninguem ter pedido. Mesma decisao do
--     Incremento 4.
--   * SUPER-ADMIN — "esses tem tudo... sao tipo ROOT", e a funcao pura ja
--     devolve o catalogo inteiro para eles. Dar linha aqui desenharia 66
--     caixinhas marcadas para o dono da plataforma e sugeriria que alguem
--     poderia DESMARCA-LAS.
--   * QUIOSQUE (o `viewer` do link publico de TV) — nao e admin e nao tem
--     linha em `user_telas`, entao nao casa com nada aqui. O que aquele
--     link alcanca continua decidido por KIOSK_GET_PERMITIDOS e pelo
--     conjunto fixo `PERMISSOES_QUIOSQUE`.
WITH marca AS (
    INSERT INTO migration_backfills (nome)
    VALUES ('add_permissoes_por_acao:compat_telas_e_papel')
    ON CONFLICT (nome) DO NOTHING
    RETURNING nome
), mapa(tela, permissao, exige_admin) AS (
    -- (tela de hoje, permissao nova, so para quem e admin hoje)
    VALUES
        -- Trabalho do dia a dia
        ('gestao'::text, 'gestao.ver', FALSE),
        ('gestao', 'gestao.exportar', FALSE),
        ('gestao', 'gestao.anexo_baixar', FALSE),
        ('gestao', 'gestao.criar', TRUE),
        ('gestao', 'gestao.editar', TRUE),
        ('gestao', 'gestao.excluir', TRUE),
        ('rm', 'rm.ver', FALSE),
        ('rm', 'rm.exportar', FALSE),
        ('rm', 'rm.criar', TRUE),
        ('rm', 'rm.editar', TRUE),
        ('rm', 'rm.excluir', TRUE),
        ('documentos', 'documentos.ver', FALSE),
        ('documentos', 'documentos.exportar', FALSE),
        ('documentos', 'documentos.criar', TRUE),
        ('documentos', 'documentos.editar', TRUE),
        ('documentos', 'documentos.excluir', TRUE),
        -- Convenios e transferencias (atualizar = disparar coleta = escrita)
        ('convenios', 'convenios.ver', FALSE),
        ('convenios', 'convenios.exportar', FALSE),
        ('convenios', 'convenios.atualizar', TRUE),
        ('transferegov', 'transferegov.ver', FALSE),
        ('transferegov', 'transferegov.exportar', FALSE),
        ('transferegov', 'transferegov.atualizar', TRUE),
        ('cauc', 'cauc.ver', FALSE),
        ('cauc', 'cauc.exportar', FALSE),
        ('cauc', 'cauc.atualizar', TRUE),
        ('sismob', 'sismob.ver', FALSE),
        ('sismob', 'sismob.exportar', FALSE),
        ('sismob', 'sismob.atualizar', TRUE),
        ('acordofes', 'acordofes.ver', FALSE),
        ('acordofes', 'acordofes.exportar', FALSE),
        ('acordofes', 'acordofes.atualizar', TRUE),
        -- Consultas e fontes
        ('emendas', 'emendas.ver', FALSE),
        ('emendas', 'emendas.exportar', FALSE),
        ('fns', 'fns.ver', FALSE),
        ('fns', 'fns.exportar', FALSE),
        ('investsus', 'investsus.ver', FALSE),
        ('simec', 'simec.ver', FALSE),
        ('simec', 'simec.exportar', FALSE),
        ('parlamentares', 'parlamentares.ver', FALSE),
        ('parlamentares', 'parlamentares.exportar', FALSE),
        ('dou', 'dou.ver', FALSE),
        ('dou', 'dou.exportar', FALSE),
        (NULL, 'frescor.ver', TRUE),
        (NULL, 'frescor.exportar', TRUE),
        -- Painel de Indicadores: as tres telas viraram quatro caixinhas
        ('bi', 'bi.ver', FALSE),
        ('bi', 'bi.exportar', FALSE),
        ('bi_tela', 'bi.tela', FALSE),
        ('bi_link', 'bi.link', FALSE),
        -- IA: hoje quem abre a tela conversa e exporta
        ('ai', 'ai.usar', FALSE),
        ('ai', 'ai.exportar', FALSE),
        -- Cofre e sessoes: listagem pela tela, o resto pelo papel
        ('cofre', 'cofre.ver', FALSE),
        ('cofre', 'cofre.revelar', TRUE),
        ('cofre', 'cofre.criar', TRUE),
        ('cofre', 'cofre.editar', TRUE),
        ('cofre', 'cofre.excluir', TRUE),
        ('sessoes', 'sessoes.ver', FALSE),
        ('sessoes', 'sessoes.capturar', TRUE),
        -- Usuarios: sempre foi papel, nunca tela
        (NULL, 'usuarios.ver', TRUE),
        (NULL, 'usuarios.criar', TRUE),
        (NULL, 'usuarios.editar', TRUE),
        (NULL, 'usuarios.excluir', TRUE),
        (NULL, 'usuarios.conceder', TRUE),
        -- ⚠️ `usuarios.modelos` (Incremento 7) esta aqui porque TODA chave do
        -- catalogo precisa de linha neste mapa — sem ela, o teste
        -- tests/test_permissoes_migration.py quebra e a chave nasceria
        -- concedida a ninguem sem ninguem ter decidido isso.
        --
        -- MAS ela so alcanca BANCO NOVO, e a assimetria e proposital: este
        -- backfill roda UMA VEZ na vida do banco (a marca em
        -- `migration_backfills`), e nos tenants que ja subiram a marca existe ha
        -- semanas. Ou seja: em Monte Siao, ninguem ganha esta caixinha no
        -- deploy — ela e concedida a mao, pelo dono da plataforma, a quem ele
        -- escolher. E o resultado CERTO nas duas pontas: ninguem PERDE nada
        -- (era funcao que nao existia), e a receita que dirige o que os outros
        -- administradores concedem nao nasce distribuida por deploy.
        (NULL, 'usuarios.modelos', TRUE),
        (NULL, 'usuarios.resetar_senha', TRUE),
        -- Telegram: o proprio vinculo pela tela, o webhook pelo papel
        ('telegram', 'telegram.vincular', FALSE),
        ('telegram', 'telegram.administrar', TRUE),
        -- Auditoria
        ('auditoria', 'auditoria.ver', FALSE),
        ('auditoria', 'auditoria.exportar', FALSE),
        -- Telemetria de uso. Herda da tela `auditoria`, e nao de admin: a
        -- regra da casa (com teste proprio) e que verbo `ver` NUNCA exige
        -- admin e sempre vem de uma tela — quem tem a tela hoje nao pode
        -- perder acesso no deploy.
        -- E o agrupamento e coerente: quem ja enxerga a trilha (quem entrou,
        -- de que IP, o que revelou) enxerga tambem a navegacao. Sao duas
        -- ABAS separadas na tela, com propositos diferentes, mas uma
        -- permissao so. Se um dia o dono quiser separar de verdade, o
        -- caminho e uma tela `uso` propria — mexe no catalogo de telas.
        ('auditoria', 'uso.ver', FALSE)
)
INSERT INTO user_permissoes (user_id, permissao)
SELECT u.id, m.permissao
  FROM marca, users u
 CROSS JOIN mapa m
 WHERE u.active
   AND NOT u.super_admin
   AND (NOT m.exige_admin OR u.role = 'admin')
   AND (m.tela IS NULL
        OR EXISTS (SELECT 1
                     FROM user_telas ut
                    WHERE ut.user_id = u.id
                      AND ut.tela = m.tela))
-- `DO NOTHING` e nao `DO UPDATE`: se alguem ja tiver a linha (concedida a
-- mao antes deste boot), ela fica com o `concedido_em` e o
-- `concedido_por` originais.
ON CONFLICT DO NOTHING;
