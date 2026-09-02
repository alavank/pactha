-- RADAR DE CAPTACAO: os programas federais com prazo ABERTO para o municipio
-- apresentar proposta.
--
-- A plataforma acompanha o que o municipio JA tem (convenio assinado, emenda
-- indicada, obra em medicao). Isto e o antes: a porta que ainda esta aberta.
--
-- ⚠️ O NOME DA TABELA NAO PODE SER `oportunidades` NEM `programas_federais`.
-- As duas existiram e foram derrubadas no refactor lean de 05/2026 — e o
-- `drop_lean_tables.sql` continua na lista de migrations, rodando A CADA BOOT.
-- Reusar qualquer um dos dois nomes faria a tabela ser DROPADA em todo deploy,
-- recriada vazia logo em seguida, e o defeito so apareceria como "o radar
-- esvaziou sozinho de novo" — sem erro em lugar nenhum.
--
-- ⚠️ UMA LINHA POR PROGRAMA, E NAO POR (PROGRAMA x UF). O arquivo aberto do
-- TransfereGov repete o programa uma vez por UF habilitada: medido em
-- 02/09/2026, 307 linhas para apenas 17 programas. Guardar as UFs num array e
-- filtrar com `= ANY(ufs)` deixa a tabela legivel e a consulta exata.
--
-- ⚠️ `ufs` E QUEM PODE PROPOR, e o recorte e real — nao e enfeite. Dos 17
-- programas abertos hoje, 8 valem para o Brasil inteiro e 9 sao restritos:
-- "INFRA-ESTRUTURA BASICA SR(RS)" so aceita municipio gaucho. Um prefeito
-- mineiro que o visse na tela abriria um processo para uma porta que nao abre.
-- Medido: MG ve 9 programas, RS ve 10.
--
-- ⚠️ `naturezas` GUARDA MUNICIPIO E CONSORCIO, mas a tela mostra so o que a
-- PREFEITURA pode propor. Hoje os 12 programas de consorcio sao subconjunto
-- exato dos 17 municipais, entao a distincao nao muda nada na pratica — guardar
-- as duas custa uma coluna e evita ter que recoletar no dia em que mudar.
--
-- ⚠️ `ausente_desde` EM VEZ DE DELETE, como no `sismob_obras`. Programa que sai
-- do ar some das telas mas fica no banco: o gestor que perguntar "cade aquele
-- programa que eu vi semana passada?" tem resposta. E o coletor so marca
-- ausencia se a rodada trouxe dado — rodada vazia marcando tudo como ausente
-- limparia o radar por causa de um timeout.
--
-- ⚠️ SEM COLUNA DE VALOR, de proposito: o arquivo do TransfereGov nao traz
-- teto nem dotacao do programa. Uma coluna `valor` aqui so poderia ficar NULL
-- para sempre, e coluna sempre nula na tela de captacao lê como "programa sem
-- dinheiro".
--
-- Idempotente e aditiva.

CREATE TABLE IF NOT EXISTS programas_captacao (
    id_programa      VARCHAR(30) PRIMARY KEY,   -- ID_PROGRAMA do dado aberto
    cod_programa     VARCHAR(40),
    nome             TEXT NOT NULL,
    orgao            VARCHAR(200),
    cod_orgao        VARCHAR(20),
    modalidade       VARCHAR(60),               -- CONVENIO, CONTRATO DE REPASSE, ...
    naturezas        TEXT[]  NOT NULL DEFAULT '{}',
    ufs              TEXT[]  NOT NULL DEFAULT '{}',
    acao_orcamentaria VARCHAR(40),
    subtipo          VARCHAR(200),
    -- A janela de proposta. `fim` e o que decide se o programa aparece.
    dt_ini_receb     DATE,
    dt_fim_receb     DATE,
    -- A janela de EMENDA PARLAMENTAR, que fecha em data propria e costuma ser
    -- mais curta. E o unico prazo desta tela que o prefeito nao cumpre sozinho:
    -- depende de um gabinete indicar. Por isso vem separado, e nao somado ao
    -- prazo de proposta.
    dt_ini_emenda    DATE,
    dt_fim_emenda    DATE,
    dt_disponibilizacao DATE,
    ano_disponibilizacao INTEGER,
    raw_data         JSONB,
    visto_em         TIMESTAMPTZ DEFAULT NOW(),
    ausente_desde    TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

-- A consulta da tela: "o que esta aberto para a minha UF, do prazo mais curto
-- para o mais longo".
CREATE INDEX IF NOT EXISTS idx_prog_capt_abertos
    ON programas_captacao (dt_fim_receb)
    WHERE ausente_desde IS NULL;

CREATE INDEX IF NOT EXISTS idx_prog_capt_ufs
    ON programas_captacao USING GIN (ufs);
