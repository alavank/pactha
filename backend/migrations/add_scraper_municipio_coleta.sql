-- Rodizio de coleta por municipio (2026-07-23).
--
-- PROBLEMA: os scrapers percorriam os municipios SEMPRE na mesma ordem (a que o
-- SELECT devolvia, na pratica alfabetica) e eram cortados quando estouravam a
-- janela do cron. Medido no Freitas (41 municipios): a rodada era abortada por
-- volta do 10o municipio -- ou seja, do "D" em diante NUNCA era atualizado.
-- Pior: a falha era silenciosa, o painel mostrava dado velho sem indicar isso.
--
-- SOLUCAO: registrar quando cada municipio foi coletado com sucesso, por fonte,
-- e ordenar a proxima rodada por "mais desatualizado primeiro" (NULLS FIRST =
-- quem nunca foi coletado tem prioridade maxima). Assim, mesmo que uma rodada
-- so de conta de uma parte da carteira, em poucas rodadas todos convergem --
-- em vez de nunca.
--
-- Tabela generica de proposito: `fonte` permite reusar o mesmo rodizio para
-- transferegov, fns, etc., sem nova migracao.

CREATE TABLE IF NOT EXISTS scraper_municipio_coleta (
    fonte            VARCHAR(40)  NOT NULL,
    municipio_id     INTEGER      NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    ultima_coleta_em TIMESTAMPTZ,
    ultimo_erro_em   TIMESTAMPTZ,
    ultimo_erro      TEXT,
    tentativas       INTEGER      NOT NULL DEFAULT 0,
    PRIMARY KEY (fonte, municipio_id)
);

-- Ordenacao da proxima rodada: mais desatualizado primeiro.
CREATE INDEX IF NOT EXISTS idx_scraper_coleta_ordem
    ON scraper_municipio_coleta (fonte, ultima_coleta_em NULLS FIRST);
