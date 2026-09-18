-- RADAR DE CAPTACAO: a FICHA do programa (18/09/2026).
--
-- A lista diz QUE o programa existe e ATE QUANDO. A ficha responde as perguntas
-- que vem depois do clique, todas com dado aberto do TransfereGov, sem login:
--   - o municipio ja foi indicado? ja propos?     (apoiadores + propostas)
--   - quantos ja propuseram nesta edicao, no pais e na UF?
--   - como foram as edicoes anteriores?            (mesmo orgao, mesmo nome)
--   - o que outros municipios aprovaram com ele?   (objeto das aprovadas)
--   - quem indica emenda neste programa na UF?
--
-- ⚠️ CONTINUA SEM COLUNA DE VALOR DO PROGRAMA. O que aparece aqui e o repasse
-- das PROPOSTAS (o que cada municipio pediu e teve aprovado), nunca teto nem
-- dotacao — o arquivo nao traz, e o cabecalho de `add_programas_captacao.sql`
-- explica por que inventar seria pior que omitir.
--
-- ⚠️ SO PROPOSTA DE PREFEITURA (natureza "Administracao Publica Municipal").
-- Medido em 18/09/2026: 22.138 das 22.681 propostas dos programas abertos. As
-- outras (estado, OSC, consorcio) nao sao concorrencia nem exemplo para quem le
-- esta tela, e a regra da casa e que soma de voluntarias filtra a prefeitura.
--
-- ⚠️ `ficha_em` NULL = FICHA AINDA NAO MONTADA, e nao "zero propostas". Um
-- programa publicado depois da ultima montagem nao tem linha nas tabelas
-- filhas; sem esta coluna a tela leria o vazio como "ninguem propos".
--
-- ⚠️ CPF NAO ENTRA. `apoiadores_emendas_programas` publica
-- CPF_PF_SOLICITANTE; o coletor nem le a coluna (ver `services/voluntarias_dump.sem_cpf`).
--
-- Idempotente e aditiva. As tabelas sao trocadas inteiras pelo coletor a cada
-- montagem (DELETE + INSERT numa transacao): sao ~64 mil e ~5 mil linhas.

ALTER TABLE programas_captacao ADD COLUMN IF NOT EXISTS edicoes_anteriores JSONB;
ALTER TABLE programas_captacao ADD COLUMN IF NOT EXISTS ficha_em TIMESTAMPTZ;

-- As propostas de prefeitura dos programas ABERTOS e das suas edicoes
-- anteriores. Uma proposta pode estar em mais de um programa (23 casos em
-- 18/09/2026), dai a chave dupla.
CREATE TABLE IF NOT EXISTS programas_captacao_propostas (
    id_programa      VARCHAR(30) NOT NULL,
    id_proposta      VARCHAR(30) NOT NULL,
    ano              INTEGER,
    dt_proposta      DATE,
    uf               VARCHAR(2),
    ibge             VARCHAR(7),
    cnpj             VARCHAR(14),
    proponente       TEXT,
    nr_proposta      VARCHAR(30),
    situacao         TEXT,
    -- aprovada | rejeitada | andamento — derivada de `situacao` na coleta
    -- (`programas_captacao.fase`), para a conta sair igual em toda consulta.
    fase             VARCHAR(12) NOT NULL,
    vl_global        NUMERIC(16,2),
    vl_repasse       NUMERIC(16,2),
    vl_contrapartida NUMERIC(16,2),
    objeto           TEXT,
    PRIMARY KEY (id_programa, id_proposta)
);

CREATE INDEX IF NOT EXISTS idx_prog_capt_prop_ibge
    ON programas_captacao_propostas (ibge);

-- Quem indicou emenda para quem, nos programas abertos. Sem chave natural
-- confiavel no arquivo; a tabela e trocada inteira a cada montagem.
CREATE TABLE IF NOT EXISTS programas_captacao_apoiadores (
    id_programa      VARCHAR(30) NOT NULL,
    nr_emenda        VARCHAR(20),
    parlamentar      TEXT,
    -- Em emenda de comissao ou bancada, o parlamentar que pediu (o
    -- NOME_PARLAMENTAR e "Com. Turismo"; o solicitante e quem bateu a porta).
    solicitante      TEXT,
    indicacao        VARCHAR(40),
    cnpj             VARCHAR(14),
    proponente       TEXT,
    uf               VARCHAR(2),
    valor            NUMERIC(16,2)
);

CREATE INDEX IF NOT EXISTS idx_prog_capt_apoio_prog
    ON programas_captacao_apoiadores (id_programa);
