-- Situacao do Projeto Basico/Termo de Referencia, por proposta.
--
-- Pedido do dono (18/08/2026): quando o convenio esta em Clausula Suspensiva e
-- SEM licitacao, o RM precisa dizer em que pe esta o documento — o portal mostra
-- isso na aba "Projeto Basico/Termo de Referencia" (ex.: Situacao "Em Análise").
-- Ate aqui o PACTHA so INFERIA isso por palavra-chave no texto do motivo da
-- clausula (rm_builder._PEND_MUNICIPAL_KW), o que classificava a pendencia mas
-- nunca dizia o STATUS.
--
-- Guarda o que a tela server-rendered devolve (ver ingestion/transferegov_http.py
-- ::projeto_basico — GET na URL direta depois do contexto setado, e sob a mesma
-- sessao do SP SAML `execucao` de que a Licitacao ja depende):
--   {situacao, documentos:[{nome_arquivo, descricao, tipo, data_upload}]}
ALTER TABLE transferegov_propostas
    ADD COLUMN IF NOT EXISTS projeto_basico JSONB;
