-- Obras.gov.br: o vínculo territorial vem da FONTE, e o projeto ganha o detalhe
-- que os outros 5 endpoints da API já publicavam e nós não líamos.
--
-- ============================================================================
-- 1. O MUNICÍPIO DEIXA DE SER SÓ INFERÊNCIA NOSSA
-- ============================================================================
--
-- O cabeçalho de `add_obrasgov.sql` diz: *"A API não tem filtro territorial
-- (medido: `codigoIbge` é ignorado e devolve obra de outro estado com HTTP 200)"*.
-- Isso continua verdade — **para o endpoint `/projeto-investimento`**. Medido em
-- 07/09/2026, o `/geometria` é outra história:
--
--     /geometria sem filtro ................ 216.278 registros
--     /geometria?cod_ibge=4313102 ..........      26
--     /geometria?cod_ibge=9999999 ..........       0   (não devolve tudo)
--     /projeto-investimento?codigo_ibge=... . 130.579 = o total sem filtro
--
-- Ou seja: o filtro territorial existe, só não está no endpoint que o coletor
-- usava. `cod_ibge_geometria` guarda essa prova — quando ele está preenchido, o
-- município veio do Governo, não de um palpite por CNPJ.
--
-- ⚠️ ISSO NÃO APOSENTA O CASAMENTO POR CNPJ. Medido nos três tenants: há obra
-- que só o CNPJ acha (5 em Nova Palma, 7 em Santa Maria — projeto sem geometria
-- cadastrada) e muita obra que só a geometria acha (365 em Santa Maria). Os dois
-- caminhos se somam; nenhum substitui o outro.
--
-- ============================================================================
-- 2. `vinculo`: DE QUEM É A OBRA, JÁ QUE AGORA ENTRA OBRA DE OUTRO ENTE
-- ============================================================================
--
-- Com o território, entram no município obras que não são da prefeitura. Em
-- Santa Maria, das 436 com geometria, 365 são de outros entes — UFSM, DNIT, IF
-- Farroupilha, Receita Federal, Comando da Aeronáutica. É informação legítima
-- (investimento federal na cidade), mas misturá-la com o dinheiro da prefeitura
-- seria repetir, por outro caminho, o erro que `add_obrasgov.sql` já documenta:
-- casar por nome trouxe 379 obras da UFSM *"como se fossem da prefeitura"*.
--
--     'prefeitura'  — algum CNPJ do município bate com tomador/executor
--     'territorio'  — só a geometria aponta; a obra é de outro ente
--     'abrangencia' — projeto GUARDA-CHUVA, que não é uma obra nesta cidade
--
-- ⚠️ O TERCEIRO VALOR EXISTE POR MEDIÇÃO, não por precaução. Amostra de 124
-- projetos da carteira do freitas: 102 têm geometria em UM município, 15 em 2 a
-- 5, e **3 em mais de cem**. Esses três são:
--
--     324.31-80    "Manutenção rodoviária na malha federal do DNIT em MG"  790
--     6325.31-75   FUNASA, abastecimento de água em MG                     202
--     123265.26-04 consultoria com uf_principal=PE, geometria em MG        312
--
-- O `324.31-80` sozinho aparece em 41 dos 42 municípios do freitas. Gravá-lo
-- como "obra em Araújos" seria ruído, e o mesmo ruído 41 vezes. Fica no banco,
-- marcado, para a tela decidir — e `abrangencia_municipios` diz em quantos
-- municípios do Brasil aquele projeto tem geometria.
--
-- ============================================================================
-- 3. A CHAVE MUDA PARA (municipio_id, id_unico) — a troca que já estava prevista
-- ============================================================================
--
-- `add_obrasgov.sql` fechou assim: *"UMA OBRA PODE PERTENCER A MAIS DE UM
-- MUNICÍPIO da carteira (consórcio, obra intermunicipal). A chave é `id_unico`
-- (…) então nesse caso a última gravação vence (…). É a escolha certa enquanto
-- os tenants têm um município cada; num tenant de assessoria com carteira
-- grande, isto vira uma tabela de ligação. Registrado aqui para que a troca seja
-- uma decisão, e não uma descoberta."*
--
-- Chegou a hora, e por dois motivos somados: o freitas tem 42 municípios ativos
-- (não é mais "um município cada"), e o vínculo territorial multiplica as
-- obras intermunicipais — 5 projetos da carteira do freitas já estão em mais de
-- um município. Com `id_unico` global, 40 deles perderiam a obra em silêncio.
--
-- ⚠️ NÃO PERDE LINHA: o índice novo é mais PERMISSIVO que o antigo (toda linha
-- única em `id_unico` continua única em `(municipio_id, id_unico)`). O DROP vem
-- depois do CREATE para a tabela nunca ficar sem proteção contra duplicata.

-- --- 1. colunas do vínculo territorial ------------------------------------
ALTER TABLE obrasgov_projetos
    ADD COLUMN IF NOT EXISTS vinculo                VARCHAR(20),
    ADD COLUMN IF NOT EXISTS cod_ibge_geometria     INTEGER,
    ADD COLUMN IF NOT EXISTS abrangencia_municipios INTEGER;

-- --- 2. colunas do detalhe (os 5 endpoints que não líamos) -----------------
-- Derivadas em coluna o que a tela ordena e soma; o resto em JSONB, no mesmo
-- padrão de `transferegov_propostas.ops_obs` e `transferegov_te.pagamentos`.
ALTER TABLE obrasgov_projetos
    ADD COLUMN IF NOT EXISTS percentual_execucao   NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS data_execucao         DATE,
    ADD COLUMN IF NOT EXISTS valor_empenhado       NUMERIC(18,2),
    ADD COLUMN IF NOT EXISTS valor_liquidado       NUMERIC(18,2),
    ADD COLUMN IF NOT EXISTS valor_pago            NUMERIC(18,2),
    ADD COLUMN IF NOT EXISTS valor_restos_pagar    NUMERIC(18,2),
    ADD COLUMN IF NOT EXISTS empenhos              JSONB,
    ADD COLUMN IF NOT EXISTS contratos             JSONB,
    ADD COLUMN IF NOT EXISTS paralisacao           JSONB,
    ADD COLUMN IF NOT EXISTS estudo_viabilidade    JSONB,
    -- Carimbo PRÓPRIO da fase de detalhe, e não `atualizado_em`: a varredura de
    -- projetos e a de detalhe têm ritmos diferentes, e sem isto não há como a
    -- fase de detalhe saber o que já visitou. Mesma razão do
    -- `pagamentos_atualizado_em` da Transferência Especial.
    ADD COLUMN IF NOT EXISTS detalhe_atualizado_em TIMESTAMPTZ;

-- --- 3. a chave natural passa a incluir o município ------------------------
CREATE UNIQUE INDEX IF NOT EXISTS ux_obrasgov_projetos_mun
    ON obrasgov_projetos (municipio_id, id_unico);

DROP INDEX IF EXISTS ux_obrasgov_projetos;

-- --- 4. o que já está no banco é tudo 'prefeitura' -------------------------
-- Toda linha existente entrou pelo casamento por CNPJ, que é a definição de
-- 'prefeitura'. Sem este backfill elas ficariam com `vinculo` NULO e a tela não
-- saberia distingui-las das territoriais que chegam na próxima rodada.
UPDATE obrasgov_projetos SET vinculo = 'prefeitura' WHERE vinculo IS NULL;
