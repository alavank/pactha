"""O ALCANCE POR LINHA — "so os registros que ele criou".

A regra do dono, palavra por palavra: "o sistema valida se o ID do usuario
logado e o mesmo criador do registro. Se for, ele deixa editar; se nao for, o
botao some ou fica bloqueado. (...) isso aconteceria POR MODULO".

⚠️ OS TESTES QUE MAIS IMPORTAM AQUI NAO SAO OS QUE PROVAM QUE A TRAVA BARRA.
Sao os que provam que ela NAO barra quem nunca foi restringido:

  * usuario sem configuracao nenhuma tem alcance `todos` e a checagem nem
    ENCOSTA no banco (o custo do incremento so existe para quem foi
    deliberadamente restringido);
  * linha com `criado_por` NULO passa — registro anterior a coluna, ou de conta
    ja excluida. Negar trancaria anos de trabalho e o registro de quem saiu da
    prefeitura, que e exatamente o dano que o dono ja recusou uma camada acima
    quando vetou filtrar a leitura;
  * em `AUTHZ_MODO=aviso` nada levanta, como em todo o resto do modulo;
  * a lista NAO esconde botao por falta de permissao de verbo enquanto o modo
    for aviso — se escondesse, esta peca teria provocado sozinha o apagao que o
    modo aviso inteiro existe para evitar.

Rodar:
    python -m pytest backend/tests/test_escopo_linha.py -v
"""
import asyncio
import inspect
from datetime import date

import pytest
from fastapi import HTTPException

from routers import documentos, gestao, rm
from services import authz, permissoes

MODOS = ["aviso", "bloqueio"]
MSG = "Voce so pode alterar os registros que voce mesmo criou"


class Usuario:
    """O que o codigo real le do User depois de `load_user_scopes`."""

    def __init__(self, id=7, escopos=None, permissoes_=None, super_admin=False,
                 email="servidor@montesiao.mg.gov.br", name="Servidor"):
        self.id = id
        self.email = email
        self.name = name
        self.role = "usuario"
        self.active = True
        self.super_admin = super_admin
        self.somente_leitura = False
        self.kiosk = False
        self.allowed_telas = {"gestao", "rm", "documentos"}
        self.allowed_municipio_ids = {99}
        self.allowed_permissoes = permissoes_ if permissoes_ is not None else []
        self.allowed_escopos = escopos or {}


class _Res:
    def __init__(self, valor=None):
        self._valor = valor

    def first(self):
        return self._valor

    def fetchall(self):
        return self._valor or []


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeDb:
    """Guarda o SQL que passou por ela — e o que permite afirmar "a checagem nem
    encostou no banco" e "leu a tabela do catalogo, nao outra"."""

    def __init__(self, respostas=(), explode=False):
        self.respostas = list(respostas)
        self.sql: list = []
        self.explode = explode

    def begin_nested(self):
        return _Savepoint()

    async def execute(self, stmt, params=None):
        self.sql.append(" ".join(str(stmt).split()))
        if self.explode:
            raise RuntimeError("tabela sumiu")
        return self.respostas.pop(0) if self.respostas else _Res(None)

    async def commit(self):
        pass


@pytest.fixture(autouse=True)
def _isolar(monkeypatch):
    authz.limpar_dedupe()
    authz.limpar_contexto()
    monkeypatch.delenv("AUTHZ_MODO", raising=False)
    yield
    authz.limpar_dedupe()
    authz.limpar_contexto()


@pytest.fixture(autouse=True)
def envios(monkeypatch):
    """Intercepta o agendamento da trilha: sem isto o teste abriria sessao de
    banco de verdade numa tarefa de fundo. Autouse de proposito."""
    registrados: list = []
    monkeypatch.setattr(authz, "_enviar", lambda dados: registrados.append(dados) or True)
    return registrados


def _acoes(registrados):
    return [d["acao"] for d in registrados]


