-- Os convênios ESTADUAIS de quem está no município mas NÃO é a prefeitura.
--
-- Regra do dono (Parcerias em 07/09, Voluntárias em 15/09/2026, reafirmada em
-- 23/09 para o PR): NADA É DESCARTADO — a APAE que recebeu do Estado está na
-- cidade e o gestor quer saber —, mas nada entra na conta como se fosse da
-- prefeitura. Até 23/09 os coletores estaduais (`convenios_pr.py`,
-- `convenios_rs.py`) contavam essas linhas no log e as jogavam fora: em Juranda,
-- 6 dos 26 convênios de 2026 são da APAE local.
--
-- ⚠️ TABELA PRÓPRIA, E NÃO UMA COLUNA `municipal` EM `convenios_estadual`, de
-- propósito. Quinze leitores somam `convenios_estadual` (dashboard, painel, TV, BI,
-- RM, parlamentares, consolidado, alertas...). Uma linha de entidade lá dentro
-- exigiria o filtro nos quinze — e o que esquecesse um mostraria um número
-- diferente das outras telas. Aqui ela fica fora das contas POR CONSTRUÇÃO, e só
-- a tela de Convênios a lê, num bloco próprio.
--
-- Genérica por `fonte` ('SIT-PR' hoje): o RS descarta as mesmas linhas e pode
-- gravar aqui quando for a vez dele.

CREATE TABLE IF NOT EXISTS convenios_estadual_outros (
    id                   BIGSERIAL PRIMARY KEY,
    municipio_id         INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    fonte                VARCHAR(20) NOT NULL,
    -- A chave da fonte (no PR, "PR-" + convenio_empreendimento_cod — o mesmo
    -- formato de `convenios_estadual.nr_sigcon`).
    chave                VARCHAR(60) NOT NULL,
    convenente_nome      TEXT,
    orgao_concedente     TEXT,
    objeto               TEXT,
    situacao             VARCHAR(200),
    valor_concedente     NUMERIC(18, 2),
    valor_contrapartida  NUMERIC(18, 2),
    valor_total          NUMERIC(18, 2),
    valor_repassado      NUMERIC(18, 2),
    dt_assinatura        DATE,
    dt_vigencia_inicial  DATE,
    dt_vigencia_final    DATE,
    raw_data             JSONB,
    atualizado_em        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (fonte, chave)
);

CREATE INDEX IF NOT EXISTS ix_convenios_estadual_outros_mun
    ON convenios_estadual_outros (municipio_id);
