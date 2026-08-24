-- CONFIGURACOES DO TENANT — um VALOR por CHAVE, editavel pela TELA.
--
-- Pedido do dono: "coloque um campo digitavel mas que grave padrao para o
-- rodape". Ate aqui o rodape do RM so existia em `RM_RODAPE` (backend/config.py),
-- variavel de ambiente: mudar exige redeploy — e sao QUATRO tenants.
--
-- ⚠️ POR QUE NAO REUSAR `parametros` (a unica tabela de "configuracao" que
-- existe). Aquela e uma LISTA DE OPCOES: (tipo, valor, rotulo), onde `valor` e a
-- CHAVE imutavel e `rotulo` e o texto de tela — ver o cabecalho de
-- add_parametros.sql. Guardar o endereco do rodape em `rotulo` seria mentir
-- sobre a coluna; e o CRUD generico de /api/parametros deriva a chave do texto
-- digitado (routers/parametros.py::_chave_de), recusa duplicata por
-- (tipo, valor) e oferece "desativar"/"excluir" — operacoes que nao existem para
-- um escalar. ESCALAR e LISTA sao formas diferentes; forcar uma na outra
-- deixaria a tela de Parametros oferecendo "adicionar outro rodape".
--
-- ⚠️ SEM `tenant_id`, pela mesma razao de `parametros`: o PACTHA e single-tenant
-- (um banco, um container e uma imagem por cliente). Coluna de tenant aqui seria
-- promessa de multi-tenancy que o resto do sistema nao cumpre.
--
-- ⚠️ SEM SEMENTE, DE PROPOSITO. Linha AUSENTE significa "ninguem salvou, usa a
-- env" — a precedencia esta escrita em services/rm_config.py. Semear com o valor
-- de RM_RODAPE congelaria no banco o endereco que hoje esta no ambiente, e um
-- tenant que amanha subisse com outra env continuaria imprimindo o antigo,
-- calado. E o mesmo defeito que add_rm.sql ja teve com DEFAULT.
--
-- ⚠️ ESTE ARQUIVO RODA A CADA BOOT (o runner de services/startup.py nao guarda
-- "ja aplicada"), entao tudo aqui e IF NOT EXISTS.
CREATE TABLE IF NOT EXISTS configuracoes (
    -- A chave, no formato `modulo.assunto` (hoje so `rm.rodape`).
    chave          TEXT PRIMARY KEY,
    -- ⚠️ NOT NULL DEFAULT '': string VAZIA e valor legitimo, e significa "o dono
    -- apagou o rodape e quer pagina sem rodape". Quem le distingue "linha nao
    -- existe" (usa a env) de "linha existe e esta vazia" (respeita o vazio).
    valor          TEXT NOT NULL DEFAULT '',
    atualizado_em  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_por INTEGER REFERENCES users(id) ON DELETE SET NULL
);
