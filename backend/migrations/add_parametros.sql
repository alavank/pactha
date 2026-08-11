-- PARAMETROS DO AMBIENTE — as listas que o cliente cadastra e o sistema usa.
--
-- Pedido do dono (11/08/2026): "o administrador do cliente pode criar
-- parametros... um tipo que vai dar pra cadastrar pra usar no sistema e o
-- Perfil (Rotulo) de usuario, ele cadastra la e o sistema puxa no modulo de
-- cadastro". Primeiro tipo: `perfil_usuario`. A tabela nasce generica porque o
-- segundo tipo vem (e criar tabela por tipo seria uma migration por lista).
--
-- ⚠️ ISOLAMENTO POR CLIENTE E DE GRACA, e por isso NAO ha `tenant_id`: o PACTHA
-- e single-tenant — cada cliente tem o proprio banco, o proprio container e a
-- propria imagem. "Um nao compartilha os parametros do outro" (o dono) ja e o
-- comportamento natural da tabela. Uma coluna de tenant aqui seria uma promessa
-- falsa de multi-tenancy que o resto do sistema nao cumpre.
--
-- ⚠️ ESTE ARQUIVO RODA A CADA BOOT (o runner de `services/startup.py` nao tem
-- registro de "ja aplicada"), entao tudo aqui e IF NOT EXISTS / ON CONFLICT.
CREATE TABLE IF NOT EXISTS parametros (
    id          SERIAL PRIMARY KEY,
    -- O TIPO da lista ('perfil_usuario' hoje). Texto e nao enum: tipo novo nao
    -- pode exigir ALTER TYPE numa base em producao.
    tipo        TEXT NOT NULL,
    -- A CHAVE que o sistema grava (ex.: `users.role` recebe este valor). Nunca
    -- muda depois de criada — renomear a chave orfanaria os cadastros que a
    -- usam; quem muda e o rotulo.
    valor       TEXT NOT NULL,
    -- O que a TELA mostra. E o unico campo que o cliente edita a vontade.
    rotulo      TEXT NOT NULL,
    -- Ordem de exibicao (menor primeiro; empate desempata por rotulo).
    ordem       INTEGER NOT NULL DEFAULT 100,
    -- Desativar em vez de excluir: um rotulo aposentado nao pode sumir da lista
    -- enquanto houver gente cadastrada com ele — a tela mostraria a chave crua.
    ativo       BOOLEAN NOT NULL DEFAULT TRUE,
    -- ⭐ RESERVADO DO SISTEMA: o cliente ve, usa e reordena, mas NAO renomeia
    -- nem apaga. Hoje so `admin` — o rotulo que abre a tela de Usuarios e o
    -- Cofre (routers/users.py::_require_admin, routers/cofre.py). Deixar o
    -- cliente apagar esse rotulo e deixa-lo se trancar fora do proprio sistema.
    reservado   BOOLEAN NOT NULL DEFAULT FALSE,
    criado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    criado_por  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    UNIQUE (tipo, valor)
);

CREATE INDEX IF NOT EXISTS idx_parametros_tipo_ativo
    ON parametros (tipo, ativo, ordem);

-- SEMENTE: os tres rotulos que a tela de Usuarios ja oferecia em codigo
-- (frontend .../usuarios/page.tsx::ROLES), agora como dado editavel. Sem esta
-- semente o seletor nasceria VAZIO num tenant que ja tem gente cadastrada.
--
-- ON CONFLICT DO NOTHING e nao UPDATE: se o cliente renomeou "Usuario" para
-- "Analista de Convenios", o proximo boot NAO pode desfazer a escolha dele.
INSERT INTO parametros (tipo, valor, rotulo, ordem, reservado) VALUES
    ('perfil_usuario', 'admin',    'Administrador', 10, TRUE),
    ('perfil_usuario', 'usuario',  'Usuário',       20, FALSE),
    ('perfil_usuario', 'prefeito', 'Prefeito',      30, FALSE)
ON CONFLICT (tipo, valor) DO NOTHING;

-- Os dois rotulos LEGADOS que o sistema ainda aceita mas nao oferece:
-- `analyst` (o canal do Console ainda cria com ele) e `viewer` (contas
-- sinteticas de quiosque). Entram INATIVOS: nao aparecem no seletor de
-- cadastro, mas existem para a tela saber traduzir a chave de uma conta antiga
-- em vez de mostrar "analyst" cru — que e exatamente o defeito que a lista
-- hardcoded ja teve uma vez.
INSERT INTO parametros (tipo, valor, rotulo, ordem, ativo, reservado) VALUES
    ('perfil_usuario', 'analyst', 'Analista',      40, FALSE, TRUE),
    ('perfil_usuario', 'viewer',  'Visualizador',  50, FALSE, TRUE)
ON CONFLICT (tipo, valor) DO NOTHING;