# ===========================================================================
# 1. `escopo_de` — quem esta restrito, e quem NAO esta
# ===========================================================================
def test_sem_configuracao_o_alcance_e_todos():
    """O default nao pode restringir ninguem: e a promessa do deploy."""
    assert authz.escopo_de(Usuario(), "gestao") == permissoes.ESCOPO_TODOS


def test_usuario_sem_o_atributo_carregado_tambem_e_todos():
    """Objeto parcial (teste, snapshot, canal de integracao) nao pode virar
    restricao — restringir e ato deliberado do administrador."""
    class Parcial:
        id = 7

    assert authz.escopo_de(Parcial(), "gestao") == permissoes.ESCOPO_TODOS


def test_o_alcance_configurado_vale():
    u = Usuario(escopos={"gestao": "proprios"})
    assert authz.escopo_de(u, "gestao") == permissoes.ESCOPO_PROPRIOS


def test_o_alcance_e_por_modulo():
    """A regra do dono: "algum usuario pode ter acesso de editar em um modulo
    mas em outro ele so pode ver"."""
    u = Usuario(escopos={"gestao": "proprios"})
    assert authz.escopo_de(u, "gestao") == permissoes.ESCOPO_PROPRIOS
    assert authz.escopo_de(u, "rm") == permissoes.ESCOPO_TODOS
    assert authz.escopo_de(u, "documentos") == permissoes.ESCOPO_TODOS


@pytest.mark.parametrize("lixo", ["proprio", "PROPRIOS ", "", None, "1", "todos"])
def test_valor_torto_no_banco_nao_restringe(lixo):
    """Fail-OPEN, e e a mesma escolha de `authz.modo`: dado sujo nao pode tirar
    de alguem a edicao que ele sempre teve. `PROPRIOS ` com espaco e maiuscula E
    normalizado (e o mesmo valor); o resto cai em `todos`."""
    u = Usuario(escopos={"gestao": lixo})
    esperado = (permissoes.ESCOPO_PROPRIOS if str(lixo or "").strip().lower()
                == "proprios" else permissoes.ESCOPO_TODOS)
    assert authz.escopo_de(u, "gestao") == esperado


def test_super_admin_passa_por_cima():
    """"Esses tem tudo, fazem tudo no sistema... eles sao tipo ROOT"."""
    u = Usuario(super_admin=True, escopos={"gestao": "proprios"})
    assert authz.escopo_de(u, "gestao") == permissoes.ESCOPO_TODOS


def test_modulo_que_nao_aceita_alcance_e_sempre_todos():
    u = Usuario(escopos={"cofre": "proprios"})
    assert authz.escopo_de(u, "cofre") == permissoes.ESCOPO_TODOS


# ===========================================================================
# 2. ⭐ `exigir_dono_da_linha` — o custo zero de quem nao foi restringido
# ===========================================================================
def test_alcance_todos_nem_encosta_no_banco():
    """O caminho de todo mundo, hoje. Se esta checagem consultasse o banco em
    toda edicao, o incremento cobraria de quem nunca foi restringido."""
    db = FakeDb()
    resultado = asyncio.run(
        authz.exigir_dono_da_linha(db, "gestao", 42, Usuario()))
    assert resultado is None
    assert db.sql == []


@pytest.mark.parametrize("modo_env", MODOS)
def test_o_criador_edita_o_proprio_registro(monkeypatch, envios, modo_env):
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    db = FakeDb([_Res((7,))])
    u = Usuario(id=7, escopos={"gestao": "proprios"})
    assert asyncio.run(authz.exigir_dono_da_linha(db, "gestao", 42, u)) == 7
    assert envios == [], "editar o proprio registro nao e evento de auditoria"


def test_le_a_tabela_e_a_coluna_do_catalogo():
    """A tabela sai de `ESCOPO_RECURSOS`, e nao de um literal do router: uma
    copia divergente e uma checagem que deixa de checar sem ninguem notar."""
    db = FakeDb([_Res((7,))])
    asyncio.run(authz.exigir_dono_da_linha(
        db, "gestao", 42, Usuario(escopos={"gestao": "proprios"})))
    assert "SELECT criado_por FROM gestao_anotacoes WHERE id = :id" in db.sql[0]


