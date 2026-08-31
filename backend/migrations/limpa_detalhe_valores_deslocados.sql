-- Tira do JSONB `detalhe` o trio de valores que NAO FECHA A CONTA.
--
-- A trava `valores_coerentes` (#322) nasceu protegendo as tres COLUNAS de
-- dinheiro, e nisso ela funciona: um trio deslocado nunca fecha
-- global = repasse + contrapartida, entao as colunas ficam com o valor do CSV
-- oficial. Mas o `detalhe` seguia sendo gravado INTEIRO, com os valores
-- deslocados dentro dele.
--
-- Medido em Araujos (30/08/2026): 83 de 83 propostas tinham o trio trocado no
-- JSONB — "Valor Global" com o repasse, "Valor de Repasse" com a contrapartida —
-- e 61 tinham sido regravadas naquele mesmo dia. Nao era passivo antigo: era o
-- mesmo numero errado sendo reescrito a cada rodada, ao lado de uma coluna
-- certa, esperando alguem ler o blob em vez da coluna.
--
-- ⚠️ APAGA, NAO CORRIGE. O `detalhe` e o que a PAGINA disse; escrever o valor
-- certo aqui inventaria uma leitura que nunca houve. Quem precisa do numero tem
-- as colunas ao lado, que vem do dado aberto. O marcador `_valores_descartados`
-- deixa o silencio auditavel — sem ele, "nao tem valor no detalhe" seria
-- indistinguivel de "nunca li".
--
-- ⚠️ SO MEXE NO TRIO INCOERENTE. Onde a leitura saiu certa (o portal serve mais
-- de um layout), os tres valores continuam no blob.
--
-- ⚠️ O regex antes de cada cast nao e enfeite: `detalhe` e texto livre vindo da
-- tela, e um cast que estoure derruba a transacao do arquivo inteiro.
--
-- Idempotente: depois da primeira passada as chaves nao existem mais, e o
-- `detalhe ? 'Valor Global'` deixa de casar.

UPDATE transferegov_propostas
   SET detalhe = (detalhe - 'Valor Global' - 'Valor de Repasse' - 'Valor de Contrapartida')
                 || '{"_valores_descartados": ["Valor Global", "Valor de Repasse", "Valor de Contrapartida"]}'::jsonb,
       updated_at = NOW()
 WHERE detalhe ? 'Valor Global'
   AND detalhe ? 'Valor de Repasse'
   AND detalhe->>'Valor Global'    ~ '^R\$ ?[0-9.]+,[0-9]{2}$'
   AND detalhe->>'Valor de Repasse' ~ '^R\$ ?[0-9.]+,[0-9]{2}$'
   AND abs(
         replace(replace(replace(detalhe->>'Valor Global', 'R$', ''), '.', ''), ',', '.')::numeric
         - (
             replace(replace(replace(detalhe->>'Valor de Repasse', 'R$', ''), '.', ''), ',', '.')::numeric
             + COALESCE(
                 CASE WHEN detalhe->>'Valor de Contrapartida' ~ '^R\$ ?[0-9.]+,[0-9]{2}$'
                      THEN replace(replace(replace(detalhe->>'Valor de Contrapartida', 'R$', ''), '.', ''), ',', '.')::numeric
                 END, 0)
           )
       ) > 0.02;
