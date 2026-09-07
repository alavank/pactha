-- Transferências FUNDO A FUNDO do Transferegov.br — o outro lado do ConsultaFNS.
--
-- ⭐ O QUE ELA ACRESCENTA A UMA FONTE QUE JÁ TEMOS. O `fns_repasse_faf` coleta o
-- repasse consolidado por bloco no ConsultaFNS: **o dinheiro que entra**. Esta
-- fonte traz o que o FNS não publica — o **plano de ação** que justifica o
-- repasse: diagnóstico, objetivos, vigência, e a decomposição do valor entre
-- emenda, repasse específico, voluntário, recursos próprios e rendimentos. Uma
-- não substitui a outra; juntas fecham o ciclo entre o repasse e o que foi feito
-- com ele.
--
-- E não é só saúde: em Nova Palma o primeiro plano é do **Ministério da
-- Cultura** (Lei Aldir Blanc), com o Fundo Nacional da Cultura como repassador.
-- O módulo cobre todo fundo a fundo, não apenas o do SUS.
--
-- Conferido com dado real (Nova Palma, 07/09/2026): 4 planos de ação somando
-- R$ 413.420,20, todos AUTORIZADO e com saldo disponível zerado.
--
-- ⚠️ COMO SE ENTRA NESTA FONTE, e por que não é pelo caminho óbvio. O filtro
-- `codigo_ibge_municipio_ente_recebedor_plano_acao` **existe no Swagger e
-- devolve HTTP 500** (medido em 06 e 07/09/2026) — é defeito da fonte, não
-- nosso. O caminho que funciona tem dois passos:
--
--     /programas-beneficiarios?codigo_ibge_..._beneficiario_programa=4313102
--       -> 5 beneficiários, todos com cnpj_beneficiario_programa
--     /planos-acao?cnpj_ente_recebedor_plano_acao=88488358000156
--       -> 4 planos, com os valores batendo com os beneficiários
--
-- ⚠️ E AQUI O ENTE É A PREFEITURA, ao contrário do módulo de Parcerias, onde as
-- propostas são todas do Fundo Municipal da Saúde. Por isso o coletor descobre
-- os CNPJs pelo IBGE em vez de assumir qualquer um dos dois: a fonte diz quem
-- recebe, e a suposição erraria em um dos dois módulos, sem falhar em log.

CREATE TABLE IF NOT EXISTS faf_planos_acao (
    id                      SERIAL PRIMARY KEY,
    municipio_id            INTEGER NOT NULL REFERENCES municipios(id),
    id_plano_acao           TEXT NOT NULL,
    codigo_plano_acao       TEXT,
    id_programa             TEXT,

    situacao                TEXT,
    data_inicio_vigencia    DATE,
    data_fim_vigencia       DATE,
    -- O texto que justifica o plano. É o que dá conteúdo ao RM, e o FNS não tem.
    diagnostico             TEXT,
    objetivos               TEXT,

    -- ⭐ A DECOMPOSIÇÃO DO DINHEIRO, que é o motivo de coletar esta fonte. O
    -- ConsultaFNS diz quanto entrou; só aqui se sabe QUANTO VEIO DE EMENDA.
    valor_total             NUMERIC(18,2),
    valor_repasse_emenda    NUMERIC(18,2),
    valor_repasse_especifico NUMERIC(18,2),
    valor_repasse_voluntario NUMERIC(18,2),
    valor_recursos_proprios NUMERIC(18,2),
    valor_rendimentos       NUMERIC(18,2),
    valor_custeio           NUMERIC(18,2),
    valor_investimento      NUMERIC(18,2),
    valor_saldo_disponivel  NUMERIC(18,2),

    -- Quem repassa. Não é sempre o Ministério da Saúde: o primeiro plano de Nova
    -- Palma é do Ministério da Cultura (Lei Aldir Blanc).
    orgao_repassador        TEXT,
    sigla_orgao_repassador  TEXT,
    fundo_repassador        TEXT,

    -- Quem recebe. Guardado apesar de o município já ser coluna, porque a fonte
    -- distingue ENTE de FUNDO e a tela precisa dizer qual dos dois.
    cnpj_ente_recebedor     VARCHAR(14),
    nome_ente_recebedor     TEXT,
    tipo_unidade_recebedora TEXT,

    -- PRESTAÇÃO DE CONTAS. ⚠️ Preenche um buraco conhecido do modelo: as tabelas
    -- `prestacao_contas`/`prestacao_documentos` são DROPADAS a cada boot
    -- (`drop_lean_tables.sql`), e hoje prestação de contas só existe como texto
    -- dentro de um campo de situação. Aqui ela vem estruturada — valor
    -- executado, pendente, resultados alcançados e declaração de conformidade.
    relatorios_gestao       JSONB,

    raw_data                JSONB,
    atualizado_em           TIMESTAMPTZ DEFAULT NOW()
);

-- A chave já nasce com o município, como em `add_parcerias.sql` e pelo mesmo
-- motivo: numa carteira de assessoria o mesmo plano pode alcançar mais de um
-- município, e uma chave global faria a última gravação apagar as outras — o
-- defeito que `add_obrasgov.sql` teve de corrigir depois.
CREATE UNIQUE INDEX IF NOT EXISTS ux_faf_planos_acao
    ON faf_planos_acao (municipio_id, id_plano_acao);

CREATE INDEX IF NOT EXISTS ix_faf_planos_acao_mun
    ON faf_planos_acao (municipio_id, data_fim_vigencia DESC);
