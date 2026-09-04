-- Notas de Empenho vindas do DADO ABERTO federal (siconv_empenho.zip).
--
-- ⚠️ COLUNA SEPARADA DE PROPOSITO, e o requisito do dono e a razao: "nao podemos
-- perder informacao — nem agora, nem nas consultas automaticas". A listagem rica
-- de NEs vem do scraper autenticado (aba Execucao Concedente) e mora em
-- `notas_empenho`. Essa coluna NUNCA e tocada por esta fonte: a API grava AQUI,
-- e o RM le a rica quando existe, caindo para esta so quando a rica e nula.
-- Fundir as duas na mesma coluna arriscaria a fonte logada perder o detalhe que
-- so ela tem, dependendo da ordem em que as rotinas automaticas rodam.
--
-- POR QUE EXISTE. Medido em 04/09/2026 no freitas: a listagem do scraper e nula
-- em 2.742 de 3.200 propostas (a sessao gov.br fica fria — 298 de 720 horas
-- mortas num mes). O `siconv_empenho.zip`, publico e diario, tem a NE de 598 dos
-- 665 convenios celebrados que hoje aparecem sem listagem — sem login e sem o
-- bloqueio de IP que barra o portal estadual. O VALOR ja vinha do agregado
-- `valor_empenhado` (VL_EMPENHADO_CONV); o que faltava, e o que esta coluna
-- entrega, e a LISTAGEM nota a nota: numero, situacao e data.
--
-- Mesmo formato de `notas_empenho`, para o RM ler as duas com as mesmas funcoes:
--   [{numero, valor, situacao, dt_emissao, minuta_apenas}]
-- ⚠️ minuta_apenas vem sempre False: o coletor ja DESCARTA na origem a minuta
-- (valor <= R$1) e a anulacao/cancelamento (tipo com "ANULA"/"CANC", valor
-- negativo), medidos no dump — 105.962 linhas <= R$1 e dezenas de milhares de
-- valores negativos. So NE real entra.
ALTER TABLE transferegov_propostas
    ADD COLUMN IF NOT EXISTS notas_empenho_aberto JSONB;

ALTER TABLE transferegov_propostas
    ADD COLUMN IF NOT EXISTS notas_empenho_aberto_atualizado_em TIMESTAMPTZ;
