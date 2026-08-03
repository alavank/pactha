"""O papel virou ROTULO: quem concede agora e a permissao INDIVIDUAL.

A regra do dono, literal: "se no pactha tem esses niveis de prefeito, usuario,
analista, isso pode ate continuar tendo mas NAO VAI VALER DE NADA a nao ser
rotulo so pra organizacao interna do cliente. O que vai valer sao as permissoes
colocadas e dadas a cada usuario INDIVIDUALMENTE."

Este arquivo testa as tres travas que mudaram de fonte de verdade — e testa
principalmente o que elas NAO podem fazer:

  1. `load_user_scopes` nao pode mais zerar os limites por `role == "admin"`.
     Era ali que o rotulo virava ausencia total de limite.
  2. `is_super_admin` passou a ler a COLUNA (trocar quem manda deixou de exigir
     deploy) SEM perder a allowlist de e-mails como reforco — banco sem a coluna
     nao pode trancar a Alavank fora do proprio produto.
  3. `eh_somente_leitura` passou a ler a FLAG, e isso NAO pode afrouxar o
     quiosque: o link publico de TV e um `viewer` criado em tempo de execucao
     por `routers/bi.py::_ensure_kiosk_user`, com INSERT direto, que nao seta
     flag nenhuma.

Rodar:
    python -m pytest backend/tests/test_papel_nao_concede.py -v
"""
import asyncio

import pytest
from fastapi import HTTPException

from services import authz
from services.auth import (
    SUPER_ADMIN_EMAILS,
    create_access_token,
    eh_somente_leitura,
    get_current_user,
    is_super_admin,
    load_user_scopes,
)


class Usuario:
    """Bate com o que o codigo real le de `models.user.User`. `super_admin` e
    `somente_leitura` sao as colunas novas; o default `False` reproduz tambem o
    banco AINDA SEM a migration (os helpers usam `getattr` com default)."""

    def __init__(self, *, id=7, email="servidor@montesiao.mg.gov.br",
                 name="Servidor", role="analyst", active=True,
                 super_admin=False, somente_leitura=False, kiosk=False):
        self.id = id
        self.email = email
        self.name = name
        self.role = role
        self.active = active
        self.super_admin = super_admin
        self.somente_leitura = somente_leitura
        self.kiosk = kiosk


class UsuarioSemColunas:
    """O mesmo usuario num banco onde a migration ainda NAO rodou: sem
    `super_admin` e sem `somente_leitura`. Nenhum helper pode explodir aqui."""

    def __init__(self, *, email="qualquer@montesiao.mg.gov.br", role="analyst"):
        self.id = 9
        self.email = email
        self.name = "Sem colunas"
        self.role = role
        self.active = True


class _Resultado:
    def __init__(self, linhas=(), objeto=None):
        self._linhas = list(linhas)
        self._objeto = objeto

    def fetchall(self):
        return self._linhas

    def scalar_one_or_none(self):
        return self._objeto


class FakeDb:
    """Sessao falsa que responde as DUAS consultas de `load_user_scopes` e ao
    `select(User)` de `get_current_user`. Guarda o que foi perguntado — e disso
    que sai a asercao mais importante: o super-admin NAO consulta as tabelas."""

    def __init__(self, *, telas=(), municipios=(), usuario=None):
        self.telas = list(telas)
        self.municipios = list(municipios)
        self.usuario = usuario
        self.consultas: list[str] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.consultas.append(sql)
        if "user_municipios" in sql:
            return _Resultado(linhas=[(m,) for m in self.municipios])
        if "user_telas" in sql:
            return _Resultado(linhas=[(t,) for t in self.telas])
        return _Resultado(objeto=self.usuario)


