"""
⭐ O ATO DE CONCEDER — `PUT /api/permissoes/usuario/{id}`.

O endpoint que grava permissao de OUTRA pessoa e o unico do sistema que fabrica
poder. Tres coisas precisam ser verdade nele, e este arquivo prova as tres:

  1. NINGUEM CONCEDE O QUE NAO TEM — nem CONCEDE nem RETIRA. A simetria e o que
     mais surpreende quem le pela primeira vez: retirar parece inofensivo
     ("estou tirando poder"), mas e um administrador sem acesso ao Cofre
     desligando o acesso de quem tem. Quem so pudesse retirar ja derrubaria a
     operacao de uma prefeitura inteira em dois cliques.

  2. E NEGA NOS DOIS MODOS. `AUTHZ_MODO=aviso` existe para nao quebrar
     comportamento que JA EXISTIA; este endpoint e novo e nao tem comportamento
     antigo a preservar. Uma trava de escalonamento que "so avisa" e a ausencia
     da trava.

  3. A CAIXINHA INTOCADA NAO ATRAPALHA. A tela manda o conjunto COMPLETO, e as
     caixinhas travadas voltam como vieram. Se a regra olhasse o conjunto em vez
     da DIFERENCA, um administrador sem `cofre.revelar` ficaria impedido de
     mexer em qualquer caixinha de quem tivesse aquela — o pedido inteiro
     recusado por uma linha que ele nem tocou.

Rodar:
    python -m pytest backend/tests/test_permissoes_concessao.py -v
"""
import asyncio

import pytest
from fastapi import HTTPException

from routers import permissoes as rota
from services import authz, permissoes


class Usuario:
    """O que o codigo real le do User depois de `load_user_scopes`."""

    def __init__(self, permissoes=None, super_admin=False, somente_leitura=False,
                 role="admin", id=7):
        self.id = id
        self.email = "gestor@montesiao.mg.gov.br"
        self.name = "Gestor"
        self.role = role
        self.active = True
        self.kiosk = False
        self.super_admin = super_admin
        self.somente_leitura = somente_leitura
        self.allowed_permissoes = permissoes
        self.allowed_telas = set()
        self.allowed_municipio_ids = set()


class FakeDb:
    """Registra o SQL emitido, sem banco. So `execute` e usado por
    `_gravar_concessao`."""

    def __init__(self):
        self.chamadas: list = []

    async def execute(self, sql, params=None):
        self.chamadas.append((str(sql), params or {}))
        return None


@pytest.fixture(autouse=True)
def _isolar(monkeypatch):
    authz.limpar_dedupe()
    authz.limpar_contexto()
    monkeypatch.delenv("AUTHZ_MODO", raising=False)
    # Nenhuma linha de trilha sai para banco de verdade neste arquivo.
    monkeypatch.setattr(authz, "_enviar", lambda dados: True)
    yield
    authz.limpar_dedupe()
    authz.limpar_contexto()


@pytest.fixture(params=["aviso", "bloqueio"])
def qualquer_modo(request, monkeypatch):
    monkeypatch.setenv("AUTHZ_MODO", request.param)
    return request.param


# ===========================================================================
# 1. A chave que chega da tela
# ===========================================================================
def test_chave_fora_do_catalogo_e_recusada_com_400():
    """400 e nao 403: nao e permissao que falta, e pedido malformado. A chave
    invalida tambem morreria na FK, mas ai o erro sairia como 500 sem dizer
    QUAL chave."""
    with pytest.raises(HTTPException) as e:
        rota._validar(["rm.ver", "rm.excluri"])
    assert e.value.status_code == 400
    assert "rm.excluri" in e.value.detail


def test_chave_e_normalizada_como_o_resto_do_sistema():
    assert rota._validar(["  RM.Ver ", "rm.ver", ""]) == {"rm.ver"}


def test_conjunto_vazio_e_valido():
    """Revogar tudo e operacao legitima — desligar alguem sem desativar a conta."""
    assert rota._validar([]) == set()


# ===========================================================================
# 2. ⭐ Anti-escalonamento
# ===========================================================================
def test_ninguem_concede_o_que_nao_tem(qualquer_modo):
    editor = Usuario(permissoes={"usuarios.conceder", "rm.ver"})
    with pytest.raises(HTTPException) as e:
        rota._barrar_escalonamento(editor, set(), {"cofre.revelar"})
    assert e.value.status_code == 403
    # A mensagem traz o ROTULO, e nao a chave crua: quem le a tela nao conhece
    # `cofre.revelar`.
    assert permissoes.CATALOGO["cofre.revelar"].rotulo in e.value.detail