@pytest.mark.parametrize("bruto", [7, "7"])
def test_compara_por_inteiro_e_nao_por_tipo(bruto):
    """`criado_por` vem do banco e `usuario.id` do ORM. Comparar `==` cru faria
    `'7' != 7` e negaria o autor do proprio registro."""
    db = FakeDb([_Res((bruto,))])
    u = Usuario(id=7, escopos={"gestao": "proprios"})
    assert asyncio.run(authz.exigir_dono_da_linha(db, "gestao", 42, u)) == bruto


def test_em_aviso_o_registro_de_outra_pessoa_passa_e_vira_linha(monkeypatch, envios):
    """Modo aviso = comportamento identico ao de hoje, mais uma linha na trilha.
    Nenhuma excecao nova sai daqui."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    db = FakeDb([_Res((99,))])
    u = Usuario(id=7, escopos={"gestao": "proprios"})
    assert asyncio.run(authz.exigir_dono_da_linha(db, "gestao", 42, u)) == 99
    assert _acoes(envios) == [authz.ACAO_NEGARIA]
    assert envios[0]["tipo"] == "linha_propria"


def test_em_bloqueio_o_registro_de_outra_pessoa_e_negado(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    db = FakeDb([_Res((99,))])
    u = Usuario(id=7, escopos={"gestao": "proprios"})
    with pytest.raises(HTTPException) as e:
        asyncio.run(authz.exigir_dono_da_linha(db, "gestao", 42, u))
    assert e.value.status_code == 403
    assert e.value.detail == MSG
    assert _acoes(envios) == [authz.ACAO_NEGOU]


def test_a_mensagem_nao_e_a_de_permissao():
    """Quem le "Voce nao tem permissao para esta acao" depois de clicar em
    Editar vai pedir ao administrador a caixinha «Editar» — que ele JA TEM. O
    que falta nao e a caixinha, e o alcance."""
    assert "voce mesmo criou" in MSG
    assert MSG != "Voce nao tem permissao para esta acao"


def test_a_trilha_diz_de_quem_era_a_linha(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    db = FakeDb([_Res((99,))])
    u = Usuario(id=7, escopos={"gestao": "proprios"})
    with pytest.raises(HTTPException):
        asyncio.run(authz.exigir_dono_da_linha(db, "gestao", 42, u))
    detalhes = envios[0]["detalhes"]
    assert detalhes["origem"]["recurso"] == "gestao"
    assert detalhes["origem"]["criado_por"] == 99
    assert detalhes["possui"] == {"usuario_id": 7, "criado_por": 99}


# ===========================================================================
# 3. ⭐⭐ A DECISAO DIFICIL: linha sem criador conhecido
# ===========================================================================
@pytest.mark.parametrize("modo_env", MODOS)
def test_linha_sem_criador_passa_nos_dois_modos(monkeypatch, envios, modo_env):
    """⚠️ A decisao, e ela e deliberada: `criado_por` NULO **PASSA**.

    Linha sem criador e (1) anterior a coluna — as tres tabelas nasceram com ela
    anulavel e sem backfill — ou (2) de conta EXCLUIDA, porque a FK zera a
    coluna. Negar seria retroativo num sistema em que a restricao nao e, e
    trancaria para sempre o registro de quem saiu da prefeitura: exatamente o
    dano que o dono ja recusou quando vetou filtrar a leitura."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    db = FakeDb([_Res((None,))])
    u = Usuario(id=7, escopos={"gestao": "proprios"})
    assert asyncio.run(authz.exigir_dono_da_linha(db, "gestao", 42, u)) is None
    assert _acoes(envios) == [authz.ACAO_SEM_CRIADOR], \
        "a passagem tem de ser VISIVEL: e ela que mede o tamanho do vao"


