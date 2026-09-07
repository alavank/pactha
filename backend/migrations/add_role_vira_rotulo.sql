-- =====================================================================
-- Incremento 4 — O PAPEL VIRA ROTULO.
--
-- Ate hoje `role` CONCEDIA. `services/auth.py::load_user_scopes` zera os
-- dois limites (`allowed_telas = None`, `allowed_municipio_ids = None`)
-- quando `role == 'admin'`, e `ensure_tela`/`ensure_municipio_access`
-- voltam sem negar quando o limite e None. Admin nunca foi "coordenador do
-- cliente": era AUSENCIA TOTAL DE LIMITE — e `routers/users.py` criava
-- usuario com `role='admin'` por DEFAULT, entao um POST sem o campo fazia
-- um deus.
--
-- A regra do dono e o contrario disso: papel (prefeito, analista, usuario)
-- pode continuar existindo, mas so como ROTULO de organizacao interna do
-- cliente. O que vale e a permissao dada a cada usuario INDIVIDUALMENTE.
--
-- Este arquivo mexe em DADO, nao em comportamento: quem le as colunas novas
-- e o codigo do mesmo incremento. O trabalho dele e garantir que, no
-- instante em que o codigo parar de olhar para `role`, ninguem fique do
-- lado de fora.
--
-- ⚠️ O RISCO E O APAGAO, e ele e REAL. Todo admin de cliente hoje vive do
-- bypass por papel e por isso provavelmente NAO TEM LINHA NENHUMA em
-- user_telas/user_municipios — nunca precisou ter. No segundo em que
-- `role == 'admin'` deixa de zerar os limites, esses usuarios passam a
-- valer exatamente o que estiver naquelas duas tabelas: nada. O cliente
-- inteiro perde o sistema no deploy.
--
-- Por isso o BACKFILL vem PRIMEIRO neste arquivo, antes das colunas novas.
-- E o arquivo inteiro e UMA transacao: o runner (`services/startup.py`)
-- faz um unico `cur.execute(arquivo)` e so entao `commit()`. Ou entra
-- tudo, ou nao entra nada — nunca "colunas novas sem as permissoes".
-- =====================================================================


