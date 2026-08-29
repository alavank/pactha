-- LIMPEZA: o `prestacao_contas_sei` que nao e numero de processo nenhum.
--
-- MEDIDO EM PRODUCAO (29/08/2026, freitas): 99 de 99 convenios com o campo
-- gravado traziam a string "Cancelar Histórico Status" — os ROTULOS DOS BOTOES
-- do PrimeFaces, nao um processo SEI. Quando o campo vem VAZIO no portal, o
-- texto logo depois do rotulo e a barra de botoes; o corte do parser para no
-- proximo ROTULO, e botao nao tem dois-pontos, entao nada o cortava.
--
-- O parser ja foi corrigido (`_pc_forma`: numero de processo tem de ter cara de
-- numero de processo). ⚠️ MAS SO ISSO NAO BASTA, e e por isso que este arquivo
-- existe: o upsert do SIGCON faz `raw_data || EXCLUDED.raw_data`, que e MERGE
-- RASO. Chave que o coletor deixa de emitir NAO E APAGADA — ela sobrevive a
-- todas as rodadas futuras. Sem esta limpeza, os 99 convenios continuariam
-- exibindo "Nº SEI: Cancelar Histórico Status" na tela e no relatorio para
-- sempre, mesmo com o coletor consertado.
--
-- ⚠️ RODA A CADA BOOT, e isso esta certo: e IDEMPOTENTE (depois da 1a vez
-- nenhuma linha casa) e AUTOCURATIVA (se um valor sem numero reaparecer por
-- qualquer caminho, o proximo boot o remove).
--
-- ⚠️ NAO gera ruido em `status_changes`: o trigger `trg_status_change_conv` so
-- insere quando `NEW.situacao IS DISTINCT FROM OLD.situacao`, e aqui `situacao`
-- nao e tocada.
--
-- ⚠️ O CRITERIO DA 1a VERSAO ERA FROUXO DEMAIS, e a producao mostrou: ele era
-- "nao tem quatro digitos seguidos", e limpou 81 dos 99 — sobraram 18. Os 18
-- eram o MESMO lixo, so que mais comprido: "Cancelar Histórico Status" seguido
-- de outro texto que por acaso tinha numeros. (Eu quase os declarei legitimos:
-- a consulta de conferencia usava `left(valor,26)`, que CORTAVA exatamente na
-- parte que os diferenciava. Conferir com o campo truncado quase virou "esta
-- tudo certo".)
--
-- O criterio certo e POSITIVO e sobre o valor INTEIRO: numero de processo NAO
-- TEM LETRA. "1500.01.0234833/2024-4" nao tem; qualquer rotulo de botao tem.
--
-- ⚠️ E EXIGE A BARRA COM ANO. Medido em producao (29/08/2026): com a regra
-- anterior, `030.725.676-62` — UM CPF — estava gravado como "Nº SEI". Nao e so
-- campo errado: e DADO PESSOAL na tela e num documento entregue ao municipio.
-- O que separa os dois e a estrutura: SEI e `1500.01.0069235/2025-73`, tem
-- BARRA seguida de ANO; CPF e CNPJ nao tem. Esta linha APAGA o CPF ja gravado —
-- corrigir so o coletor o deixaria la para sempre (o merge do jsonb e raso).
UPDATE convenios_estadual
   SET raw_data = raw_data - 'prestacao_contas_sei'
 WHERE raw_data ? 'prestacao_contas_sei'
   AND (raw_data->>'prestacao_contas_sei' ~ '[[:alpha:]]'
        OR raw_data->>'prestacao_contas_sei' !~ '[0-9]{4}'
        OR raw_data->>'prestacao_contas_sei' !~ '/(19|20)[0-9]{2}');

-- AS DATAS, pelo mesmo motivo e no mesmo lote. `prestacao_contas_status_data`
-- foi gravada como "*" — o marcador de campo obrigatorio do formulario, medido
-- em producao. Data que nao tem forma de data nao e data.
UPDATE convenios_estadual
   SET raw_data = raw_data - 'prestacao_contas_data'
 WHERE raw_data ? 'prestacao_contas_data'
   AND raw_data->>'prestacao_contas_data' !~ '[0-9]{2}/[0-9]{2}/[0-9]{4}';

UPDATE convenios_estadual
   SET raw_data = raw_data - 'prestacao_contas_status_data'
 WHERE raw_data ? 'prestacao_contas_status_data'
   AND raw_data->>'prestacao_contas_status_data' !~ '[0-9]{2}/[0-9]{2}/[0-9]{4}';
