-- AGENDAMENTOS vira COMPROMISSO: hora, solicitante, cor, colunas do kanban e
-- historico de anotacoes.
--
-- O modulo nasceu em 02/09/2026 como "titulo + data + status" e tres desenhos
-- da mesma linha. O dono redesenhou a tela (05/09/2026) e o que mudou nao e
-- enfeite: o compromisso passou a ter HORA (com ou sem periodo), QUEM PEDIU,
-- CONTATO, COR e um historico de anotacoes append-only; e as tres colunas
-- cravadas do kanban viraram tabela, com ate duas colunas customizadas por
-- tenant.
--
-- ⚠️ ADITIVA E SEM DROP. Nenhuma coluna e apagada — `status`, `relato`,
-- `responsavel_id` e `anexos` continuam de pe. O que muda e quem LE cada uma:
--   · `status`  -> `coluna_id` (esta migration copia; o router nao le mais
--                  `status`). A coluna fica porque um DROP em cinco bancos e
--                  irreversivel e o CHECK dela nao atrapalha ninguem: ela tem
--                  DEFAULT, entao INSERT que nao a mencione continua valido.
--   · `relato`  -> vira a PRIMEIRA anotacao do compromisso (o texto continua
--                  legivel na tela, agora dentro do modelo novo).
--   · `anexos`  -> continua sendo servido pela rota de download; o formulario
--                  novo nao anexa, mas o que ja foi anexado nao some.
--
-- ⚠️ `titulo` VIRA `demanda`, e o RENAME e de proposito em vez de "apelidar no
-- Python". Este repo ja pagou caro por vocabulario divergente entre banco e
-- codigo (`municipios.nome` x `users.name`, que so apareceu como
-- ProgrammingError na tela do cliente). Duas palavras para o mesmo campo e a
-- mesma armadilha, so que criada de proposito.
--
-- ⚠️ `municipio_id` CONTINUA NOT NULL, e aqui esta a UNICA divergencia
-- consciente em relacao ao documento de redesenho — que pedia "nulo em
-- prefeitura". Nulo quebraria tres coisas que ja existem e ja sao testadas:
-- o JOIN de `municipios` (INNER, sumiria a linha), o recorte de carteira
-- (`municipio_id = ANY(:mids)` nunca casa com NULL — o compromisso ficaria
-- invisivel para todo usuario de carteira restrita) e a trilha de auditoria,
-- que carimba o municipio do evento. O que o documento quer — "o municipio e
-- implicito na prefeitura" — e sobre a TELA, e e assim que foi entregue: num
-- tenant de um municipio so, nao ha campo nem filtro de municipio em lugar
-- nenhum, e o backend preenche a coluna sozinho com o unico municipio ativo.
--
-- ⚠️ VALORES PARA A LINHA QUE JA EXISTE. `hora_inicio` e `solicitante` sao
-- obrigatorios no formulario novo e as linhas antigas nao tem nem um nem
-- outro. A escolha:
--   · `hora_inicio` recebe DEFAULT '08:00' — inicio do expediente. E a unica
--     resposta possivel: sem hora nao ha onde desenhar o bloco na semana.
--   · `solicitante` recebe DEFAULT '' — e uma informacao que NAO EXISTE, e
--     inventa-la (copiando o responsavel, por exemplo) seria pior: a tela
--     passaria a afirmar que fulano pediu algo que ninguem sabe quem pediu.
--     Vazio a tela mostra "—"; o formulario continua exigindo no que e novo.
--
-- Idempotente: roda a cada boot dos cinco tenants.

-- ---------------------------------------------------------------- colunas ---
-- As colunas do kanban. Eram tres constantes em Python + um CHECK no banco;
-- viram linha para que o tenant possa acrescentar ate duas.
--
-- ⚠️ `chave` EXISTE POR CAUSA DAS TRES FIXAS. `fixa = true` diz que a coluna
-- nao se renomeia nem se apaga, mas nao diz QUAL delas e a de entrada — e o
-- router precisa saber isso em dois lugares: o default de um compromisso novo
-- e o destino dos cartoes de uma coluna customizada removida. Identificar pelo
-- NOME quebraria no dia em que alguem trocasse o acento de "Concluida"; pelo
-- ID quebraria porque SERIAL nao promete o mesmo numero em cinco bancos.
-- `chave` e NULL nas customizadas — e por isso o UNIQUE nao as atrapalha.
CREATE TABLE IF NOT EXISTS agendamentos_colunas (
    id          SERIAL PRIMARY KEY,
    nome        VARCHAR(40) NOT NULL,
    ordem       INTEGER NOT NULL DEFAULT 0,
    fixa        BOOLEAN NOT NULL DEFAULT FALSE,
    chave       VARCHAR(30) UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- As tres fixas, na ordem do quadro. `ON CONFLICT (chave)` torna o seed
-- idempotente sem depender de contagem.
INSERT INTO agendamentos_colunas (nome, ordem, fixa, chave) VALUES
    ('Solicitada',   1, TRUE, 'solicitada'),
    ('Em andamento', 2, TRUE, 'em_andamento'),
    ('Concluída',    3, TRUE, 'concluida')
ON CONFLICT (chave) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_agend_col_ordem ON agendamentos_colunas (ordem);

-- ------------------------------------------------------------ compromisso ---
-- `titulo` -> `demanda`. Guardado dos dois lados: so renomeia se `titulo`
-- existir E `demanda` ainda nao — em banco ja migrado o bloco e no-op.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'agendamentos' AND column_name = 'titulo')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'agendamentos' AND column_name = 'demanda')
    THEN
        ALTER TABLE agendamentos RENAME COLUMN titulo TO demanda;
    END IF;
