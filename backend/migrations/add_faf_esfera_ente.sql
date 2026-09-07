-- O dinheiro do ESTADO estava sendo contado como do MUNICÍPIO.
--
-- ⚠️ O DEFEITO, medido em 07/09/2026 no tenant trust. O coletor entra pelo
-- filtro `codigo_ibge_municipio_ente_beneficiario_programa`, que devolve todo
-- ente **sediado** naquele município — e a sede do governo estadual é a
-- capital. Resultado gravado:
--
--     Goiânia   ESTADO DE GOIAS ....................... R$ 470.381.305
--     Goiânia   SEC. DE ESTADO DA SEGURANÇA PÚBLICA ... R$ 265.232.961
--     Goiânia   DIRETORIA-GERAL DE POLÍCIA PENAL ...... R$  29.093.331
--     Goiânia   MUNICIPIO DE GOIANIA .................. R$  73.789.174   ← o real
--     Palmas    SECRETARIA DA SEGURANÇA PÚBLICA ....... R$ 243.681.257
--     Palmas    ESTADO DO TOCANTINS ................... R$ 164.825.590
--     Palmas    MUNICIPIO DE PALMAS ................... R$  20.297.831   ← o real
--
-- Dos R$ 1,42 bilhão da carteira, cerca de 85% era dinheiro estadual creditado
-- à capital. Uma tela construída sobre isso diria que Goiânia recebeu meio
-- bilhão em planos fundo a fundo — e estaria mentindo por um fator de 8.
--
-- ⚠️ E NÃO HÁ O QUE APROVEITAR nesses planos. O IBGE ali é a SEDE do ente, não
-- onde o dinheiro é aplicado: um plano do Estado de Goiás é executado no estado
-- inteiro. Guardá-lo com `municipio_id` de Goiânia seria afirmar um vínculo
-- municipal que a fonte não faz.
--
-- ⭐ O QUE SEPARA OS DOIS é `descricao_tipo_unidade_ente_plano_acao`, que tem
-- exatamente dois valores em toda a base — "Ente Municipal" e "Ente
-- Estadual/Distrital" — e é a própria fonte dizendo a esfera. O coletor passou
-- a filtrar por ele (`ingestion/faf_planos.py::e_do_municipio`) e a gravar o
-- valor aqui, para que quem abrir o banco confira sem reler o coletor.
--
-- É o mesmo erro de chave que já custou caro duas vezes neste repo: filtrar
-- município por algo que descreve *onde a entidade fica* em vez de *de quem é o
-- dinheiro* (as 379 obras da UFSM em Santa Maria, os 40.707 planos órfãos de
-- `transferegov_te`). Entidade sediada no município não é o município.

ALTER TABLE faf_planos_acao
    ADD COLUMN IF NOT EXISTS esfera_ente TEXT;

-- ⚠️ A LIMPEZA DO QUE JÁ ENTROU. Idempotente e segura em banco novo: sem linhas
-- estaduais, apaga zero. E o DELETE é reversível pela própria coleta — a rodada
-- seguinte regrava o que for legítimo.
--
-- Só apaga o que a fonte AFIRMA ser estadual: `raw_data` é o payload cru que o
-- coletor guardou, e um plano cujo campo esteja ausente fica onde está, pela
-- mesma razão que `e_do_municipio` devolve True no nulo — esvaziar a tela em
-- silêncio é pior que um plano estadual a mais.
DELETE FROM faf_planos_acao
 WHERE raw_data ->> 'descricao_tipo_unidade_ente_plano_acao'
       = 'Ente Estadual/Distrital';

-- O que sobreviveu e já tem a informação no payload ganha a coluna preenchida,
-- sem esperar a próxima rodada.
UPDATE faf_planos_acao
   SET esfera_ente = raw_data ->> 'descricao_tipo_unidade_ente_plano_acao'
 WHERE esfera_ente IS NULL
   AND raw_data ->> 'descricao_tipo_unidade_ente_plano_acao' IS NOT NULL;
