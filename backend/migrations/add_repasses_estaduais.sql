-- REPASSES ESTADUAIS — pagamento, não instrumento.
--
-- ⚠️ POR QUE UMA TABELA NOVA, e não `convenios_estadual`.
-- O SIGCON-MG e o GConv-ES publicam o INSTRUMENTO: número do convênio,
-- vigência, situação, valor pactuado. Goiás publica o PAGAMENTO: quem recebeu,
-- quando, quanto, por qual unidade orçamentária — e mais nada. Gravar isso em
-- `convenios_estadual` deixaria metade das colunas vazias na tela, e o gestor
-- que conhece Minas concluiria que o sistema PERDEU dado. Aqui a tela mostra o
-- que existe, do jeito que existe.
--
-- A tabela nasce genérica (fonte + uf) porque este não é um problema de Goiás:
-- vários estados publicam execução e não instrumento.

CREATE TABLE IF NOT EXISTS repasses_estaduais (
    id            SERIAL PRIMARY KEY,
    municipio_id  INTEGER NOT NULL REFERENCES municipios(id),
    -- Qual coletor trouxe. Ex.: 'TRANSFVOL-GO'.
    fonte         VARCHAR(40) NOT NULL,
    -- ⚠️ A CHAVE DE DEDUPLICAÇÃO, e ela é COMPOSTA porque a origem NÃO TEM id.
    -- Medido no CSV de 05/2026: CNPJ+data+valor+unidade+processo deixava 1 par
    -- colidindo — duas parcelas do MESMO valor, no MESMO dia, do mesmo processo,
    -- que só se distinguem pelo outro número de processo e pela fonte de
    -- recursos. Com os 7 campos: 1281 linhas -> 1281 chaves, zero colisão.
    -- Chave curta demais aqui = pagamento sumindo em silêncio na reingestão.
    chave         TEXT NOT NULL,
    cnpj          VARCHAR(14),
    credor        VARCHAR(300),
    orgao         VARCHAR(300),   -- Unidade Orçamentária (quem pagou)
    formalidade   VARCHAR(120),   -- Convênio / Outras / ...
    elemento      VARCHAR(160),
    sub_elemento  VARCHAR(200),
    processo      VARCHAR(60),
    processo_alt  VARCHAR(60),    -- a origem tem DUAS colunas de processo, ambas reais
    fonte_recursos VARCHAR(40),
    descricao     TEXT,
    -- Extraídos da descrição quando ela os traz (em GO, ~25% das linhas).
    emenda_numero VARCHAR(20),
    emenda_autor  VARCHAR(160),
    data_repasse  DATE,
    valor         NUMERIC(18,2),
    ano           INTEGER,
    raw_data      JSONB,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- O alvo do ON CONFLICT do coletor.
CREATE UNIQUE INDEX IF NOT EXISTS ux_repasses_estaduais_fonte_chave
    ON repasses_estaduais(fonte, chave);

-- A tela filtra por município e ordena por data.
CREATE INDEX IF NOT EXISTS ix_repasses_estaduais_mun_data
    ON repasses_estaduais(municipio_id, data_repasse DESC);
CREATE INDEX IF NOT EXISTS ix_repasses_estaduais_ano
    ON repasses_estaduais(municipio_id, ano);
