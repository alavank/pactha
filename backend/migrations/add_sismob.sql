-- SISMOB — obras de saúde do Ministério da Saúde (financiamento fundo a fundo).
--
-- Fonte: https://sismobcidadao.saude.gov.br/api/public/obras — API JSON PÚBLICA,
-- sem token e sem login. Não é scraping.
--
-- TABELA PRÓPRIA, não reuso de `convenios_estadual`: a unidade aqui é a OBRA
-- FÍSICA, com etapa, percentual executado, empresa contratada e prazo de norma.
-- Nada disso cabe no vocabulário de convênio, e misturar faria as obras entrarem
-- nos KPIs de valor da aba de convênios — contando o mesmo dinheiro duas vezes,
-- porque parte dele já aparece como proposta do FNS.

CREATE TABLE IF NOT EXISTS sismob_obras (
    -- Identidade da FONTE: é o id de rota da própria API (GET /obras/{id}),
    -- portanto único e estável — o MS não pode mudá-lo sem quebrar os próprios
    -- permalinks. NÃO usar `numero_proposta` (tem 3 formatos incompatíveis) nem
    -- hash de payload (o bug que `run_fns_local.chave_fns` documenta: o valor
    -- mudava, a chave mudava, o ON CONFLICT não casava e nascia linha nova a
    -- cada repasse).
    proposta_id             BIGINT PRIMARY KEY,
    municipio_id            INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    numero_proposta         TEXT,

    -- CONVENENTE: é o FUNDO MUNICIPAL DE SAÚDE, não a prefeitura.
    -- Sem máscara (14 dígitos) porque é chave de junção com cagec_situacao.cnpj,
    -- emendas_estaduais.cnpj_beneficiario e transferegov_pac.cnpj — que gravam
    -- com máscaras diferentes.
    nu_cnpj                 VARCHAR(14),
    entidade                TEXT,              -- ex.: "FMS MONTE SIÃO/MG"

    -- Classificação
    co_programa             INTEGER,
    programa                TEXT,
    rede_programa           TEXT,
    co_tipo_obra            SMALLINT,
    tipo_obra               TEXT,
    co_tipo_recurso         SMALLINT,
    tipo_recurso            TEXT,              -- 'Programa' | 'Emenda'
    porte_programa          TEXT,
    -- Vem de `nuAnoReferencia`. NUNCA derivar de numero_proposta: coexistem
    -- CNPJ-12+ano-2+seq-3, CNPJ-14+ano-4+seq-2 e IBGE-6+CNES-7+...
    ano_referencia          INTEGER,

    -- Situação. A coluna se chama `situacao` de propósito: é o nome usado por
    -- convenios_estadual e transferegov_propostas, então o trigger de
    -- status_changes e a leitura humana ficam uniformes.
    co_situacao_obra        SMALLINT,          -- 0..8, ver services/sismob_catalogo.py
    situacao                TEXT,
    etapa                   TEXT,
    co_fase_projeto         SMALLINT,
    fase_projeto            TEXT,
    dt_mudanca_situacao     DATE,
    justificativa           TEXT,

    -- Localização e estabelecimento
    bairro                  TEXT,
    logradouro              TEXT,
    cep                     VARCHAR(8),
    -- ⚠️ A FONTE TEM COORDENADA ERRADA: a obra 193527 (Monte Sião/MG) vem com
    -- lat/long em Mato Grosso, ~700 km fora. Guardamos, mas NÃO exibimos em
    -- mapa. Se um dia entrar mapa, validar contra a bounding box do município.
    latitude                NUMERIC(11,7),
    longitude               NUMERIC(11,7),
    co_cnes                 VARCHAR(10),       -- CNES do estabelecimento existente
    nu_cnes                 VARCHAR(10),       -- CNES do NOVO estabelecimento (4a etapa)
    estabelecimento         TEXT,

    -- Dinheiro
    vl_proposta             NUMERIC(15,2),     -- repasse federal previsto
    vl_total_contrato       NUMERIC(15,2),
    vl_percentual_executado NUMERIC(5,2),

    -- PARCELAS 1..4, TODAS OPCIONAIS de propósito.
    -- Não existe "1a/2a/3a parcela" fixa: a norma vigente (Portaria de
    -- Consolidação 6/GM/MS de 2017, Título IX, arts. 1.104-1.120, que absorveu a
    -- 381/2017) determina PARCELA ÚNICA. Medido nesta base: obras de 2011/2012
    -- vieram 20% + 80% em DUAS parcelas; as de 2020 e 2025 vieram 100% em
    -- parcela única. Nem o "20/60/20" que se repete por aí confere.
    -- O regime é DERIVADO do que veio, nunca assumido.
    dt_primeira_parcela     DATE,   vl_primeira_parcela  NUMERIC(15,2),
    dt_segunda_parcela      DATE,   vl_segunda_parcela   NUMERIC(15,2),
    dt_terceira_parcela     DATE,   vl_terceira_parcela  NUMERIC(15,2),
    dt_quarta_parcela       DATE,   vl_quarta_parcela    NUMERIC(15,2),
    repasse_total           NUMERIC(15,2),
    parcelas_pagas          SMALLINT DEFAULT 0,
    regime_parcelas         TEXT,              -- 'unica' | 'multipla' | 'sem_repasse'

    -- Cronograma
    nu_portaria             TEXT,
    dt_portaria             DATE,
    dt_cadastro             DATE,
    dt_inicio_projeto       DATE,
    dt_conclusao_projeto    DATE,
    dt_ordem_servico        DATE,
    dt_inicio_obra          DATE,
    dt_provavel_execucao    DATE,
    dt_execucao             DATE,
    dt_provavel_conclusao_final DATE,
    dt_conclusao_final      DATE,
    dt_inicio_funcionamento DATE,
    dt_inauguracao          DATE,
    st_aditivo_contratual   BOOLEAN,
    possui_etapa_funcionamento BOOLEAN,

    -- FOTOS: só agregados. Decisão de produto: não exibimos imagem (a rota
    -- /fotografias/{uuid} devolve 500 hoje; só o thumbnail responde). Guardar
    -- 40+ UUIDs por obra numa tabela filha custaria escrita para nada — a lista
    -- crua fica em raw_data.
    fotos_grupos            SMALLINT DEFAULT 0,
    fotos_total             INTEGER  DEFAULT 0,
    fotos_ultima_em         TIMESTAMPTZ,

    -- SINAL DE ATIVIDADE.
    -- `dt_atualizacao_fonte` fica SÓ PARA AUDITORIA — não usar como sinal de
    -- acompanhamento: medido, ela vale 2026-07-30 tanto para obra abandonada há
    -- 3,7 anos quanto para obra que se moveu há 7 semanas (houve toque em lote),
    -- e é NULL em pelo menos uma obra. Zero poder discriminante onde importa.
    dt_atualizacao_fonte    DATE,
    -- Observação NOSSA: data em que o coletor viu o percentual mudar. Existe
    -- porque atualização só de percentual, sem foto nova, seria invisível.
    pct_mudou_em            DATE,
    -- GREATEST(ultima foto, dt_mudanca_situacao, pct_mudou_em). É este o campo
    -- que as regras de estagnação usam.
    ultima_atividade_em     DATE,

    raw_data                JSONB,

    -- Reconciliação: obra que some da listagem NUNCA é apagada, só marcada.
    visto_em                TIMESTAMPTZ,
    ausente_desde           TIMESTAMPTZ,

    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_sismob_obras_mun
    ON sismob_obras (municipio_id);
CREATE INDEX IF NOT EXISTS ix_sismob_obras_mun_sit
    ON sismob_obras (municipio_id, co_situacao_obra);
-- Ordenação "mais parada primeiro", só obras vivas — é a consulta da tela e das regras.
CREATE INDEX IF NOT EXISTS ix_sismob_obras_parada
    ON sismob_obras (municipio_id, ultima_atividade_em NULLS FIRST)
    WHERE ausente_desde IS NULL;
-- Junção com cagec_situacao pelo CNPJ do fundo.
CREATE INDEX IF NOT EXISTS ix_sismob_obras_cnpj
    ON sismob_obras (nu_cnpj) WHERE nu_cnpj IS NOT NULL;

-- --------------------------------------------------------------------------
-- EMPRESAS: tabela FILHA, não JSONB.
--
-- O CNPJ é chave de JUNÇÃO (cagec_situacao.cnpj, transferegov_pac.cnpj) e a
-- pergunta "a mesma construtora está em quantas obras?" é real nesta base: em
-- Monte Sião uma única empresa concentra 90% do valor contratado vivo. Isso em
-- JSONB viraria jsonb_array_elements no caminho quente do BI.
--
-- numero_contrato entra na PK porque aditivo pode gerar um segundo contrato da
-- mesma empresa na mesma obra. DEFAULT '' para NULL não quebrar a PK.
CREATE TABLE IF NOT EXISTS sismob_obra_empresas (
    proposta_id          BIGINT NOT NULL
                         REFERENCES sismob_obras(proposta_id) ON DELETE CASCADE,
    cnpj                 VARCHAR(14) NOT NULL,
    numero_contrato      TEXT NOT NULL DEFAULT '',
    razao_social         TEXT,
    valor_final_licitado NUMERIC(15,2),
    atualizado_em        TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (proposta_id, cnpj, numero_contrato)
);
CREATE INDEX IF NOT EXISTS ix_sismob_empresas_cnpj ON sismob_obra_empresas (cnpj);

-- --------------------------------------------------------------------------
-- Mudança de situação -> status_changes (timeline do painel, push e PDF, tudo
-- de graça). Função PRÓPRIA: a `log_status_change()` existente ramifica por
-- TG_TABLE_NAME e o ramo ELSE referencia NEW.nr_sigcon, coluna que não existe
-- aqui — reaproveitá-la daria erro em runtime a cada UPDATE.
CREATE OR REPLACE FUNCTION log_status_change_sismob() RETURNS trigger AS $$
BEGIN
    IF NEW.situacao IS DISTINCT FROM OLD.situacao THEN
        INSERT INTO status_changes
            (municipio_id, fonte, tabela, ref, orgao, objeto,
             status_anterior, status_novo)
        VALUES
            (NEW.municipio_id, 'sismob', 'sismob_obras',
             NEW.numero_proposta, 'MS — SISMOB',
             -- Mais de 3 caracteres é requisito do consumidor: o cron de push
             -- filtra por length(trim(objeto)) > 3.
             COALESCE(NULLIF(NEW.estabelecimento, ''), 'Obra da saúde')
               || ' — ' || COALESCE(NEW.programa, 'SISMOB'),
             OLD.situacao, NEW.situacao);
    END IF;
    RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_status_change_sismob ON sismob_obras;
CREATE TRIGGER trg_status_change_sismob
    AFTER UPDATE ON sismob_obras
    FOR EACH ROW EXECUTE FUNCTION log_status_change_sismob();

-- --------------------------------------------------------------------------
-- Preferência de notificação. Uma só cobre prazo de etapa, obra parada,
-- conclusão sem funcionamento e cancelada com repasse. Nenhuma das 5 colunas
-- existentes descreve "prazo de obra": enfiar em `vigencia_60d` faria desligar
-- avisos de vigência de convênio desligar também os de obra.
ALTER TABLE painel_preferencias
    ADD COLUMN IF NOT EXISTS obra_prazo BOOLEAN DEFAULT TRUE;
