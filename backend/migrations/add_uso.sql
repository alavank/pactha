-- TELEMETRIA DE USO — separada da trilha de auditoria, de proposito.
--
-- Sao dois sistemas com propositos opostos. A trilha (`audit_log`) e append-only
-- com cadeia de hash, existe para PROVA, e tem ~181 eventos em 30 dias. Isto
-- aqui gera CENTENAS por sessao e existe para ENTENDER O USO. Misturar mataria
-- o sinal da trilha (a linha suspeita se perde no meio de mil cliques) e
-- engordaria a cadeia de hash.
--
-- ⚠️ E nao e so indesejavel: `add_auditoria_imutavel.sql` instala um gatilho que
-- RECUSA UPDATE e DELETE em audit_log. Telemetria la e impossivel — a coluna de
-- tempo ativo precisa ser somada a cada batimento.
--
-- Idempotente por construcao (IF NOT EXISTS em tudo): o runner do PACTHA executa
-- a lista inteira de migrations a CADA BOOT, sem registro de aplicada.

CREATE TABLE IF NOT EXISTS uso_sessao (
  sid           CHAR(32) PRIMARY KEY,
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  -- Nome e e-mail CONGELADOS na linha: a tela de uso precisa continuar legivel
  -- depois que o usuario for excluido, e a exclusao de usuario ja e um caminho
  -- suportado do produto.
  user_email    TEXT NOT NULL,
  usuario_nome  TEXT,
  inicio        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ultimo_sinal  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  -- `fim` so e escrito por evento REAL (logout, despedida da aba). Sessao que
  -- morre sem aviso — aba fechada, notebook sem bateria, rede caindo — fica com
  -- fim NULO e e resolvida na LEITURA, comparando `ultimo_sinal` com agora.
  -- Nao ha varredor: nao existe agendador dentro do processo, e um UPDATE de
  -- fechamento pendurado em requisicao rodaria justamente quando ninguem esta
  -- consultando (as 18h, que e quando as sessoes morrem).
  fim           TIMESTAMPTZ,
  motivo_fim    VARCHAR(16),
  seg_ativos    INTEGER NOT NULL DEFAULT 0,
  seg_ociosos   INTEGER NOT NULL DEFAULT 0,
  tela_atual    VARCHAR(40),
  eventos       INTEGER NOT NULL DEFAULT 0,
  -- Eventos cortados por exceder o teto do lote. A TELA MOSTRA este numero:
  -- telemetria que descarta em silencio ensina o dono a confiar num total
  -- incompleto.
  descartados   INTEGER NOT NULL DEFAULT 0,
  ip            VARCHAR(64),
  user_agent    TEXT
) WITH (fillfactor = 85);

CREATE INDEX IF NOT EXISTS ix_uso_sessao_user   ON uso_sessao (user_id, inicio DESC);
CREATE INDEX IF NOT EXISTS ix_uso_sessao_sinal  ON uso_sessao (ultimo_sinal DESC);

CREATE TABLE IF NOT EXISTS uso_evento (
  id           BIGSERIAL PRIMARY KEY,
  sid          CHAR(32) NOT NULL,
  user_id      INTEGER NOT NULL,
  municipio_id INTEGER,
  -- Ancorado no SERVIDOR: o cliente manda "ha quantos ms" e o servidor calcula.
  -- Relogio de desktop de prefeitura nao e fonte de verdade.
  ocorrido_em  TIMESTAMPTZ NOT NULL,
  -- DUAS colunas de propósito. `tela` e a chave do RBAC, que funde as SETE
  -- rotas transferegov* numa so; `rota` preserva a diferenca entre Voluntarias,
  -- PAC, Rejeitadas e CNPJ — que e exatamente a pergunta "o que acessam mais".
  tela         VARCHAR(40) NOT NULL,
  rota         VARCHAR(80),
  -- Vocabulario FECHADO (ver routers/uso.py::_ACOES). Valor desconhecido vira
  -- 'outro' no servidor, NUNCA erro: recusar quebraria o lote inteiro, e
  -- telemetria nao pode derrubar a acao do usuario.
  acao         VARCHAR(24) NOT NULL,
  alvo         VARCHAR(120),
  ms           INTEGER,
  detalhe      JSONB
);

CREATE INDEX IF NOT EXISTS ix_uso_evento_data ON uso_evento (ocorrido_em DESC);
CREATE INDEX IF NOT EXISTS ix_uso_evento_sess ON uso_evento (sid, ocorrido_em);
CREATE INDEX IF NOT EXISTS ix_uso_evento_user ON uso_evento (user_id, ocorrido_em DESC);

-- Tabela de alta rotatividade com expurgo diario: o autovacuum padrao (20%)
-- deixaria o bloat crescer entre passadas.
ALTER TABLE uso_evento SET (autovacuum_vacuum_scale_factor = 0.02);

-- ⚠️ A chave de permissao `uso.ver` NAO entra aqui: o catalogo do sistema mora
-- inteiro em `add_permissoes_por_acao.sql`, e ha teste que exige que o SQL e o
-- Python sejam espelhos EXATOS. Chave semeada em outro arquivo passaria no boot
-- e quebraria o teste — que e como esta linha foi parar aqui na primeira vez.
