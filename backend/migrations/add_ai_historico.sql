-- Historico de conversas da IA PACTHA.
--
-- PRIVACIDADE: o historico e ESTRITAMENTE por usuario. Toda leitura filtra por
-- user_id do token; nao existe endpoint que devolva conversa de outra pessoa,
-- nem para admin. O gestor pergunta coisas sobre a gestao dele e isso nao pode
-- vazar para o colega de sala.
--
-- RETENCAO: 30 dias, contados da criacao. Depois disso a conversa e APAGADA
-- (nao anonimizada, nao arquivada). O expurgo roda no boot e tambem de forma
-- preguicosa quando alguem abre o painel de historico, para que a promessa
-- exibida na tela ("apagadas definitivamente apos 30 dias") seja verdadeira
-- mesmo se a API ficar semanas sem reiniciar.
--
-- ON DELETE CASCADE nas mensagens: apagar a conversa tem de levar o conteudo
-- junto, senao o expurgo deixaria as perguntas do usuario orfas no banco.

CREATE TABLE IF NOT EXISTS ai_conversas (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    municipio_id  INTEGER,
    titulo        TEXT NOT NULL DEFAULT 'Nova conversa',
    criado_em     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ai_mensagens (
    id          SERIAL PRIMARY KEY,
    conversa_id INTEGER NOT NULL REFERENCES ai_conversas(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    conteudo    TEXT NOT NULL,
    tool_calls  JSONB,
    criado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Listagem do painel: "minhas conversas, mais recentes primeiro".
CREATE INDEX IF NOT EXISTS ix_ai_conversas_user
    ON ai_conversas (user_id, atualizado_em DESC);

-- Usado pelo expurgo dos 30 dias.
CREATE INDEX IF NOT EXISTS ix_ai_conversas_criado
    ON ai_conversas (criado_em);

CREATE INDEX IF NOT EXISTS ix_ai_mensagens_conversa
    ON ai_mensagens (conversa_id, id);
