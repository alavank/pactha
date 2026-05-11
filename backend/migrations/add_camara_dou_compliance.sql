-- Frente C: Camara Deputados + DOU + CEIS + Oportunidades
-- Cria 7 tabelas para fechar gap vs plataforma Alavank.

-- ============ CAMARA ============
CREATE TABLE IF NOT EXISTS camara_despesas (
    id SERIAL PRIMARY KEY,
    parlamentar_id INTEGER REFERENCES parlamentares(id),
    id_camara INTEGER,
    ano INTEGER,
    mes INTEGER,
    tipo_despesa VARCHAR(200),
    fornecedor VARCHAR(300),
    cnpj_cpf VARCHAR(20),
    valor_documento NUMERIC(18, 2),
    valor_liquido NUMERIC(18, 2),
    dt_documento DATE,
    url_documento VARCHAR(500),
    nr_documento VARCHAR(50),
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_cd_parl ON camara_despesas(parlamentar_id);
CREATE INDEX IF NOT EXISTS ix_cd_idcamara ON camara_despesas(id_camara);
CREATE INDEX IF NOT EXISTS ix_cd_ano ON camara_despesas(ano);

CREATE TABLE IF NOT EXISTS camara_proposicoes (
    id SERIAL PRIMARY KEY,
    id_camara INTEGER UNIQUE,
    sigla_tipo VARCHAR(20),
    numero INTEGER,
    ano INTEGER,
    ementa TEXT,
    descricao_tipo VARCHAR(200),
    autor_id_camara INTEGER,
    autor_nome VARCHAR(300),
    autor_partido VARCHAR(20),
    autor_uf VARCHAR(2),
    situacao VARCHAR(200),
    dt_apresentacao DATE,
    url VARCHAR(500),
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_cp_idcamara ON camara_proposicoes(id_camara);
CREATE INDEX IF NOT EXISTS ix_cp_ano ON camara_proposicoes(ano);
CREATE INDEX IF NOT EXISTS ix_cp_autor ON camara_proposicoes(autor_id_camara);

CREATE TABLE IF NOT EXISTS camara_votacoes (
    id SERIAL PRIMARY KEY,
    id_votacao VARCHAR(50),
    proposicao_id_camara INTEGER,
    dt_votacao DATE,
    descricao TEXT,
    resultado VARCHAR(100),
    parlamentar_id INTEGER REFERENCES parlamentares(id),
    id_camara_dep INTEGER,
    voto VARCHAR(20),
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_cv_idvotacao ON camara_votacoes(id_votacao);
CREATE INDEX IF NOT EXISTS ix_cv_dt ON camara_votacoes(dt_votacao);
CREATE INDEX IF NOT EXISTS ix_cv_parl ON camara_votacoes(parlamentar_id);
CREATE INDEX IF NOT EXISTS ix_cv_dep ON camara_votacoes(id_camara_dep);

CREATE TABLE IF NOT EXISTS emendas_camara (
    id SERIAL PRIMARY KEY,
    cd_emenda VARCHAR(20) UNIQUE,
    ano INTEGER,
    autor_id_camara INTEGER,
    autor_nome VARCHAR(300),
    tipo VARCHAR(50),
    funcao VARCHAR(100),
    subfuncao VARCHAR(100),
    valor_indicado NUMERIC(18, 2),
    valor_empenhado NUMERIC(18, 2),
    valor_pago NUMERIC(18, 2),
    objeto TEXT,
    municipio_id INTEGER REFERENCES municipios(id),
    codigo_ibge VARCHAR(10),
    parlamentar_id INTEGER REFERENCES parlamentares(id),
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_ec_ano ON emendas_camara(ano);
CREATE INDEX IF NOT EXISTS ix_ec_autor_id ON emendas_camara(autor_id_camara);
CREATE INDEX IF NOT EXISTS ix_ec_autor_nome ON emendas_camara(autor_nome);
CREATE INDEX IF NOT EXISTS ix_ec_mun ON emendas_camara(municipio_id);
CREATE INDEX IF NOT EXISTS ix_ec_ibge ON emendas_camara(codigo_ibge);
CREATE INDEX IF NOT EXISTS ix_ec_parl ON emendas_camara(parlamentar_id);

-- ============ DOU ============
CREATE TABLE IF NOT EXISTS dou_publicacoes (
    id SERIAL PRIMARY KEY,
    id_oficio VARCHAR(50) UNIQUE,
    secao VARCHAR(20),
    dt_publicacao DATE,
    orgao VARCHAR(300),
    titulo VARCHAR(1000),
    texto TEXT,
    autoridade VARCHAR(300),
    materia VARCHAR(200),
    valor VARCHAR(50),
    edicao VARCHAR(50),
    pagina VARCHAR(20),
    url_pdf VARCHAR(500),
    raw_xml TEXT,
    keywords_match JSONB,
    municipio_match VARCHAR(300),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_dou_dt ON dou_publicacoes(dt_publicacao);
CREATE INDEX IF NOT EXISTS ix_dou_dt_secao ON dou_publicacoes(dt_publicacao, secao);

-- ============ COMPLIANCE ============
CREATE TABLE IF NOT EXISTS sancoes_ceis (
    id SERIAL PRIMARY KEY,
    cpf_cnpj VARCHAR(20),
    razao_social VARCHAR(500),
    nome_fantasia VARCHAR(500),
    tipo_pessoa VARCHAR(20),
    tipo_sancao VARCHAR(200),
    fundamentacao TEXT,
    dt_inicio_sancao DATE,
    dt_fim_sancao DATE,
    dt_publicacao DATE,
    orgao_sancionador VARCHAR(300),
    uf_sancionador VARCHAR(2),
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_ceis_cnpj ON sancoes_ceis(cpf_cnpj);
CREATE INDEX IF NOT EXISTS ix_ceis_dt_ini ON sancoes_ceis(dt_inicio_sancao);
CREATE INDEX IF NOT EXISTS ix_ceis_dt_fim ON sancoes_ceis(dt_fim_sancao);

CREATE TABLE IF NOT EXISTS programas_federais (
    id SERIAL PRIMARY KEY,
    id_programa INTEGER UNIQUE,
    nome_programa VARCHAR(500),
    orgao VARCHAR(300),
    objetivo TEXT,
    publico_alvo VARCHAR(500),
    valor_minimo NUMERIC(18, 2),
    valor_maximo NUMERIC(18, 2),
    dt_inicio_inscricao DATE,
    dt_fim_inscricao DATE,
    contrapartida_min_pct NUMERIC(5, 2),
    modalidade VARCHAR(200),
    natureza VARCHAR(100),
    situacao VARCHAR(100),
    url VARCHAR(500),
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_prog_inicio ON programas_federais(dt_inicio_inscricao);
CREATE INDEX IF NOT EXISTS ix_prog_fim ON programas_federais(dt_fim_inscricao);
CREATE INDEX IF NOT EXISTS ix_prog_situacao ON programas_federais(situacao);