# ---------------------------------------------------------------------------
# 1. `role` deixou de conceder escopo
# ---------------------------------------------------------------------------
def test_admin_do_cliente_nao_zera_mais_os_limites():
    """O coracao do incremento. `role='admin'` era ausencia TOTAL de limite —
    e como o cadastro nascia com esse papel por default, um POST que esquecesse
    o campo criava um deus. Agora o admin do cliente vale pelo que foi dado a
    ELE, como todo mundo."""
    u = Usuario(role="admin", email="secretaria@montesiao.mg.gov.br")
    db = FakeDb(telas=["dashboard", "cauc"], municipios=[3])
    asyncio.run(load_user_scopes(db, u))
    assert u.allowed_telas == {"dashboard", "cauc"}
    assert u.allowed_municipio_ids == {3}


def test_admin_sem_linha_nenhuma_fica_sem_nada_e_nao_com_tudo():
    """Fail-closed: conjunto VAZIO e "nao pode nada", nunca "pode tudo" (`None`).

    E exatamente por isso que a migration deste incremento tem de conceder o
    catalogo inteiro aos admins ATUAIS antes desta regra valer — sem o backfill,
    este teste descreve o cliente inteiro trancado para fora."""
    u = Usuario(role="admin")
    db = FakeDb()
    asyncio.run(load_user_scopes(db, u))
    assert u.allowed_telas == set()
    assert u.allowed_municipio_ids == set()
    assert u.allowed_telas is not None and u.allowed_municipio_ids is not None


@pytest.mark.parametrize("papel", ["analyst", "user", "prefeito", "viewer"])
def test_nenhum_outro_papel_concede(papel):
    """`analyst` e `user` sempre foram byte-identicos e continuam sendo: papel
    nenhum entra na conta do escopo."""
    u = Usuario(role=papel)
    db = FakeDb(telas=["bi"], municipios=[1])
    asyncio.run(load_user_scopes(db, u))
    assert u.allowed_telas == {"bi"}
    assert u.allowed_municipio_ids == {1}


def test_super_admin_segue_sem_limite_e_sem_consultar_o_banco():
    """A Alavank e dona da plataforma e precisa de porta de entrada: sem esta
    excecao, um tenant com cadastro de telas vazio trancaria o suporte fora do
    proprio produto e ninguem sobraria para devolver o acesso."""
    u = Usuario(role="analyst", email="tiagomiller@alavank.com.br")
    db = FakeDb(telas=["dashboard"], municipios=[1])
    asyncio.run(load_user_scopes(db, u))
    assert u.allowed_telas is None
    assert u.allowed_municipio_ids is None
    assert db.consultas == []


def test_super_admin_pela_coluna_vale_mesmo_com_email_do_cliente():
    """A coluna e a autoridade: promover um dono deixou de exigir deploy."""
    u = Usuario(role="user", email="novo.dono@alavank.com.br", super_admin=True)
    db = FakeDb(telas=["dashboard"], municipios=[1])
    asyncio.run(load_user_scopes(db, u))
    assert u.allowed_telas is None
    assert u.allowed_municipio_ids is None


# ---------------------------------------------------------------------------
# 2. Quem e dono da plataforma
# ---------------------------------------------------------------------------
def test_is_super_admin_le_a_coluna():
    assert is_super_admin(Usuario(email="ninguem@exemplo.com", super_admin=True))


def test_is_super_admin_mantem_a_allowlist_como_reforco():
    """Coluna `false` (ou migration que nao rodou) nao pode tirar a chave da
    Alavank. As duas fontes so AMPLIAM — nao ha caminho em que erro de dado
    tranque o dono para fora."""
    for email in SUPER_ADMIN_EMAILS:
        assert is_super_admin(Usuario(email=email, super_admin=False))
        assert is_super_admin(UsuarioSemColunas(email=email))


def test_is_super_admin_nega_o_resto():
    assert not is_super_admin(Usuario(role="admin"))
    assert not is_super_admin(UsuarioSemColunas())
    # Saiu da lista em 02/08/2026 justamente por ser adivinhavel: qualquer admin
    # do cliente que recriasse esse e-mail ganharia a plataforma.
    assert not is_super_admin(Usuario(email="admin@pactha.com.br"))


def test_is_super_admin_normaliza_o_email():
    assert is_super_admin(Usuario(email="  Matheus@Alavank.com.BR "))