def test_ninguem_retira_o_que_nao_tem(qualquer_modo):
    """A simetria e deliberada — ver o cabecalho."""
    editor = Usuario(permissoes={"usuarios.conceder"})
    with pytest.raises(HTTPException):
        rota._barrar_escalonamento(editor, {"cofre.revelar"}, set())


def test_o_que_o_editor_tem_ele_concede_e_retira():
    editor = Usuario(permissoes={"rm.ver", "rm.excluir"})
    rota._barrar_escalonamento(editor, set(), {"rm.ver"})          # concede
    rota._barrar_escalonamento(editor, {"rm.excluir"}, set())      # retira


def test_caixinha_intocada_fora_do_alcance_nao_bloqueia_o_pedido():
    """O pedido carrega o conjunto INTEIRO. `cofre.revelar` esta nos dois lados
    (o editor nao a tocou) e nao pode fazer a edicao inteira falhar."""
    editor = Usuario(permissoes={"rm.ver"})
    rota._barrar_escalonamento(
        editor, {"cofre.revelar"}, {"cofre.revelar", "rm.ver"})


def test_super_admin_concede_qualquer_uma():
    dono = Usuario(super_admin=True, permissoes=None)
    rota._barrar_escalonamento(dono, set(), set(permissoes.TODAS))


def test_editor_em_somente_leitura_nao_concede_escrita():
    """A funcao pura subtrai os verbos de escrita do conjunto EFETIVO, e e o
    efetivo que vale aqui. Na pratica o guard de somente-leitura ja barra o PUT
    antes; esta e a segunda trava, para o dia em que a primeira mudar."""
    editor = Usuario(permissoes={"rm.ver", "rm.excluir"}, somente_leitura=True)
    rota._barrar_escalonamento(editor, set(), {"rm.ver"})
    with pytest.raises(HTTPException):
        rota._barrar_escalonamento(editor, set(), {"rm.excluir"})


def test_sem_permissao_nenhuma_nao_concede_nada(qualquer_modo):
    """`allowed_permissoes=None` e VAZIO, e nao 'sem limite'."""
    with pytest.raises(HTTPException):
        rota._barrar_escalonamento(Usuario(permissoes=None), set(), {"rm.ver"})


# ===========================================================================
# 3. A gravacao
# ===========================================================================
def _gravou(antes, depois):
    db = FakeDb()
    asyncio.run(rota._gravar_concessao(db, 42, antes, depois, autor_id=1))
    return db.chamadas


def test_grava_so_a_diferenca():
    """DELETE+INSERT do conjunto inteiro reescreveria `concedido_em` e
    `concedido_por` de TODAS as linhas a cada salvamento: a concessao feita ha um
    ano por outra pessoa passaria a dizer que fui eu, hoje."""
    chamadas = _gravou({"rm.ver", "rm.editar"}, {"rm.ver", "rm.excluir"})
    assert len(chamadas) == 2
    sql_del, p_del = chamadas[0]
    assert "DELETE" in sql_del and p_del["p"] == "rm.editar"
    sql_ins, p_ins = chamadas[1]
    assert "INSERT" in sql_ins and p_ins["p"] == "rm.excluir"
    assert p_ins["por"] == 1


def test_sem_mudanca_nao_toca_no_banco():
    assert _gravou({"rm.ver"}, {"rm.ver"}) == []


def test_revogar_tudo_apaga_uma_a_uma():
    chamadas = _gravou({"rm.ver", "rm.editar"}, set())
    assert len(chamadas) == 2
    assert all("DELETE" in sql for sql, _ in chamadas)


# ===========================================================================
# 4. A fiacao — o que o boot e a trilha enxergam
# ===========================================================================
def test_as_duas_rotas_declaram_permissao():
    """Rota que nao declara e rota PENDENTE no boot (services/registro_rotas.py)
    — e a de gravar precisa declarar `usuarios.conceder`, que e a caixinha que o
    catalogo descreve como 'decide o que a equipe faz no sistema'."""
    from services.registro_rotas import _permissoes_declaradas

    declaradas = {
        (m, r.path): _permissoes_declaradas(r)
        for r in rota.router.routes for m in (r.methods or ())
    }
    assert declaradas[("GET", "/api/permissoes/usuarios")] == ("usuarios.ver",)
    assert declaradas[("PUT", "/api/permissoes/usuario/{user_id}")] \
        == ("usuarios.conceder",)


def test_a_acao_da_trilha_tem_rotulo_em_portugues():
    """Chave sem entrada no catalogo didatico cai na derivacao, e a trilha da
    concessao de poder vira jargao que ninguem le."""
    from services import audit_catalog

    acao = audit_catalog.descrever_acao("usuarios.conceder")
    assert acao.conhecida
    assert acao.risco == audit_catalog.RISCO_ALTO
    assert acao.modulo == audit_catalog.MOD_USUARIOS
