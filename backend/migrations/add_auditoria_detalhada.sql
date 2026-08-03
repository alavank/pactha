-- Auditoria detalhada (Incremento 1) — as colunas que faltavam para a trilha
-- responder, sozinha, o que o dono pediu: quem, quando, de onde, em qual
-- SESSAO, sobre qual MUNICIPIO, com que RESULTADO, e o que exatamente mudou.
--
-- ADITIVA de proposito: nenhuma coluna existente muda de nome ou de tipo, nada
-- e apagado, nenhuma linha antiga e reescrita. As 32 gravacoes que ja existiam
-- continuam validas; nas linhas anteriores a este incremento as colunas novas
-- nascem NULL — e aqui NULL significa "linha anterior ao incremento", nunca
-- "nao aconteceu". Quem for ler a trilha precisa distinguir os dois.
--
-- ⚠️ ESTE ARQUIVO RODA A CADA BOOT. O runner de `services/startup.py` nao tem
-- registro de "migration ja aplicada": ele executa a lista inteira todo start e
-- engole o erro. Por isso TUDO aqui e IF NOT EXISTS e o unico UPDATE tem guarda
-- que o faz convergir. Sem a guarda, cada reinicio reescreveria a trilha — que
-- e exatamente a unica coisa que ela nao pode sofrer.
--
-- ⚠️ O arquivo inteiro roda em UMA transacao (psycopg2). Um statement que falhe
-- derruba os outros junto. Nao acrescente aqui nada que nao seja idempotente.
--
-- IMUTABILIDADE FICA PARA O INCREMENTO 3: nao ha coluna de hash encadeado nem
-- trigger append-only. Nada abaixo atrapalha: as colunas de hash e a trigger
-- entram depois como novo ALTER, sem tocar nestas.

-- --------------------------------------------------------------------------
-- Colunas novas
-- --------------------------------------------------------------------------

-- Recorte por municipio. SEM FOREIGN KEY, de proposito: a trilha nao pode ficar
-- refem da integridade referencial. Com FK, apagar um municipio ou bloquearia o
-- ato (RESTRICT) ou zeraria a coluna (SET NULL) — e um recorte de auditoria que
-- se apaga sozinho quando o alvo some nao serve como prova.
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS municipio_id INTEGER;

-- Sessao de trabalho: agrupa "essa pessoa entrou as 9h12 e ate as 9h40 fez
-- isto, isto e aquilo". Guarda um DERIVADO (hash curto) do identificador do
-- token, nunca o token nem o jti cru — ver services/audit.py::_sessao.
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS sessao_id VARCHAR(64);
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS sessao_inicio TIMESTAMPTZ;

-- sucesso | negado | erro. Tentativa BARRADA e evento de auditoria tao
-- importante quanto acao concluida: sem esta coluna, "tentou e o sistema
-- impediu" e "fez" ficam com a mesma cara na tela.
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS resultado VARCHAR(16);

-- Rota tocada. Guardamos so metodo + caminho, NUNCA a query string: parametro
-- de busca carrega CPF, nome e e-mail digitados pelo usuario, e minimizacao
-- (LGPD art. 6, III) manda nao arrastar para a trilha dado que ela nao precisa.
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS http_metodo VARCHAR(10);
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS http_path VARCHAR(300);

-- Snapshots legiveis, congelados no instante do evento.
--
-- `alvo_nome` existe porque `target_id` isolado nao explica nada a ninguem:
-- "excluiu o usuario 47" nao e auditoria didatica, "excluiu o usuario Maria
-- Souza (id 47)" e. E se a linha 47 for apagada depois, o id vira um numero
-- morto — o nome congelado e o que sobra.
--
-- `usuario_nome` pelo mesmo motivo, do lado do AUTOR: `control.user.delete`
-- zera `audit_log.user_id` ao remover a conta (e o que permite excluir alguem
-- sem quebrar a FK). Sem o nome congelado, sobraria so o e-mail.
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS alvo_nome VARCHAR(300);
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS usuario_nome VARCHAR(200);

