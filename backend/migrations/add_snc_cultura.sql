-- SNC — a adesão do município ao Sistema Nacional de Cultura e as leis que ele
-- registrou (26/09/2026, `ingestion/snc_cultura.py`).
--
-- Serve ao alerta do PNAB: Lei 14.399/2022, art. 6º, § 8º (Lei 15.132/2025) —
-- "a partir de 2027, somente receberão os recursos [...] os entes federativos que
-- dispuserem de fundo de cultura". Lido da página pública de adesão por IBGE
-- (snc.cultura.gov.br/adesao/detalhar/<IBGE7>), que também traz nome e e-mail de
-- conselheiros — NADA disso é gravado aqui: só a situação e os componentes.
--
-- Uma linha por município, trocada a cada leitura. Tabela nova, FK só para `municipios`.

CREATE TABLE IF NOT EXISTS snc_cultura (
    municipio_id     INTEGER PRIMARY KEY REFERENCES municipios(id) ON DELETE CASCADE,
    situacao         TEXT NOT NULL,             -- "Publicado no DOU" | "Nao possui adesão" | ...
    data_publicacao  DATE,                      -- do acordo de cooperação no DOU
    componentes      JSONB NOT NULL,            -- [{nome, registrado, documento}]
    fundo_registrado BOOLEAN NOT NULL,          -- "Lei do Fundo de Cultura" com documento
    lido_em          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
