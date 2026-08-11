-- HISTORICO DOS ALERTAS DO VIGIA — para o aviso ter para onde ir.
--
-- Achado em 11/08/2026, na auditoria: o watchdog fez o trabalho dele
-- perfeitamente — detectou credencial recusada em 2 municipios e emitiu o
-- alerta as 10:07 — e a linha seguinte do log era "(Telegram nao configurado
-- -- alerta so no log)". O Telegram foi desligado por decisao do dono (09/08) e
-- o canal de WhatsApp ainda nao existe: na pratica o sistema tinha vigia, e o
-- vigia gritava para uma sala vazia.
--
-- A tabela `watchdog_alertas` que ja existia guarda so o ULTIMO envio por
-- (tipo, chave) — ela e o anti-spam, nao o historico: nao tem a mensagem, e
-- cada alerta novo sobrescreve o anterior. Esta aqui guarda o QUE foi dito,
-- para a tela de Status dos Dados mostrar. E o canal que nao depende de
-- credencial nenhuma: o dono abre o sistema e ve.
CREATE TABLE IF NOT EXISTS watchdog_historico (
    id          SERIAL PRIMARY KEY,
    tipo        TEXT NOT NULL,          -- fonte_parada | municipio_defasado | ...
    chave       TEXT NOT NULL,          -- a fonte/recurso do alerta
    mensagem    TEXT NOT NULL,          -- o texto que o operador le
    criado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- A leitura e sempre "os mais recentes primeiro".
CREATE INDEX IF NOT EXISTS idx_watchdog_historico_recentes
    ON watchdog_historico (criado_em DESC);
