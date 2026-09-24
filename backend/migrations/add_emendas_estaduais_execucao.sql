-- Emendas estaduais de MG: a EXECUÇÃO pela planilha oficial do emendas.mg.gov.br
-- (24/09/2026, `ingestion/emendas_mg.py`).
--
-- Até aqui `emendas_estaduais` só tinha o que o SIGCON mostra em "Pesquisar
-- Emendas por Convenente": a indicação e o VALOR INDICADO. A planilha da SEGOV
-- (`DADOS_EMENDAS_*.xlsx`, sem login) traz, para a mesma indicação (mesmo
-- número), o empenhado, o liquidado e o pago — e traz as indicações que o SIGCON
-- não mostra à prefeitura (Resolução SES ao Fundo Municipal de Saúde) e as dos
-- municípios sem senha do SIGCON no Cofre.
--
-- ⚠️ NULO ≠ ZERO nas quatro colunas: nulo é "a planilha não trouxe esta
-- indicação" (ela só veio do SIGCON); zero é a SEGOV afirmando zero.
-- `execucao_em` é a data da planilha (o nome da aba, "12-05" = 12/05/2026) — a
-- tela mostra, porque a planilha pode ficar meses sem ser regerada e "pago
-- R$ 0" de uma planilha velha não é "não foi pago".

ALTER TABLE emendas_estaduais ADD COLUMN IF NOT EXISTS valor_empenhado    NUMERIC(15,2);
ALTER TABLE emendas_estaduais ADD COLUMN IF NOT EXISTS valor_liquidado    NUMERIC(15,2);
ALTER TABLE emendas_estaduais ADD COLUMN IF NOT EXISTS valor_pago         NUMERIC(15,2);
ALTER TABLE emendas_estaduais ADD COLUMN IF NOT EXISTS valor_resto_saldo  NUMERIC(15,2);
ALTER TABLE emendas_estaduais ADD COLUMN IF NOT EXISTS execucao_em        DATE;

-- As indicações a quem NÃO é o município (OSC, caixa escolar, órgão estadual,
-- consórcio). Regra do dono: nada é descartado, nada entra na conta como se
-- fosse da prefeitura. Tabela própria — e não coluna em `emendas_estaduais` —
-- pelo motivo de `convenios_estadual_outros`: onze leitores leem aquela tabela
-- (tela, BI, RM, parlamentares, alertas...), e uma coluna exigiria o filtro nos
-- onze. Aqui fica fora das somas por construção.
CREATE TABLE IF NOT EXISTS emendas_estaduais_outros (
    id                   BIGSERIAL PRIMARY KEY,
    municipio_id         INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    nr_indicacao         VARCHAR(50) NOT NULL,
    ano                  INTEGER,
    nome_responsavel     VARCHAR(300),
    tipo_indicacao       VARCHAR(100),
    tipo_beneficiario    VARCHAR(100),
    beneficiario         VARCHAR(300),
    cnpj_beneficiario    VARCHAR(20),
    uo_sigla             VARCHAR(50),
    tipo_atendimento     VARCHAR(300),
    valor_indicacao      NUMERIC(15,2),
    valor_empenhado      NUMERIC(15,2),
    valor_liquidado      NUMERIC(15,2),
    valor_pago           NUMERIC(15,2),
    status_indicacao     VARCHAR(50),
    execucao_em          DATE,
    raw_data             JSONB,
    atualizado_em        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (municipio_id, nr_indicacao)
);

CREATE INDEX IF NOT EXISTS ix_emendas_estaduais_outros_mun
    ON emendas_estaduais_outros (municipio_id);
