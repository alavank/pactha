-- Saldo das contas do Fundo Municipal de Saúde, pelo arquivo anual do Portal FNS
-- (`REPASSE-FAF-COM-POPULACAO-<ANO>`, portalfns.saude.gov.br/downloads — 24/09/2026,
-- `ingestion/fns_saldo.py`).
--
-- ⚠️ É A ÚNICA FONTE PÚBLICA DESTE NÚMERO. A API do ConsultaFNS (que dá o fundo a
-- fundo por bloco, `fns_repasse_faf`) não expõe saldo: o extrato da conta foi
-- desligado (404, botão comentado na tela). O arquivo é ANUAL — o de 2025 saiu em
-- 16/01/2026, com saldo de 30/11/2025 —, então `dt_saldo` vai para a tela sempre.
--
-- Uma linha por CONTA (banco + agência + conta do CNPJ do fundo). O arquivo repete
-- o saldo em cada estratégia que usa a conta (medido: nenhuma das 52.885 contas de
-- 2025 tem dois saldos diferentes) — somar as linhas contaria o mesmo dinheiro de
-- novo a cada estratégia.

CREATE TABLE IF NOT EXISTS fns_saldo_conta (
    id              BIGSERIAL PRIMARY KEY,
    municipio_id    INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    ano             SMALLINT NOT NULL,          -- o ano do ARQUIVO (do nome), não o do IBGE
    cnpj            VARCHAR(14) NOT NULL,
    entidade        TEXT,
    banco           VARCHAR(10) NOT NULL,
    agencia         VARCHAR(10) NOT NULL,
    conta           VARCHAR(20) NOT NULL,
    saldo           NUMERIC(18, 2),
    dt_saldo        DATE,
    repassado_ano   NUMERIC(18, 2),             -- soma do VL_LIQUIDO que a conta recebeu no ano
    estrategias     JSONB,                      -- [{bloco, grupo, estrategia, liquido}]
    arquivo         TEXT NOT NULL,
    atualizado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (municipio_id, ano, cnpj, banco, agencia, conta)
);

CREATE INDEX IF NOT EXISTS ix_fns_saldo_conta_mun_ano
    ON fns_saldo_conta (municipio_id, ano DESC);