def test_a_passagem_sem_criador_nao_e_uma_negativa(monkeypatch, envios):
    """Ela nao pode aparecer como `authz.negou`: nao houve negativa, e contar
    uma passagem como barreira faria a semana de observacao mentir."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    db = FakeDb([_Res((None,))])
    asyncio.run(authz.exigir_dono_da_linha(
        db, "gestao", 42, Usuario(escopos={"gestao": "proprios"})))
    assert authz.ACAO_NEGOU not in _acoes(envios)


def test_a_acao_sem_criador_tem_rotulo_na_auditoria():
    from services import audit_catalog

    acao = audit_catalog.descrever_acao(authz.ACAO_SEM_CRIADOR)
    assert acao.conhecida, "sairia com rotulo derivado, com cara de rotina"
    assert acao.nota and "criador em branco" in acao.nota


# ===========================================================================
# 4. Os casos em que nao ha decisao a tomar
# ===========================================================================
@pytest.mark.parametrize("modo_env", MODOS)
def test_registro_inexistente_nao_vira_403(monkeypatch, envios, modo_env):
    """Quem decide o 404 e o endpoint — o unico que sabe se "nao achei" e "nao
    existe" ou "nao e seu". Mesma regra de `ensure_dono`."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    db = FakeDb([_Res(None)])
    u = Usuario(escopos={"gestao": "proprios"})
    assert asyncio.run(authz.exigir_dono_da_linha(db, "gestao", 999, u)) is None
    assert envios == []


@pytest.mark.parametrize("modo_env", MODOS)
def test_falha_de_leitura_nao_inventa_negativa(monkeypatch, modo_env):
    """Sem leitura nao ha decisao. Inventar 403 aqui seria negativa nova — o
    endpoint vai esbarrar no mesmo problema na consulta dele, em seguida."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    db = FakeDb(explode=True)
    u = Usuario(escopos={"gestao": "proprios"})
    assert asyncio.run(authz.exigir_dono_da_linha(db, "gestao", 42, u)) is None


def test_id_nulo_nao_consulta_nada():
    db = FakeDb()
    u = Usuario(escopos={"gestao": "proprios"})
    assert asyncio.run(authz.exigir_dono_da_linha(db, "gestao", None, u)) is None
    assert db.sql == []


def test_recurso_desconhecido_levanta_value_error():
    """ValueError e nao 403, pelo mesmo motivo de `exigir` com chave fora do
    catalogo: e erro de programacao num literal do router. Tratado como "sem
    permissao" viraria um 403 permanente e silencioso."""
    with pytest.raises(ValueError):
        asyncio.run(authz.exigir_dono_da_linha(
            FakeDb(), "cofre", 42, Usuario(escopos={"gestao": "proprios"})))


# ===========================================================================
# 5. ⭐ O BOTAO DA LISTA — e o apagao que ele NAO pode causar
# ===========================================================================
COM_ESCRITA = ["gestao.editar", "gestao.excluir"]


def test_em_aviso_a_falta_de_permissao_nao_esconde_o_botao(monkeypatch):
    """⚠️ O TESTE MAIS IMPORTANTE DESTE ARQUIVO.

    Em modo aviso o servidor NAO barra quem nao tem `gestao.editar` — registra e
    deixa passar. Uma conta que trabalha hoje justamente porque nunca houve gate
    continua trabalhando. Se a LISTA escondesse o botao dela agora, esta peca
    teria provocado sozinha o apagao que o modo aviso inteiro existe para
    evitar — e sem mudar o servidor, que e a pior forma de quebrar: ninguem
    procuraria a causa numa resposta de listagem."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    sem_permissao = Usuario(id=7, permissoes_=[])
    assert authz.pode_editar_item(sem_permissao, "gestao", "editar", 99) is True


def test_em_bloqueio_a_falta_de_permissao_esconde_o_botao(monkeypatch):
    """Ai sim: o servidor barra de verdade, e desenhar um botao que devolve 403
    e pior do que nao desenhar."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    sem_permissao = Usuario(id=7, permissoes_=[])
    assert authz.pode_editar_item(sem_permissao, "gestao", "editar", 99) is False


