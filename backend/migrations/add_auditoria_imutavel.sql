-- ============================================================================
-- Auditoria IMUTAVEL (Incremento 3) — o BANCO passa a recusar a alteracao.
-- ============================================================================
--
-- Ate aqui a trilha era imutavel por AUSENCIA: nenhuma tela, nenhuma rota e
-- nenhuma funcao da aplicacao oferecia editar ou apagar um evento. Isso protege
-- contra o acidente, nao contra a intencao — quem chegasse ao banco (psql, um
-- endpoint novo escrito sem saber da regra, um script de manutencao) reescrevia
-- a linha sem encontrar obstaculo nenhum. Este arquivo poe o obstaculo no unico
-- lugar em que ele vale para TODOS os caminhos: dentro do proprio Postgres.
--
-- SAO TRES CAMADAS, e elas fazem coisas diferentes:
--
--   1. APPEND-ONLY   gatilho que levanta excecao em UPDATE, DELETE e TRUNCATE.
--                    IMPEDE. Vale para qualquer conexao, inclusive o psql.
--
--   2. CADEIA DE HASH  cada linha guarda sha256(hash da linha anterior || o
--                    conteudo desta linha), calculado DENTRO do banco. Nao
--                    impede nada: DENUNCIA. Alterar uma linha antiga quebra o
--                    elo dela e o de todas as seguintes, e a conferencia diz
--                    exatamente onde.
--
--   3. PAPEL DE BANCO  o usuario da aplicacao sem permissao de UPDATE/DELETE na
--                    tabela. E a unica das tres que segura o dono do banco. NAO
--                    esta ligada aqui — trocar o DATABASE_URL de um cliente vivo
--                    e mudanca de infra, e a decisao e do dono. O SQL pronto e o
--                    passo a passo estao no fim deste arquivo.
--
-- ⚠️ HONESTIDADE SOBRE O ALCANCE: quem tem a senha de DONO do banco pode
-- derrubar o gatilho (`DROP TRIGGER`) e reescrever o que quiser. Nenhuma linha
-- deste arquivo muda isso, e prometer o contrario na tela seria mentira. O que
-- este arquivo entrega e: (a) nenhum caminho da aplicacao consegue alterar; e
-- (b) se alguem alterar por fora, a cadeia de hash NAO FECHA e a conferencia
-- aponta a primeira linha divergente. Prova de deteccao, nao de impedimento.
-- Impedir de verdade exige a camada 3 + backup fora do alcance de quem opera.
--
-- ⚠️ E UM LIMITE ESPECIFICO DA CADEIA, que a tela nao pode esconder: hash
-- encadeado detecta alteracao NO MEIO (a linha seguinte deixa de fechar) e
-- remocao NO MEIO (o elo da sobrevivente aponta para um hash que ninguem tem).
-- Nao detecta CORTE NA PONTA: apagar as ultimas N linhas deixa uma cadeia
-- perfeitamente valida, so mais curta — nao ha "linha seguinte" para acusar a
-- falta. E propriedade de qualquer cadeia de hash, nao defeito desta.
-- O que fecha esse flanco e ANCORAR o ultimo hash fora do banco de tempos em
-- tempos (a exportacao da trilha ja leva o hash junto; guardada por fora, ela
-- vira testemunha: se a cadeia de hoje nao contem mais aquele hash, a ponta foi
-- cortada). Ancoragem automatica nao esta feita — nao afirme, em tela nenhuma,
-- que a ponta esta protegida.
--
-- ----------------------------------------------------------------------------
-- ⚠️ ESTE ARQUIVO RODA A CADA BOOT, INTEIRO, NUMA UNICA TRANSACAO.
-- ----------------------------------------------------------------------------
-- O runner de `services/startup.py` nao tem registro de "migration ja aplicada":
-- executa a lista toda em todo start e ENGOLE o erro (so loga). Entao aqui
-- TUDO e `IF NOT EXISTS` / `CREATE OR REPLACE`, e rodar duas vezes tem de ser
-- inofensivo. O selo da cadeia (no fim) converge: a partir do segundo boot ele
-- nem chega a executar UPDATE nenhum.
--
-- POSICAO NA LISTA: este arquivo e o ULTIMO de MIGRATION_FILES, e isso e
-- requisito, nao arrumacao. As migrations anteriores ainda fazem backfill
-- (`add_auditoria_detalhada.sql` reescreve `usuario_nome`); se o gatilho
-- append-only entrasse antes delas, o proprio boot bateria na trava.
--
-- ----------------------------------------------------------------------------
-- CUSTO HONESTO: a cadeia SERIALIZA as insercoes.
-- ----------------------------------------------------------------------------
-- Para encadear, cada INSERT precisa ler o hash da ultima linha — e duas
-- transacoes que lessem o mesmo "ultimo" produziriam uma bifurcacao silenciosa
-- na cadeia. Por isso o gatilho pega um advisory lock por transacao: as
-- insercoes de auditoria passam a acontecer UMA DE CADA VEZ.
--
--   Ordem de grandeza: um INSERT com o lock custa fracao de milissegundo, entao
--   o teto pratico fica na casa de milhares de eventos por segundo. Este sistema
--   grava CENTENAS POR DIA. A serializacao e irrelevante aqui, e a afirmacao tem
--   de vir com o numero para nao virar fe.
--
--   O QUE VIGIAR: o lock e por TRANSACAO, entao ele so e devolvido no commit. Uma
--   transacao que registre auditoria cedo (`commit=False`) e depois fique muito
--   tempo aberta segura a fila de auditoria inteira. Registrar perto do commit
--   continua sendo a pratica certa.
--
--   SE UM DIA CRESCER (dezenas de milhares/dia, ou lock aparecendo em
--   pg_stat_activity): quebrar em UMA CADEIA POR DIA — o elo passa a ser
--   "ultima linha DAQUELE DIA", o lock vira por dia e insercoes de dias
--   diferentes deixam de se esperar. Custo: a conferencia passa a validar N
--   cadeias curtas em vez de uma longa, e a raiz de cada dia precisa ser
--   ancorada (ex.: guardar o hash final do dia anterior no proprio primeiro
--   evento do dia). Nao faca isso antes de precisar: cadeia unica e mais simples
--   de conferir e de explicar a um auditor.

