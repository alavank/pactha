-- SIMEC/PAR: as quatro colunas de DINHEIRO que a pagina sempre teve e o parser
-- descartava.
--
-- Achado em 31/08/2026, investigando o convenio federal 932836/2021 (creche,
-- Programa SIMEC/PAR4, Araujos): o RM mostrava "Desembolsado: R$ 0,00" e o dono
-- apontou que no SIMEC ha empenho e pagamento. Estava certo — e o dado nunca
-- saiu do portal.
--
-- A tabela de `carregaTermos.php` tem 12 a 14 colunas. O `_COLS` de
-- `ingestion/simec_termos.py` mapeava NOVE, e as que ficaram de fora sao
-- justamente as de dinheiro:
--
--     Valor Empenhado | Pagamento Efetivado (ou Valor Pago) |
--     Saldo Bancario (CC + CP + Fundo) | Prestacao de Contas
--
-- Medido na propria pagina de Araujos: o TC 202141430-1 (Obra, com clausula
-- suspensiva) traz Valor do Termo R$ 3.157.096,83, Valor Empenhado
-- R$ 1.875.147,32 e Pagamento Efetivado R$ 572.978,05. So o primeiro numero
-- chegava ao banco.
--
-- ⚠️ O rotulo do PAGO MUDA entre as tabelas da mesma pagina: "Pagamento
-- Efetivado" nas tabelas de TC/aditivo e "Valor Pago" na de PAR/PAC. As duas
-- caem nesta unica coluna `valor_pago`.
--
-- ⚠️ `prestacao_contas` e TEXTO, nao booleano: o portal escreve "Enviada",
-- "Sem Valor a Comprovar" e afins. Reduzir a sim/nao perderia o estado do meio.
--
-- ⚠️ Todas ANULAVEIS e sem DEFAULT. NULL aqui e "ainda nao coletado" — o valor
-- so aparece depois que o coletor rodar de novo. Um DEFAULT 0 diria "nao houve
-- empenho" sobre termo que ninguem releu ainda.
--
-- Puramente ADITIVA e idempotente.

ALTER TABLE simec_termos
    ADD COLUMN IF NOT EXISTS valor_empenhado   NUMERIC(16,2),
    ADD COLUMN IF NOT EXISTS valor_pago        NUMERIC(16,2),
    ADD COLUMN IF NOT EXISTS saldo_bancario    NUMERIC(16,2),
    ADD COLUMN IF NOT EXISTS prestacao_contas  VARCHAR(120);
