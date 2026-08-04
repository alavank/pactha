"""`POST /api/session-capture` — a rota com DOIS donos, e o motivo que so valia
para um deles.

Ela grava, cifrada no Cofre, o cookie de uma sessao autenticada de portal do
governo (gov.br, FNS, SIMEC) e dispara o scraper. E a escrita mais sensivel do
sistema: aquele cookie vale como credencial viva enquanto nao expira.

⭐ O QUE ESTE ARQUIVO TRAVA. A rota estava na allowlist de rotas livres com o
motivo "autentica por SERVICE TOKEN, nao por usuario". Metade verdade —
`get_capture_principal` tem DOIS modos, e o Modo 2 aceita o cookie de QUALQUER
conta ativa. Como allowlist dispensa declaracao, a rota nao cobrava permissao de
usuario nenhuma, e `sessoes.capturar` ficou sendo uma caixinha do catalogo que
rota nenhuma consultava: o administrador marcava e nada mudava.

A correcao respeita a diferenca entre os dois donos, que e o ponto todo:

    service token  ->  a autoridade e o SCOPE `session:write`, conferido por
                       `require_scope`. Nao ha `User`, e nao ha o que cobrar.
    JWT de usuario ->  ha `User`, entao ha `sessoes.capturar`.

Rodar:
    python -m pytest backend/tests/test_captura_de_sessao_permissao.py -v
"""
import asyncio

import pytest
from fastapi import HTTPException

from routers import session_capture
from services import authz
from services.registro_rotas import ATRIBUTO, motivo_livre, varrer


class Servidor:
    def __init__(self, permissoes=(), active=True, kiosk=False):
        self.id = 7
        self.email = "servidor@montesiao.mg.gov.br"
        self.name = "Servidor"
        self.role = "usuario"
        self.active = active
        self.kiosk = kiosk
        self.super_admin = False
        self.somente_leitura = False
        self.allowed_permissoes = list(permissoes)
        self.allowed_telas = set()
        self.allowed_municipio_ids = set()


class _Res:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class DbComUsuario:
    def __init__(self, usuario):
        self.usuario = usuario

    async def execute(self, *a, **kw):
        return _Res(self.usuario)

    async def commit(self):
        return None


class RequestFalso:
    """So o que `get_capture_principal` le: cabecalhos, cookies e client."""

    def __init__(self, cookie="jwt-de-mentira"):
        self.headers = {}
        self.cookies = {"pactha_access": cookie} if cookie else {}
        self.client = None


@pytest.fixture(autouse=True)
def _isolar(monkeypatch):
    authz.limpar_dedupe()
    authz.limpar_contexto()
    monkeypatch.delenv("AUTHZ_MODO", raising=False)
    # Nenhuma linha de trilha sai para banco de verdade.
    monkeypatch.setattr(authz, "_enviar", lambda dados: True)
    yield
    authz.limpar_dedupe()
    authz.limpar_contexto()


@pytest.fixture
def jwt_valido(monkeypatch):
    """O decode e do JWT, nao da permissao: aqui ele sempre devolve o id 7."""
    monkeypatch.setattr(session_capture, "decode_access", lambda t: {"sub": "7"})
    monkeypatch.setattr(session_capture, "COOKIE_NAME_ACCESS", "pactha_access")


def _principal(usuario):
    return asyncio.run(session_capture.get_capture_principal(
        request=RequestFalso(), x_service_token=None, db=DbComUsuario(usuario)))


# ---------------------------------------------------------------------------
# 1. A rota nao e mais "livre"
# ---------------------------------------------------------------------------
def test_a_rota_saiu_da_allowlist_de_rotas_livres():
    assert motivo_livre("POST", "/api/session-capture") is None


def test_a_rota_declara_sessoes_capturar():
    """`declarado()` e nao `exige()`: quem checa e o resolvedor de principal, que
    e o unico que sabe qual dos dois modos entrou. Mas declarar e obrigatorio —
    sem a marca, o boot volta a acusar a rota como pendente."""
    import main

    rota = next(r for r in varrer(main.app).rotas
                if r.caminho == "/api/session-capture" and r.metodo == "POST")
    assert rota.permissoes == ("sessoes.capturar",)


# ---------------------------------------------------------------------------
# 2. O caminho do USUARIO passa a cobrar
# ---------------------------------------------------------------------------
def test_em_bloqueio_quem_nao_tem_a_caixinha_nao_captura(jwt_valido, monkeypatch):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    with pytest.raises(HTTPException) as e:
        _principal(Servidor(permissoes=["cofre.ver"]))
    assert e.value.status_code == 403


def test_em_bloqueio_quem_tem_a_caixinha_captura(jwt_valido, monkeypatch):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    p = _principal(Servidor(permissoes=["sessoes.capturar"]))
    assert p.via == "jwt" and p.user_id == 7


def test_em_modo_aviso_nada_muda(jwt_valido, monkeypatch):
    """A promessa do incremento inteiro, e ela vale AQUI tambem: o default e
    aviso, e em aviso quem captura hoje continua capturando amanha. Sem isto, o
    deploy seria o dia em que o bookmarklet parou para todo mundo de uma vez."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    p = _principal(Servidor(permissoes=[]))
    assert p.via == "jwt" and p.user_id == 7


# ---------------------------------------------------------------------------
# 3. E os guards que ja existiam continuam ANTES da permissao
# ---------------------------------------------------------------------------
def test_conta_inativa_leva_401_e_nao_403(jwt_valido, monkeypatch):
    """Ordem importa: conta desativada nao e "falta permissao", e o 401 tem de
    sair mesmo para quem TEM a caixinha marcada."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    with pytest.raises(HTTPException) as e:
        _principal(Servidor(permissoes=["sessoes.capturar"], active=False))
    assert e.value.status_code == 401


def test_quiosque_continua_barrado_antes_da_permissao(jwt_valido, monkeypatch):
    """⚠️ O link publico de TV e um usuario REAL. `permissoes_efetivas` ja o
    reduziria a `bi.ver`, mas a barreira do quiosque nao pode depender disso: ela
    e anterior, e vale igual em modo aviso — onde a permissao nao barraria nada."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    with pytest.raises(HTTPException) as e:
        _principal(Servidor(permissoes=["sessoes.capturar"], kiosk=True))
    assert e.value.status_code == 403
    assert "quiosque" in e.value.detail.lower()


# ---------------------------------------------------------------------------
# 4. A extensao do Chrome nao foi junto
# ---------------------------------------------------------------------------
def test_o_service_token_nao_passa_por_permissao_de_usuario():
    """`declarado()` marca e NAO checa — e e por isso que ele foi escolhido.
    Com `exige()` a rota ganharia `get_current_user` como dependencia e a
    extensao, que nao manda cookie de sessao, levaria 401 na primeira captura."""
    marcador = None
    for rota in session_capture.router.routes:
        # `APIRouter(prefix=...)` ja aplica o prefixo em `route.path`.
        if (getattr(rota, "path", "") == "/api/session-capture"
                and "POST" in (getattr(rota, "methods", None) or ())):
            marcador = rota
    assert marcador is not None
    chamadas = [getattr(d.call, ATRIBUTO, None)
                for d in marcador.dependant.dependencies]
    assert ("sessoes.capturar",) in chamadas
    nomes = [getattr(d.call, "__name__", "") for d in marcador.dependant.dependencies]
    assert "get_current_user" not in nomes
