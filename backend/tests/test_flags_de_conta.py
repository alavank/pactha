"""As DUAS FLAGS que substituiram o papel onde ele decidia poder de verdade.

`test_papel_nao_concede.py` prova que o papel parou de conceder escopo e
`test_apagao_incremento_4.py` prova que ninguem fica trancado do lado de fora.
Sobra o que nenhum dos dois cobre, e que e onde a mudanca vaza:

  1. A SEMENTE E O CODIGO SAO A MESMA COISA. A coluna virou autoridade e a lista
     do codigo virou semente/reforco — mas so enquanto as duas disserem o mesmo.
     Sao QUATRO copias da lista de donos (services/auth.py, setup_db.py,
     migrations/, frontend/lib/conta.ts) e elas divergem em silencio.

  2. AS DUAS PORTAS CONCORDAM. `GET /users` calculava as flags com os helpers e
     `GET /auth/me` nao as mandava. Promover um dono por UPDATE na coluna — a
     capacidade que este incremento abriu — valia no backend e nao chegava na
     tela: a sidebar continuava escondendo Sessoes e Service Tokens dele.

  3. A TRAVA DE ESCRITA E ALCANCAVEL. Sem caminho para liga-la, o guard trocar
     PAPEL por FLAG AFROUXA a unica trava de acao do sistema: marcar alguem como
     "Prefeito" produzia, ate a vespera, uma conta que nao escreve. Depois do
     deploy produziria uma conta que escreve — e sem jeito de conte-la fora do
     banco.
"""
import asyncio
import pathlib
import re

import pytest
from fastapi import HTTPException

from routers.users import UpdateUserRequest, _trava_inicial, update_user
from schemas.auth import UserResponse
from services.auth import (
    PAPEIS_SEMPRE_SOMENTE_LEITURA,
    READONLY_ROLES,
    SUPER_ADMIN_EMAILS,
)

BACKEND = pathlib.Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
MIGRATION = (BACKEND / "migrations" / "add_role_vira_rotulo.sql").read_text(encoding="utf-8")


def _emails(texto: str) -> set[str]:
    return set(re.findall(r"[\"']([\w.\-]+@[\w.\-]+)[\"']", texto))


# ---------------------------------------------------------------------------
# 1. As quatro copias da lista de donos
# ---------------------------------------------------------------------------
def test_a_migration_semeia_exatamente_a_lista_do_codigo():
    """A coluna manda e a lista reforca (`is_super_admin` le as duas). Se a
    migration semear um e-mail a mais, ele vira dono no banco sem estar no codigo
    — e some do reforco no dia em que a coluna for zerada. Se semear a menos, a
    conta so entra pelo reforco e a tela de Usuarios a mostra como comum."""
    trecho = MIGRATION[MIGRATION.index("SET super_admin = TRUE"):]
    trecho = trecho[:trecho.index(";")]
    assert _emails(trecho) == SUPER_ADMIN_EMAILS


def test_o_seed_de_tenant_novo_semeia_a_mesma_lista():
    """`setup_db.py` roda FORA do app (nao da para importar `services.auth` de
    la), entao a lista esta repetida — e divergir aqui significa tenant novo com
    dono faltando, ou com um dono a mais que ninguem colocou."""
    fonte = (BACKEND / "setup_db.py").read_text(encoding="utf-8")
    trecho = fonte[fonte.index("AS CONTAS DE DONO"):]
    trecho = trecho[:trecho.index("conn.commit()")]
    # O quarto e-mail vem de `ADMIN_EMAIL`, com o default escrito no arquivo.
    do_seed = _emails(trecho) | _emails(fonte[fonte.index('os.getenv("ADMIN_EMAIL"'):][:120])
    assert do_seed == SUPER_ADMIN_EMAILS


def test_o_frontend_espelha_as_duas_listas_do_backend():
    """`lib/conta.ts` decide o que a TELA desenha (o selo de dono, o item de menu
    de Sessoes). Nao barra nada — mas divergir esconde a tela de quem tem acesso,
    ou mostra um link que da 403."""
    ts = REPO / "frontend" / "src" / "lib" / "conta.ts"
    if not ts.exists():
        pytest.skip("frontend nao esta neste checkout")
    fonte = ts.read_text(encoding="utf-8")
    assert _emails(fonte) == SUPER_ADMIN_EMAILS
    papeis = fonte[fonte.index("const PAPEIS_SEMPRE_SOMENTE_LEITURA"):]
    papeis = set(re.findall(r'"(\w+)"', papeis[:papeis.index(";")]))
    assert papeis == PAPEIS_SEMPRE_SOMENTE_LEITURA


