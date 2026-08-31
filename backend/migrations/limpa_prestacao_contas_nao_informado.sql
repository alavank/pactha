-- Apaga o AVISO do portal gravado como se fosse o status da prestacao de contas.
--
-- A tela do SIGCON imprime "STATUS DE PRESTAÇÃO DE CONTAS NÃO INFORMADO" no
-- lugar onde o status apareceria, e o parser guardava a FRASE como valor.
--
-- Medido em Araujos (30/08/2026): 6 dos 13 convenios com a secao lida traziam
-- esse aviso gravado, com SEI e data nulos — todos de 2025/2026, recem-assinados.
-- Na tela e no RM isso virava "Situacao: STATUS DE PRESTAÇÃO DE CONTAS NÃO
-- INFORMADO", ruido em caixa alta no lugar de um campo vazio honesto.
--
-- O parser ja foi corrigido; isto limpa o que ficou. Irmao do
-- `limpa_prestacao_contas_sei_lixo.sql`, mesma disciplina: o portal dizendo "nao
-- ha" nao e um dado, e ausencia.
--
-- ⚠️ AS DUAS PALAVRAS-ANCORA NAO TEM ACENTO — "STATUS" e "INFORMADO" — entao o
-- ILIKE basta e nao e preciso `unaccent` (que exige extensao e nao esta
-- instalada em todos os tenants). Exigir as DUAS evita apagar um status REAL:
-- nenhum dos cinco valores verdadeiros vistos em producao ("Prestação de contas
-- aprovada", "Aguardando análise da prestação de contas final", ...) contem
-- qualquer uma delas.
-- ⚠️ Idempotente: depois da primeira passada a chave nao existe mais.

UPDATE convenios_estadual
   SET raw_data = raw_data - 'prestacao_contas_status',
       updated_at = NOW()
 WHERE raw_data ? 'prestacao_contas_status'
   AND raw_data->>'prestacao_contas_status' ILIKE '%status%'
   AND raw_data->>'prestacao_contas_status' ILIKE '%informado%';