@pytest.mark.parametrize("modo_env", MODOS)
def test_o_alcance_esconde_o_botao_nos_dois_modos(monkeypatch, modo_env):
    """O alcance NUNCA e retroativo: nasce `todos` para todo mundo e so vira
    `proprios` quando um administrador marca aquele radio, para aquela pessoa,
    naquele modulo. Nao ha comportamento antigo a preservar — entao o botao some
    no instante em que a configuracao e salva, que e o que o dono pediu ver."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    u = Usuario(id=7, permissoes_=COM_ESCRITA, escopos={"gestao": "proprios"})
    assert authz.pode_editar_item(u, "gestao", "editar", 7) is True
    assert authz.pode_editar_item(u, "gestao", "editar", 99) is False


@pytest.mark.parametrize("modo_env", MODOS)
def test_a_lista_deixa_o_botao_na_linha_sem_criador(monkeypatch, modo_env):
    """A tela tem de desenhar o botao que o servidor vai deixar clicar. Se a
    lista escondesse o que `exigir_dono_da_linha` deixa passar, os dois
    discordariam — e o servidor e quem manda."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    u = Usuario(id=7, permissoes_=COM_ESCRITA, escopos={"gestao": "proprios"})
    assert authz.pode_editar_item(u, "gestao", "editar", None) is True