def test_o_frontend_soma_por_OU_como_o_backend():
    """⚠️ `if (typeof super_admin === "boolean") return super_admin` NAO e um OU:
    um `false` vindo do campo DESLIGA a allowlist. Enquanto a API manda o valor ja
    somado da no mesmo — mas no dia em que qualquer rota serializar a COLUNA crua,
    um dos quatro donos aparece como conta comum. As duas fontes so AMPLIAM."""
    ts = REPO / "frontend" / "src" / "lib" / "conta.ts"
    if not ts.exists():
        pytest.skip("frontend nao esta neste checkout")
    fonte = ts.read_text(encoding="utf-8")
    assert "typeof u?.super_admin" not in fonte
    assert "u?.super_admin === true" in fonte
    assert "u?.somente_leitura === true" in fonte


# ---------------------------------------------------------------------------
# 2. `/auth/me` e `/users` respondem a mesma coisa
# ---------------------------------------------------------------------------
class Conta:
    def __init__(self, **kw):
        self.id = kw.get("id", 5)
        self.email = kw.get("email", "servidor@montesiao.mg.gov.br")
        self.name = kw.get("name", "Servidor")
        self.role = kw.get("role", "usuario")
        self.active = kw.get("active", True)
        self.must_change_password = kw.get("must_change_password", False)
        self.super_admin = kw.get("super_admin", False)
        self.somente_leitura = kw.get("somente_leitura", False)
        # Lido por `authz.permissoes_de`. Sem ele o duplo nao pode NADA, e os
        # dois testes de PATCH abaixo passavam a medir a falta de
        # `usuarios.conceder` em vez da regra que dizem medir.
        self.allowed_permissoes = kw.get("permissoes", [])


def test_a_resposta_calcula_as_flags_e_nao_copia_a_coluna():
    """A coluna crua nao e a resposta certa para nenhuma das duas: quem esta na
    semente da Alavank manda no sistema mesmo com `super_admin = false`, e o
    quiosque nao escreve mesmo com `somente_leitura = false`. `model_validate`
    sozinho copiaria os dois `false` e a tela mentiria sobre quem tem a chave."""
    dono = UserResponse.de_usuario(
        Conta(email="matheus@alavank.com.br", super_admin=False))
    assert dono.super_admin is True

    quiosque = UserResponse.de_usuario(
        Conta(email="kiosk-u3-abc@painel.local", role="viewer", somente_leitura=False))
    assert quiosque.somente_leitura is True

    comum = UserResponse.de_usuario(Conta())
    assert comum.super_admin is False and comum.somente_leitura is False


def test_a_promocao_por_coluna_chega_na_tela():
    """O ponto do incremento: trocar quem manda deixou de exigir deploy. Se a
    resposta nao carregar a flag, a sidebar volta a decidir so pela allowlist e o
    dono promovido por UPDATE nao ve Sessoes nem Service Tokens — o backend
    autoriza e a tela esconde."""
    novo = UserResponse.de_usuario(
        Conta(email="suporte@alavank.com.br", role="usuario", super_admin=True))
    assert novo.super_admin is True
    assert "super_admin" in UserResponse.model_fields
    assert "somente_leitura" in UserResponse.model_fields


# ---------------------------------------------------------------------------
# 3. A trava de escrita e alcancavel — e nao afrouxou no caminho
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("papel", sorted(READONLY_ROLES))
def test_quem_era_somente_leitura_pelo_papel_continua_nascendo_travado(papel):
    """⚠️ A REGRESSAO QUE ESTE TESTE EXISTE PARA PEGAR. O guard passou a ler a
    FLAG; a migration semeou a flag de quem JA existia. Faltava o nascimento: sem
    isto, todo prefeito cadastrado DEPOIS do deploy nasce com escrita liberada em
    tudo o que tiver tela — trocando, em silencio, "prefeito nao escreve" por
    "prefeito escreve"."""
    assert _trava_inicial(papel, None) is True


def test_quem_nunca_foi_somente_leitura_continua_escrevendo():
    """O outro lado: a semente nao pode travar quem sempre escreveu."""
    for papel in ("admin", "analyst", "user", "usuario"):
        assert _trava_inicial(papel, None) is False


