-- CAGEC — Cadastro Geral de Convenentes de Minas Gerais (SIGCON-MG).
-- Regularidade ESTADUAL: o par mineiro do CAUC federal. Sem CAGEC valido o
-- municipio nao assina convenio com o Estado.
--
-- ESTADO: a tabela existe e o endpoint responde, mas NENHUM SCRAPER ALIMENTA
-- ISTO AINDA. Falta a credencial do SIGCON-MG (uma por municipio, guardada no
-- Cofre com sistema='SIGCON-MG', que o sigcon_scraper.py ja usa para os
-- convenios). Enquanto nao houver linha, a API devolve `tem_dados: false` e a
-- tela mostra "aguardando coleta" — nunca um verde, que seria lido como
-- "regularidade estadual em dia".
--
-- ESPELHA cauc_situacao de proposito: mesma forma de payload => o mesmo
-- componente desenha as duas colunas, e ligar a coleta depois nao mexe na tela.
-- 1 linha por municipio (snapshot mais recente).
CREATE TABLE IF NOT EXISTS cagec_situacao (
    municipio_id        INT PRIMARY KEY REFERENCES municipios(id),
    nome                TEXT,
    uf                  VARCHAR(2),
    cnpj                VARCHAR(20),
    -- Rotulo cru do portal ("Regular", "Bloqueado", "Vencido"...). Guardado
    -- como texto porque o vocabulario do SIGCON ainda nao foi observado; quando
    -- for, normalizamos em cima disto sem perder o original.
    situacao            TEXT,
    regular             BOOLEAN,
    validade            DATE,          -- validade do certificado CAGEC
    -- Lista de exigencias/bloqueios no MESMO formato do CAUC:
    -- [{"codigo","grupo","label","valor","tipo","status"}]
    -- `tipo` in ('regular','pendente','na'). JSONB para absorver o que o portal
    -- expuser sem migration nova a cada campo descoberto.
    itens               JSONB,
    pendencias          INT DEFAULT 0,
    pendencias_codigos  TEXT[],
    data_pesquisa       DATE,
    atualizado_em       TIMESTAMPTZ DEFAULT NOW()
);