def test_editar_e_excluir_sao_perguntas_SEPARADAS(monkeypatch):
    """Uma flag so desenharia o botao errado: da para ter «Editar» sem «Excluir»."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    u = Usuario(id=7, permissoes_=["gestao.editar"])
    assert authz.pode_editar_item(u, "gestao", "editar", 7) is True
    assert authz.pode_editar_item(u, "gestao", "excluir", 7) is False


def test_pode_escrever_na_linha_nao_tem_efeito_nenhum(envios):
    """E chamada uma vez POR ITEM da lista: nao pode registrar nada (afogaria a
    trilha) nem levantar (derrubaria a listagem inteira por uma linha)."""
    u = Usuario(id=7, escopos={"gestao": "proprios"})
    assert authz.pode_escrever_na_linha(u, "gestao", 99) is False
    assert envios == []


# ===========================================================================
# 6. A APLICACAO nos tres modulos
# ===========================================================================
ESCRITA = [
    (rm._exigir_escrita, "rm"),
    (documentos._exigir_escrita, "documentos"),
    (gestao._exigir_escrita, "gestao"),
]


@pytest.mark.parametrize("helper,recurso", ESCRITA,
                         ids=[r for _, r in ESCRITA])
def test_o_helper_de_escrita_cobra_o_alcance(helper, recurso):
    fonte = inspect.getsource(helper)
    assert "exigir_dono_da_linha(" in fonte
    assert f'"{recurso}"' in fonte


@pytest.mark.parametrize("funcao,nome", [
    (rm.atualizar, "rm.PUT"), (rm.repopular, "rm.auto-popular"),
    (rm.remover, "rm.DELETE"),
    (documentos.atualizar, "documentos.PUT"), (documentos.remover, "documentos.DELETE"),
    (gestao.atualizar, "gestao.PUT"), (gestao.remover, "gestao.DELETE"),
], ids=lambda v: v if isinstance(v, str) else "")
def test_todo_endpoint_de_escrita_passa_pelo_alcance(funcao, nome):
    """Os SETE endpoints que alteram linha nos tres modulos com CRUD."""
    assert "_exigir_escrita(" in inspect.getsource(funcao), nome


@pytest.mark.parametrize("funcao,nome", [
    (rm.detalhe, "rm.detalhe"), (rm.pdf, "rm.pdf"), (rm.listar, "rm.listar"),
    (documentos.detalhe, "documentos.detalhe"),
    (documentos.exportar, "documentos.export"),
    (documentos.listar, "documentos.listar"),
    (gestao.detalhe, "gestao.detalhe"), (gestao.listar, "gestao.listar"),
    (gestao.download_anexo, "gestao.anexo"),
], ids=lambda v: v if isinstance(v, str) else "")
def test_leitura_e_exportacao_NAO_sao_escopadas(funcao, nome):
    """⭐ A decisao do dono, e ela e o coracao do desenho: o escopo vale SO PARA
    ESCRITA. Filtrar tambem a leitura foi RECUSADO — dois servidores do mesmo
    setor deixariam de ver o trabalho um do outro, e o registro de quem saiu da
    prefeitura sumiria da tela."""
    fonte = inspect.getsource(funcao)
    assert "_exigir_escrita(" not in fonte, nome
    assert "exigir_dono_da_linha(" not in fonte, nome


@pytest.mark.parametrize("funcao,nome", [
    (documentos.criar, "documentos.criar"), (gestao.criar, "gestao.criar"),
], ids=lambda v: v if isinstance(v, str) else "")
def test_criar_nao_e_escopado(funcao, nome):
    """Nao ha linha anterior de quem julgar o dono: o registro nasce dele.

    ⚠️ `rm.criar` NAO esta nesta lista, e a excecao e o assunto do teste abaixo:
    o INSERT dele e um UPSERT. Estes dois sao INSERT puro — o teste guarda essa
    diferenca, porque o dia em que um deles ganhar um `ON CONFLICT` a frase
    "criar nao e escopado" deixa de ser verdade sem ninguem notar."""
    fonte = inspect.getsource(funcao)
    assert "exigir_dono_da_linha(" not in fonte, nome
    assert "ON CONFLICT" not in fonte, f"{nome} virou UPSERT: agora ele ESCREVE em linha alheia"


def test_o_upsert_do_rm_e_escopado():
    """⭐ A PORTA DOS FUNDOS DO RM. `POST /api/rm` nao so cria: o
    `ON CONFLICT (municipio_id, data_referencia) DO UPDATE` sobrescreve o
    relatorio que ja existe naquela data — titulo, cidade, rodape e, com
    `auto_popular`, o conteudo inteiro.

    Sem o gate, quem esta em "somente os que ele criou" levava 403 no PUT do RM
    do colega e apagava o MESMO relatorio pelo POST, com o mesmo corpo. E o
    unico `criar` dos tres modulos que precisa da checagem, e ele precisa
    exatamente porque nem sempre esta criando."""
    fonte = inspect.getsource(rm.criar)
    assert "ON CONFLICT" in fonte and "DO UPDATE" in fonte, (
        "o upsert saiu do endpoint — reveja se o gate abaixo ainda faz sentido")
    assert 'exigir_dono_da_linha(db, "rm"' in fonte
    # So quando a linha JA EXISTE: RM novo nao tem dono anterior de quem julgar,
    # e cobrar alcance ali tiraria a CRIACAO de quem esta restrito.
    assert "if ja_existia:" in fonte


class _ResUpsert(_Res):
    """`_Res` com `.scalar()` — o `RETURNING id` do upsert le por ali."""

    def scalar(self):
        return self._valor[0] if self._valor else None


class _DbUpsert(FakeDb):
    """Responde por CONSULTA, e nao por ordem de chegada: o caminho do 403 faz
    menos consultas que o caminho feliz, e uma fila posicional daria a resposta
    errada para um dos dois."""

    def __init__(self, *, existe: bool, criado_por=None):
        super().__init__()
        self.existe = existe
        self.criado_por = criado_por
        self.escreveu = False

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.sql.append(sql)
        if "SELECT id FROM rm_relatorios" in sql:
            return _ResUpsert((42,) if self.existe else None)
        if "SELECT criado_por FROM rm_relatorios" in sql:
            return _ResUpsert((self.criado_por,))
        if sql.startswith("INSERT INTO rm_relatorios"):
            self.escreveu = True
            return _ResUpsert((42,))
        return _ResUpsert(None)


def _municipio_fake(monkeypatch):
    class _Mun:
        id, nome, uf = 99, "Monte Siao", "MG"

    async def _get(_db, _mid):
        return _Mun()

    monkeypatch.setattr(rm, "_get_municipio", _get)

    async def _nada(*a, **k):
        return None

    monkeypatch.setattr(rm, "registrar", _nada)


def _corpo(auto=True):
    return rm.RmCreate(municipio_id=99, data_referencia=date(2024, 3, 1),
                       titulo="TROCADO POR QUEM NAO E O DONO", auto_popular=auto)


def test_o_upsert_do_rm_nega_o_relatorio_de_outra_pessoa(monkeypatch, envios):
    """A prova pelo COMPORTAMENTO: o POST que cai em cima do RM de outra pessoa
    leva o mesmo 403 do PUT — e o UPDATE nao chega a sair."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    _municipio_fake(monkeypatch)
    db = _DbUpsert(existe=True, criado_por=999)
    u = Usuario(id=7, escopos={"rm": "proprios"},
                permissoes_=["rm.ver", "rm.criar", "rm.editar"])
    with pytest.raises(HTTPException) as erro:
        asyncio.run(rm.criar(_corpo(), None, db, u))
    assert erro.value.status_code == 403
    assert erro.value.detail == MSG
    assert db.escreveu is False, "o UPDATE saiu antes do 403"


