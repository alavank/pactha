-- RADAR DE CAPTACAO, a terceira porta: BENEFICIARIO ESPECIFICO (17/09/2026).
--
-- O programa ja nomeia quem pode propor. A janela vem em
-- DT_PROG_INI/FIM_BENEF_ESP (`siconv_programa.zip`) e os nomeados em
-- `siconv_programa_proponentes.zip`, com o CNPJ tirado de `siconv_proponentes.zip`.
-- Medido em 17/09/2026: Nova Palma nomeada em 4 programas abertos, Santa Maria
-- em 13, Monte Siao em 3, e o radar nao mostrava nenhum.
--
-- ⚠️ `proponentes_cnpj` NULL = programa SEM lista, e nao "ninguem pode". Quem
-- decide o que a lista significa e o router: na porta de beneficiario, fora da
-- lista a porta nao abre; na de emenda a lista so marca o municipio (ela cresce
-- durante a janela, conforme os gabinetes indicam).
--
-- ⚠️ TEXT[] E NAO TABELA FILHA. Sao ~110 programas abertos, com lista mediana de
-- 16 CNPJs e maxima de 5.623 (Novo PAC Agua/Esgoto), e a consulta e sempre
-- `:cnpj = ANY(proponentes_cnpj)` sobre a linha ja filtrada por UF.
--
-- Idempotente e aditiva: as colunas nascem nulas e a proxima coleta as preenche.

ALTER TABLE programas_captacao ADD COLUMN IF NOT EXISTS dt_ini_benef DATE;
ALTER TABLE programas_captacao ADD COLUMN IF NOT EXISTS dt_fim_benef DATE;
ALTER TABLE programas_captacao ADD COLUMN IF NOT EXISTS proponentes_cnpj TEXT[];