def test_a_escolha_explicita_do_administrador_ganha_do_rotulo():
    """E aqui o papel deixa de decidir tambem isto: dois prefeitos, um que so le
    o Painel e outro que lanca — os dois marcados "prefeito" no cadastro."""
    assert _trava_inicial("prefeito", False) is False
    assert _trava_inicial("admin", True) is True


# ---------------------------------------------------------------------------
# 4. A porta que fecha por fora
# ---------------------------------------------------------------------------
class _Resultado:
    def __init__(self, objeto):
        self._objeto = objeto

    def scalar_one_or_none(self):
        return self._objeto

    def fetchall(self):
        # Escopo vazio: este teste e sobre a flag, nao sobre telas/municipios.
        return []


class FakeDb:
    def __init__(self, usuario):
        self.usuario = usuario
        self.escreveu = False

    async def execute(self, *a, **kw):
        return _Resultado(self.usuario)

    async def commit(self):
        self.escreveu = True

    async def refresh(self, *a, **kw):
        return None


def test_ninguem_se_poe_em_somente_leitura():
    """Em somente leitura a pessoa nao consegue nem desfazer o proprio PATCH — o
    guard de `get_current_user` barra POST/PUT/PATCH/DELETE fora do Painel, e
    este endpoint e um PATCH. Ela perderia, no mesmo ato, a escrita e o unico
    caminho de volta: so por outro admin, ou pelo banco. Mesma familia do
    "nao pode desativar a si mesmo" que ja existia aqui."""
    # Com a permissao NA MAO: o 400 tem de vir da regra do proprio umbigo, e nao
    # de `usuarios.conceder` faltando — senao este teste passaria a verde pelo
    # motivo errado no dia em que a regra do umbigo fosse removida.
    eu = Conta(id=1, role="admin", permissoes=["usuarios.conceder"])
    db = FakeDb(eu)
    with pytest.raises(HTTPException) as e:
        asyncio.run(update_user(
            user_id=1, req=UpdateUserRequest(somente_leitura=True),
            request=None, db=db, current=eu,
        ))
    assert e.value.status_code == 400
    assert "somente leitura" in e.value.detail.lower()
    assert not db.escreveu


def test_travar_OUTRA_pessoa_continua_permitido(monkeypatch):
    """A recusa e sobre si mesmo, e so. Travar outra conta e o uso NORMAL da
    flag — e e por ele que o prefeito volta a ser somente-leitura sem que o
    rotulo "prefeito" volte a decidir por todos os prefeitos.

    A trilha entra como duplo: `registrar_critico` fala com o banco de verdade e
    o que se verifica aqui e a decisao, nao a gravacao. Ela tem teste proprio."""
    registrado = {}

    async def _falsa_trilha(db, **kw):
        registrado.update(kw)

    monkeypatch.setattr("routers.users.registrar_critico", _falsa_trilha)

    eu = Conta(id=1, role="admin", permissoes=["usuarios.conceder"])
    outro = Conta(id=2, role="prefeito", somente_leitura=False)
    db = FakeDb(outro)
    asyncio.run(update_user(
        user_id=2, req=UpdateUserRequest(somente_leitura=True),
        request=None, db=db, current=eu,
    ))
    assert outro.somente_leitura is True
    assert db.escreveu
    # E a trilha registra a mudanca de poder: sem `somente_leitura` nos dois
    # retratos, "quem liberou o prefeito para editar, e quando" fica sem resposta.
    assert registrado["valor_antes"]["somente_leitura"] is False
    assert registrado["valor_depois"]["somente_leitura"] is True


def test_a_flag_nao_e_aceita_para_super_admin():
    """`super_admin` fica FORA dos payloads de propósito: aceita-lo deixaria
    qualquer admin do tenant se promover a dono num PATCH e alcancar Sessoes,
    Service Tokens e as contas dos outros donos."""
    assert "super_admin" not in UpdateUserRequest.model_fields
    from routers.users import CreateUserRequest
    assert "super_admin" not in CreateUserRequest.model_fields
    # E `somente_leitura` esta nos dois, senao a trava e inalcancavel.
    assert "somente_leitura" in UpdateUserRequest.model_fields
    assert "somente_leitura" in CreateUserRequest.model_fields
