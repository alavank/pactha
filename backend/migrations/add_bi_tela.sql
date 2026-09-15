-- Modo Tela do BI: filtro POR USUARIO + links publicos curtos e revogaveis.
--
-- POR QUE POR USUARIO: cada gestor filtra o que precisa. O secretario de Saude
-- olha a saude no periodo dele; o de Obras, outro. Um nao pode mexer no que o
-- outro ve. Entao o filtro do Modo Tela e do link publico e do DONO do link --
-- nao do tenant.
--
-- POR QUE O SLUG: antes o JWT de 365 dias ia inteiro na URL (uns 300 chars,
-- impossivel de ditar por telefone) e nao dava para revogar sem desativar o
-- usuario de quiosque, que era COMPARTILHADO entre todos. Agora a URL leva so
-- um codigo curto; o token fica no banco e cada link morre sozinho.

-- Filtro corrente de cada usuario (o que a TV dele deve mostrar).
CREATE TABLE IF NOT EXISTS bi_tela_filtros (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    scope      TEXT NOT NULL DEFAULT '__all__',  -- '__all__' | '<municipio_id>'
    anos       TEXT NOT NULL DEFAULT '',         -- CSV '2025,2026' (vazio = todos)
    aba        TEXT,                             -- aba corrente (opcional)
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Links publicos de TV. Um por "tela publicada"; o dono revoga quando quiser.
CREATE TABLE IF NOT EXISTS bi_tela_links (
    slug          TEXT PRIMARY KEY,
    owner_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kiosk_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    municipio_id  INTEGER,                       -- NULL = segue o escopo do dono
    token         TEXT NOT NULL,                 -- JWT de quiosque (fora da URL)
    nome          TEXT,                          -- rotulo livre ("TV do gabinete")
    criado_em     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expira_em     TIMESTAMPTZ,
    revogado      BOOLEAN NOT NULL DEFAULT FALSE,
    ultimo_acesso TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_bi_tela_links_owner ON bi_tela_links(owner_id);

-- Preserva o acesso de quem JA usava: o Modo Tela vinha junto com a tela 'bi',
-- entao quem tem 'bi' ganha 'bi_tela'. Sem isto o botao sumiria para todo mundo
-- no deploy, inclusive para o prefeito, ate um admin sair concedendo na mao.
--
-- 'bi_link' NAO e concedido em massa de proposito: publicar dado para fora da
-- prefeitura era exclusivo de admin e continua sendo uma decisao explicita.
-- (Admin nao aparece aqui porque passa por todas as telas por definicao.)
--
-- ATENCAO ao NOT EXISTS: este arquivo roda de novo sempre que for editado (o
-- runner compara o checksum em `migrations_aplicadas`; ate 15/09/2026 rodava
-- TODOS os arquivos a cada boot). Sem esta
-- guarda, o backfill rodaria de novo nessa hora e devolveria a permissao a
-- quem o admin tivesse revogado. Com ela, so roda enquanto ninguem tiver
-- 'bi_tela'. (Se um dia revogarem de TODO mundo, o proximo boot reconcede uma
-- vez -- caso raro e preferivel a permissao voltando sozinha toda semana.)
INSERT INTO user_telas (user_id, tela)
SELECT user_id, 'bi_tela' FROM user_telas
WHERE tela = 'bi'
  AND NOT EXISTS (SELECT 1 FROM user_telas WHERE tela = 'bi_tela')
ON CONFLICT DO NOTHING;
