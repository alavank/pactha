-- Texto de fonte externa vira TEXT — três defeitos que só a carga REAL revelou.
--
-- ⚠️ O QUE ACONTECEU, em 06/09/2026, na primeira rodada completa de Nova Palma:
--
--     ERROR: value too long for type character varying(20)
--
-- A rodada inteira da fase 2 abortou. O campo era `emendas_federais_cgu.autor`,
-- declarado `VARCHAR(20)` porque eu supus que "autor" fosse um CÓDIGO curto (o
-- `3298` de Heitor Schuch). Não é: em emenda de colegiado a CGU manda o NOME do
-- colegiado no mesmo campo — **"COM. DESENV REGIONAL E TURISMO", 30 caracteres**.
--
-- ⚠️ E `tipo_emenda` estava a DOIS caracteres do teto: `VARCHAR(60)` para um
-- valor real de 58 ("Emenda Individual - Transferências com Finalidade
-- Definida"). Um rótulo novo do Governo derrubaria a carga do mesmo jeito.
--
-- É a mesma lição que `add_obrasgov_taxonomias_text.sql` já tinha registrado —
-- Santa Maria abortou uma carga inteira por UM caractere ("Projeto de
-- Investimento em Infraestrutura" = 41, coluna = 40). A regra que sai daqui:
--
--   ⭐ TEXTO QUE VEM DE FONTE EXTERNA NÃO TEM LARGURA. VARCHAR(n) só protege
--   contra o que NÓS escrevemos; contra o que o Governo escreve, ele só troca
--   um dado inesperado por uma coleta abortada. E no Postgres TEXT e VARCHAR(n)
--   custam o mesmo.
--
-- Ficam com largura só os campos cujo formato NÓS controlamos e cuja violação é
-- defeito nosso: `codigo_emenda` (12 dígitos que o coletor constrói),
-- `beneficiario_cnpj` (14) e as colunas do dump que são numéricas por contrato.
--
-- ⚠️ Idempotente por natureza: `ALTER ... TYPE TEXT` sobre coluna que já é TEXT
-- é no-op no Postgres. Não precisa de guarda, e roda a cada boot sem custo.

-- --- o que a CGU escreve -----------------------------------------------------
ALTER TABLE emendas_federais_cgu ALTER COLUMN autor TYPE TEXT;
ALTER TABLE emendas_federais_cgu ALTER COLUMN nome_autor TYPE TEXT;
ALTER TABLE emendas_federais_cgu ALTER COLUMN tipo_emenda TYPE TEXT;
ALTER TABLE emendas_federais_cgu ALTER COLUMN numero_emenda TYPE TEXT;

-- `codigoDocumento` medido em 23 caracteres ("540007000012015NE800448"); a
-- coluna tinha 60 e não estourou, mas é texto de fonte externa como os demais.
ALTER TABLE emendas_federais_documentos ALTER COLUMN codigo_documento TYPE TEXT;
ALTER TABLE emendas_federais_documentos
    ALTER COLUMN codigo_documento_resumido TYPE TEXT;

-- --- o que o dump do TransfereGov escreve ------------------------------------
-- `TIPO_PARLAMENTAR` hoje cabe folgado (o maior é "RELATOR GERAL", 13), mas é
-- vocabulário de fonte externa: o dia em que o Governo criar uma categoria, ela
-- não pode abortar a carteira — que é a fase que funciona SEM chave nenhuma.
ALTER TABLE emendas_federais_carteira ALTER COLUMN tipo_parlamentar TYPE TEXT;
ALTER TABLE emendas_federais_carteira ALTER COLUMN parlamentar TYPE TEXT;
ALTER TABLE emendas_federais_carteira ALTER COLUMN beneficiario_nome TYPE TEXT;
ALTER TABLE emendas_federais_carteira ALTER COLUMN qualif_proponente TYPE TEXT;
