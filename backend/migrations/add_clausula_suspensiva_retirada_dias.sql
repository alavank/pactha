-- =====================================================================
-- Clausula suspensiva COMPLETA, pelo dado aberto — as duas colunas que
-- faltavam.
--
-- O `siconv_convenio.zip` sempre trouxe QUATRO colunas de clausula suspensiva;
-- `transferegov_opendata.py` lia duas (`DATA_SUSPENSIVA`, `MOTIVO_SUSPENSAO`).
-- As outras duas viram coluna aqui:
--
--   clausula_suspensiva_dt_retirada  "Data de retirada do instrumento da
--                                     situacao de Clausula Suspensiva"
--   clausula_suspensiva_dias         "Quantidade de dias calculado a partir da
--                                     diferenca entre as datas de previsao para
--                                     resolucao da Clausula Suspensiva e da data
--                                     de assinatura do instrumento"
--
-- (textos do dicionario oficial, versionado em docs/dados-abertos-transferegov/)
--
-- ⚠️ POR QUE ISSO IMPORTA MAIS DO QUE "duas colunas a mais". Sem a data de
-- RETIRADA nao ha como distinguir "clausula ainda travando o instrumento" de
-- "clausula ja resolvida": a tela mostrava a data PREVISTA de um convenio ja
-- liberado como se ele continuasse suspenso. A unica forma de saber era a
-- navegacao Struts AUTENTICADA ("Detalhar Clausula Suspensiva"), que depende de
-- sessao gov.br viva — a mesma sessao que, ao morrer, para a coleta gated dos
-- SEIS tenants sem erro visivel em lugar nenhum (medido em 09/09/2026: 169h
-- parada porque um Chrome foi fechado).
--
-- Trocar navegacao autenticada por coluna de CSV que ja e baixado todo dia e o
-- primeiro passo do plano da auditoria de 29/08 (§B.6.1, linha "TransfereGov —
-- clausula suspensiva detalhada", esforco P): "Desligar a navegacao Struts;
-- derivar `situacao_contratacao_detalhe` do dump".
--
-- ⚠️ NAO desliga nada ainda. Esta migration so cria as colunas e o coletor so
-- passa a preenche-las; a navegacao Struts continua rodando. Desligar exige
-- comparar os dois lados em producao — o que sem estas colunas era impossivel,
-- porque nao havia onde guardar o lado do dump para comparar.
--
-- Tipos: DATE e INTEGER (no CSV as duas vem como texto, como todo o dump).
-- `clausula_suspensiva_dias` aceita NEGATIVO por definicao — e uma subtracao de
-- datas, e previsao anterior a assinatura da numero negativo.
--
-- Idempotente (roda a cada boot, em seis bancos, um deles criado do zero).
-- =====================================================================

ALTER TABLE transferegov_propostas
    ADD COLUMN IF NOT EXISTS clausula_suspensiva_dt_retirada DATE,
    ADD COLUMN IF NOT EXISTS clausula_suspensiva_dias        INTEGER;

COMMENT ON COLUMN transferegov_propostas.clausula_suspensiva_dt_retirada IS
    'Data de retirada do instrumento da situacao de Clausula Suspensiva '
    '(siconv_convenio.DATA_RETIRADA_SUSPENSIVA). Preenchida = clausula resolvida.';

COMMENT ON COLUMN transferegov_propostas.clausula_suspensiva_dias IS
    'Dias entre a previsao de resolucao da Clausula Suspensiva e a assinatura do '
    'instrumento (siconv_convenio.DIAS_CLAUSULA_SUSPENSIVA). Pode ser negativo.';
