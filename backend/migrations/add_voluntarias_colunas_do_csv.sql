-- Voluntarias: as colunas que o dado aberto JA TRAZ e a plataforma nunca leu.
--
-- Levantamento de 31/08/2026, ao mapear a migracao para o ambiente
-- `api-publica`: o coletor baixa `siconv_proposta` (36 colunas) e
-- `siconv_convenio` (40) todos os dias e le cerca de vinte. O resto fica no
-- arquivo, em casa, sem uso — enquanto varias dessas informacoes sao hoje
-- raspadas da tela LOGADA, ou simplesmente nao existem no produto.
--
-- Nao ha endereco novo nem chamada nova aqui: sao colunas de arquivos que o
-- coletor ja puxa. E a mudanca de menor risco de toda a migracao.
--
-- DE ONDE VEM CADA UMA
--   siconv_proposta : NM_BANCO, CD_AGENCIA, CD_CONTA, SITUACAO_CONTA,
--                     SITUACAO_PROJETO_BASICO, ENVIADA_MANDATARIA
--   siconv_convenio : VL_EMPENHADO_CONV, VL_DESEMBOLSADO_CONV, VL_SALDO_CONTA,
--                     DIA_LIMITE_PREST_CONTAS, QTD_TA, QTD_PRORROGA,
--                     DIA_FIM_VIGENC_ORIGINAL_CONV, IND_OPERA_OBTV
--
-- ⚠️ `dt_fim_vigencia_original` merece nota. A briga entre os dois coletores
-- pela coluna `dt_fim_vigencia` (PR #328) existia porque o CSV do convenio traz
-- a vigencia ORIGINAL e a tela traz a ATUAL, e as duas disputavam o mesmo campo.
-- Com esta coluna, as duas passam a caber lado a lado e a ambiguidade acaba na
-- origem, em vez de ser arbitrada por quem rodou por ultimo.
--
-- ⚠️ TODAS ANULAVEIS e sem DEFAULT: NULL aqui significa "ainda nao coletado", e
-- e um estado que o resto do codigo ja sabe tratar. Um DEFAULT 0 em
-- `qtd_termos_aditivos` afirmaria "nao ha aditivo" sobre linha nunca lida.
--
-- ⚠️ Datas como VARCHAR, seguindo o que ja existe na tabela (dt_proposta,
-- dt_fim_vigencia sao `character varying`). Divergir aqui criaria duas
-- convencoes de data na mesma tabela — pior que a convencao imperfeita.
--
-- Puramente ADITIVA e idempotente.

ALTER TABLE transferegov_propostas
    ADD COLUMN IF NOT EXISTS banco                    VARCHAR(120),
    ADD COLUMN IF NOT EXISTS agencia                  VARCHAR(30),
    ADD COLUMN IF NOT EXISTS conta_corrente           VARCHAR(40),
    ADD COLUMN IF NOT EXISTS situacao_conta           VARCHAR(120),
    ADD COLUMN IF NOT EXISTS situacao_projeto_basico  VARCHAR(120),
    ADD COLUMN IF NOT EXISTS enviada_mandataria       VARCHAR(20),
    ADD COLUMN IF NOT EXISTS valor_empenhado          NUMERIC(18,2),
    ADD COLUMN IF NOT EXISTS valor_desembolsado       NUMERIC(18,2),
    ADD COLUMN IF NOT EXISTS saldo_conta              NUMERIC(18,2),
    ADD COLUMN IF NOT EXISTS dt_limite_prest_contas   VARCHAR(20),
    ADD COLUMN IF NOT EXISTS dt_fim_vigencia_original VARCHAR(20),
    ADD COLUMN IF NOT EXISTS qtd_termos_aditivos      INTEGER,
    ADD COLUMN IF NOT EXISTS qtd_prorrogas            INTEGER,
    ADD COLUMN IF NOT EXISTS opera_obtv               VARCHAR(20);

-- A tela de vigencias e o RM filtram por prazo de prestacao de contas; sem
-- indice isso vira varredura da tabela inteira a cada abertura.
CREATE INDEX IF NOT EXISTS ix_tg_propostas_limite_pc
    ON transferegov_propostas (dt_limite_prest_contas)
    WHERE dt_limite_prest_contas IS NOT NULL;