def test_o_upsert_do_rm_barra_ANTES_de_remontar_o_conteudo(monkeypatch, envios):
    """`montar_conteudo` varre o banco do municipio inteiro. Em modo bloqueio
    nao ha por que pagar isso para descartar tudo no 403 — e, mais importante,
    o gate tem de estar acima de qualquer preparo da escrita."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    _municipio_fake(monkeypatch)
    chamou = []

    async def _montar(*a, **k):
        chamou.append(True)
        return {"partes": []}

    monkeypatch.setattr(rm, "montar_conteudo", _montar)
    with pytest.raises(HTTPException):
        asyncio.run(rm.criar(_corpo(auto=True), None,
                             _DbUpsert(existe=True, criado_por=999),
                             Usuario(id=7, escopos={"rm": "proprios"},
                                     permissoes_=["rm.criar"])))
    assert chamou == []


def test_o_upsert_do_rm_em_aviso_passa_como_todo_o_resto(monkeypatch, envios):
    """`AUTHZ_MODO=aviso` = comportamento identico ao de hoje, mais uma linha na
    trilha. Este gate nao pode ser o unico do sistema que barra em modo aviso."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    _municipio_fake(monkeypatch)
    db = _DbUpsert(existe=True, criado_por=999)
    u = Usuario(id=7, escopos={"rm": "proprios"}, permissoes_=["rm.criar"])
    assert asyncio.run(rm.criar(_corpo(auto=False), None, db, u))["id"] == 42
    assert db.escreveu is True
    assert _acoes(envios) == [authz.ACAO_NEGARIA]


