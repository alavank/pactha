-- MCP TOKENS: a credencial que dá a um assistente de IA (Claude, ChatGPT) o
-- MESMO alcance de leitura que o dono do token já tem na plataforma.
--
-- ⚠️ O TOKEN É UM USUÁRIO, NÃO UMA CREDENCIAL SOLTA. Ele NÃO guarda escopo
-- próprio de propósito: o escopo (quais municípios enxerga) é lido do DONO em
-- tempo de verificação, via `services/auth.py::load_user_scopes`. Guardar um
-- escopo aqui criaria uma segunda fonte de permissão que divergiria da conta na
-- primeira vez que alguém trocasse a pessoa de carteira — o mesmo erro que o
-- `services/service_token.py` comete (scopes próprios) e que este modelo existe
-- para NÃO repetir. Ver `services/mcp_auth.py`.
--
-- ⚠️ DONO INATIVO OU APAGADO = TOKEN MORTO, na hora. `ON DELETE CASCADE` cobre o
-- apagar; o inativar é coberto na verificação (recusa `users.active = false`).
-- Desabilitar alguém na tela de Usuários não pode deixar o acesso de IA vivo —
-- é a pior porta esquecida.
--
-- ⚠️ SÓ LEITURA. O servidor MCP que consome este token não escreve, não apaga e
-- não dispara coleta — o contrato inteiro é leitura. Não há aqui, nem no router,
-- caminho que mude dado.
--
-- Aditiva e idempotente.

CREATE TABLE IF NOT EXISTS mcp_tokens (
    id            SERIAL PRIMARY KEY,
    -- O DONO. FK, e não INT solto: um `user_id` órfão seria um token que herda o
    -- escopo de ninguém — a verificação já falha fechado nesse caso, mas a FK
    -- torna o estado impossível em vez de improvável.
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- Nome humano, p/ a pessoa saber qual revogar depois ("Claude do gabinete").
    name          VARCHAR(100) NOT NULL,
    -- Primeiros chars do token em claro — só p/ identificar na tela e no log.
    -- NÃO é segredo (é curto de propósito) e nunca serve para autenticar.
    token_prefix  VARCHAR(16),
    -- SHA-256 hex (64 chars) do token raw. O valor em claro sai UMA vez, na
    -- criação, e nunca é guardado: é isso que faz dele segredo. Sem coluna que
    -- possa devolvê-lo.
    token_hash    VARCHAR(64) NOT NULL,
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    -- Última vez que o token autenticou uma chamada. NULL = "nunca usado" — e um
    -- token criado e nunca plugado é justamente o que se revoga.
    last_used_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Revogar NÃO apaga a linha: a linha é o registro de que o acesso existiu.
    -- Revogado = active=false E revoked_at preenchido.
    revoked_at    TIMESTAMPTZ
);

-- A verificação busca por hash em TODA chamada de ferramenta — é o caminho
-- quente. UNIQUE porque dois registros com o mesmo hash só aconteceriam por
-- colisão de 256 bits (impossível na prática); barrar é mais barato que tratar.
-- Seguro num único deploy: a tabela nasce vazia neste mesmo arquivo.
CREATE UNIQUE INDEX IF NOT EXISTS idx_mcp_tokens_hash ON mcp_tokens (token_hash);

-- A tela lista "os tokens desta pessoa", mais recentes primeiro.
CREATE INDEX IF NOT EXISTS idx_mcp_tokens_user ON mcp_tokens (user_id, created_at DESC);
