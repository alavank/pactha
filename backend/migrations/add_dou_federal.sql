-- DOU federal — o que saiu no Diário Oficial da União sobre cada município.
--
-- Coletor: `ingestion/dou_federal.py` (busca pública do in.gov.br + página de cada
-- ato). Medido em 22/09/2026: Nova Palma/RS tem 11 atos em 60 dias (a Defesa
-- Civil autorizando e prorrogando repasse, o PSE e o FUNDEB por código IBGE, o
-- extrato do contrato de repasse); Santa Maria/RS, 28 em 14 dias — dos quais 20
-- citam a cidade só como endereço (UFSM, Exército, vara federal).
--
-- Três tabelas, todas novas e só com FK para `municipios`:
--
-- 1. `dou_atos` — um ato por linha, TODO ato que o coletor leu inteiro, cite ele
--    um município do cliente ou não. É o que impede a rodada seguinte de baixar
--    de novo a mesma página: a janela revê os últimos dias e "Santa Maria" traz
--    ~16 candidatos por dia. O texto integral NÃO é guardado (uma portaria do MS
--    com os 5.570 municípios passa de 1 MB); fica o trecho em (2) e o link.
-- 2. `dou_atos_municipio` — a citação: qual município, com que evidência
--    (`orgao` > `ibge` > `cnpj` > `municipio` > `cidade`) e o trecho em volta.
-- 3. `dou_cobertura` — até que dia a busca do município foi feita INTEIRA. Busca
--    que falhou não avança a data, e "sem ato no DOU" só é afirmação depois dela.
--
-- ⚠️ `dou_publicacoes` (a tabela antiga, apagada por `drop_lean_tables.sql`) NÃO
-- volta: os nomes aqui são outros de propósito.

CREATE TABLE IF NOT EXISTS dou_atos (
    id              BIGSERIAL PRIMARY KEY,
    -- A chave da própria Imprensa Nacional: in.gov.br/web/dou/-/{url_titulo}
    url_titulo      TEXT NOT NULL UNIQUE,
    class_pk        VARCHAR(20),
    -- DO1, DO2, DO3, DO1_EXTRA_A...
    secao           VARCHAR(20),
    edicao          VARCHAR(20),
    pagina          VARCHAR(10),
    data_publicacao DATE NOT NULL,
    -- artType da fonte: Portaria, Extrato de Convênio, Aviso de Licitação...
    tipo_ato        VARCHAR(120),
    -- hierarchyStr: "Ministério da Saúde/Gabinete do Ministro"
    orgao           TEXT,
    titulo          TEXT,
    ementa          TEXT,
    -- A NOSSA classificação (`dou_federal.categoria`): emergencia, selecao,
    -- habilitacao e repasse são de CAPTAÇÃO; prazo, convenio, licitacao, outros.
    categoria       VARCHAR(20) NOT NULL DEFAULT 'outros',
    avaliado_em     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_dou_atos_data ON dou_atos (data_publicacao DESC);

CREATE TABLE IF NOT EXISTS dou_atos_municipio (
    ato_id       BIGINT NOT NULL REFERENCES dou_atos(id) ON DELETE CASCADE,
    municipio_id INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    evidencia    VARCHAR(12) NOT NULL,
    trecho       TEXT,
    visto_em     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ato_id, municipio_id)
);

CREATE INDEX IF NOT EXISTS ix_dou_atos_municipio_mun
    ON dou_atos_municipio (municipio_id);

CREATE TABLE IF NOT EXISTS dou_cobertura (
    municipio_id  INTEGER PRIMARY KEY REFERENCES municipios(id) ON DELETE CASCADE,
    conferido_ate DATE NOT NULL,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
