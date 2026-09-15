-- FNS: o valor PAGO sai da coluna do valor PROPOSTO e vai para a sua propria.
--
-- O coletor gravava `valor = vl_pago or vl_prop` (run_fns_local.py) e alimentava
-- com esse mesmo parametro `valor_total` E `valor_concedente`. O `or` do Python
-- devolve o pago sempre que ele nao e zero, entao a coluna significava:
--   * "valor da PROPOSTA" nas linhas pagas por inteiro (a maioria — e por isso o
--     defeito passou despercebido: os dois numeros sao iguais ali);
--   * "valor PAGO" nas linhas pagas pela metade, sem nada dizendo que mudou.
--
-- Medido em Araujos (30/08/2026), as 2 linhas parciais de 43:
--   FNS-310390-2019-INCREMEN   proposta 500.000,00   pago 400.000,00
--   FNS-310390-2026-CUSTEIO_   proposta 800.000,00   pago 200.000,00
-- A tela mostrava 400.000 e 200.000 como valor total: R$ 700.000,00 de valor
-- proposto sumindo, com as duas rotuladas "Empenhado".
--
-- O conserto no coletor ja foi feito, mas ele so alcanca a linha na PROXIMA
-- coleta. Este arquivo repara o que ja esta gravado, lendo do proprio
-- `raw_data` da linha — nao ha dado novo aqui, so o que o FNS ja devolveu.
--
-- migration: a-cada-boot
-- (a marca acima faz o runner rodar este arquivo em TODO boot, mesmo ja
-- registrado em `migrations_aplicadas` — ver `services/startup.py`)
--
-- ⚠️ IDEMPOTENTE E AUTOCURATIVO, roda a cada boot. O `IS DISTINCT FROM` faz o
-- UPDATE nao tocar em nada quando ja esta certo, e o `jsonb_typeof = 'number'`
-- impede que um raw_data com texto no lugar do numero derrube o cast — e com
-- ele o arquivo inteiro, que roda numa transacao so.

-- 1) o pago ganha coluna propria
UPDATE convenios_estadual
   SET valor_repassado = NULLIF((raw_data->>'vlPago')::numeric, 0)
 WHERE fonte = 'FNS'
   AND jsonb_typeof(raw_data->'vlPago') = 'number'
   AND valor_repassado IS DISTINCT FROM NULLIF((raw_data->>'vlPago')::numeric, 0);

-- 2) valor_total / valor_concedente voltam a ser o PROPOSTO
--    (com queda para o pago quando o FNS nao informou proposta — mesmo criterio
--    do coletor, para as duas fontes nao divergirem)
UPDATE convenios_estadual
   SET valor_total = COALESCE(NULLIF((raw_data->>'vlProposta')::numeric, 0),
                              NULLIF((raw_data->>'vlPago')::numeric, 0)),
       valor_concedente = COALESCE(NULLIF((raw_data->>'vlProposta')::numeric, 0),
                                   NULLIF((raw_data->>'vlPago')::numeric, 0))
 WHERE fonte = 'FNS'
   AND jsonb_typeof(raw_data->'vlProposta') = 'number'
   AND valor_total IS DISTINCT FROM COALESCE(
           NULLIF((raw_data->>'vlProposta')::numeric, 0),
           NULLIF((raw_data->>'vlPago')::numeric, 0));
