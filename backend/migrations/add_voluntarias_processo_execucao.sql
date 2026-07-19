-- Processo de Execução (Licitações) do instrumento — TransfereGov Execução Convenente.
-- Para convênios com Situação de Contratação "Normal": nº de licitações/processos
-- registrados. 0 = convênio Normal SEM processo de execução iniciado (flag de
-- monitoramento, destacado igual à cláusula suspensiva). NULL = ainda não capturado.
ALTER TABLE transferegov_propostas
    ADD COLUMN IF NOT EXISTS processo_execucao_qtd INTEGER;
