-- As OUTRAS entidades do município, reconhecidas por CNPJ.
--
-- ⚠️ POR QUE ISTO EXISTE, com o número que o motivou. Em 06/09/2026 a primeira
-- carga de emendas federais de Nova Palma trouxe **69 das 77 linhas** do dump.
-- As 8 que faltaram são da **Associação Hospital Nossa Senhora da Piedade**
-- (CNPJ 91026138000115) — R$ 1,2 milhão em emendas parlamentares que existem,
-- são do município, e não apareciam em lugar nenhum do produto.
--
-- O motivo é que `municipios.cnpj` guarda UM CNPJ, o da prefeitura, e os
-- coletores que precisam de mais (`obrasgov`, `portal_transparencia`) vinham
-- garimpando os demais em `sismob_obras.nu_cnpj` e `transferegov_pac.cnpj` — o
-- que só acha entidade que por acaso já apareceu numa obra de saúde ou numa
-- proposta do PAC. Um hospital filantrópico não aparece em nenhum dos dois.
--
-- ⚠️⚠️ E A SAÍDA FÁCIL ERA A PROIBIDA. Dava para descobrir o CNPJ casando o
-- NOME do município no dump `siconv_proponentes.zip` — e é exatamente a regra
-- que o dono cravou em 04/09/2026 depois de casar por nome ter trazido 379
-- obras da UFSM como se fossem da prefeitura de Santa Maria, e Santa Maria do
-- Herval como se fosse Santa Maria. O CNPJ tem de ter ORIGEM, não dedução.
--
-- ⚠️ E o CNPJ do hospital NÃO entra nesta migration. Dado de um município de um
-- tenant não pode viajar nos cinco bancos — a migration cria a CASA, e quem
-- provisiona põe a linha (mesmo desenho de `municipios.cnpj`, que veio por
-- `POST /api/control/municipios` e não por INSERT em migration).

CREATE TABLE IF NOT EXISTS municipio_entidades (
    municipio_id INTEGER NOT NULL REFERENCES municipios(id) ON DELETE CASCADE,
    -- Só dígitos, sem máscara: é o formato que as APIs de governo aceitam e o
    -- mesmo de `municipios.cnpj`. A comparação nos coletores é feita com
    -- `regexp_replace(..., '\D', '', 'g')` dos dois lados.
    cnpj         VARCHAR(14) NOT NULL,
    nome         VARCHAR(300),
    -- 'fundo' · 'hospital' · 'entidade' · 'consorcio' … Texto livre de
    -- propósito: é rótulo de exibição, e um enum obrigaria migration a cada
    -- categoria nova. ⚠️ NUNCA é chave de nada.
    tipo         VARCHAR(40),
    -- De onde veio a informação — para a próxima pessoa saber se pode confiar.
    -- 'manual' (alguém cadastrou), 'cnes', 'oficio'… Ausente = manual.
    origem       VARCHAR(40),
    observacao   TEXT,
    criado_em    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (municipio_id, cnpj)
);

-- A leitura quente é "quais CNPJ deste município", já coberta pela PK. Este
-- índice serve à pergunta inversa — "de quem é este CNPJ?" —, que é a que um
-- coletor faz ao varrer um dump nacional linha a linha.
CREATE INDEX IF NOT EXISTS ix_municipio_entidades_cnpj
    ON municipio_entidades (cnpj);