END $$;

ALTER TABLE agendamentos
    -- 24h, sempre. Ver a nota do cabecalho sobre o DEFAULT.
    ADD COLUMN IF NOT EXISTS hora_inicio       TIME NOT NULL DEFAULT '08:00',
    -- `tem_periodo` e um campo de VERDADE e nao `hora_fim IS NOT NULL`: o
    -- toggle do formulario pode ser desmarcado depois de a hora de termino ja
    -- ter sido digitada, e sem a bandeira o bloco voltaria a esticar sozinho na
    -- semana. Guardar a intencao separa "nao tem termino" de "tinha e tirei".
    ADD COLUMN IF NOT EXISTS tem_periodo       BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS hora_fim          TIME,
    -- Quando a demanda CHEGOU, que nao e quando ela acontece. Anulavel: a
    -- linha antiga nao tem como saber, e hoje-por-padrao vale so no formulario.
    ADD COLUMN IF NOT EXISTS data_solicitacao  DATE,
    ADD COLUMN IF NOT EXISTS solicitante       VARCHAR(120) NOT NULL DEFAULT '',
    -- So digito no banco ((99) 99999-9999 e mascara de tela). Guardar a
    -- pontuacao faria "5199999-9999" e "(51) 99999-9999" virarem dois numeros
    -- diferentes para qualquer busca futura.
    ADD COLUMN IF NOT EXISTS contato_whatsapp  VARCHAR(11),
    -- Hex da paleta de acento (`routers/agendamentos.PALETA`). O DEFAULT e a
    -- PRIMEIRA cor da paleta — a mesma que o formulario ja marca, e o
    -- `test_agendamentos.py` cruza os dois valores para nao divergirem.
    ADD COLUMN IF NOT EXISTS cor               VARCHAR(7) NOT NULL DEFAULT '#12b886',
    ADD COLUMN IF NOT EXISTS coluna_id         INTEGER REFERENCES agendamentos_colunas(id);

-- `status` -> `coluna_id`. So onde ainda nao ha coluna: rodar de novo nao
-- desfaz um cartao que alguem ja arrastou.
UPDATE agendamentos a
   SET coluna_id = c.id
  FROM agendamentos_colunas c
 WHERE a.coluna_id IS NULL
   AND c.chave = CASE a.status
                     WHEN 'em_andamento' THEN 'em_andamento'
                     WHEN 'realizado'    THEN 'concluida'
                     ELSE 'solicitada'
                 END;

-- Rede: qualquer linha que tenha escapado do CASE acima (status fora do CHECK,
-- que o banco nao permite, mas custa uma linha garantir) cai na coluna de
-- entrada. Sem isso o SET NOT NULL abaixo abortaria a migration inteira.
UPDATE agendamentos
   SET coluna_id = (SELECT id FROM agendamentos_colunas WHERE chave = 'solicitada')
 WHERE coluna_id IS NULL;

ALTER TABLE agendamentos ALTER COLUMN coluna_id SET NOT NULL;

-- O kanban le por coluna; o calendario ordena por dia e hora dentro do dia.
CREATE INDEX IF NOT EXISTS idx_agend_coluna    ON agendamentos (coluna_id);
CREATE INDEX IF NOT EXISTS idx_agend_data_hora ON agendamentos (data, hora_inicio);

-- -------------------------------------------------------------- anotacoes ---
-- ⚠️ APPEND-ONLY POR DECISAO DE PRODUTO, e o banco nao tem trigger para isso
-- (diferente do `audit_log`): quem garante e o router, que simplesmente NAO
-- expoe rota de editar nem de apagar. Registrar isto aqui porque a proxima
-- pessoa que abrir esta tabela vai procurar a trava e nao vai achar.
--
-- ON DELETE CASCADE: a anotacao so existe dentro de um compromisso. Apagar o
-- compromisso e deixar as anotacoes orfas produziria historico sem dono, que
-- nao serve a ninguem e nao tem tela.
CREATE TABLE IF NOT EXISTS agendamentos_anotacoes (
    id              SERIAL PRIMARY KEY,
    compromisso_id  INTEGER NOT NULL REFERENCES agendamentos(id) ON DELETE CASCADE,
    -- SET NULL como no resto do modulo: apagar a pessoa nao pode apagar o que
    -- ela escreveu, e "autor desconhecido" e uma informacao honesta.
    autor_id        INTEGER REFERENCES users(id) ON DELETE SET NULL,
    texto           TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agend_anot_compromisso
    ON agendamentos_anotacoes (compromisso_id, created_at);

-- O `relato` antigo vira a primeira anotacao, com o autor e a data de quem
-- registrou o compromisso.
--
-- ⚠️ IDEMPOTENTE PELO `NOT EXISTS`, e ele so e seguro porque anotacao NAO SE
-- APAGA: um compromisso que ja tenha qualquer anotacao e pulado para sempre.
-- Se um dia existir rota de exclusao de anotacao, este bloco passa a poder
-- ressuscitar o relato num boot — e ai ele precisa de uma marca propria.
INSERT INTO agendamentos_anotacoes (compromisso_id, autor_id, texto, created_at)
SELECT a.id, a.criado_por, a.relato, a.created_at
  FROM agendamentos a
 WHERE a.relato IS NOT NULL
   AND btrim(a.relato) <> ''
   AND NOT EXISTS (SELECT 1 FROM agendamentos_anotacoes n
                    WHERE n.compromisso_id = a.id);