-- Valor-antes / valor-depois. Responde "quem deu essa permissao a essa pessoa,
-- e quando" — hoje impossivel. Gravam SO os campos que mudaram (minimizacao) e
-- passam pelo mesmo sanitizador de `details`: senha, token e cookie nunca
-- entram, nem como valor antigo.
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS valor_antes JSONB;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS valor_depois JSONB;

-- --------------------------------------------------------------------------
-- Vocabulario fechado de `resultado`
-- --------------------------------------------------------------------------
-- O Python ja normaliza antes de gravar (services/audit.py::_resultado), entao
-- na pratica esta CHECK nunca dispara — ela esta aqui para o dia em que alguem
-- inserir por fora. NULL e aceito: sao as linhas anteriores ao incremento, e
-- rotula-las de "sucesso" no backfill seria a trilha afirmando o que nao sabe.
--
-- ADD CONSTRAINT nao tem IF NOT EXISTS; o DO block faz o papel. O filtro por
-- `conrelid` importa: `conname` NAO e unico no banco (so por tabela), entao
-- procurar so pelo nome daria "ja existe" por causa de uma constraint homonima
-- em outra tabela e a de audit_log nunca nasceria — em silencio, porque o runner
-- engole o erro. A tabela ja existe aqui (o ALTER acima falharia antes), entao o
-- ::regclass e seguro.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_audit_resultado'
           AND conrelid = 'audit_log'::regclass
    ) THEN
        ALTER TABLE audit_log ADD CONSTRAINT ck_audit_resultado
            CHECK (resultado IS NULL OR resultado IN ('sucesso', 'negado', 'erro'));
    END IF;
END $$;

-- --------------------------------------------------------------------------
-- Indices
-- --------------------------------------------------------------------------
-- created_at DESC porque toda leitura da trilha e "os mais recentes primeiro".
CREATE INDEX IF NOT EXISTS idx_audit_municipio_created
    ON audit_log (municipio_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action_created
    ON audit_log (action, created_at DESC);

-- Parcial: linha sem sessao (job, control-plane, login que falhou antes de
-- haver sessao) nunca e procurada por sessao_id, entao nao precisa ocupar o
-- indice. Atende igual as consultas `WHERE sessao_id = ...`.
CREATE INDEX IF NOT EXISTS idx_audit_sessao
    ON audit_log (sessao_id) WHERE sessao_id IS NOT NULL;

-- --------------------------------------------------------------------------
-- Backfill do nome do autor (converge — nao reescreve a cada boot)
-- --------------------------------------------------------------------------
-- So preenche onde ainda esta vazio E onde existe um usuario para casar. Linha
-- de conta ja excluida (user_id NULL) nao casa no JOIN e permanece intocada:
-- para ela o e-mail ja registrado continua sendo a identificacao.
UPDATE audit_log a
   SET usuario_nome = u.name
  FROM users u
 WHERE u.id = a.user_id
   AND a.usuario_nome IS NULL;

-- --------------------------------------------------------------------------
-- Documentacao no proprio schema (quem abrir o banco direto tambem entende)
-- --------------------------------------------------------------------------
COMMENT ON COLUMN audit_log.municipio_id  IS 'Recorte por municipio. Sem FK: a trilha nao segue o ciclo de vida do alvo.';
COMMENT ON COLUMN audit_log.sessao_id     IS 'Hash curto do identificador da sessao. Agrupa os atos de uma mesma entrada no sistema.';
COMMENT ON COLUMN audit_log.resultado     IS 'sucesso | negado | erro. NULL = linha anterior ao incremento de auditoria detalhada.';
COMMENT ON COLUMN audit_log.http_path     IS 'Caminho da rota, SEM query string (minimizacao LGPD).';
COMMENT ON COLUMN audit_log.alvo_nome     IS 'Nome legivel do alvo, congelado no evento. Sobrevive a exclusao do alvo.';
COMMENT ON COLUMN audit_log.usuario_nome  IS 'Nome do autor, congelado no evento. Sobrevive a exclusao da conta (que zera user_id).';
COMMENT ON COLUMN audit_log.valor_antes   IS 'Somente os campos que mudaram, sanitizados. Nunca segredo.';
COMMENT ON COLUMN audit_log.valor_depois  IS 'Somente os campos que mudaram, sanitizados. Nunca segredo.';
