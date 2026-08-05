-- CONTAS JULGADAS IRREGULARES pelo tribunal de contas do estado.
--
-- ⚠️ ISTO É INDÍCIO, NÃO DOCUMENTO — e essa distinção tem de sobreviver do
-- banco até a tela. A lista diz quem TEM conta julgada irregular; ela NÃO diz
-- que o município está regular quando não aparece. "Zero registros" significa
-- "sem conta irregular listada", e nada mais: o município pode ter pendência
-- em qualquer das outras exigências. Um medidor verde alimentado por esta
-- tabela colocaria um "apto" falso na frente de um prefeito.
--
-- Nasce genérica (fonte + chave) porque não é peculiaridade de Goiás: MG, SP e
-- RJ publicam listas equivalentes. O que Goiás tem de próprio é QUEM julga —
-- em GO a conta municipal é do TCM-GO, um tribunal separado do TCE-GO.

CREATE TABLE IF NOT EXISTS contas_irregulares (
    id            SERIAL PRIMARY KEY,
    municipio_id  INTEGER NOT NULL REFERENCES municipios(id),
    -- Quem publicou. Ex.: 'TCM-GO'.
    fonte         VARCHAR(40) NOT NULL,
    -- Dedup: a origem não tem id. Processo+CPF+acórdão identificam a linha.
    chave         TEXT NOT NULL,
    -- O sufixo depois do " - " no nome do município na origem: FMS, COMURG,
    -- FUNDEB... NULL = a própria prefeitura. É o que distingue "a prefeitura
    -- tem conta irregular" de "uma autarquia tem".
    entidade      VARCHAR(200),
    responsavel   VARCHAR(200),
    -- Já vem MASCARADO da origem ("41***.***-***"). Guardado como veio; não é
    -- dado pessoal completo e não deve virar um.
    cpf           VARCHAR(30),
    assunto       VARCHAR(200),
    competencia   VARCHAR(20),
    processo      VARCHAR(80),
    dt_transito   DATE,
    dt_julgamento DATE,
    acordao       VARCHAR(160),
    url           TEXT,
    -- Gradua a gravidade: "Contas de Prefeitos e Ex-Prefeitos" pesa mais que
    -- "Contas de Gestão de Demais Autoridades".
    tipo_lista    VARCHAR(160),
    raw_data      JSONB,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_contas_irregulares_fonte_chave
    ON contas_irregulares(fonte, chave);
CREATE INDEX IF NOT EXISTS ix_contas_irregulares_mun
    ON contas_irregulares(municipio_id, dt_julgamento DESC);