# ---------------------------------------------------------------------------
# 3. Somente-leitura virou flag, sem afrouxar o quiosque
# ---------------------------------------------------------------------------
def test_flag_manda_mesmo_com_papel_de_admin():
    """O que era impossivel ate aqui: um usuario marcado `admin` posto em
    somente-leitura."""
    assert eh_somente_leitura(Usuario(role="admin", somente_leitura=True))


def test_prefeito_sem_a_flag_pode_escrever():
    """O desacoplamento que o dono pediu: `prefeito` vira ROTULO. O prefeito que
    precisar lancar alguma coisa ganha escrita individualmente — sem deixar de
    aparecer como prefeito, e sem que isso conceda nada aos outros prefeitos."""
    assert not eh_somente_leitura(Usuario(role="prefeito", somente_leitura=False))


def test_viewer_continua_somente_leitura_mesmo_sem_a_flag():
    """⚠️ REGRESSAO CARA. `viewer` nao e rotulo de pessoa: e a credencial do link
    publico de TV, criada em tempo de execucao com INSERT direto que nao seta a
    flag. Se este teste cair, todo quiosque emitido DEPOIS do deploy vira uma
    conta que ESCREVE — e o link circula em WhatsApp."""
    assert eh_somente_leitura(Usuario(role="viewer", somente_leitura=False))
    assert eh_somente_leitura(UsuarioSemColunas(role="viewer"))


def test_usuario_comum_nao_e_somente_leitura():
    assert not eh_somente_leitura(Usuario(role="analyst"))
    assert not eh_somente_leitura(UsuarioSemColunas())


# ---------------------------------------------------------------------------
# 4. O guard de verdade, dentro de `get_current_user`
# ---------------------------------------------------------------------------
class _Url:
    def __init__(self, path):
        self.path = path


class FakeRequest:
    def __init__(self, metodo, caminho):
        self.method = metodo
        self.url = _Url(caminho)
        self.cookies = {}
        self.headers = {}


class FakeCreds:
    """Bearer: `get_current_user` so exige CSRF quando o token vem por COOKIE."""

    def __init__(self, token):
        self.credentials = token


def _chamar(usuario, metodo, caminho, *, telas=("bi",), municipios=(1,)):
    req = FakeRequest(metodo, caminho)
    creds = FakeCreds(create_access_token({"sub": usuario.id}))
    db = FakeDb(telas=telas, municipios=municipios, usuario=usuario)
    try:
        return asyncio.run(get_current_user(req, creds, db))
    finally:
        authz.limpar_contexto()


def test_guard_barra_escrita_de_quem_tem_a_flag():
    u = Usuario(role="admin", somente_leitura=True)
    with pytest.raises(HTTPException) as e:
        _chamar(u, "POST", "/api/convenios")
    assert e.value.status_code == 403
    assert e.value.detail == "Perfil somente-leitura"


def test_guard_barra_escrita_do_viewer_sem_flag():
    """A mesma trava do quiosque, agora pelo caminho real da requisicao."""
    with pytest.raises(HTTPException) as e:
        _chamar(Usuario(role="viewer"), "PUT", "/api/convenios/1")
    assert e.value.status_code == 403


def test_guard_deixa_o_somente_leitura_escrever_nos_endpoints_do_painel():
    """A excecao que sempre existiu: o gestor filtra e publica a PROPRIA TV."""
    u = Usuario(role="prefeito", somente_leitura=True)
    assert _chamar(u, "POST", "/api/bi/tela-filtros") is u


def test_guard_nao_toca_em_leitura():
    u = Usuario(role="prefeito", somente_leitura=True)
    assert _chamar(u, "GET", "/api/convenios") is u


def test_guard_deixa_passar_quem_nao_e_somente_leitura():
    """Sem isto o incremento teria trocado "prefeito nao escreve" por "ninguem
    escreve" — e o sistema inteiro pararia para o cliente."""
    u = Usuario(role="admin")
    assert _chamar(u, "POST", "/api/convenios") is u
