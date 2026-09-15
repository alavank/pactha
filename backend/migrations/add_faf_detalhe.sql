-- FUNDO A FUNDO pela API oficial INTEIRA (15/09/2026): a arvore de cada plano de
-- acao, as contas com extrato, os beneficiarios de programa e o catalogo de
-- programas de `api-publica.transferegov.gestao.gov.br/fundoafundo`.
--
-- Tudo isto so aparecia no modulo Fundo a Fundo do Transferegov para quem entrava
-- LOGADO como o ente: metas e acoes, parecer do ministerio, historico, termo de
-- adesao, conta, extrato, pagamentos a beneficiarios e o relatorio de gestao com o
-- percentual de execucao fisica por acao. A API publica abriu.
--
-- `detalhe` guarda, por plano, as rotas penduradas nele (resposta CRUA da fonte,
-- pelos nomes que ela manda) mais um `_resumo` calculado pelo coletor
-- (`ingestion/faf_planos.resumo_do_plano`). Mesmo desenho de
-- `parcerias_propostas.detalhe` (add_parcerias_detalhe.sql).
--
-- ⚠️ NULO SIGNIFICA "AINDA NAO COLHIDO", nunca "o plano nao tem nada". O coletor
-- so grava arvore completa: consulta sem resposta = nada gravado.
ALTER TABLE faf_planos_acao
    ADD COLUMN IF NOT EXISTS detalhe               JSONB,
    ADD COLUMN IF NOT EXISTS detalhe_atualizado_em TIMESTAMPTZ;

-- A fila da arvore: os mais velhos primeiro.
CREATE INDEX IF NOT EXISTS ix_faf_planos_acao_detalhe_fila
    ON faf_planos_acao (detalhe_atualizado_em NULLS FIRST);

-- AS CONTAS, uma linha por conta — e NAO dentro do plano.
--
-- ⚠️ A MESMA CONTA SERVE A VARIOS PLANOS. Medido em 15/09/2026: em Goiania, cinco
-- planos (6811, 6954, 8691, 14779, 14876) dividem as contas 1126-8216 e 1126-8217.
-- Guardar o extrato dentro de cada plano repetiria a busca e o dado cinco vezes, e
-- somar o saldo por plano DOBRARIA o dinheiro do municipio. Aqui a conta e uma so,
-- e `planos` diz quem a usa.
--
-- `saldo_final` e o saldo que a FONTE informa (`saldo_final_dado_bancario`). Nao
-- se deriva do extrato: credito menos debito da ZERO na conta corrente, porque o
-- dinheiro vai para a aplicacao automatica.
--
-- `lancamentos` e o extrato inteiro, com as subtransacoes (quem recebeu: nome,
-- CPF mascarado pela fonte, valor, categoria) aninhadas no lancamento. `cabecalho`
-- recebe os campos que se repetem em TODOS os lancamentos da conta (ente, banco,
-- agencia, programa agil): nada se perde, e o JSON encolhe.
CREATE TABLE IF NOT EXISTS faf_contas (
    id                  BIGSERIAL PRIMARY KEY,
    municipio_id        INTEGER NOT NULL REFERENCES municipios(id),
    id_agencia_conta    TEXT NOT NULL,
    codigo_banco        TEXT,
    nome_banco          TEXT,
    agencia             TEXT,
    dv_agencia          TEXT,
    conta               TEXT,
    dv_conta            TEXT,
    situacao            TEXT,
    data_abertura       DATE,
    programa_agil       TEXT,
    saldo_final         NUMERIC(18, 2),
    planos              TEXT[] NOT NULL DEFAULT '{}',
    cabecalho           JSONB,
    lancamentos         JSONB,
    resumo              JSONB,
    n_lancamentos       INTEGER,
    ultimo_lancamento   DATE,
    atualizado_em       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_faf_contas
    ON faf_contas (municipio_id, id_agencia_conta);
CREATE INDEX IF NOT EXISTS ix_faf_contas_planos
    ON faf_contas USING GIN (planos);

-- BENEFICIARIOS DE PROGRAMA (`/programas-beneficiarios`): quanto cada programa
-- DESTINA ao municipio — com plano de acao enviado ou nao. A consulta ja era feita
-- desde 07/09 (so para achar os CNPJs) e a resposta ia fora. E a pergunta "tem
-- dinheiro reservado para nos que ainda nao pedimos?".
--
-- So entra ente MUNICIPAL (ver `ingestion/faf_planos.ente_municipal`): a consulta
-- por IBGE da capital devolve tambem o Estado e as secretarias estaduais.
-- O coletor troca o conjunto do municipio quando a consulta volta completa.
CREATE TABLE IF NOT EXISTS faf_programas_beneficiarios (
    id                      BIGSERIAL PRIMARY KEY,
    municipio_id            INTEGER NOT NULL REFERENCES municipios(id),
    id_beneficiario_programa BIGINT NOT NULL,
    id_programa             BIGINT,
    cnpj_beneficiario       VARCHAR(14),
    nome_beneficiario       TEXT,
    nome_ente               TEXT,
    tipo_beneficiario       TEXT,
    valor                   NUMERIC(18, 2),
    numero_emenda           TEXT,
    parlamentar             TEXT,
    raw_data                JSONB,
    atualizado_em           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_faf_programas_beneficiarios
    ON faf_programas_beneficiarios (municipio_id, id_beneficiario_programa);

-- CATALOGO NACIONAL DE PROGRAMAS (125 em 15/09/2026), com o programa da Gestao
-- Agil (a conta BB) aninhado. As seis datas sao a JANELA em que o ente pode enviar
-- o plano de acao — por tipo de beneficiario (especifico, emenda, voluntario).
CREATE TABLE IF NOT EXISTS faf_programas (
    id_programa             BIGINT PRIMARY KEY,
    ano                     INTEGER,
    codigo                  TEXT,
    nome                    TEXT,
    modalidade              TEXT,
    situacao                TEXT,
    sigla_orgao             TEXT,
    nome_orgao              TEXT,
    nome_fundo              TEXT,
    valor_global            NUMERIC(18, 2),
    janela_especificos_ini  DATE,
    janela_especificos_fim  DATE,
    janela_emendas_ini      DATE,
    janela_emendas_fim      DATE,
    janela_voluntarios_ini  DATE,
    janela_voluntarios_fim  DATE,
    gestao_agil             JSONB,
    raw_data                JSONB,
    atualizado_em           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