@pytest.mark.parametrize("rotulo,escopos,existe,criador", [
    ("sem restricao nenhuma, RM que ja existe", {}, True, 999),
    ("restrito, mas o RM e DELE", {"rm": "proprios"}, True, 7),
    ("restrito, RM ainda nao existe", {"rm": "proprios"}, False, None),
    ("restrito, RM sem criador conhecido", {"rm": "proprios"}, True, None),
], ids=lambda v: v if isinstance(v, str) else "")
def test_o_upsert_do_rm_nao_tirou_a_criacao_de_ninguem(
        monkeypatch, envios, rotulo, escopos, existe, criador):
    """A contrapartida obrigatoria do gate novo, e a parte que importa mais: ele
    nao pode custar a criacao de RM a quem quer que seja. O primeiro caso e a
    esmagadora maioria das contas."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    _municipio_fake(monkeypatch)
    db = _DbUpsert(existe=existe, criado_por=criador)
    u = Usuario(id=7, escopos=escopos, permissoes_=["rm.criar"])
    assert asyncio.run(rm.criar(_corpo(auto=False), None, db, u))["id"] == 42, rotulo
    assert db.escreveu is True, rotulo


def test_o_upsert_do_rm_nao_consulta_nada_a_mais_de_quem_nao_foi_restringido(
        monkeypatch, envios):
    """A leitura do dono e a MESMA que ja separava "criou" de "substituiu" na
    trilha (era `SELECT 1`, virou `SELECT id`). Quem esta em `todos` nao paga
    consulta nenhuma pelo incremento."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    _municipio_fake(monkeypatch)
    db = _DbUpsert(existe=True, criado_por=999)
    asyncio.run(rm.criar(_corpo(auto=False), None, db,
                         Usuario(id=7, escopos={}, permissoes_=["rm.criar"])))
    assert not [s for s in db.sql if "SELECT criado_por" in s]


# ===========================================================================
# 7. O QUE A LISTA DEVOLVE — o contrato com o frontend
# ===========================================================================
CAMPOS = ("criado_por", "pode_editar", "pode_excluir")


def test_a_lista_de_gestao_devolve_os_campos_por_item(monkeypatch):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    linha = (1, 99, "sigcon", "ref", "nr", "Em analise", None, None, None,
             "obs", [], 7, None, None)
    u = Usuario(id=7, permissoes_=COM_ESCRITA, escopos={"gestao": "proprios"})
    item = gestao._row_to_dict(linha, u, with_anexos=False)
    assert all(c in item for c in CAMPOS)
    assert item["criado_por"] == 7
    assert item["pode_editar"] is True and item["pode_excluir"] is True

    de_outro = gestao._row_to_dict(linha[:11] + (99,) + linha[12:], u,
                                   with_anexos=False)
    assert de_outro["pode_editar"] is False and de_outro["pode_excluir"] is False


def test_a_lista_de_documentos_devolve_os_campos_por_item(monkeypatch):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    linha = (1, 99, "plano_sustentabilidade", "Titulo", {}, "rascunho", 7,
             None, None)
    u = Usuario(id=7, permissoes_=["documentos.editar", "documentos.excluir"],
                escopos={"documentos": "proprios"})
    item = documentos._row_to_dict(linha, u)
    assert all(c in item for c in CAMPOS)
    assert item["pode_editar"] is True
    outro = documentos._row_to_dict(linha[:6] + (99,) + linha[7:], u)
    assert outro["pode_editar"] is False


def test_a_lista_de_rm_devolve_os_campos_por_item(monkeypatch):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    linha = (1, 99, None, "Monte Siao/MG", "RM", "rodape", "rascunho", None, 7,
             None, None)
    u = Usuario(id=7, permissoes_=["rm.editar", "rm.excluir"],
                escopos={"rm": "proprios"})
    item = rm._row_to_dict(linha, u)
    assert all(c in item for c in CAMPOS)
    assert item["pode_editar"] is True
    outro = rm._row_to_dict(linha[:8] + (99,) + linha[9:], u)
    assert outro["pode_editar"] is False


def test_a_lista_continua_mostrando_o_registro_dos_outros(monkeypatch):
    """⭐ O escopo NAO filtra a leitura. O item do colega continua na resposta —
    so vem com `pode_editar: false`."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    linha = (1, 99, "sigcon", "ref", "nr", "st", None, None, None, "obs", [],
             99, None, None)
    u = Usuario(id=7, permissoes_=COM_ESCRITA, escopos={"gestao": "proprios"})
    item = gestao._row_to_dict(linha, u, with_anexos=False)
    assert item["id"] == 1 and item["observacoes"] == "obs"
    assert item["pode_editar"] is False
