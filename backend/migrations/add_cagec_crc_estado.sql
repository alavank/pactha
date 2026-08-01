-- O detalhamento do CAGEC nao vem da listagem: vem do CRC, o PDF que o botao
-- "Emitir CRC" gera. A listagem so diz "Situacao para Parceria: Irregular".
--
-- EM 2026-08-01 o portal do Estado passou a recusar a emissao para TODO mundo
-- ("Nao foi possivel recuperar dados do Convenente/Parceiro para geracao do
-- relatorio" — reproduzido 9x/9, inclusive para Belo Horizonte). O coletor caiu
-- para o fallback de 2 linhas e GRAVOU essas 2 linhas por cima das ~28
-- obrigacoes que ja conhecia. A tela perdeu o detalhamento inteiro, e o
-- ingestion_log registrou "ok".
--
-- Duas colunas consertam a classe do problema, nao so este episodio:
--   crc_em   — de QUANDO e o detalhamento que esta na tela. Sem isso nao da
--              para distinguir "cadastro tem 2 exigencias" de "so consegui ler
--              2 linhas hoje", que e a confusao que apagou o dado.
--   crc_erro — a palavra do PORTAL quando a emissao falha. Guardada crua: e o
--              que a tela mostra ao gestor e o que prova de quem e a falha.
ALTER TABLE cagec_situacao ADD COLUMN IF NOT EXISTS crc_em   DATE;
ALTER TABLE cagec_situacao ADD COLUMN IF NOT EXISTS crc_erro TEXT;

-- Retroativo. Quem tem mais que as 2 linhas do fallback so pode ter vindo de um
-- CRC lido. Nao existe a data exata (nao havia coluna), e `data_pesquisa` e a
-- aproximacao honesta — nunca superestima, porque a linha foi gravada naquele
-- dia. So toca quem HOJE tem detalhe; nao inventa historico para ninguem.
UPDATE cagec_situacao
   SET crc_em = data_pesquisa
 WHERE crc_em IS NULL
   AND itens IS NOT NULL
   AND jsonb_typeof(itens) = 'array'
   AND jsonb_array_length(itens) > 2;