-- ----------------------------------------------------------------------------
-- 1. A FOREIGN KEY `audit_log.user_id -> users(id)` SAI
-- ----------------------------------------------------------------------------
-- Ela e incompativel com append-only, e o conflito e concreto: para excluir um
-- usuario, `routers/control.py` fazia `UPDATE audit_log SET user_id = NULL` —
-- justamente para nao esbarrar nesta FK. Com o gatilho, esse UPDATE passaria a
-- estourar e QUEBRARIA A EXCLUSAO DE USUARIO.
--
-- Derrubar a FK e o certo, e nao um contorno: a trilha guarda `user_id`,
-- `user_email` e `usuario_nome` como SNAPSHOT do instante do ato. Ela nao segue
-- o ciclo de vida de quem registrou — pelo mesmo motivo que `municipio_id` ja
-- nasceu sem FK (ver add_auditoria_detalhada.sql). Um recorte de auditoria que
-- se apaga sozinho quando o alvo some nao serve como prova.
--
-- Sem a FK, `user_id` vira o que sempre deveria ter sido: um numero congelado.
-- Ele pode apontar para uma conta que nao existe mais — e isso e correto, nao e
-- inconsistencia. Quem lê a trilha usa o e-mail e o nome congelados.
--
-- Busca a constraint pelo QUE ELA FAZ (FK sobre a coluna user_id) e nao pelo
-- nome: em banco existente ela nasceu do `REFERENCES` de add_audit_and_user_cols
-- .sql, em banco novo do `create_all` do SQLAlchemy, e nada garante que os dois
-- caminhos escolham o mesmo nome. Loop porque, em tese, pode haver mais de uma.
--
-- Em banco NOVO, `add_audit_and_user_cols.sql` (que ainda tem o REFERENCES)
-- roda ANTES deste arquivo no mesmo boot — entao a FK chega a existir por alguns
-- milissegundos e sai aqui. Por isso o DROP mora nesta migration e nao la: e o
-- ultimo a rodar, e so ele pode garantir o estado final.
DO $$
DECLARE
    r record;
BEGIN
    IF to_regclass('public.audit_log') IS NULL THEN
        RETURN;   -- banco sem a tabela ainda: nada a fazer (nem a errar)
    END IF;
    FOR r IN
        SELECT con.conname
          FROM pg_constraint con
          JOIN pg_attribute att
            ON att.attrelid = con.conrelid
           AND att.attnum = ANY (con.conkey)
         WHERE con.conrelid = 'public.audit_log'::regclass
           AND con.contype  = 'f'
           AND att.attname  = 'user_id'
    LOOP
        -- `IF EXISTS` nao e redundancia com o SELECT acima: entre ler o catalogo e
        -- conseguir o ACCESS EXCLUSIVE do ALTER cabe OUTRO boot. A API sobe com
        -- `uvicorn --workers 2` (Dockerfile.api/Procfile) e os dois processos
        -- chamam `run_migrations()`; se os dois chegarem aqui, um espera o outro
        -- commitar e depois encontra a FK ja removida. Sem o `IF EXISTS` isso e
        -- ERRO ("constraint does not exist"), e como o arquivo inteiro roda em UMA
        -- transacao, o perdedor da corrida aborta a migration TODA e o runner
        -- registra "Migration add_auditoria_imutavel.sql falhou" num boot que
        -- deu certo. O banco ficaria correto (o vencedor commitou), mas o log
        -- passaria a acusar falha em boot saudavel — e log de migration que grita
        -- erro no dia a dia e log que ninguem le mais.
        --
        -- O lock de boot deveria evitar essa corrida e agora evita (ver
        -- services/startup.py::_tomar_lock_migrations, que ate hoje soltava o lock
        -- antes da primeira migration rodar). Este `IF EXISTS` fica como segunda
        -- linha: ele custa uma palavra e vale tambem quando o lock nao pode ser
        -- tomado, caso em que o runner segue sem ele de proposito.
        EXECUTE format('ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS %I', r.conname);
        RAISE NOTICE 'audit_log: FK % removida (trilha e snapshot, nao referencia viva)', r.conname;
    END LOOP;
END $$;

-- ----------------------------------------------------------------------------
-- 2. AS COLUNAS DA CADEIA
-- ----------------------------------------------------------------------------
-- CHAR(64) porque e sha256 em hexadecimal: 64 caracteres, sempre. Tipo de
-- tamanho fixo deixa obvio, para quem abre o banco, que ali nao cabe outra
-- coisa.
--
-- `hash_anterior` NULO significa "elo raiz": ou e a primeira linha da tabela, ou
-- e a primeira linha depois de uma poda autorizada. As duas situacoes sao
-- legitimas e a conferencia sabe distinguir (ver secao 6).
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS hash_anterior CHAR(64);
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS hash          CHAR(64);

-- ----------------------------------------------------------------------------
-- 3. AS PECAS DE CALCULO (fonte unica da verdade)
-- ----------------------------------------------------------------------------
-- Sao TRES, e quem confere a integridade (GET /api/auditoria/integridade) chama
-- `audit_log_selo(a.*)` — a de cima, que ja compoe as outras duas. Nunca
-- reimplemente o calculo em Python: duas implementacoes do mesmo hash divergem
-- no dia em que uma das duas mudar, e o sintoma seria "a trilha inteira esta
-- corrompida" — o alarme mais caro que este sistema pode dar em falso.
--
--   audit_log_conteudo(linha)          -> texto canonico que entra no hash
--   audit_log_hash(anterior, conteudo) -> sha256 hex do elo
--   audit_log_selo(linha)              -> o hash que a linha deveria ter
--
-- O gatilho tambem chama `audit_log_selo`: ele descobre o elo, escreve em
-- `NEW.hash_anterior` e so entao sela. Gravar e conferir passam, literalmente,
-- pela mesma funcao — nao ha uma "versao do gatilho" e uma "versao da
-- conferencia" que possam divergir.

