-- Skip incremental de OPs/OBs/Obras: timestamp de quando a proposta foi checada
-- (marcado MESMO quando vazia). O enrich pula a re-navegacao das ja frescas
-- (ops_obs_atualizado_em recente) -> so as novas/vencidas navegam o portal por
-- instrumento, cortando o grosso da carga no cron diario. Espelha a mecanica do
-- historico_atualizado_em.
ALTER TABLE transferegov_propostas
    ADD COLUMN IF NOT EXISTS ops_obs_atualizado_em TIMESTAMPTZ;
