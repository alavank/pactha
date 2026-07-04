-- CAUC — Servico Auxiliar de Informacoes para Transferencias Voluntarias (STN).
-- Regularidade fiscal FEDERAL do municipio (libera/trava transferencias voluntarias).
-- Fonte: dados abertos CKAN do Tesouro (CSV "situacao dos municipios no CAUC"),
-- atualizado diariamente. Casado por IBGE com nossos municipios.
-- 1 linha por municipio (snapshot mais recente).
CREATE TABLE IF NOT EXISTS cauc_situacao (
    municipio_id        INT PRIMARY KEY REFERENCES municipios(id),
    ibge                VARCHAR(7),
    nome                TEXT,
    uf                  VARCHAR(2),
    cod_siafi           VARCHAR(10),
    populacao           INT,
    data_pesquisa       DATE,
    itens               JSONB,        -- {"1.1":"08/12/26","1.2":"!","1.3":"Desabilitado",...}
    pendencias          INT DEFAULT 0, -- qtd de exigencias com "!" (irregular/impeditivo)
    pendencias_codigos  TEXT[],        -- ["1.2","3.2.4"]
    regular             BOOLEAN,       -- pendencias = 0
    atualizado_em       TIMESTAMPTZ DEFAULT NOW()
);
