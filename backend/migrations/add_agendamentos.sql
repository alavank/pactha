-- AGENDAMENTOS: a agenda de trabalho da equipe, por municipio.
--
-- O que a plataforma nao tinha: um lugar para registrar o COMPROMISSO — a visita
-- marcada, a reuniao, o prazo interno — com quem e o responsavel, o que foi
-- feito, e o documento que sobrou daquilo. Tudo o mais aqui e dado que vem de
-- fora; isto e o unico que a equipe escreve.
--
-- Tres visualizacoes da MESMA tabela (decisao do dono, 02/09/2026): LISTA,
-- CALENDARIO e KANBAN. As tres leem estas mesmas linhas — nao ha coluna nem
-- tabela "de calendario". O que o kanban precisa e so o `status`.
--
-- ⚠️ `data` E DATE, E NAO TIMESTAMPTZ — decisao explicita do dono. Agendamento
-- aqui e "no dia 15", nao "as 14h30". A escolha tem consequencia boa e uma
-- ressalva:
--   BOA: DATE nao tem fuso. `2026-09-15` e o dia 15 em Brasilia, em UTC e em
--   qualquer lugar — o container roda em UTC e, com TIMESTAMPTZ, um compromisso
--   das 21h de Brasilia cairia no dia seguinte no calendario. Com DATE isso nao
--   acontece, e o bug de fuso que mordeu o radar hoje nao tem como existir aqui.
--   RESSALVA: nao da para ordenar nem filtrar por hora. Se um dia precisar,
--   e coluna nova (`hora TIME NULL`), e nao troca de tipo desta.
--
-- ⚠️ `status` COM CHECK, e nao texto livre. As tres colunas do kanban sao a
-- razao de existir da coluna; um valor fora da lista nao apareceria em coluna
-- nenhuma e o agendamento sumiria da tela sem erro. O CHECK torna isso
-- impossivel em vez de improvavel. Acrescentar um quarto status e migration
-- nova, de proposito: e mudanca de produto, nao de dado.
--
-- ⚠️ ANEXOS EM JSONB, no MESMO formato do `gestao_anotacoes`
-- ([{nome, mime, dados_b64, tamanho}]). Nao e o formato mais bonito possivel —
-- base64 no banco engorda a linha —, mas e o que este repo ja usa, ja tem
-- limite de tamanho no router, ja tem rota de download com permissao propria e
-- ja tem o cuidado de OMITIR o `dados_b64` na listagem. Inventar um segundo
-- jeito de guardar anexo aqui criaria duas regras de seguranca para o mesmo
-- problema, e a mais nova seria a menos testada.
--
-- ⚠️ AS CHAVES ESTRANGEIRAS DIVERGEM DO `gestao_anotacoes` DE PROPOSITO. La
-- `municipio_id` e um INT solto; aqui e FK. O motivo e o filtro: a tela inteira
-- (lista, calendario e kanban) recorta por municipio, e um `municipio_id` que
-- nao existe produz uma linha que NENHUM filtro alcanca — o agendamento fica no
-- banco e some da tela, sem erro em lugar nenhum. Ja nas colunas de usuario o
-- ON DELETE SET NULL e o certo: apagar uma pessoa nao pode apagar o historico
-- do que ela agendou, e "responsavel em branco" e uma informacao honesta.
--
-- Idempotente e aditiva.

CREATE TABLE IF NOT EXISTS agendamentos (
    id              SERIAL PRIMARY KEY,
    municipio_id    INTEGER NOT NULL REFERENCES municipios(id),
    -- Quem VAI FAZER. Separado de `criado_por` (quem registrou): a secretaria
    -- marca a visita do tecnico, e as duas informacoes sao diferentes.
    responsavel_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    -- O rotulo curto. O calendario e o kanban mostram cartoes pequenos, e o
    -- `relato` pode ter paragrafos — sem um titulo proprio, a celula do dia 15
    -- exibiria as primeiras palavras de um texto corrido.
    titulo          VARCHAR(200) NOT NULL,
    relato          TEXT,
    data            DATE NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'a_fazer'
                    CHECK (status IN ('a_fazer', 'em_andamento', 'realizado')),
    anexos          JSONB NOT NULL DEFAULT '[]'::jsonb,
    criado_por      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- A consulta da LISTA e do CALENDARIO: "os agendamentos deste municipio, neste
-- periodo". Municipio primeiro porque e o recorte que sempre existe; a data
-- vem depois e serve tanto ao BETWEEN do mes quanto a ordenacao.
CREATE INDEX IF NOT EXISTS idx_agend_mun_data ON agendamentos (municipio_id, data);

-- A consulta do calendario de QUEM VE VARIOS MUNICIPIOS (a carteira do freitas
-- tem 42 ativos): o mes inteiro, sem recorte de municipio.
CREATE INDEX IF NOT EXISTS idx_agend_data ON agendamentos (data);

-- O KANBAN le por status dentro do municipio.
CREATE INDEX IF NOT EXISTS idx_agend_status ON agendamentos (municipio_id, status);

-- "Os meus": o filtro por responsavel, que e o segundo mais usado depois do
-- municipio numa agenda de equipe.
CREATE INDEX IF NOT EXISTS idx_agend_resp ON agendamentos (responsavel_id);
