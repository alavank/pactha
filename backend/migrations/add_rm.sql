-- Relatorio de Monitoramento (RM). O desenho nasceu do padrao Freitas.
-- Um RM por municipio + data_referencia. Conteudo (partes/secoes/grupos/itens)
-- guardado em JSONB pra flexibilidade total de edicao.
--
-- ⚠️ NADA DE DADO DE CLIENTE EM DEFAULT. `cidade_emissao` e `rodape` nasciam
-- com 'Brasília/DF' e com o endereco do escritorio da Freitas. Como o INSERT de
-- criacao nao passava `rodape`, o DEFAULT era aplicado e o endereco daquela
-- empresa saia impresso no rodape de TODA pagina do relatorio oficial de
-- QUALQUER cliente — inclusive de municipio de Minas, carimbado "Brasília/DF".
-- Agora: `cidade_emissao` e derivada do proprio municipio do RM (routers/rm.py)
-- e o rodape vem de `RM_RODAPE` no ambiente do tenant.
CREATE TABLE IF NOT EXISTS rm_relatorios (
    id              SERIAL PRIMARY KEY,
    municipio_id    INT NOT NULL,
    data_referencia DATE NOT NULL,
    cidade_emissao  TEXT NOT NULL DEFAULT '',
    titulo          TEXT,                    -- opcional override do titulo
    rodape          TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'rascunho',   -- 'rascunho' | 'finalizado'
    conteudo        JSONB NOT NULL DEFAULT '{"partes": []}'::jsonb,
    criado_por      INT,                     -- users.id
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (municipio_id, data_referencia)
);

-- `CREATE TABLE IF NOT EXISTS` NAO reescreve o DEFAULT de tabela que ja existe.
-- Sem estes dois ALTER, todo tenant ja instalado continuaria gravando o
-- endereco da Freitas em cada RM novo. Nao mexe em NENHUMA linha existente: RM
-- ja emitido preserva o que tem.
ALTER TABLE rm_relatorios ALTER COLUMN cidade_emissao SET DEFAULT '';
ALTER TABLE rm_relatorios ALTER COLUMN rodape         SET DEFAULT '';

CREATE INDEX IF NOT EXISTS ix_rm_mun_data ON rm_relatorios (municipio_id, data_referencia DESC);
