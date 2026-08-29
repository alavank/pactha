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
-- O criterio e o mesmo do parser, na sua forma mais conservadora: quatro digitos
-- seguidos em algum lugar. Um SEI real ("1500.01.0234833/2024-4") tem;
-- "Cancelar Histórico Status" nao tem digito algum. Na duvida o valor FICA — a
-- migration so remove o que comprovadamente nao e numero.
UPDATE convenios_estadual
   SET raw_data = raw_data - 'prestacao_contas_sei'
 WHERE raw_data ? 'prestacao_contas_sei'
   AND raw_data->>'prestacao_contas_sei' !~ '[0-9]{4}';
