-- CADASTRO DE PARLAMENTARES: partido, UF, cargo e foto de quem assina emenda
-- (17/09/2026). Coletor: `ingestion/parlamentares_cadastro.py` (Camara, Senado e
-- ALMG, todas abertas).
--
-- ⚠️ TABELA NOVA, E NAO A `parlamentares` ANTIGA. Aquela so sobrevive ao
-- `drop_lean_tables.sql` porque `emendas_estaduais.parlamentar_id` ainda a
-- referencia, e ninguem a preenche. Nomes derrubados por aquele arquivo
-- (`emendas`, `emendas_camara`, `dados_eleitorais`) nao podem voltar.
--
-- ⚠️ UMA LINHA POR (casa, id_externo), E NAO POR PESSOA. O deputado que virou
-- senador tem duas linhas; quem decide qual vale para uma emenda e
-- `services/nome_parlamentar.py::escolhe_cadastro`.
--
-- ⚠️ `nomes_norm` guarda TODAS as grafias vistas, em `chave_nome` (so letras,
-- sem acento e sem espaco: "CHICODANGELO"). A Camara renomeia o mesmo deputado
-- entre legislaturas, e a emenda antiga usa o nome antigo. O indice GIN existe
-- porque a tela casa pelo nome do autor (`= ANY(nomes_norm)`).
--
-- Idempotente e aditiva.

CREATE TABLE IF NOT EXISTS parlamentares_cadastro (
    casa          VARCHAR(10) NOT NULL,          -- camara | senado | almg
    id_externo    VARCHAR(20) NOT NULL,
    nome          TEXT NOT NULL,                 -- nome parlamentar (o da urna)
    nomes_norm    TEXT[] NOT NULL DEFAULT '{}',
    nome_civil    TEXT,
    partido       VARCHAR(30),                   -- o da legislatura mais recente
    uf            CHAR(2),
    cargo         VARCHAR(40) NOT NULL,          -- Deputado(a) Federal | Senador(a) | Deputado(a) Estadual
    foto_url      TEXT,
    legislaturas  INTEGER[] NOT NULL DEFAULT '{}',  -- numeracao federal (57 = 2023-2027)
    visto_em      TIMESTAMPTZ DEFAULT NOW(),
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (casa, id_externo)
);

CREATE INDEX IF NOT EXISTS idx_parl_cadastro_nome
    ON parlamentares_cadastro USING GIN (nomes_norm);

-- APELIDOS: quando a fonte da emenda grafa o nome de um jeito que nao casa
-- (erro de digitacao, nome civil longo). Curado a mao, com o motivo. A chave e
-- `chave_nome` do texto da FONTE; o alvo, a chave do nome no cadastro.
CREATE TABLE IF NOT EXISTS parlamentares_apelidos (
    nome_norm_fonte     TEXT PRIMARY KEY,
    nome_norm_cadastro  TEXT NOT NULL,
    motivo              TEXT
);

-- Os maiores sem casamento, medidos no siconv_emenda.zip de 17/09/2026 (em
-- parenteses, emendas individuais daquele nome).
INSERT INTO parlamentares_apelidos (nome_norm_fonte, nome_norm_cadastro, motivo) VALUES
    ('ABERLADOCAMARINHA',            'ABELARDOCAMARINHA', 'grafia da fonte (293)'),
    ('MARIAAPARECIDABORGHETTI',      'CIDABORGHETTI',     'nome civil (247)'),
    ('PAULOPIAUNOGUEIRA',            'PAULOPIAU',         'nome civil (174)'),
    ('NEUTODECANTO',                 'NEUTODECONTO',      'grafia da fonte (159)'),
    ('LAUREZDAROCHAMOREIRA',         'LAUREZMOREIRA',     'nome civil (145)'),
    ('EDUARDOBRNADAODEAZEREDO',      'EDUARDOAZEREDO',    'grafia da fonte (129)'),
    ('MICHELMIGUELELIASTEMERLULIA',  'MICHELTEMER',       'nome civil (84)'),
    ('JAIROPAESDELIRA',              'PAESDELIRA',        'nome civil (157)'),
    ('MARCIOREINALDODIASMOREIRA',    'MARCIOREINALDOMOREIRA', 'nome civil (80)'),
    ('GIMARGELLO',                   'JORGEAFONSOARGELLO', 'apelido (78)'),
    ('CLAUDIOVIGNATTI',              'VIGNATTI',          'nome civil (69)'),
    ('JOAQUIMBELTRAOSIQUEIRA',       'JOAQUIMBELTRAO',    'nome civil (68)'),
    ('ANTONIOPALOCCIFILHO',          'ANTONIOPALOCCI',    'nome civil (67)'),
    ('GERALDOMAGELA',                'MAGELA',            'nome civil (67)'),
    ('CIROFRANCISCOPEDROSA',         'CIROPEDROSA',       'nome civil (52)'),
    ('GERMANOMOSTARDEIROBONOW',      'GERMANOBONOW',      'nome civil (45)'),
    ('JOSEPHWALLACEFARIABANDEIRA',   'JOSEPHBANDEIRA',    'nome civil (45)')
ON CONFLICT (nome_norm_fonte) DO NOTHING;
