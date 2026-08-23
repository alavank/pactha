-- NEs / Notas de Empenho (aba Execucao Concedente > NEs), por proposta.
--
-- Pedido do dono: carregar a listagem de notas de empenho e exibir numero, valor
-- e data no modal do TransfereGov e no RM ("Situacao do NEs").
--
-- Ate aqui o unico sinal de empenho no PACTHA era `detalhe->>'Empenhado'`, um
-- Sim/Nao que o proprio rm_builder documenta como furado (marcava "Aprovadas"
-- como empenhadas sem empenho real). Isto troca a INFERENCIA pelo DOCUMENTO.
--
-- Guarda o que a listagem devolve (ver ingestion/transferegov_http.py
-- ::notas_empenho):
--   [{numero, minuta, valor, valor_siafi, situacao, dt_emissao, minuta_apenas}]
--
-- ⚠️ `minuta_apenas` marca a linha que NAO e dinheiro: a listagem mistura o
-- empenho com a MINUTA, que vem sem numero e com valor de R$ 1,00. Quem somar
-- sem olhar essa marca poe R$ 1,00 no relatorio como se fosse recurso.
ALTER TABLE transferegov_propostas
    ADD COLUMN IF NOT EXISTS notas_empenho JSONB;
