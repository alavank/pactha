-- Lista de licitacoes/processos de execucao COM a situacao, por proposta.
--
-- Ate 16/08/2026 so guardavamos processo_execucao_qtd (INTEGER, a contagem). O
-- dono pediu a SITUACAO da licitacao ("Concluído", "Em execução"...), que so
-- existe por-linha. Esta coluna guarda a lista raspada da tela Execucao
-- Convenente > Processo de Execucao (URL direta server-rendered):
--   [{numero, modalidade, data_publicacao, situacao, sistema_origem, aceite}]
-- processo_execucao_qtd continua sendo len(lista) — nada quebra quem so le o qtd.
ALTER TABLE transferegov_propostas
    ADD COLUMN IF NOT EXISTS processo_execucao JSONB;