-- ---------------------------------------------------------------------
-- 0. REGISTRO DE BACKFILL — o "ja rodou" que este runner nao tem.
-- ---------------------------------------------------------------------
-- `services/startup.py` roda TODO arquivo da lista a CADA boot e engole
-- erro; nao existe registro de migration aplicada. Para DDL idempotente
-- (`IF NOT EXISTS`) isso e inofensivo. Para BACKFILL nao e: um
-- `INSERT ... ON CONFLICT DO NOTHING` de permissao que rode a cada boot
-- DEVOLVE o acesso que o administrador REVOGOU no dia anterior. E defeito
-- ja registrado neste repo — add_users_kiosk.sql precisou de guarda
-- (`AND NOT kiosk`) pelo mesmo motivo, e la a guarda so evita a reescrita,
-- nao a re-concessao.
--
-- Com esta tabela o backfill roda UMA VEZ na vida do banco: o
-- `INSERT ... RETURNING` da marca so devolve linha na PRIMEIRA vez, e e o
-- cruzamento com essa linha que habilita a concessao. Do segundo boot em
-- diante a marca ja existe, `ON CONFLICT DO NOTHING` nao devolve nada, o
-- cruzamento fica vazio e nenhuma linha de permissao e escrita.
--
-- O detalhe que faz isso funcionar esta no manual do Postgres: comando de
-- escrita dentro de `WITH` executa SEMPRE e por inteiro, mesmo que a
-- consulta externa nao leia a saida dele. Ou seja, a marca fica gravada no
-- mesmo boot em que ela habilitou o backfill.
--
-- Uma marca POR STATEMENT, e nao uma para o arquivo todo: a primeira
-- gravacao ja e visivel para os comandos seguintes da mesma transacao, e
-- eles nao veriam linha nenhuma — o segundo backfill nunca rodaria.
CREATE TABLE IF NOT EXISTS migration_backfills (
    nome        TEXT PRIMARY KEY,
    aplicado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ---------------------------------------------------------------------
-- 1. BACKFILL DAS TELAS — antes de qualquer outra coisa.
-- ---------------------------------------------------------------------
-- Concede EXPLICITAMENTE, a todo usuario hoje `role='admin'` e ativo, o
-- conjunto COMPLETO de telas. E o que ele ja enxerga hoje pelo bypass;
-- aqui isso vira dado, que e o unico jeito de continuar valendo depois.
--
-- A lista e a UNIAO DOS DOIS CATALOGOS, porque eles DIVERGEM:
--   frontend/src/lib/telas.ts        -> 24 chaves
--   backend/services/telas_catalog.py -> 18 chaves
-- O do backend e o que a Central oferece ao CLIENTE e omite de proposito
-- as operacionais da Alavank (cofre, sessoes) e as que nasceram depois
-- (bi_tela, bi_link, suas, paineis). Conceder so as 18 tiraria 6 acessos
-- que o admin TEM HOJE — o objetivo aqui e nao mudar nada para quem ja
-- entra, entao vale a uniao. Tirar acesso e decisao do administrador do
-- cliente, na tela de Usuarios, nao efeito colateral de um deploy.
--
-- Quem NAO entra: usuario inativo. Ele nao passa nem pelo login
-- (`get_current_user` recusa `not user.active`), entao concessao para ele
-- seria acesso dormente aparecendo na tela de permissoes sem ninguem ter
-- pedido. Se um admin desativado for reativado amanha, as telas dele sao
-- dadas a mao — visivel, e a regra nova do sistema.
WITH marca AS (
    INSERT INTO migration_backfills (nome)
    VALUES ('add_role_vira_rotulo:telas_admin')
    ON CONFLICT (nome) DO NOTHING
    RETURNING nome
), catalogo(tela) AS (
    -- Uniao dos dois catalogos, na ordem do frontend (o mais completo).
    -- `telegram` SAIU desta lista em 05/09/2026 pelo mesmo caminho de `suas`:
    -- modulo removido do codigo, tela removida dos tres catalogos.
    VALUES ('dashboard'), ('ai'), ('parlamentares'),
           ('gestao'), ('agendamentos'), ('rm'), ('documentos'),
           ('convenios'), ('emendas'),
           ('cauc'), ('sismob'), ('obrasgov'),
           -- Parcerias (07/09/2026): o modulo do Transferegov onde a emenda
           -- de saude passou a ser processada de 2024 em diante.
           ('parcerias'),
           -- O plano de acao fundo a fundo (07/09/2026): o que justifica o
           -- repasse que o `fns` ja conta, e a origem do dinheiro.
           ('faf_planos'),
           ('acordofes'), ('fns'),
           -- ⭐⭐ O INCREMENTO «PERMISSAO POR TELA» (05/09/2026).
           --
           -- ⚠️ `transferegov` SAIU: deixou de ser tela quando o grupo FEDERAIS
           -- virou oito folhas de menu com chave propria. A chave sobrevive no
           -- catalogo de PERMISSOES so para «Atualizar dados» (a coleta, cujo
           -- botao mora em Configuracoes › Sessões), e por isso nao entra numa
           -- lista de TELAS.
           --
           -- Mesma logica de `investsus` e `agendamentos` acima: este bloco e
           -- guardado pela marca em `migration_backfills`, entao so alcanca
           -- TENANT NOVO — e um tenant novo deve nascer com o administrador
           -- vendo o produto inteiro. Nos cinco bancos ja no ar, quem traduz as
           -- concessoes e `add_permissoes_por_tela.sql`.
           ('transferegov_radar'), ('transferegov_geral'),
           ('transferegov_especiais'), ('transferegov_pac'),
           ('transferegov_voluntarias'), ('transferegov_rejeitadas'),
           ('transferegov_encerradas'), ('transferegov_cnpj'),
           -- ⚠️ `emendas_federais` (06/09/2026) entra AQUI porque `TELAS_TODAS`
           -- e este bloco tem de ser a MESMA lista — e um teste crava isso
           -- (`test_apagao_incremento_4::test_telas_todas_e_a_mesma_lista_do_backfill`):
           -- dois "acesso total" diferentes no mesmo sistema divergem em
           -- silencio. ⚠️ Mas o backfill em si NAO alcanca os cinco tenants:
           -- este arquivo tem guard em `migration_backfills` e ja disparou, o
           -- que faz esta linha valer so para banco NOVO. Quem concede a tela
           -- nos que ja estao no ar e `add_tela_emendas_federais.sql`.
           ('emendas_federais'),
           ('repasses'), ('cofinanciamento'), ('monitoramento'),
           ('consulta_popular'), ('programas_rs'), ('funrigs'),
           ('emendas_rs'), ('tce_rs'),
           -- As quatro abas de Configuracoes que eram governadas pelo PAPEL
           -- `admin` e viraram telas de verdade.
           ('telemetria'), ('frescor'), ('usuarios'), ('parametros'),
           -- ⚠️ `suas` SAIU DESTA LISTA depois que a tela foi aposentada (o
           -- painel do MDS vive dentro de `paineis`). Editar migration já
           -- aplicada seria proibido se ela pudesse rodar de novo — esta NÃO
           -- pode: o bloco inteiro é guardado pela marca em
           -- `migration_backfills`, então em todo banco que já subiu ele é
           -- pulado e nada muda. Quem lê esta lista daqui para a frente é
           -- apenas o TENANT NOVO, e para ele conceder uma tela que não existe
           -- mais seria dar uma linha morta em `user_telas`.
           -- `agendamentos` ENTROU (02/09/2026). Mesma logica: o bloco so
           -- roda em TENANT NOVO, e um tenant novo deve nascer com o
           -- administrador vendo a agenda da equipe. Em tenant que JA EXISTE a
           -- tela e concedida a mao, em Configuracoes -> Usuarios — modulo
           -- novo e capacidade nova, e dar capacidade nova sem ninguem pedir
           -- seria decisao de seguranca tomada pela migration.
           -- `investsus` ENTROU (08/2026, menu SAUDE). Mesma logica do `suas`
           -- acima, no sentido inverso: o bloco e guardado pela marca em
           -- `migration_backfills` e so roda em TENANT NOVO — e um tenant novo
           -- deve nascer com o administrador vendo a pasta da saude inteira.
           -- Nos bancos ja aplicados, quem concede aos existentes e o
           -- add_tela_investsus.sql (quem tem fns ganha investsus).
           ('simec'), ('investsus'), ('paineis'), ('bi'), ('bi_tela'),
           ('bi_link'), ('dou'), ('cofre'), ('sessoes'), ('auditoria')
)
INSERT INTO user_telas (user_id, tela)
SELECT u.id, c.tela
  FROM marca, users u, catalogo c
 WHERE u.role = 'admin'
   AND u.active
-- `ON CONFLICT DO NOTHING` e nao `DO UPDATE`: quem ja tem a linha (porque
-- alguem ja tinha configurado telas para esse admin) fica exatamente como
-- esta, com o `created_at` original.
ON CONFLICT DO NOTHING;


-- ---------------------------------------------------------------------
-- 2. BACKFILL DOS MUNICIPIOS — mesma logica, mesmo risco.
-- ---------------------------------------------------------------------
-- Sem isto, `ensure_municipio_access` passa a negar TODA consulta do admin
-- ("Voce nao tem acesso a este municipio"), inclusive na instancia de um
-- municipio so.
--
-- TODOS os municipios, INCLUSIVE os inativos — e a ausencia do filtro e a
-- decisao. Este arquivo havia escrito `AND m.active`, "para casar com a
-- definicao de municipio ativo que o resto do sistema usa". Casava com o
-- listador e NAO com a verdade que ele esta traduzindo: hoje o admin tem
-- `allowed_municipio_ids = None`, e `ensure_municipio_access` volta sem
-- olhar `active` — ou seja, o admin passa em municipio inativo tambem.
-- Filtrar aqui nao "casa com o sistema": TIRA um acesso que a pessoa tem,
-- que e exatamente o que o backfill das telas evitou ao usar a UNIAO dos
-- dois catalogos em vez do menor deles.
--
-- E o estrago aparece TARDE, que e o pior jeito de aparecer. Municipio
-- inativo nao sai em `GET /api/municipios` (o listador filtra `active`),
-- entao ele nao aparece na tela de Usuarios e ninguem consegue conceder a
-- mao o que este arquivo deixou de conceder. No dia em que a Central
-- REATIVAR aquele municipio — contrato renovado, cidade que voltou para a
-- assessoria — ele reaparece na lista para todo mundo e responde
-- "Voce nao tem acesso a este municipio" para o cliente inteiro, meses
-- depois deste deploy, sem nada na tela ligando uma coisa a outra.
--
-- Conceder o inativo nao expoe nada: enquanto ele estiver desativado nao e
-- listado, nao e coletado e nao entra em consulta nenhuma. A linha fica
-- dormente em `user_municipios` — e some sozinha se o municipio for
-- apagado (a FK e ON DELETE CASCADE).
WITH marca AS (
    INSERT INTO migration_backfills (nome)
    VALUES ('add_role_vira_rotulo:municipios_admin')
    ON CONFLICT (nome) DO NOTHING
    RETURNING nome
)
INSERT INTO user_municipios (user_id, municipio_id)
SELECT u.id, m.id
  FROM marca, users u, municipios m
 WHERE u.role = 'admin'
   AND u.active
ON CONFLICT DO NOTHING;


-- ---------------------------------------------------------------------
-- 3. AS DUAS COLUNAS NOVAS.
-- ---------------------------------------------------------------------
-- super_admin: dono da PLATAFORMA (Alavank), nao "mais um admin do
-- cliente". Ate aqui isso era a allowlist `SUPER_ADMIN_EMAILS`, escrita no
-- CODIGO e copiada em tres arquivos (services/auth.py, setup_db.py,
-- frontend layout.tsx): trocar quem manda exigia DEPLOY, e tres copias de
-- uma regra de permissao divergem em silencio. Virando coluna, a lista do
-- codigo passa a ser SEMENTE (e reforco), nao autoridade.
--
-- DEFAULT FALSE e NOT NULL: quem nao foi semeado explicitamente nao e dono
-- de nada. Fail-closed.
ALTER TABLE users ADD COLUMN IF NOT EXISTS super_admin BOOLEAN NOT NULL DEFAULT FALSE;

-- somente_leitura: a trava de ACAO, agora por USUARIO. Hoje ela mora no
-- papel (`READONLY_ROLES = {'prefeito','viewer'}` em services/auth.py) e e
-- a UNICA trava de acao que o sistema tem — barra POST/PUT/PATCH/DELETE
-- fora de quatro prefixos do Painel.
--
-- Sair do papel para a flag e o que torna possivel o caso que o dono
-- descreveu e que hoje NAO EXISTE: um prefeito que so ve o Painel de
-- Indicadores, outro que tambem acompanha convenios, os dois marcados como
-- "prefeito" no cadastro, cada um com um acesso. Enquanto a trava for o
-- papel, marcar alguem como prefeito decide o acesso dele.
ALTER TABLE users ADD COLUMN IF NOT EXISTS somente_leitura BOOLEAN NOT NULL DEFAULT FALSE;


-- ---------------------------------------------------------------------
-- 4. SEMENTE DO super_admin — os QUATRO e-mails, e so eles.
-- ---------------------------------------------------------------------
-- Espelha `services/auth.py::SUPER_ADMIN_EMAILS` (e a copia em
-- setup_db.py::seed_data). `admin@pactha.com.br` saiu da lista em
-- 02/08/2026 e NAO entra aqui: o e-mail era generico e adivinhavel, entao
-- qualquer admin do cliente que o recriasse na tela de Usuarios ganhava
-- poder de dono.
--
-- Roda a CADA boot, de proposito — ao contrario dos backfills acima. Sao
-- as contas donas da plataforma e a lista continua no codigo como reforco
-- (`is_super_admin` le a coluna E a lista), entao re-semear aqui nao
-- desfaz decisao de ninguem: apenas mantem o dado igual ao codigo. Cobre
-- tambem o caso de uma dessas contas ser criada num tenant DEPOIS deste
-- boot. Conceder super_admin a QUALQUER OUTRO usuario e decisao de
-- runtime, e esta migration nunca encosta nela.
--
-- `AND NOT super_admin` e a guarda contra reescrever a mesma linha em todo
-- start (mesma razao do `AND NOT kiosk` em add_users_kiosk.sql).
-- `lower(btrim(email))` porque a comparacao no codigo tambem e feita em
-- minusculas e sem espaco.
UPDATE users
   SET super_admin = TRUE
 WHERE lower(btrim(email)) IN (
        'super-admin@alavank.com.br',
        'alavank.tecnologia@gmail.com',
        'matheus@alavank.com.br',
        'tiagomiller@alavank.com.br'
       )
   AND NOT super_admin;


-- ---------------------------------------------------------------------
-- 5. SEMENTE DO somente_leitura — UMA VEZ, a partir do papel de hoje.
-- ---------------------------------------------------------------------
-- Traduz a regra que ja vale (`READONLY_ROLES`) para a coluna, para a
-- troca de "papel" por "flag" nao afrouxar nada: quem e somente-leitura
-- hoje continua somente-leitura no primeiro boot depois do deploy.
--
-- UMA VEZ (marca), diferente da semente do super_admin: aqui a decisao
-- passa a ser do administrador do cliente. Se ele DESMARCAR "somente
-- leitura" de um prefeito amanha — que e exatamente a liberdade que este
-- incremento entrega —, o boot seguinte nao pode remarcar.
WITH marca AS (
    INSERT INTO migration_backfills (nome)
    VALUES ('add_role_vira_rotulo:semente_somente_leitura')
    ON CONFLICT (nome) DO NOTHING
    RETURNING nome
)
UPDATE users u
   SET somente_leitura = TRUE
  FROM marca
 WHERE u.role IN ('prefeito', 'viewer')
   AND NOT u.somente_leitura;

-- QUIOSQUE: este SIM a cada boot, e sem marca.
--
-- A conta de quiosque (o link publico de TV, `/t/<slug>` e `/m/<slug>`) e
-- um `viewer` REAL, criada em runtime por `routers/bi.py::_ensure_kiosk_user`
-- toda vez que um gestor publica um link. Ela NAO e cadastro humano: nao
-- ha ninguem para "desmarcar somente leitura" nela, entao reforcar a cada
-- boot nao desfaz decisao de ninguem — so impede que uma conta nascida
-- depois do backfill fique de fora da trava.
--
-- O criterio e o MESMO de add_users_kiosk.sql (dois emissores, mesmo
-- padrao de e-mail), mais a propria marca `kiosk` para quem tiver sido
-- marcado a mao.
--
-- A JANELA ENTRE DOIS BOOTS ja esta fechada em outro lugar, e este comando
-- e a rede por baixo dela: `routers/bi.py::_ensure_kiosk_user` passou a
-- gravar `kiosk` e `somente_leitura` no proprio INSERT, entao o link
-- publicado as 10h nasce travado em vez de esperar o proximo restart (um
-- token de 365 dias que circula em WhatsApp nao pode ficar solto ate la).
--
-- Este UPDATE continua valendo para as contas de quiosque CRIADAS ANTES
-- deste incremento, que nasceram sem as duas colunas — e para qualquer
-- emissor futuro que esqueca de marca-las. E a terceira camada: o guard
-- ainda barra `viewer` pelo PAPEL (`PAPEIS_SEMPRE_SOMENTE_LEITURA`),
-- independentemente do que houver na coluna.
UPDATE users
   SET somente_leitura = TRUE
 WHERE NOT somente_leitura
   AND (kiosk OR email LIKE 'kiosk-%@painel.local');


-- ---------------------------------------------------------------------
-- 6. NORMALIZACAO DO ROTULO: analyst/user -> 'usuario'.
-- ---------------------------------------------------------------------
-- `analyst` e `user` sao BYTE-IDENTICOS no sistema: nenhuma linha de
-- codigo testa nenhum dos dois. Eram dois nomes para a mesma coisa —
-- "usuario comum do cliente" — e dois nomes para a mesma coisa fazem o
-- administrador acreditar que escolher entre eles muda alguma coisa.
-- Agora que o papel e so rotulo, fica UM rotulo.
--
-- `prefeito` e `viewer` NAO sao tocados: continuam existindo como rotulo
-- (e o Painel/quiosque ainda se apoiam neles), so pararam de conceder.
-- `admin` tambem fica: e o rotulo de quem coordena o sistema no cliente.
--
-- UMA VEZ (marca), porque isto e normalizacao de dado historico e nao
-- politica permanente: enquanto os validadores de papel (routers/users.py,
-- routers/auth.py, routers/control.py, services/users_admin.py) e o
-- seletor do frontend ainda oferecerem "analyst", um valor escolhido por
-- gente depois do deploy nao pode ser reescrito no boot seguinte.
WITH marca AS (
    INSERT INTO migration_backfills (nome)
    VALUES ('add_role_vira_rotulo:normaliza_role')
    ON CONFLICT (nome) DO NOTHING
    RETURNING nome
)
UPDATE users u
   SET role = 'usuario'
  FROM marca
 WHERE u.role IN ('analyst', 'user');
