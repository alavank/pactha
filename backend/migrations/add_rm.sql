-- Relatorio de Monitoramento (RM) — padrao Freitas.
-- Um RM por municipio + data_referencia. Conteudo (partes/secoes/grupos/itens)
-- guardado em JSONB pra flexibilidade total de edicao.
CREATE TABLE IF NOT EXISTS rm_relatorios (
    id              SERIAL PRIMARY KEY,
    municipio_id    INT NOT NULL,
    data_referencia DATE NOT NULL,
    cidade_emissao  TEXT NOT NULL DEFAULT 'Brasília/DF',
    titulo          TEXT,                    -- opcional override do titulo
    rodape          TEXT NOT NULL DEFAULT 'Setor SHS Quadra 6, Conjunto A, Bloco E, Sala 624, Asa Sul, CEP: 70.316.902, Brasília/DF.',
    status          TEXT NOT NULL DEFAULT 'rascunho',   -- 'rascunho' | 'finalizado'
    conteudo        JSONB NOT NULL DEFAULT '{"partes": []}'::jsonb,
    criado_por      INT,                     -- users.id
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (municipio_id, data_referencia)
);

CREATE INDEX IF NOT EXISTS ix_rm_mun_data ON rm_relatorios (municipio_id, data_referencia DESC);
