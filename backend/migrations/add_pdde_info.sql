-- PDDE (Programa Dinheiro Direto na Escola, FNDE) — o SALDO parado na conta de
-- cada escola e a SITUAÇÃO de cada escola para receber a próxima parcela
-- (25/09/2026, `ingestion/pdde_info.py`; armadilhas no cabeçalho do coletor).
--
-- Fonte: PDDE Info (www.fnde.gov.br/pddeinfo), três relatórios exportados em
-- Excel, um por município (código FNDE = IBGE de 6 dígitos):
--   * Consulta de saldo das entidades — por CONTA e mês: saldo em conta, fundos,
--     poupança e RDB/CDB;
--   * Situação da prestação de contas — por ESCOLA (INEP) e programa, no ano:
--     quem executa (EEx: a prefeitura/secretaria; UEx: a caixa escolar), a
--     situação da PC de cada um, a suspensão e o valor previsto;
--   * Relatório de suspensão — por escola, programa e PARCELA: o motivo de o
--     dinheiro não sair (UEx sem dirigente, inadimplente, CNPJ irregular...).
--
-- O PDDE PAGO (o dinheiro que entrou) NÃO é gravado aqui: são as liberações do
-- FNDE por entidade (`simec_par_liberacoes`, consulta `pls/simad`), e a tela as
-- soma pelo CNPJ da caixa escolar. O mesmo dado da tela do SIMEC, uma fonte só.
--
-- Quatro tabelas novas, FK só para `municipios`. Cada relatório é trocado INTEIRO
-- por (município, mês) ou (município, ano) numa transação, e só com a planilha
-- lida até o fim — não há chave natural confiável para upsert linha a linha.

-- 1. Saldo por conta e mês. ⚠️ A mesma conta aparece DUAS vezes no relatório
--    quando a caixa escolar atende escola de duas redes (municipal e estadual),
--    com o MESMO saldo: o coletor grava UMA linha por conta, com as redes em
--    `redes`. Somar as duas contaria o mesmo dinheiro de novo.
CREATE TABLE IF NOT EXISTS pdde_saldo (
    id              BIGSERIAL PRIMARY KEY,
    municipio_id    INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    -- 1º dia do mês de referência do saldo ("Mês: 08/2026" no cabeçalho).
    mes             DATE NOT NULL,
    cnpj            VARCHAR(14) NOT NULL,
    razao_social    TEXT,
    banco           VARCHAR(10) NOT NULL,
    agencia         VARCHAR(10) NOT NULL,
    conta           VARCHAR(20) NOT NULL,
    programa        VARCHAR(80) NOT NULL,
    -- 'municipal' | 'estadual' | 'particular' | 'federal' | 'outra'
    redes           TEXT[] NOT NULL,
    saldo_conta     NUMERIC(18, 2) NOT NULL,
    saldo_fundos    NUMERIC(18, 2) NOT NULL,
    saldo_poupanca  NUMERIC(18, 2) NOT NULL,
    saldo_rdb_cdb   NUMERIC(18, 2) NOT NULL,
    UNIQUE (municipio_id, mes, cnpj, banco, agencia, conta, programa)
);

CREATE INDEX IF NOT EXISTS ix_pdde_saldo_mun_mes ON pdde_saldo (municipio_id, mes DESC);

-- 2. Situação da prestação de contas, por escola e programa, no ano.
CREATE TABLE IF NOT EXISTS pdde_prestacao (
    id              BIGSERIAL PRIMARY KEY,
    municipio_id    INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    ano             SMALLINT NOT NULL,
    programa        VARCHAR(80),
    escola_inep     VARCHAR(12),
    escola_nome     TEXT,
    -- Entidade Executora (prefeitura, secretaria estadual, ou a própria APAE).
    eex_cnpj        VARCHAR(14),
    eex_nome        TEXT,
    eex_situacao    VARCHAR(80),
    eex_suspensa    BOOLEAN,
    -- Unidade Executora (caixa escolar/APM/CPM) — NULA quando a escola não tem.
    uex_cnpj        VARCHAR(14),
    uex_situacao    VARCHAR(80),
    uex_suspensa    BOOLEAN,
    valor_previsto  NUMERIC(18, 2),
    -- Veio também na consulta filtrada pela rede MUNICIPAL (esferaAdm=2): o
    -- relatório não traz a rede como coluna.
    municipal       BOOLEAN NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_pdde_prestacao_mun_ano ON pdde_prestacao (municipio_id, ano);

-- 3. Suspensões: por escola, programa, parcela (destinação) e motivo, no ano.
CREATE TABLE IF NOT EXISTS pdde_suspensao (
    id              BIGSERIAL PRIMARY KEY,
    municipio_id    INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    ano             SMALLINT NOT NULL,
    rede            VARCHAR(20) NOT NULL,
    programa        VARCHAR(80),
    destinacao      TEXT,
    escola_inep     VARCHAR(12),
    escola_nome     TEXT,
    -- Vazio quando o motivo é justamente não ter UEx ("Escola sem UEX").
    uex_cnpj        VARCHAR(14),
    uex_nome        TEXT,
    tipo            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_pdde_suspensao_mun_ano ON pdde_suspensao (municipio_id, ano);

-- 4. O que já foi lido INTEIRO: (município, relatório, referência). Sem linha
--    aqui = "ainda não conferimos", nunca "não há". `referencia` é o 1º dia do
--    mês (saldo) ou 01/01 do ano (prestação, suspensão).
CREATE TABLE IF NOT EXISTS pdde_carga (
    municipio_id    INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    relatorio       VARCHAR(12) NOT NULL,     -- saldo | prestacao | suspensao
    referencia      DATE NOT NULL,
    linhas          INTEGER NOT NULL,
    carregado_em    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (municipio_id, relatorio, referencia)
);
