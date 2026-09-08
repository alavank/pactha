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
    -- AGENDAMENTOS (02/09/2026), modulo novo.
    -- ⚠️ ENTRA TAMBEM NO MAPA DE COMPATIBILIDADE mais abaixo, e nao so aqui.
    -- Um comentario anterior dizia o contrario, e estava errado: permissao sem
    -- linha no mapa nasce concedida A NINGUEM, e o
    -- `test_toda_permissao_tem_regra_de_compatibilidade` cobra isso. A regra
    -- la e "quem tem a TELA agendamentos ganha estas chaves" — que hoje nao
    -- concede nada a ninguem em tenant existente (ninguem tem a tela ainda) e
    -- em tenant NOVO da ao administrador o modulo inteiro, junto com o resto.
    ('agendamentos.ver', 'trabalho', FALSE),
    ('agendamentos.criar', 'trabalho', TRUE),
    ('agendamentos.editar', 'trabalho', TRUE),
    ('agendamentos.excluir', 'trabalho', TRUE),
    ('agendamentos.exportar', 'trabalho', FALSE),
    ('agendamentos.anexo_baixar', 'trabalho', FALSE),
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
    -- ⚠️ `transferegov.ver` e `transferegov.exportar` SAIRAM em 05/09/2026,
    -- quando o grupo FEDERAIS virou oito telas (ver o bloco novo abaixo).
    -- Sobrou `atualizar`: a COLETA nao e de tela nenhuma — o botao dela mora em
    -- Configuracoes › Sessões, e uma coleta so alimenta as oito de uma vez.
    -- Sair daqui so alcanca BANCO NOVO; nos cinco que ja estao no ar as duas
    -- linhas ficam dormentes em `permissoes_catalogo` (apagar esbarraria no ON
    -- DELETE RESTRICT de `user_permissoes`), e a migration
    -- `add_permissoes_por_tela.sql` traduz as concessoes antigas para as novas.
    ('transferegov.atualizar', 'convenios', TRUE),

    -- ⭐⭐ AS DEZOITO TELAS DO INCREMENTO «PERMISSAO POR TELA» (05/09/2026).
    --
    -- Pedido do dono: granularidade Modulo › Tela › Acao — «em Federais posso
    -- liberar Em execução e não PAC». Ate aqui UMA chave governava as sete
    -- telas de FEDERAIS e outra as dez de ESTADUAIS: o administrador marcava
    -- «Transfere Gov» e concedia sete telas sem saber que estava concedendo
    -- sete.
    --
    -- ⚠️ ENTRAM NESTA SEMENTE, e nao numa migration propria, pela mesma razao
    -- ja escrita para `vigencias.*` mais abaixo: e AQUI que mora a
    -- tabela-catalogo que serve de chave estrangeira, e esta semente roda a
    -- CADA boot com DO NOTHING — entao a chave nova passa a ser gravavel nos
    -- cinco tenants que ja estao no ar, sem migration nenhuma. Quem traduz as
    -- concessoes ANTIGAS para elas e `add_permissoes_por_tela.sql`.
    ('transferegov_radar.ver', 'convenios', FALSE),
    ('transferegov_geral.ver', 'convenios', FALSE),
    ('transferegov_geral.exportar', 'convenios', FALSE),
    ('transferegov_especiais.ver', 'convenios', FALSE),
    ('transferegov_especiais.exportar', 'convenios', FALSE),
    ('transferegov_pac.ver', 'convenios', FALSE),
    ('transferegov_voluntarias.ver', 'convenios', FALSE),
    ('transferegov_voluntarias.exportar', 'convenios', FALSE),
    ('transferegov_rejeitadas.ver', 'convenios', FALSE),
    ('transferegov_rejeitadas.exportar', 'convenios', FALSE),
    ('transferegov_encerradas.ver', 'convenios', FALSE),
    ('transferegov_encerradas.exportar', 'convenios', FALSE),
    ('transferegov_cnpj.ver', 'convenios', FALSE),
    -- EMENDAS FEDERAIS (06/09/2026). Entra NESTA semente, que roda a cada boot
    -- com DO NOTHING: e assim que a chave passa a ser GRAVAVEL nos cinco tenants
    -- ja no ar (`user_permissoes.permissao` e FK para `permissoes_catalogo.chave`,
    -- entao chave que existe so no Python nao pode ser concedida a ninguem).
    -- So `ver` — a razao esta no catalogo do Python.
    ('emendas_federais.ver', 'convenios', FALSE),
    -- As oito estaduais que sairam de dentro de `convenios`. So `ver`: nenhuma
    -- delas tem rota de exportacao nem de coleta sob demanda hoje.
    ('repasses.ver', 'convenios', FALSE),
    ('cofinanciamento.ver', 'convenios', FALSE),
    ('monitoramento.ver', 'convenios', FALSE),
    ('consulta_popular.ver', 'convenios', FALSE),
    ('programas_rs.ver', 'convenios', FALSE),
    ('funrigs.ver', 'convenios', FALSE),
    ('emendas_rs.ver', 'convenios', FALSE),
    ('tce_rs.ver', 'convenios', FALSE),
    ('cauc.ver', 'convenios', FALSE),
    ('cauc.exportar', 'convenios', FALSE),
    ('cauc.atualizar', 'convenios', TRUE),
    ('sismob.ver', 'convenios', FALSE),
    ('sismob.exportar', 'convenios', FALSE),
    ('sismob.atualizar', 'convenios', TRUE),
    -- Obras Federais (CIPI/Obras.gov.br) entrou em 04/09/2026, junto com o
    -- grupo OBRAS do menu. Herda de 'convenios' no mapa de compatibilidade
    -- abaixo pela tela `obrasgov`. So `ver`: nao ha rota de exportacao nem
    -- de coleta sob demanda para `exportar`/`atualizar` governarem.
    ('obrasgov.ver', 'convenios', FALSE),
    -- Parcerias (Transferegov) entrou em 07/09/2026 com a fonte. Herda de
    -- 'convenios' pela mesma razao que a tela: quem acompanha a emenda que
    -- virou instrumento e quem ja acompanha convenio. So `ver`.
    ('parcerias.ver', 'convenios', FALSE),
    -- Planos de Acao Fundo a Fundo (07/09/2026), pelo mesmo criterio: quem
    -- acompanha o instrumento federal acompanha o plano que o justifica.
    ('faf_planos.ver', 'convenios', FALSE),
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
    -- Vigencias a vencer (08/2026). Caixinha PROPRIA, e nao parte de
    -- `convenios`: o botao «Vigencias <=120d» mora no Painel de Indicadores e o
    -- pedido do dono e liberar SO o monitoramento de vencimento para certas
    -- pessoas, sem entregar o modulo inteiro de Convenios Estaduais. Entra
    -- NESTA semente (que roda a cada boot) e nao numa migration propria, pela
    -- mesma razao de `usuarios.modelos`: e aqui que mora a tabela-catalogo que
    -- serve de chave estrangeira.
    ('vigencias.ver', 'bi', FALSE),
    -- Exportar as vigencias (08/2026). Entra NESTA semente, e nao numa migration
    -- propria, pelo motivo escrito no topo do bloco: e aqui que mora a
    -- tabela-catalogo que serve de chave estrangeira, e a semente roda a cada
    -- boot com DO NOTHING — entao a chave nova passa a ser gravavel nos quatro
    -- tenants que ja estao no ar sem migration nenhuma.
    ('vigencias.exportar', 'bi', FALSE),
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
    -- ⚠️ `usuarios.modelos` (Incremento 7) SAIU desta semente em 05/09/2026,
    -- com o subsistema de MODELOS DE PERMISSAO inteiro (decisao do dono). Mesma
    -- mecanica do Telegram, logo abaixo: sair daqui so alcanca BANCO NOVO, e nos
    -- cinco que ja estao no ar a linha fica dormente em `permissoes_catalogo`.
    ('usuarios.resetar_senha', 'usuarios', TRUE),
    -- ⭐ PARAMETROS (05/09/2026): a aba que cadastra as listas do cliente ganhou
    -- chave propria. Ate aqui ela pegava carona em `usuarios.ver`/`editar` —
    -- quem editava PESSOAS editava as LISTAS, sem jeito de separar.
    ('parametros.ver', 'usuarios', FALSE),
    ('parametros.editar', 'usuarios', TRUE),
    -- `telegram.vincular` e `telegram.administrar` SAIRAM desta semente em
    -- 05/09/2026, com o modulo. Editar migration ja aplicada so alcanca BANCO
    -- NOVO — e e exatamente o efeito desejado: nos cinco bancos que ja estao no
    -- ar as duas linhas ficam dormentes em `permissoes_catalogo` (apagar
    -- esbarraria no ON DELETE RESTRICT de `user_permissoes`), e chave sem par no
    -- catalogo Python e caixinha que nunca aparece na tela.
    -- ⚠️ Sairam DAQUI e do modelo em `add_modelos_de_permissao.sql` no MESMO
    -- commit: aquela tabela referencia esta por chave estrangeira, entao tirar
    -- so de um lado quebraria o bootstrap de um banco novo — a classe de bug
    -- que ja mordeu duas vezes neste repo.
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
        ('agendamentos', 'agendamentos.ver', FALSE),
        ('agendamentos', 'agendamentos.exportar', FALSE),
        ('agendamentos', 'agendamentos.anexo_baixar', FALSE),
        ('agendamentos', 'agendamentos.criar', TRUE),
        ('agendamentos', 'agendamentos.editar', TRUE),
        ('agendamentos', 'agendamentos.excluir', TRUE),
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
        -- ⚠️ ESTE BLOCO SO ALCANCA BANCO NOVO. O guard `migration_backfills`
        -- ('add_permissoes_por_acao:compat_telas_e_papel') ja disparou nos cinco
        -- tenants no ar, entao acrescentar linhas aqui nao os alcanca — quem
        -- traduz as concessoes antigas LA e `add_permissoes_por_tela.sql`, com
        -- guard proprio. Aqui as linhas existem para um tenant criado do zero
        -- nascer coerente, que e o caso de Santa Maria (08/2026) e Nova Palma
        -- (01/09/2026).
        --
        -- ⚠️ `transferegov.atualizar` sai da tela `sessoes`, e nao de uma das
        -- oito de FEDERAIS: o botao da coleta mora em Configuracoes › Sessões.
        ('sessoes', 'transferegov.atualizar', TRUE),
        ('transferegov_radar', 'transferegov_radar.ver', FALSE),
        ('transferegov_geral', 'transferegov_geral.ver', FALSE),
        ('transferegov_geral', 'transferegov_geral.exportar', FALSE),
        ('transferegov_especiais', 'transferegov_especiais.ver', FALSE),
        ('transferegov_especiais', 'transferegov_especiais.exportar', FALSE),
        ('transferegov_pac', 'transferegov_pac.ver', FALSE),
        ('transferegov_voluntarias', 'transferegov_voluntarias.ver', FALSE),
        ('transferegov_voluntarias', 'transferegov_voluntarias.exportar', FALSE),
        ('transferegov_rejeitadas', 'transferegov_rejeitadas.ver', FALSE),
        ('transferegov_rejeitadas', 'transferegov_rejeitadas.exportar', FALSE),
        ('transferegov_encerradas', 'transferegov_encerradas.ver', FALSE),
        ('transferegov_encerradas', 'transferegov_encerradas.exportar', FALSE),
        ('transferegov_cnpj', 'transferegov_cnpj.ver', FALSE),
        -- ⚠️ Este bloco tem guard em `migration_backfills` e JA DISPAROU nos
        -- cinco tenants, entao esta linha so alcanca banco NOVO. Quem alcanca os
        -- cinco e `add_tela_emendas_federais.sql`, que concede a tela E a acao.
        ('emendas_federais', 'emendas_federais.ver', FALSE),
        ('repasses', 'repasses.ver', FALSE),
        ('cofinanciamento', 'cofinanciamento.ver', FALSE),
        ('monitoramento', 'monitoramento.ver', FALSE),
        ('consulta_popular', 'consulta_popular.ver', FALSE),
        ('programas_rs', 'programas_rs.ver', FALSE),
        ('funrigs', 'funrigs.ver', FALSE),
        ('emendas_rs', 'emendas_rs.ver', FALSE),
        ('tce_rs', 'tce_rs.ver', FALSE),
        -- Parametros: tela NULL e admin, como as demais abas de administracao.
        (NULL, 'parametros.ver', TRUE),
        (NULL, 'parametros.editar', TRUE),
        ('cauc', 'cauc.ver', FALSE),
        ('cauc', 'cauc.exportar', FALSE),
        ('cauc', 'cauc.atualizar', TRUE),
        ('sismob', 'sismob.ver', FALSE),
        ('sismob', 'sismob.exportar', FALSE),
        ('sismob', 'sismob.atualizar', TRUE),
        ('obrasgov', 'obrasgov.ver', FALSE),
        ('parcerias', 'parcerias.ver', FALSE),
        ('faf_planos', 'faf_planos.ver', FALSE),
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
        -- ⚠️ `vigencias.ver` esta aqui porque TODA chave do catalogo precisa de
        -- linha neste mapa — sem ela o teste tests/test_permissoes_migration.py
        -- quebra e a chave nasceria concedida a ninguem sem ninguem ter
        -- decidido isso.
        --
        -- MAS, como `usuarios.modelos`, ela so alcanca BANCO NOVO: este bloco e
        -- guardado pela marca em `migration_backfills` e nos quatro tenants que
        -- ja subiram ele e pulado. E esta certo assim — nos bancos que ja estao
        -- no ar NINGUEM perde nada, porque /api/convenios/alertas passou a
        -- aceitar `convenios.ver` OU `vigencias.ver` (ver routers/convenios.py):
        -- quem ja tem Convenios Estaduais continua vendo o botao exatamente
        -- como antes, e a caixinha nova serve para liberar QUEM NAO TEM.
        ('convenios', 'vigencias.ver', FALSE),
        -- Mesma historia de `vigencias.ver`: linha obrigatoria no mapa (senao o
        -- teste de semente quebra) e alcance so de BANCO NOVO, porque este bloco
        -- e guardado pela marca em `migration_backfills`. Nos tenants que ja
        -- subiram ninguem perde: o endpoint aceita `convenios.exportar` OU
        -- `vigencias.exportar`, e quem exporta Convenios continua exportando.
        ('convenios', 'vigencias.exportar', FALSE),
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
        -- (`usuarios.modelos` ocupava esta linha ate 05/09/2026, com os moldes)
        (NULL, 'usuarios.resetar_senha', TRUE),
        -- (o Telegram ocupava estas duas linhas ate 05/09/2026)
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
