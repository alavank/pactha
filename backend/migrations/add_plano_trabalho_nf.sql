-- Frente 1: Cálculo automático de prestação de contas (NF × plano de trabalho)
-- Cria tabelas plano_trabalho e notas_fiscais para suportar comparativo automatizado.

CREATE TABLE IF NOT EXISTS plano_trabalho (
    id SERIAL PRIMARY KEY,
    prestacao_id INTEGER NOT NULL REFERENCES prestacao_contas(id) ON DELETE CASCADE,
    item VARCHAR(500) NOT NULL,
    categoria VARCHAR(100),
    quantidade NUMERIC(12, 2),
    valor_unitario NUMERIC(18, 2),
    valor_planejado NUMERIC(18, 2) NOT NULL,
    observacao TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_plano_trabalho_prestacao ON plano_trabalho(prestacao_id);

CREATE TABLE IF NOT EXISTS notas_fiscais (
    id SERIAL PRIMARY KEY,
    prestacao_id INTEGER NOT NULL REFERENCES prestacao_contas(id) ON DELETE CASCADE,
    plano_item_id INTEGER REFERENCES plano_trabalho(id) ON DELETE SET NULL,
    nf_numero VARCHAR(50),
    nf_serie VARCHAR(20),
    fornecedor_nome VARCHAR(300),
    fornecedor_cnpj VARCHAR(20),
    descricao TEXT,
    valor NUMERIC(18, 2) NOT NULL,
    dt_emissao DATE,
    dt_pagamento DATE,
    arquivo_path VARCHAR(500),
    validada BOOLEAN DEFAULT FALSE,
    obs_validacao TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nf_prestacao ON notas_fiscais(prestacao_id);
CREATE INDEX IF NOT EXISTS idx_nf_plano_item ON notas_fiscais(plano_item_id);