-- Chave do advisory lock que serializa a cadeia. Existe como funcao, e nao como
-- numero repetido em tres lugares, porque dois lugares com o mesmo numero
-- escrito a mao viram, um dia, dois numeros diferentes — e ai a serializacao
-- deixa de existir em silencio.
CREATE OR REPLACE FUNCTION audit_log_chave_lock() RETURNS bigint
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT 918273645::bigint
$$;

-- Serializacao CANONICA da linha: o texto que entra no hash.
--
-- Tres cuidados que nao sao obvios:
--
-- (a) `quote_nullable` em cada campo. Sem delimitar, os valores "AB" + "C" e
--     "A" + "BC" produziriam o mesmo texto concatenado e, portanto, o mesmo
--     hash — daria para trocar o conteudo de dois campos vizinhos sem quebrar a
--     cadeia. Com aspas e escape, cada campo tem fronteira propria. Bonus:
--     `quote_nullable` devolve a string 'NULL' para nulo, entao NUNCA retorna
--     NULL — o que importa porque `concat_ws` IGNORA argumento nulo e um campo
--     ignorado deslocaria todos os outros.
--
-- (b) O timestamp NAO entra como `::text`. A representacao textual de
--     timestamptz depende de `TimeZone` e `DateStyle` da SESSAO: a mesma linha
--     hasheada por uma conexao em America/Sao_Paulo e por outra em UTC daria
--     hashes diferentes, e a trilha pareceria adulterada por causa de uma
--     variavel de ambiente. `to_char(... AT TIME ZONE 'UTC', <formato so
--     numerico>)` e determinista: o formato nao tem nome de mes nem de dia, que
--     sao as unicas partes sensiveis a locale.
--
-- (c) A LISTA DE COLUNAS E FIXA e comeca com 'v1'. Nao use `to_jsonb(a)` nem
--     `a::text`: os dois passariam a incluir sozinhos qualquer coluna nova, e
--     no boot seguinte TODA a trilha antiga apareceria como divergente — a
--     cadeia diria "adulteraram tudo" por causa de um ALTER TABLE. Se um dia
--     uma coluna nova precisar ser coberta, isso e uma versao 'v2' do conteudo,
--     valendo dos ids novos em diante, com a conferencia sabendo qual versao
--     aplicar a cada faixa. Reescrever hashes antigos NAO e opcao: seria a
--     aplicacao reassinando o passado, que e o oposto do que se esta provando.
CREATE OR REPLACE FUNCTION audit_log_conteudo(a audit_log) RETURNS text
LANGUAGE sql STABLE PARALLEL SAFE
SET search_path = pg_catalog, public AS $$
    SELECT concat_ws('|',
        'v1',
        a.id::text,
        quote_nullable(a.user_id),
        quote_nullable(a.user_email),
        quote_nullable(a.usuario_nome),
        quote_nullable(a.action),
        quote_nullable(a.target_type),
        quote_nullable(a.target_id),
        quote_nullable(a.alvo_nome),
        quote_nullable(a.resultado),
        quote_nullable(a.municipio_id),
        quote_nullable(a.ip),
        quote_nullable(a.user_agent),
        quote_nullable(a.http_metodo),
        quote_nullable(a.http_path),
        quote_nullable(a.sessao_id),
        coalesce(to_char(a.sessao_inicio AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US'), 'NULL'),
        quote_nullable(a.details::text),
        quote_nullable(a.valor_antes::text),
        quote_nullable(a.valor_depois::text),
        coalesce(to_char(a.created_at   AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US'), 'NULL')
    )
$$;

-- sha256(hash anterior || conteudo). `sha256(bytea)` e nativo no Postgres 11+ —
-- nao precisa de pgcrypto, que e extensao e poderia nao existir no servidor do
-- cliente. `convert_to(..., 'UTF8')` fixa a codificacao: hashear texto sem
-- fixar o encoding faria o resultado depender do banco.
CREATE OR REPLACE FUNCTION audit_log_hash(p_anterior text, p_conteudo text)
RETURNS CHAR(64)
LANGUAGE sql IMMUTABLE PARALLEL SAFE
SET search_path = pg_catalog, public AS $$
    SELECT encode(
        sha256(convert_to(coalesce(p_anterior, '') || '|' || coalesce(p_conteudo, ''), 'UTF8')),
        'hex')::char(64)
$$;

-- O SELO DE UMA LINHA, em UMA chamada: `audit_log_selo(a.*)` devolve o hash que
-- aquela linha deveria ter, a partir do elo que ela mesma declara em
-- `hash_anterior`. E a composicao das duas funcoes acima — nao ha calculo novo
-- aqui, de proposito: se houvesse, existiriam duas definicoes do mesmo selo e
-- elas divergiriam no primeiro dia em que alguem mexesse numa so.
--
-- Existe separada porque a conferencia precisa exatamente disto: "recalcule ESTA
-- linha inteira e me diga o selo". Com ela, o SELECT do lote e
--
--   SELECT a.id, a.hash_anterior, a.hash, audit_log_selo(a.*) AS recalculado
--     FROM audit_log a WHERE a.id > :cursor ORDER BY a.id LIMIT :lote;
--
-- e o recalculo acontece DENTRO do banco, na mesma fonte que o gatilho usa para
-- gravar. Reimplementar o sha256 em Python seria manter duas versoes da mesma
-- regra e chamar a divergencia entre elas de "trilha adulterada" — o alarme
-- falso mais caro que este sistema pode dar.
--
-- ⚠️ DUAS CONFERENCIAS DIFERENTES, e elas se completam:
--   `audit_log_selo(a.*) = a.hash`      a linha nao foi alterada;
--   `a.hash_anterior = hash da anterior` nenhuma linha foi removida no meio.
-- A primeira sozinha nao ve remocao; a segunda sozinha nao ve edicao.
CREATE OR REPLACE FUNCTION audit_log_selo(a audit_log) RETURNS CHAR(64)
LANGUAGE sql STABLE PARALLEL SAFE
SET search_path = pg_catalog, public AS $$
    SELECT audit_log_hash(a.hash_anterior, audit_log_conteudo(a))
$$;

-- ----------------------------------------------------------------------------
-- 4. O GATILHO QUE ENCADEIA (BEFORE INSERT)
-- ----------------------------------------------------------------------------
-- O hash e calculado AQUI, no banco, e sobrescreve o que a aplicacao tiver
-- mandado nas duas colunas. E o ponto do incremento: se o valor viesse da
-- aplicacao, bastaria um cliente mentiroso para gravar um hash que "fecha" com
-- um conteudo forjado. Do jeito que esta, nem a aplicacao consegue mentir.
--
-- `NEW.id` ja existe aqui: o Postgres aplica os DEFAULT das colunas (o nextval
-- do SERIAL) ANTES de rodar os gatilhos BEFORE ROW. O mesmo vale para
-- `created_at` (DEFAULT NOW()), que e o instante de INICIO DA TRANSACAO — nao o
-- do INSERT. A diferenca so importa para quem for comparar horarios de duas
-- transacoes longas; o hash cobre o valor gravado, seja ele qual for.
CREATE OR REPLACE FUNCTION audit_log_encadear() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public AS $$
DECLARE
    v_anterior CHAR(64);
    v_ultimo   bigint;
    v_seq      text;
BEGIN
    -- Serializa a cadeia. Sem isto, duas transacoes concorrentes leem o MESMO
    -- "ultimo hash" e as duas se declaram filhas dele: a cadeia bifurca e a
    -- conferencia acusa adulteracao onde houve so concorrencia. O lock e por
    -- transacao (liberado no commit/rollback, sem precisar de unlock).
    --
    -- O lock resolve a leitura porque esta funcao e VOLATILE: em READ COMMITTED,
    -- cada comando DENTRO de uma funcao volatil pega um snapshot NOVO. Entao o
    -- SELECT abaixo, executado depois da espera, ja enxerga a linha que a
    -- transacao anterior commitou. Se esta funcao fosse STABLE ela usaria o
    -- snapshot da query chamadora e o lock nao adiantaria nada — o `LANGUAGE
    -- plpgsql` sem volatilidade declarada (VOLATILE por padrao) e requisito.
    PERFORM pg_advisory_xact_lock(audit_log_chave_lock());

    SELECT a.id, a.hash INTO v_ultimo, v_anterior
      FROM audit_log a
     ORDER BY a.id DESC
     LIMIT 1;

    -- ⚠️ A CORRIDA QUE O LOCK SOZINHO NAO PEGA — e que produziria alarme falso
    -- PERMANENTE. O `id` desta linha saiu da sequencia ANTES do gatilho rodar
    -- (o Postgres aplica os DEFAULT primeiro). Entre tirar o numero e conseguir
    -- o lock acima cabe outra transacao: ela pode ter tirado um numero MAIOR e
    -- gravado primeiro. Resultado: esta linha entra na cadeia apontando para um
    -- elo cujo id e MAIOR que o dela.
    --
    -- A cadeia continuaria matematicamente correta, mas a conferencia percorre a
    -- trilha em ordem de ID (e nao ha outra ordem possivel de percorrer) — e
    -- leria a inversao como "apagaram um registro do meio". Divergencia que
    -- ninguem causou, impossivel de consertar depois (consertar exigiria UPDATE,
    -- que o proximo gatilho recusa), num painel cuja unica serventia e ser
    -- acreditado.
    --
    -- A janela e de microssegundos e este sistema grava centenas de eventos por
    -- DIA, entao isto quase nunca aconteceria — "quase nunca" nao serve para
    -- prova. Tirar um numero NOVO aqui dentro, ja com o lock na mao, faz a ordem
    -- dos ids ser SEMPRE a mesma ordem da cadeia. O numero descartado vira um
    -- buraco na sequencia, o que e inofensivo: sequencia nunca foi contagem, e a
    -- trilha ja tem buracos de id por qualquer transacao que deu rollback.
    IF v_ultimo IS NOT NULL AND NEW.id <= v_ultimo THEN
        v_seq := pg_get_serial_sequence('audit_log', 'id');
        IF v_seq IS NOT NULL THEN
            -- `nextval` devolve valor maior que qualquer um ja devolvido, e
            -- v_ultimo veio de uma linha COMMITADA (logo, de um valor ja
            -- devolvido) — entao o novo id e maior que v_ultimo. Nenhuma outra
            -- insercao pode ter commitado no meio: o lock esta nesta transacao.
            NEW.id := nextval(v_seq);
        END IF;
        -- Sem sequencia (coluna preenchida a mao, cenario que nao existe aqui)
        -- nao ha o que renumerar: grava assim mesmo, porque recusar a linha
        -- seria perder o evento — e perder evento e pior que ter de explicar
        -- uma inversao de ordem na conferencia.
    END IF;

    -- Preenche o elo PRIMEIRO e so entao sela: assim o gatilho chama
    -- `audit_log_selo` — a MESMA funcao que a conferencia usa para recalcular.
    -- Nao e economia de linha: e a garantia de que gravar e conferir sao a mesma
    -- conta. Se fossem duas expressoes parecidas, bastaria uma delas mudar para
    -- a trilha inteira passar a parecer adulterada.
    NEW.hash_anterior := v_anterior;                     -- NULL = elo raiz
    NEW.hash := audit_log_selo(NEW);
    RETURN NEW;
END;
$$;

-- ----------------------------------------------------------------------------
-- 5. O GATILHO QUE RECUSA (BEFORE UPDATE OR DELETE / BEFORE TRUNCATE)
-- ----------------------------------------------------------------------------
-- Duas portas se abrem, e as duas sao estreitas de proposito:
--
--   DELETE  so dentro de `audit_log_podar()` (secao 6), que registra a propria
--           poda na trilha antes de terminar.
--   UPDATE  so o SELO da cadeia (secao 7) e so em linha AINDA NAO SELADA, e
--           ainda assim sem poder tocar em nenhum outro campo.
--
-- As duas portas exigem uma variavel de sessao marcada com o ID DA TRANSACAO
-- ATUAL. Comparar com a transacao — em vez de aceitar qualquer valor — evita
-- que uma marca esquecida continue valendo depois: ela vale so enquanto durar a
-- transacao que a colocou, e as funcoes ainda a limpam ao terminar.
--
-- ⚠️ Isso e uma trava CONTRA ACIDENTE E CONTRA CAMINHO NAO PREVISTO, nao contra
-- um adversario com poder de dono no banco: qualquer sessao pode dar `SET` numa
-- variavel de sessao. Quem fecha essa porta e a camada 3 (papel sem UPDATE/
-- DELETE), porque ali a negativa vem da PERMISSAO e nao do gatilho. O que a
-- variavel garante hoje: nenhum UPDATE/DELETE acontece POR DESCUIDO, e todo
-- caminho autorizado passa por funcao que deixa rastro.
CREATE OR REPLACE FUNCTION audit_log_imutavel() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF current_setting('pactha.audit_poda', true) = txid_current()::text THEN
            RETURN OLD;   -- poda autorizada e registrada (audit_log_podar)
        END IF;
        RAISE EXCEPTION
            'audit_log e append-only: evento ja gravado nao pode ser excluido'
            USING HINT = 'Poda por retencao: SELECT audit_log_podar(<data de corte>, '
                       || '<quem esta podando>, <motivo>[, <prefixos de acao>]); '
                       || 'ela registra a propria poda na trilha.';
    END IF;

    -- --- UPDATE: unica forma aceita e o selo da cadeia ---
    -- `to_jsonb(NEW) - 'hash' - 'hash_anterior' = to_jsonb(OLD) - ...` compara
    -- TODAS as demais colunas de uma vez, inclusive as que ainda nao existem:
    -- uma coluna nova entra na comparacao sozinha, sem ninguem lembrar de vir
    -- aqui. Listar coluna por coluna seria uma lista que envelhece — e envelhecer
    -- aqui significa abrir um buraco calado por onde uma coluna nova poderia ser
    -- reescrita.
    IF current_setting('pactha.audit_selo', true) = txid_current()::text
       AND OLD.hash IS NULL
       AND (to_jsonb(NEW) - 'hash' - 'hash_anterior')
         = (to_jsonb(OLD) - 'hash' - 'hash_anterior')
    THEN
        -- Recalcula em vez de aceitar o que veio: nem o selo pode escolher o
        -- valor do hash. `id < OLD.id` porque o selo caminha em ordem crescente
        -- e o elo anterior ja esta selado.
        SELECT a.hash INTO NEW.hash_anterior
          FROM audit_log a
         WHERE a.id < OLD.id
         ORDER BY a.id DESC
         LIMIT 1;
        NEW.hash := audit_log_selo(NEW);   -- mesma conta do INSERT e da conferencia
        RETURN NEW;
    END IF;

    RAISE EXCEPTION
        'audit_log e append-only: evento ja gravado nao pode ser alterado'
        USING HINT = 'A trilha e prova. Corrigir um registro errado se faz '
                   || 'gravando um evento NOVO que explique a correcao.';
END;
$$;

-- TRUNCATE nao dispara gatilho de linha: apagaria a tabela inteira sem que
-- nenhum FOR EACH ROW fosse chamado. Precisa de um gatilho proprio, por
-- statement — e este nao tem porta nenhuma: nao existe motivo legitimo para
-- truncar uma trilha de auditoria. Retencao se faz por `audit_log_podar`.
CREATE OR REPLACE FUNCTION audit_log_imutavel_truncate() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public AS $$
BEGIN
    RAISE EXCEPTION
        'audit_log e append-only: TRUNCATE apagaria a trilha inteira'
        USING HINT = 'Retencao se faz por SELECT audit_log_podar(...), que apaga '
                   || 'so a faixa pedida e registra a poda na propria trilha.';
END;
$$;

-- CREATE OR REPLACE TRIGGER (Postgres 14+) em vez de DROP + CREATE: nao existe
-- instante nenhum, nem dentro desta transacao, em que a tabela fique sem
-- protecao.
CREATE OR REPLACE TRIGGER trg_audit_log_encadear
    BEFORE INSERT ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_encadear();

CREATE OR REPLACE TRIGGER trg_audit_log_imutavel
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_imutavel();

CREATE OR REPLACE TRIGGER trg_audit_log_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_imutavel_truncate();

-- ⚠️ ENABLE ALWAYS — SEM ISTO O GATILHO TEM UM INTERRUPTOR DE UMA LINHA.
-- Gatilho nasce em modo "origin": ele NAO dispara quando a sessao esta com
-- `session_replication_role = replica`. Isso existe para replicacao, mas e um
-- comando de sessao como outro qualquer:
--
--   SET session_replication_role = replica;
--   UPDATE audit_log SET action = 'login.success' WHERE id = 42;   -- passaria
--
-- Nao deixa marca no schema (nada de DROP TRIGGER para alguem notar depois), nao
-- precisa de janela e desfaz-se sozinho ao fechar a conexao. Com ALWAYS o
-- gatilho dispara em qualquer papel de replicacao e esse atalho deixa de
-- existir. A cadeia de selos denunciaria a alteracao de qualquer forma — mas
-- denunciar depois e o segundo melhor resultado; recusar na hora e o primeiro.
--
-- SO NOS DOIS QUE RECUSAM, e a assimetria e deliberada: o gatilho de INSERT fica
-- em "origin" de proposito, para que uma RESTAURACAO de backup
-- (`pg_restore --disable-triggers`, que e exatamente isto por baixo) recoloque a
-- trilha com os selos ORIGINAIS dela, em vez de reassinar tudo na entrada. Um
-- backup restaurado tem de continuar conferindo contra o passado, e nao contra
-- o momento em que foi restaurado. Recusar UPDATE/DELETE nunca atrapalha um
-- restore, porque restore so insere.
--
-- Idempotente: e um estado do gatilho, nao um objeto novo. Vem DEPOIS do
-- `CREATE OR REPLACE TRIGGER` porque o replace devolve o gatilho ao modo padrao.
ALTER TABLE audit_log ENABLE ALWAYS TRIGGER trg_audit_log_imutavel;
ALTER TABLE audit_log ENABLE ALWAYS TRIGGER trg_audit_log_truncate;

-- ----------------------------------------------------------------------------
-- 6. O CAMINHO CONTROLADO DE PODA
-- ----------------------------------------------------------------------------
-- A politica de retencao e do DONO e esta declarada em routers/auditoria.py
-- (`retencao`): 5 anos para acesso, seguranca e permissoes; 12 meses para
-- navegacao. O PADRAO DE FABRICA E NAO APAGAR NADA — nao ha job, nao ha cron,
-- nao ha expurgo automatico. Podar e um ato consciente, disparado a mao.
--
-- PODAR AUDITORIA SEM RASTRO E APAGAR RASTRO. Por isso a funcao:
--   - exige QUEM esta podando (sem autor, nao roda);
--   - recusa data de corte no futuro (que seria "apague tudo" disfarcado);
--   - NUNCA apaga os proprios registros de poda (o livro-caixa da poda fica);
--   - grava na trilha, na MESMA transacao, quantas linhas sairam, ate que data,
--     com que filtro, por quem e por que. Se essa gravacao falhar, o DELETE cai
--     junto — nao ha poda silenciosa.
--
-- O QUE A PODA FAZ COM A CADEIA (e por que isso nao e um buraco): apagar linhas
-- deixa um vao. A linha seguinte continua apontando, em `hash_anterior`, para o
-- hash da ultima linha apagada — e esse hash fica registrado em
-- `details.hash_ultimo_podado` do evento de poda. Entao a conferencia consegue
-- dizer "aqui houve um vao, e ele casa com a poda registrada no evento X",
-- que e diferente de "aqui alguem apagou linhas sem avisar". O hash de cada
-- linha sobrevivente continua conferindo sozinho, porque ele nao depende das
-- linhas apagadas — so do proprio conteudo e do elo guardado.
--
-- E o inverso e o que da valor a tudo isto: um vao SEM evento de poda que o
-- explique e a assinatura de uma remocao por fora. Nao ha como apagar linha do
-- meio da trilha e deixar a cadeia fechada — teria de recalcular o hash de todas
-- as linhas seguintes, e para isso teria de conseguir dar UPDATE nelas.
--
-- EXEMPLOS DE USO (a mao, no psql, por quem for autorizado):
--   -- navegacao com mais de 12 meses:
--   SELECT audit_log_podar(now() - interval '12 months', 'fulano@prefeitura.gov.br',
--                          'retencao 12 meses (navegacao)', ARRAY['nav.','navegacao.']);
--   -- tudo com mais de 5 anos:
--   SELECT audit_log_podar(now() - interval '5 years', 'fulano@prefeitura.gov.br',
--                          'retencao 5 anos');
CREATE OR REPLACE FUNCTION audit_log_podar(
    p_ate      timestamptz,
    p_autor    text,
    p_motivo   text   DEFAULT NULL,
    p_prefixos text[] DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE
    v_linhas   bigint;
    v_min      bigint;
    v_max      bigint;
    v_hash     CHAR(64);
    v_contigua boolean;
    v_res      jsonb;
BEGIN
    IF p_ate IS NULL OR p_ate > now() THEN
        RAISE EXCEPTION 'audit_log_podar: a data de corte tem de estar no passado (recebido: %)', p_ate
            USING HINT = 'Corte no futuro apagaria a trilha inteira.';
    END IF;
    IF coalesce(btrim(p_autor), '') = '' THEN
        RAISE EXCEPTION 'audit_log_podar: informe QUEM esta podando (p_autor)'
            USING HINT = 'Poda sem autor identificado nao e retencao, e apagamento de rastro.';
    END IF;

    -- Mesma fila da insercao: a poda mexe na cadeia e nao pode correr em
    -- paralelo com quem esta encadeando.
    PERFORM pg_advisory_xact_lock(audit_log_chave_lock());

    -- Abre a porta do gatilho SO para esta transacao (o `true` do set_config e
    -- o "local": morre no fim da transacao, como um SET LOCAL).
    PERFORM set_config('pactha.audit_poda', txid_current()::text, true);

    WITH podadas AS (
        DELETE FROM audit_log a
         WHERE a.created_at < p_ate
           -- o livro-caixa da poda nunca e podado
           AND a.action IS DISTINCT FROM 'auditoria.poda'
           AND (
                p_prefixos IS NULL
                OR EXISTS (SELECT 1 FROM unnest(p_prefixos) px
                            WHERE starts_with(a.action, px))
               )
        RETURNING a.id, a.hash
    )
    SELECT count(*)::bigint,
           min(p.id),
           max(p.id),
           -- hash da ULTIMA linha apagada: e o elo que a proxima linha
           -- sobrevivente aponta. Guardado aqui, o vao fica explicavel.
           (array_agg(p.hash ORDER BY p.id DESC))[1]
      INTO v_linhas, v_min, v_max, v_hash
      FROM podadas p;

    -- Fecha a porta antes de sair: sem isto, a marca continuaria valida pelo
    -- resto da transacao do chamador e um DELETE solto depois desta chamada
    -- passaria pelo gatilho.
    PERFORM set_config('pactha.audit_poda', '', true);

    -- ⚠️ A PODA E CONTIGUA OU ESBURACADA? A conferencia PRECISA saber, e so aqui
    -- da para responder.
    --
    -- Poda sem filtro apaga uma faixa inteira e deixa UM vao: a primeira linha
    -- sobrevivente aponta para o selo da ultima linha removida, que e o
    -- `hash_ultimo_podado` acima. Prova exata, um selo para um vao.
    --
    -- Poda COM `p_prefixos` (o caso do dono: navegacao com 12 meses, o resto com
    -- 5 anos) apaga linhas SALPICADAS no meio das que ficam. Cada trecho removido
    -- vira um vao proprio, e cada vao aponta para um selo DIFERENTE — nenhum
    -- deles e o `hash_ultimo_podado`, que so guarda o ultimo. Guardar os selos de
    -- todos os vaos seria guardar dezenas de milhares de hashes num `details`, e
    -- provaria pouco: `hash_anterior` ja entra no selo da propria linha
    -- sobrevivente, entao ele nao pode ser forjado sem quebrar o selo dela.
    --
    -- Entao o que se registra e a FAIXA (menor/maior id removido) mais este
    -- sinalizador. Com ele a conferencia pode ser ESTRITA quando a poda diz
    -- "removi tudo entre X e Y" (um unico vao, casado pelo selo) e aceitar vaos
    -- por faixa apenas quando a poda ADMITE ter deixado buracos. Sem o
    -- sinalizador, ou a conferencia aceita vao por faixa sempre (e afrouxa o
    -- caso estrito de graca) ou nunca (e a primeira poda de retencao por
    -- prefixo deixa a tela em alarme vermelho para sempre).
    IF v_linhas > 0 THEN
        v_contigua := NOT EXISTS (
            SELECT 1 FROM audit_log a WHERE a.id > v_min AND a.id < v_max
        );
    END IF;

    v_res := jsonb_build_object(
        'linhas_removidas',   v_linhas,
        'ate',                to_char(p_ate AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US'),
        'menor_id_removido',  v_min,
        'maior_id_removido',  v_max,
        'hash_ultimo_podado', v_hash,
        'faixa_contigua',     v_contigua,
        'prefixos',           to_jsonb(p_prefixos),
        'motivo',             p_motivo,
        'origem',             'funcao audit_log_podar, executada direto no banco'
    );

    -- Registra a poda na propria trilha, na MESMA transacao do DELETE. Nao ha
    -- Request aqui (isto roda no banco), entao ip/user_agent/http_* ficam NULL —
    -- e `origem` diz de onde veio, em vez de deixar a linha parecendo um ato de
    -- tela. Este INSERT passa pelo gatilho de encadeamento como qualquer outro.
    INSERT INTO audit_log
        (user_email, usuario_nome, action, target_type, alvo_nome, resultado, details, created_at)
    VALUES
        (CASE WHEN position('@' in p_autor) > 0 THEN left(btrim(p_autor), 255) END,
         left(btrim(p_autor), 200),
         'auditoria.poda', 'audit_log', 'a trilha de auditoria', 'sucesso',
         v_res, now());

    RETURN v_res;
END;
$$;

-- Ninguem executa a poda por acaso. Hoje ha UM usuario de banco (dono), entao
-- este REVOKE nao muda nada na pratica — ele existe para que, quando a camada 3
-- for ligada, `pactha_app` NAO herde a poda de PUBLIC sem que alguem decida.
REVOKE ALL ON FUNCTION audit_log_podar(timestamptz, text, text, text[]) FROM PUBLIC;

-- ----------------------------------------------------------------------------
-- 7. SELO DAS LINHAS QUE JA EXISTIAM (backfill convergente)
-- ----------------------------------------------------------------------------
-- A trilha do cliente vivo ja tem eventos gravados antes deste incremento: eles
-- nascem com `hash` NULO e precisam entrar na cadeia, em ordem de id, para que
-- a conferencia possa comecar do inicio.
--
-- CONVERGE DE VERDADE, e nao "por sorte": a primeira coisa que a funcao faz e
-- perguntar se existe alguma linha sem hash. A partir do segundo boot a resposta
-- e nao e ela retorna sem executar UPDATE nenhum — nao e um UPDATE de zero
-- linhas, e nenhum UPDATE. E o selo NUNCA recalcula hash de linha ja selada (o
-- gatilho exige `OLD.hash IS NULL`), entao mesmo que alguem a chame de novo ela
-- nao tem como reassinar o passado.
--
-- CUSTO, sem maquiagem: uma linha por UPDATE, em ordem, tudo dentro da transacao
-- da migration. Dezenas de milhares de linhas = alguns segundos; centenas de
-- milhares = dezenas de segundos. Acontece UMA VEZ, no boot em que este arquivo
-- estreia, e nesse boot a tabela fica travada para escrita (a transacao ja segura
-- lock forte desde o DROP da FK). Nao ha versao "em lotes por boot": selar so
-- metade deixaria as linhas do meio sem hash, e o proximo INSERT encadearia a
-- partir de um NULL — nasceria uma raiz falsa no meio da trilha, que e
-- exatamente o que a conferencia acusaria como adulteracao.
-- Indice PARCIAL que, em regime normal, fica VAZIO — e e exatamente para isso
-- que ele serve. Todo boot pergunta "sobrou alguma linha sem selo?"; sem indice
-- essa pergunta varre a tabela inteira justamente no caso em que a resposta e
-- "nenhuma" (nao ha o que encontrar, entao nao ha onde parar antes do fim). Com
-- ele, a resposta sai imediata e o custo de manutencao e nulo: linha selada nao
-- entra no indice.
CREATE INDEX IF NOT EXISTS ix_audit_log_sem_selo
    ON audit_log (id) WHERE hash IS NULL;

CREATE OR REPLACE FUNCTION audit_log_selar() RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE
    r record;
    n bigint := 0;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM audit_log WHERE hash IS NULL) THEN
        RETURN 0;   -- ja selada: o caso de todo boot depois do primeiro
    END IF;

    PERFORM pg_advisory_xact_lock(audit_log_chave_lock());
    PERFORM set_config('pactha.audit_selo', txid_current()::text, true);

    -- ORDER BY id: cada elo precisa do anterior JA selado. Fora de ordem, a
    -- cadeia nasceria com buracos que a conferencia leria como adulteracao.
    -- `SET hash = NULL` e de proposito um nao-valor: quem calcula os dois campos
    -- e o gatilho, aqui so se pede o recalculo.
    FOR r IN SELECT id FROM audit_log WHERE hash IS NULL ORDER BY id
    LOOP
        UPDATE audit_log SET hash = NULL WHERE id = r.id;
        n := n + 1;
    END LOOP;

    PERFORM set_config('pactha.audit_selo', '', true);
    RETURN n;
END;
$$;

REVOKE ALL ON FUNCTION audit_log_selar() FROM PUBLIC;

DO $$
DECLARE
    n bigint;
BEGIN
    n := audit_log_selar();
    IF n > 0 THEN
        RAISE NOTICE 'audit_log: % linhas antigas entraram na cadeia de hash', n;
    END IF;
END $$;

-- ----------------------------------------------------------------------------
-- 8. Documentacao no proprio schema
-- ----------------------------------------------------------------------------
COMMENT ON COLUMN audit_log.hash IS
    'sha256(hash_anterior || conteudo canonico da linha), calculado pelo gatilho no banco. Nem a aplicacao escolhe este valor.';
COMMENT ON COLUMN audit_log.hash_anterior IS
    'Hash da linha imediatamente anterior. NULL = elo raiz (primeira linha, ou primeira apos poda autorizada).';
COMMENT ON FUNCTION audit_log_conteudo(audit_log) IS
    'Serializacao canonica v1 da linha. Fonte UNICA do que entra no hash - quem confere integridade chama esta funcao, nunca reimplementa.';
COMMENT ON FUNCTION audit_log_hash(text, text) IS
    'sha256 hex do elo anterior + conteudo. Use junto de audit_log_conteudo para refazer a cadeia.';
COMMENT ON FUNCTION audit_log_selo(audit_log) IS
    'Selo que a linha deveria ter, recalculado do proprio hash_anterior dela. E o que a conferencia de integridade chama: audit_log_selo(a.*) = a.hash.';
COMMENT ON FUNCTION audit_log_podar(timestamptz, text, text, text[]) IS
    'Unico caminho de DELETE em audit_log. Exige autor, recusa corte no futuro, preserva os registros de poda e grava a propria poda na trilha.';
COMMENT ON FUNCTION audit_log_selar() IS
    'Entra na cadeia as linhas ainda sem hash, em ordem de id. Convergente: nao recalcula hash ja existente.';

-- ============================================================================
-- CAMADA 3 — SEPARACAO DE PAPEL NO BANCO (DECISAO DO DONO, NAO EXECUTADA AQUI)
-- ============================================================================
-- Hoje existe UM usuario de banco (`pactha`), dono de tudo: das tabelas, dos
-- gatilhos e das funcoes. Para ele, os gatilhos deste arquivo sao um obstaculo
-- que ele mesmo pode remover. A trava que segura ate o dono da APLICACAO e
-- separar o papel: a aplicacao passa a conectar com um usuario que simplesmente
-- NAO TEM permissao de UPDATE nem DELETE em audit_log. Ai a negativa vem do
-- sistema de permissoes, antes do gatilho, e derrubar o gatilho nao adianta —
-- porque para derruba-lo tambem falta permissao.
--
-- ⚠️ NAO E PARA FAZER SOZINHO: isto troca o DATABASE_URL de um cliente vivo. Se
-- faltar um GRANT, a aplicacao sobe sem conseguir ler o proprio banco. Rode com
-- o dono avisado e com janela para voltar atras.
--
-- SQL pronto (rodar como o dono `pactha`, uma vez):
--
--   CREATE ROLE pactha_app LOGIN PASSWORD '<senha forte, gerada na hora>';
--   GRANT CONNECT ON DATABASE <banco> TO pactha_app;
--   GRANT USAGE ON SCHEMA public TO pactha_app;
--   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA public TO pactha_app;
--   GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA public TO pactha_app;
--   ALTER DEFAULT PRIVILEGES FOR ROLE pactha IN SCHEMA public
--       GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pactha_app;
--   ALTER DEFAULT PRIVILEGES FOR ROLE pactha IN SCHEMA public
--       GRANT USAGE, SELECT ON SEQUENCES TO pactha_app;
--
--   -- o ponto de tudo: a trilha e SO-INSERT para a aplicacao
--   REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM pactha_app;
--   GRANT  SELECT, INSERT             ON audit_log TO pactha_app;
--   GRANT  USAGE, SELECT ON SEQUENCE audit_log_id_seq TO pactha_app;
--
--   -- conferir integridade e leitura: pode. Podar: nao.
--   GRANT EXECUTE ON FUNCTION audit_log_conteudo(audit_log) TO pactha_app;
--   GRANT EXECUTE ON FUNCTION audit_log_hash(text, text)    TO pactha_app;
--   -- audit_log_podar e audit_log_selar continuam SEM grant para pactha_app:
--   -- sao SECURITY DEFINER (rodam como o dono), entao dar EXECUTE a aplicacao
--   -- devolveria por dentro exatamente o poder que o REVOKE acima tirou.
--
-- PASSO A PASSO:
--   1. criar o papel e os grants acima (o dono continua existindo, intocado);
--   2. testar com o novo usuario ANTES de trocar nada:
--        psql "postgresql://pactha_app:...@host/banco" \
--          -c "INSERT INTO audit_log (action) VALUES ('teste.permissao');" \
--          -c "UPDATE audit_log SET action='x' WHERE id=1;"   -- tem de dar ERRO de permissao
--   3. so entao trocar DATABASE_URL / DATABASE_URL_SYNC no Coolify e redeployar;
--   4. ⚠️ as MIGRATIONS de boot continuam precisando do DONO (elas fazem DDL).
--      Ou o boot roda com uma URL separada de dono (variavel propria), ou as
--      migrations passam a ser um passo manual. Decidir ISTO antes do passo 3 —
--      e a parte que trava o deploy se for descoberta depois.
--   5. guardar a senha do dono no cofre, fora do alcance de quem opera o dia a
--      dia. Sem esse ultimo passo, a camada 3 protege menos do que parece.
