-- Portal da Transparencia de MG: empenhos e PAGAMENTOS do Estado ao municipio.
--
-- Pedido do dono (26/08/2026): "no portal fazemos as pesquisas por CNPJ do
-- Municipio para confirmar se o pagamento foi realizado ... vc acha que e
-- possivel puxar essa informacao para o sistema vinculado ao convenio".
--
-- O CAMINHO, provado em teste real e so com HTTP (sem browser, sem login):
--   CNPJ -> GET listagem com id_favorecido=0   -> resolve o id interno
--        -> GET listagem com o id              -> ids de empenho + token de sessao
--        -> GET detalhamento=1                 -> HISTORICO (traz o nº do convenio)
--        -> GET detalhamento=3                 -> pagamento (data, OB, situacao, valor)
--
-- ⚠️ POR QUE TABELA, E NAO COLUNA EM `convenios_estadual`. Tres razoes, e cada
-- uma sozinha ja decide:
--   1. a busca e por CNPJ e devolve empenho QUE NAO TEM CONVENIO — nao ha linha
--      em `convenios_estadual` onde pendurar;
--   2. `convenios_estadual` e multi-fonte (SIGCON-MG, FNS, GConv-ES, CAGE-RS): a
--      coluna nasceria NULA para sempre em tenant sem municipio de MG;
--   3. todo UPDATE naquela tabela passa pelo trigger `trg_status_change_conv`, e
--      um coletor diario a mais ali encheria `status_changes` de ruido.
--
-- ⚠️ E NAO SE ESCREVE NO `raw_data` DO CONVENIO. O upsert do SIGCON faz
-- `raw_data || EXCLUDED.raw_data`, e o `||` do jsonb e merge RASO: o segundo
-- escritor apaga a chave do primeiro, calado.
--
-- ⚠️ SEM TRIGGER DE status_changes AQUI. `log_status_change()` ramifica por
-- TG_TABLE_NAME e o ramo ELSE le `NEW.nr_sigcon`, coluna que esta tabela nao
-- tem — seria erro em runtime a cada UPDATE.
CREATE TABLE IF NOT EXISTS transparencia_mg_empenhos (
    -- A identidade e a DA FONTE (`data-idEmpenho`), nunca um hash do conteudo.
    id_empenho        BIGINT PRIMARY KEY,
    municipio_id      INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    cnpj_favorecido   VARCHAR(14),
    -- O id interno do favorecido no portal, resolvido a partir do CNPJ. Guardado
    -- para a proxima rodada pular o passo 1 — e para se saber DE ONDE veio.
    id_favorecido     TEXT,
    ano_exercicio     INTEGER,
    nr_empenho        TEXT,
    dt_empenho        DATE,
    unidade_executora TEXT,
    tipo_empenho      TEXT,
    vr_empenho        NUMERIC(18, 2),
    vr_liquidado      NUMERIC(18, 2),
    vr_pago           NUMERIC(18, 2),
    -- O texto CRU do "Descricao Historico do Empenho". E o UNICO lugar onde o
    -- vinculo com o convenio existe, e por isso ele e guardado inteiro: se a
    -- regra de extracao mudar, da para reprocessar sem re-raspar o portal.
    historico         TEXT,
    -- O vinculo. ANULAVEL de proposito: empenho sem convenio e caso NORMAL.
    -- ⚠️ `ON DELETE SET NULL` nao e estilo, e obrigatorio: `fix_duplicatas_
    -- chave_natural.sql` faz DELETE em `convenios_estadual` e roda a CADA boot.
    -- Com NO ACTION, aquela migration passaria a falhar em todo deploy assim que
    -- existisse uma linha ligada aqui.
    convenio_id       INTEGER REFERENCES convenios_estadual(id) ON DELETE SET NULL,
    convenio_ref      TEXT,      -- '1261002849/2025', como extraido do historico
    -- O numero solto que aparece logo depois no historico ('9492993'). GUARDADO,
    -- e NAO usado para juntar: ele TEM CARA de nr_siafi, mas isso e hipotese e
    -- nao medicao — juntar por hipotese vincula pagamento ao convenio errado,
    -- que e pior do que nao vincular.
    numero_solto      TEXT,
    -- ⚠️ VOCABULARIO FECHADO, e nenhum destes colapsa num NULL. Sem isto, uma
    -- mudanca de rotulo do portal se disfarca de "empenho sem historico" para
    -- sempre, e a cobertura cai sem ninguem ver:
    --   casado          o numero extraido achou UM convenio
    --   ambiguo         achou MAIS DE UM (nao escolhe: registra e cala)
    --   nao_casou       extraiu numero e nenhum convenio bate
    --   sem_numero      historico lido, sem token no formato N/AAAA
    --   sem_historico   o rotulo veio, o valor estava vazio (dado legitimo)
    --   detalhe_falhou  a chamada nao devolveu corpo util
    --   layout_mudou    corpo valido, mas o rotulo do historico sumiu
    vinculo_status    VARCHAR(20),
    -- Qual coluna casou: nr_proposta | nr_plano_trabalho | nr_siafi | nr_sigcon.
    -- E o que permite medir, depois, qual chave vale a pena.
    vinculo_metodo    VARCHAR(30),
    -- ⚠️ NULO = NAO CONSULTADO, nunca "nao houve pagamento". Mesma doutrina de
    -- `add_te_pagamentos.sql` e de `notas_empenho`.
    pagamentos        JSONB,
    -- Fila incremental: o detalhe do empenho e caro (2 GET) e o historico nao
    -- muda depois de emitido.
    detalhe_lido_em   TIMESTAMPTZ,
    raw_data          JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_transp_mg_emp_mun
    ON transparencia_mg_empenhos (municipio_id);
CREATE INDEX IF NOT EXISTS ix_transp_mg_emp_conv
    ON transparencia_mg_empenhos (convenio_id) WHERE convenio_id IS NOT NULL;
-- A FILA do detalhe: quem nunca foi lido vem primeiro.
CREATE INDEX IF NOT EXISTS ix_transp_mg_emp_fila
    ON transparencia_mg_empenhos (detalhe_lido_em NULLS FIRST);
-- Re-vinculo: quem tem numero extraido e ainda nao achou convenio. E por aqui
-- que uma coleta futura do SIGCON "resgata" empenhos que chegaram antes do
-- convenio existir no banco.
CREATE INDEX IF NOT EXISTS ix_transp_mg_emp_revinculo
    ON transparencia_mg_empenhos (municipio_id)
    WHERE convenio_id IS NULL AND convenio_ref IS NOT NULL;
