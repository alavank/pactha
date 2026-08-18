-- TERMOS DE COMPROMISSO do SIMEC/PAR (MEC), por municipio.
--
-- O que ja tinhamos do SIMEC era `simec_par_liberacoes`: os PAGAMENTOS (OB, data,
-- valor). Faltava o INSTRUMENTO — o Termo de Compromisso em si: processo, tipo,
-- vigencia e valor. E o que a consulta publica
-- https://simec.mec.gov.br/par/carregaTermos.php devolve (POST estuf + muncod,
-- SEM login). Ver ingestion/simec_termos.py.
--
-- Idempotente. Chave natural: (municipio_id, processo, nr_documento) — o portal
-- repete a mesma linha em blocos diferentes da pagina, entao a chave e o que
-- impede duplicata.
CREATE TABLE IF NOT EXISTS simec_termos (
    id                SERIAL PRIMARY KEY,
    municipio_id      INTEGER NOT NULL REFERENCES municipios(id),
    processo          VARCHAR(40),
    nr_documento      VARCHAR(40),
    tipo_documento    VARCHAR(200),
    tipo_objeto       VARCHAR(120),
    dt_validacao      DATE,
    periodo_pagamento TEXT,
    vigencia_txt      TEXT,          -- como o portal escreve ("30/12/2024 - (-595 dias)")
    dt_vigencia       DATE,          -- a data extraida, p/ ordenar e alertar
    valor_termo       NUMERIC(16,2),
    quantidade_obra   VARCHAR(20),
    raw_data          JSONB,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_simec_termos_chave
    ON simec_termos (municipio_id, COALESCE(processo, ''), COALESCE(nr_documento, ''));
CREATE INDEX IF NOT EXISTS idx_simec_termos_municipio ON simec_termos (municipio_id);
