-- Gestão de Parcerias do Transferegov.br — a fonte que o PACTHA não coletava.
--
-- ⭐ POR QUE ELA EXISTE E O QUE ELA **NÃO** É. O módulo de Parcerias é novo
-- (Comunicado nº 23/2026 do MGI) e **não substitui o SICONV**: os convênios
-- discricionários continuam nos dumps CSV que `transferegov_opendata.py` lê. Ele
-- é onde as transferências passaram a ser processadas de 2024 em diante —
-- medido em 06/09/2026: dos 176 programas publicados, **144 são Transferências
-- Fundo a Fundo da Saúde**. Em outras palavras, é aqui que a emenda de saúde do
-- município vive hoje, e era o único instrumento federal que a plataforma não
-- enxergava.
--
-- O que a fonte entrega, na cadeia conferida com dado real (Nova Palma,
-- proposta 75376):
--
--     /proposta?cd_ibge_recebedor=4313102 ..... 11 propostas, R$ 2,18 mi
--       └─ ds_objeto "AQUISIÇÃO DE EQUIPAMENTO PARA UNIDADE BÁSICA DE SAÚDE"
--       └─ /parceria?id_proposta=75376 ........ o instrumento celebrado
--       └─ /distribuicao-recurso-proposta ..... emenda 2026.2023.0002,
--                                              PAULO PAIM, Individual, GND4,
--                                              R$ 299.999
--
-- ⚠️ O FILTRO TERRITORIAL É DE PRIMEIRA CLASSE AQUI, ao contrário do
-- `/projeto-investimento` do Obras.gov: `cd_ibge_recebedor` filtra no servidor
-- (11 de 89.400 para Nova Palma). Não há casamento por CNPJ nem por nome, e
-- portanto não há a classe de erro que o `obrasgov.py` passa o cabeçalho inteiro
-- descrevendo.
--
-- ⚠️ ESTA TABELA É O NÚCLEO, E NÃO A CADEIA INTEIRA. A execução financeira
-- (empenho → documento hábil → ordem de pagamento → extrato) fica de fora desta
-- primeira entrega por CUSTO medido, não por esquecimento: buscar os 8 filhos de
-- cada proposta custaria 4.418 requisições no freitas (27 min) e 5.668 no trust
-- (35 min), contra 1.136 e 1.432 do núcleo. Ela entra depois, incremental, no
-- mesmo desenho do `transferegov_te.pagamentos`. O `extrato-bancario` sozinho
-- tem 1.275.217 registros — 6.377 páginas — e nunca poderá ser varrido inteiro.

CREATE TABLE IF NOT EXISTS parcerias_propostas (
    id                  SERIAL PRIMARY KEY,
    municipio_id        INTEGER NOT NULL REFERENCES municipios(id),
    -- Id da fonte. É estável e global, como o `id_proposta` do SICONV.
    id_proposta         BIGINT NOT NULL,
    id_programa         BIGINT,

    -- QUEM RECEBE. ⚠️ Raramente é a prefeitura: em Nova Palma as 11 propostas
    -- são todas do FUNDO MUNICIPAL DA SAUDE, com CNPJ próprio. Por isso o
    -- vínculo com o município vem do `cd_ibge_recebedor` da fonte, e não de um
    -- casamento por CNPJ — que aqui perderia tudo.
    cnpj_ente_recebedor VARCHAR(14),
    nome_ente_recebedor TEXT,
    natureza_juridica   TEXT,

    -- O QUE É. `ds_objeto` é o que a tela mostra; os outros três são o texto
    -- longo que a fonte publica e que o RM pode citar.
    objeto              TEXT,
    problema            TEXT,
    resultado_esperado  TEXT,
    publico_alvo        TEXT,
    situacao            TEXT,
    valor_total         NUMERIC(18,2),
    ano_proposta        INTEGER,
    data_proposta       DATE,

    -- O INSTRUMENTO CELEBRADO (de `/parceria`). Nulo enquanto a proposta não
    -- virou parceria — que é estado legítimo e frequente.
    id_parceria         BIGINT,
    codigo_parceria     TEXT,
    situacao_parceria   TEXT,
    data_assinatura     DATE,

    -- A EMENDA (de `/distribuicao-recurso-proposta`). ⭐ É o campo que liga a
    -- proposta ao parlamentar, e o motivo de esta fonte importar para o produto:
    -- sem ela, a emenda de saúde de 2024 em diante não aparecia em lugar nenhum.
    numero_emenda       TEXT,
    parlamentar         TEXT,
    tipo_emenda         TEXT,
    valor_emenda        NUMERIC(18,2),

    -- ⚠️ TEXTO DE FONTE EXTERNA NASCE `TEXT`, sem largura — a regra que o repo
    -- já escreveu em `add_obrasgov_taxonomias_text.sql` e
    -- `add_emendas_federais_texto.sql`. Largura só onde NÓS controlamos o
    -- formato (o CNPJ de 14).
    raw_data            JSONB,
    atualizado_em       TIMESTAMPTZ DEFAULT NOW()
);

-- ⚠️ A CHAVE INCLUI O MUNICÍPIO, e não é decoração. `add_obrasgov.sql` deixou a
-- chave global e teve de trocá-la depois (ver
-- `add_obrasgov_territorio_e_detalhe.sql`, 07/09/2026): numa carteira de
-- assessoria, o mesmo instrumento pode pertencer a mais de um município e a
-- última gravação apagava as outras. Aqui já nasce certo.
CREATE UNIQUE INDEX IF NOT EXISTS ux_parcerias_propostas
    ON parcerias_propostas (municipio_id, id_proposta);

CREATE INDEX IF NOT EXISTS ix_parcerias_propostas_mun
    ON parcerias_propostas (municipio_id, ano_proposta DESC);
