-- Skip incremental do DETALHE por proposta.
--
-- Por que: o loop de detalhe re-lia TODAS as propostas em toda rodada (freitas
-- ~3.2k, trust ~9.1k), ~2,5-3s cada. Isso e o piso que estoura a janela do cron:
-- nenhum teto de tempo faz 9.1k x 3s caber em 22 min. Os campos que vem do
-- detalhe (codigo_instrumento, modalidade, situacao_siafi, numero_processo,
-- objeto, programa, datas) mudam RARAMENTE; a `situacao` vem da LISTAGEM, que e
-- barata e roda sempre.
--
-- Com esta coluna o scraper pula o detalhe quando (a) foi lido ha menos de N dias
-- E (b) a situacao da listagem continua igual a gravada. Qualquer mudanca de
-- situacao invalida o skip e forca a releitura.
--
-- Mesmo padrao ja usado em ops_obs_atualizado_em.
ALTER TABLE transferegov_propostas
    ADD COLUMN IF NOT EXISTS detalhe_atualizado_em TIMESTAMPTZ;

-- Suporta o SELECT do skip (por municipio, filtrando pela idade do detalhe).
CREATE INDEX IF NOT EXISTS idx_tgprop_detalhe_atualizado
    ON transferegov_propostas (municipio_id, detalhe_atualizado_em);
