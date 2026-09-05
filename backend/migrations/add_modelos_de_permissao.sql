-- =====================================================================
-- Incremento 7 — MODELOS DE PERMISSAO (o MOLDE), por COPIA.
--
-- O PROBLEMA E DE OPERACAO, NAO DE SEGURANCA. O catalogo tem dezenas de
-- permissoes, mais o alcance por modulo. Cadastrar um servidor novo virou
-- marcar todas as caixinhas a mao — e um administrador cansado marca
-- TUDO. Sem esta peca, o RBAC por usuario do Incremento 5 se desfaz
-- sozinho na pratica, sem ninguem mexer numa linha de codigo.
--
-- ⚠️⚠️ E A SOLUCAO NAO PODE TRAIR A REGRA DO DONO:
--
--     "as permissoes sao colocadas no usuario da pessoa, INDIVIDUALMENTE.
--      Grupo e so ROTULO. Nao da pra limitar dentro de uma prefeitura que
--      todos os analistas terao o mesmo acesso, isso e besteira."
--
-- Entao estas tres tabelas NAO sao grupos e NAO sao heranca. Note o que
-- elas NAO tem: **nao existe coluna nenhuma ligando um usuario a um
-- modelo**. Nem em `users`, nem numa tabela de junção. A ausencia e a
-- feature: aplicar um modelo COPIA as permissoes para `user_permissoes` e
-- `user_escopos` naquele instante, e o vinculo acaba ali. Depois disso o
-- modelo pode mudar, ser renomeado ou ser APAGADO que o usuario nao muda.
--
-- E o que mantem o sistema respondivel: "o que esta pessoa pode?" continua
-- tendo resposta olhando a PESSOA. Com heranca, seria preciso saber a que
-- grupo ela pertence, o que aquele grupo tem hoje e o que ele tinha na
-- semana em que alguem reclamou.
--
-- ⚠️ CONSEQUENCIA, e ela precisa estar escrita: editar um modelo NAO
-- corrige ninguem. Molde errado ja aplicado a cinco pessoas = cinco
-- cadastros a corrigir. E o preco da regra do dono, e e menor do que o
-- preco de nao conseguir dizer quem pode o que.
--
-- ---------------------------------------------------------------------
-- ⚠️ POR QUE A SEMENTE DOS MOLDES CRUZA `migration_backfills` (e a do
--    catalogo de permissoes NAO cruza) — leia antes de mexer.
-- ---------------------------------------------------------------------
-- `services/startup.py` roda TODO arquivo da lista a CADA boot e engole
-- erro. Para DDL idempotente isso e inofensivo. Para dado que o
-- ADMINISTRADOR pode editar, nao e.
--
-- A semente de `permissoes_catalogo` (add_permissoes_por_acao.sql) roda a
-- cada boot de proposito: aquilo e CATALOGO — ninguem apaga, ninguem
-- edita, e declarar que uma chave existe nao concede nada a ninguem.
--
-- Modelo e o contrario: e dado de trabalho do cliente. O administrador
-- apaga o molde que nao serve a prefeitura dele, renomeia, tira uma
-- caixinha. Sem a marca, o boot seguinte RESSUSCITARIA o molde apagado e
-- REPORIA a caixinha removida — e o defeito seria invisivel ate alguem
-- reclamar que "o modelo voltou sozinho". Por isso a semente inteira roda
-- UMA VEZ na vida do banco, cruzada com a marca.
--
-- (Semear moldes NAO concede permissao a ninguem: molde e inerte ate
-- alguem aplica-lo, e aplicar continua limitado ao que quem aplica tem.
-- A marca aqui protege o TRABALHO DO ADMINISTRADOR, nao o acesso.)
--
-- ⚠️ DEPENDE de add_permissoes_por_acao.sql (`permissoes_catalogo`, que e
-- o alvo da FK, e a chave `usuarios.modelos`) e de add_escopo_por_modulo
-- (`escopo_recursos`). As duas vem antes nesta lista do runner.
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1. O MODELO — so o rotulo e a procedencia.
-- ---------------------------------------------------------------------
-- `nome` UNIQUE porque o molde e escolhido PELO NOME num seletor: dois
-- "Somente consulta" fariam o administrador aplicar um achando que era o
-- outro. O indice funcional em `lower(nome)` fecha a mesma porta pela
-- caixa alta ("Cofre" x "cofre"), que a UNIQUE crua deixaria passar — o
-- banco como ultima linha de defesa, junto com a checagem do router.
--
-- `criado_por`/`atualizado_por` sao a resposta BARATA para "de onde veio
-- este molde?"; a trilha de auditoria continua sendo a fonte oficial do
-- "quem, quando e o que mudou" (modelo_permissao.criar/editar/excluir).
-- ON DELETE SET NULL: apagar a conta de quem criou nao pode levar junto o
-- molde que a prefeitura inteira usa.
--
-- ⚠️ NAO ha coluna `sistema`/`protegido` nos moldes semeados abaixo, e a
-- ausencia e deliberada: um molde semeado e um molde como outro qualquer,
-- editavel e apagavel. Marca-lo como "do sistema" sugeriria que o cliente
-- nao pode adapta-lo a prefeitura dele — que e justamente o que ele mais
-- precisa fazer.
CREATE TABLE IF NOT EXISTS modelos_permissao (
    id            SERIAL PRIMARY KEY,
    nome          TEXT NOT NULL UNIQUE,
    descricao     TEXT,
    criado_em     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    criado_por    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    atualizado_em TIMESTAMPTZ,
    atualizado_por INTEGER REFERENCES users(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_modelos_permissao_nome_lower
    ON modelos_permissao (lower(nome));


-- ---------------------------------------------------------------------
-- 2. O CONTEUDO — as caixinhas do molde.
-- ---------------------------------------------------------------------
-- FK para `permissoes_catalogo` pela MESMA razao de `user_permissoes`: um
-- typo (`cofre.revellar`) gravaria sem reclamar e produziria um molde que
-- promete uma permissao e nunca a concede — falha silenciosa, e desta vez
-- multiplicada por todo mundo que aplicar o molde.
--
-- ON DELETE CASCADE no modelo: apagou o molde, some o conteudo dele.
-- ON DELETE RESTRICT no catalogo: mesma regra do resto do sistema — tirar
-- uma permissao do catalogo com alguem usando tem de DOER.
CREATE TABLE IF NOT EXISTS modelo_permissoes (
    modelo_id INTEGER NOT NULL REFERENCES modelos_permissao(id) ON DELETE CASCADE,
    permissao TEXT NOT NULL REFERENCES permissoes_catalogo(chave)
                   ON UPDATE CASCADE ON DELETE RESTRICT,
    PRIMARY KEY (modelo_id, permissao)
);

-- A leitura quente ("o conteudo DESTE molde") ja esta na chave primaria.
-- Este indice serve a pergunta inversa — "que moldes carregam
-- `cofre.revelar`?" —, que e a que o controle interno faz quando quer
-- saber por onde uma permissao sensivel esta se espalhando.
CREATE INDEX IF NOT EXISTS idx_modelo_permissoes_permissao
    ON modelo_permissoes (permissao);


-- ---------------------------------------------------------------------
-- 3. O ALCANCE do molde — "editar somente os que ele criou", por modulo.
-- ---------------------------------------------------------------------
-- Mesma forma de `user_escopos`, e pelas mesmas razoes: tabela propria (e
-- nao coluna em `modelo_permissoes`, que e por CHAVE e nao por MODULO), FK
-- para o catalogo de modulos escopaveis, e CHECK como terceira trava do
-- vocabulario.
--
-- ⚠️ SO O QUE RESTRINGE VIRA LINHA. Ausencia de linha e `todos`, exatamente
-- como em `user_escopos` — ha um unico jeito de dizer "sem restricao" no
-- banco inteiro, e ele e a ausencia. Materializar `todos` aqui criaria uma
-- segunda resposta para a mesma pergunta.
CREATE TABLE IF NOT EXISTS modelo_escopos (
    modelo_id INTEGER NOT NULL REFERENCES modelos_permissao(id) ON DELETE CASCADE,
    recurso   TEXT NOT NULL REFERENCES escopo_recursos(recurso)
                   ON UPDATE CASCADE ON DELETE RESTRICT,
    escopo    TEXT NOT NULL DEFAULT 'todos'
                   CHECK (escopo IN ('todos', 'proprios')),
    PRIMARY KEY (modelo_id, recurso)
);


-- ---------------------------------------------------------------------
-- 4. ⭐ SEMENTE — QUATRO MOLDES, UMA VEZ NA VIDA DO BANCO.
-- ---------------------------------------------------------------------
-- Os nomes saem das TELAS que o sistema tem, e nao de cargos inventados:
-- quem so consulta, quem opera a Gestao Interna, quem cuida do Cofre e das
-- coletas, e o prefeito que ve o Painel. Sao os quatro modos de usar o
-- PACTHA que existem hoje em Monte Siao.
--
-- ⚠️ TRES REGRAS VALERAM NA ESCOLHA DAS CAIXINHAS, e a proxima pessoa que
-- editar esta semente precisa delas:
--
--   a) MOLDE E PISO, NAO TETO. Ele existe para o administrador nao marcar
--      tudo por cansaco; se ele proprio ja vier marcando demais, o remedio
--      vira a doenca. Na duvida, a caixinha FICA DE FORA — acrescentar uma
--      e um clique, e o administrador ve o que esta acrescentando.
--
--   b) NENHUM MOLDE CARREGA O IRREVERSIVEL. `cofre.excluir` e o `excluir`
--      sem alcance ficam de fora: aplicar o molde no usuario errado nao
--      pode custar dado que nao volta. (Revelar a senha do portal FICA no
--      molde do Cofre — sem ela "cuidar do cofre" nao existe, e e leitura,
--      nao destruicao. Ela vira linha na trilha a cada uso.)
--
--   c) O QUE CRIA ACESSO PARA TERCEIROS FICA DE FORA. `bi.link` publica um
--      endereco que abre o Painel SEM LOGIN e circula por WhatsApp; e a
--      unica acao do Painel que nao afeta so quem clicou. Publicar tem de
--      ser um clique deliberado, nunca efeito de aplicar um molde.
WITH marca AS (
    INSERT INTO migration_backfills (nome)
    VALUES ('add_modelos_de_permissao:semente_dos_quatro_moldes')
    ON CONFLICT (nome) DO NOTHING
    RETURNING nome
), definicao(nome, descricao) AS (
    VALUES
        ('Somente consulta'::text,
         'Ve e exporta as telas de consulta, os convenios e o trabalho do '
         'setor, e nao altera nada. Nao dispara coleta de dados, nao abre o '
         'Cofre e nao baixa os anexos digitalizados da Gestao Interna (esse '
         'e o unico item de leitura que entrega documento escaneado — marque '
         'a mao se a pessoa precisar).'::text),
        ('Gestao Interna - operacao',
         'Quem produz o trabalho do dia a dia: anotacoes da Gestao Interna, '
         'Relatorio de Monitoramento e Documentos, com criar, editar e '
         'excluir. Vem com o alcance em SOMENTE OS QUE ELE CRIOU nos tres '
         'modulos: a pessoa nao apaga nem altera o registro de um colega. Se '
         'o setor trabalha em cima dos mesmos registros, troque o alcance '
         'para «Todos os registros» antes de salvar.'),
        ('Cofre e convenios',
         'Quem cuida das credenciais dos portais do governo e das coletas: '
         've e revela as senhas do Cofre, cadastra e altera credencial, '
         'acompanha as sessoes, e manda o sistema buscar dados novos no '
         'SIGCON, TransfereGov, CAUC, SISMOB e Acordo FES. NAO inclui apagar '
         'credencial — marque a mao quando for o caso.'),
        ('Painel do prefeito',
         'So o Painel de Indicadores: ver, exportar e configurar o Modo Tela '
         'da TV do gabinete. NAO inclui gerar o link publico (aquele abre o '
         'painel sem login para quem tiver o endereco). Costuma vir junto '
         'com a trava de «somente leitura» no cadastro da pessoa.')
), novos AS (
    INSERT INTO modelos_permissao (nome, descricao)
    SELECT d.nome, d.descricao
      FROM marca, definicao d
    ON CONFLICT (nome) DO NOTHING
    RETURNING id, nome
), conteudo(modelo, permissao) AS (
    VALUES
        -- --- 1. Somente consulta: ver + exportar, e nada mais ------------
        ('Somente consulta'::text, 'gestao.ver'::text),
        ('Somente consulta', 'gestao.exportar'),
        ('Somente consulta', 'rm.ver'),
        ('Somente consulta', 'rm.exportar'),
        ('Somente consulta', 'documentos.ver'),
        ('Somente consulta', 'documentos.exportar'),
        ('Somente consulta', 'convenios.ver'),
        ('Somente consulta', 'convenios.exportar'),
        ('Somente consulta', 'transferegov.ver'),
        ('Somente consulta', 'transferegov.exportar'),
        ('Somente consulta', 'cauc.ver'),
        ('Somente consulta', 'cauc.exportar'),
        ('Somente consulta', 'sismob.ver'),
        ('Somente consulta', 'sismob.exportar'),
        ('Somente consulta', 'acordofes.ver'),
        ('Somente consulta', 'acordofes.exportar'),
        ('Somente consulta', 'emendas.ver'),
        ('Somente consulta', 'emendas.exportar'),
        ('Somente consulta', 'fns.ver'),
        ('Somente consulta', 'fns.exportar'),
        ('Somente consulta', 'simec.ver'),
        ('Somente consulta', 'simec.exportar'),
        ('Somente consulta', 'parlamentares.ver'),
        ('Somente consulta', 'parlamentares.exportar'),
        ('Somente consulta', 'dou.ver'),
        ('Somente consulta', 'dou.exportar'),

        -- --- 2. Gestao Interna - operacao -------------------------------
        ('Gestao Interna - operacao', 'gestao.ver'),
        ('Gestao Interna - operacao', 'gestao.criar'),
        ('Gestao Interna - operacao', 'gestao.editar'),
        ('Gestao Interna - operacao', 'gestao.excluir'),
        ('Gestao Interna - operacao', 'gestao.exportar'),
        -- Quem produz a anotacao precisa reabrir o oficio que anexou nela.
        ('Gestao Interna - operacao', 'gestao.anexo_baixar'),
        ('Gestao Interna - operacao', 'rm.ver'),
        ('Gestao Interna - operacao', 'rm.criar'),
        ('Gestao Interna - operacao', 'rm.editar'),
        ('Gestao Interna - operacao', 'rm.excluir'),
        ('Gestao Interna - operacao', 'rm.exportar'),
        ('Gestao Interna - operacao', 'documentos.ver'),
        ('Gestao Interna - operacao', 'documentos.criar'),
        ('Gestao Interna - operacao', 'documentos.editar'),
        ('Gestao Interna - operacao', 'documentos.excluir'),
        ('Gestao Interna - operacao', 'documentos.exportar'),
        -- Leitura das bases sobre as quais ele anota. Sem `atualizar`: uma
        -- coleta muda dezenas de registros para TODO MUNDO, e nao e o
        -- trabalho de quem opera a Gestao Interna.
        ('Gestao Interna - operacao', 'convenios.ver'),
        ('Gestao Interna - operacao', 'convenios.exportar'),
        ('Gestao Interna - operacao', 'transferegov.ver'),
        ('Gestao Interna - operacao', 'transferegov.exportar'),
        ('Gestao Interna - operacao', 'cauc.ver'),
        ('Gestao Interna - operacao', 'cauc.exportar'),
        -- (`telegram.vincular` saiu daqui em 05/09/2026, no mesmo commit que a
        --  tirou da semente de `permissoes_catalogo` — esta coluna e FK daquela
        --  tabela, entao as duas TEM de sair juntas ou o banco novo nao sobe.)

        -- --- 3. Cofre e convenios ---------------------------------------
        ('Cofre e convenios', 'cofre.ver'),
        ('Cofre e convenios', 'cofre.criar'),
        ('Cofre e convenios', 'cofre.editar'),
        ('Cofre e convenios', 'cofre.revelar'),
        ('Cofre e convenios', 'sessoes.ver'),
        ('Cofre e convenios', 'convenios.ver'),
        ('Cofre e convenios', 'convenios.exportar'),
        ('Cofre e convenios', 'convenios.atualizar'),
        ('Cofre e convenios', 'transferegov.ver'),
        ('Cofre e convenios', 'transferegov.exportar'),
        ('Cofre e convenios', 'transferegov.atualizar'),
        ('Cofre e convenios', 'cauc.ver'),
        ('Cofre e convenios', 'cauc.exportar'),
        ('Cofre e convenios', 'cauc.atualizar'),
        ('Cofre e convenios', 'sismob.ver'),
        ('Cofre e convenios', 'sismob.exportar'),
        ('Cofre e convenios', 'sismob.atualizar'),
        ('Cofre e convenios', 'acordofes.ver'),
        ('Cofre e convenios', 'acordofes.exportar'),
        ('Cofre e convenios', 'acordofes.atualizar'),
        -- Ha quanto tempo cada fonte foi coletada: e o painel de quem
        -- responde pela coleta.
        ('Cofre e convenios', 'frescor.ver'),

        -- --- 4. Painel do prefeito --------------------------------------
        ('Painel do prefeito', 'bi.ver'),
        ('Painel do prefeito', 'bi.exportar'),
        ('Painel do prefeito', 'bi.tela')
), ins_conteudo AS (
    INSERT INTO modelo_permissoes (modelo_id, permissao)
    SELECT n.id, c.permissao
      FROM novos n
      JOIN conteudo c ON c.modelo = n.nome
    ON CONFLICT DO NOTHING
    RETURNING modelo_id
), alcance(modelo, recurso, escopo) AS (
    -- ⚠️ SO O MOLDE DE OPERACAO RESTRINGE, e so ele deveria. O alcance
    -- `proprios` e o que impede um operador de apagar (sem desfazer) a
    -- anotacao de um colega — e o que faz o molde poder incluir `excluir`
    -- sem violar a regra (b) la de cima.
    VALUES
        ('Gestao Interna - operacao'::text, 'gestao'::text, 'proprios'::text),
        ('Gestao Interna - operacao', 'rm', 'proprios'),
        ('Gestao Interna - operacao', 'documentos', 'proprios')
)
INSERT INTO modelo_escopos (modelo_id, recurso, escopo)
SELECT n.id, a.recurso, a.escopo
  FROM novos n
  JOIN alcance a ON a.modelo = n.nome
ON CONFLICT DO NOTHING;
