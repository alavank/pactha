"""A FLAG que substituiu o papel onde ele decidia poder de verdade.

⚠️ ERAM DUAS ate 05/09/2026. A segunda — `somente_leitura`, a trava de escrita
da conta — foi REMOVIDA por decisao do dono, e com ela saiu a secao 3 deste
arquivo ("a trava de escrita e alcancavel"). O que ela fazia agora se faz
desmarcando as caixinhas de escrita de cada tela, e quem cobre isso e
`test_permissoes_concessao.py`. Ver o topo de `services/auth.py`.

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

"""
import pathlib
import re

import pytest

from schemas.auth import UserResponse
from services.auth import SUPER_ADMIN_EMAILS

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


def test_o_frontend_espelha_a_lista_de_donos_do_backend():
    """`lib/conta.ts` decide o que a TELA desenha (o selo de dono, o item de menu
    de Sessoes). Nao barra nada — mas divergir esconde a tela de quem tem acesso,
    ou mostra um link que da 403."""
    ts = REPO / "frontend" / "src" / "lib" / "conta.ts"
    if not ts.exists():
        pytest.skip("frontend nao esta neste checkout")
    fonte = ts.read_text(encoding="utf-8")
    assert _emails(fonte) == SUPER_ADMIN_EMAILS


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
        self.funcao = kw.get("funcao")
        self.whatsapp = kw.get("whatsapp")
        self.allowed_permissoes = kw.get("permissoes", [])


def test_a_resposta_calcula_a_flag_e_nao_copia_a_coluna():
    """A coluna crua nao e a resposta certa: quem esta na semente da Alavank
    manda no sistema mesmo com `super_admin = false`. `model_validate` sozinho
    copiaria o `false` e a tela mentiria sobre quem tem a chave."""
    dono = UserResponse.de_usuario(
        Conta(email="matheus@alavank.com.br", super_admin=False))
    assert dono.super_admin is True

    comum = UserResponse.de_usuario(Conta())
    assert comum.super_admin is False


def test_a_promocao_por_coluna_chega_na_tela():
    """O ponto do incremento: trocar quem manda deixou de exigir deploy. Se a
    resposta nao carregar a flag, a sidebar volta a decidir so pela allowlist e o
    dono promovido por UPDATE nao ve Sessoes nem Service Tokens — o backend
    autoriza e a tela esconde."""
    novo = UserResponse.de_usuario(
        Conta(email="suporte@alavank.com.br", role="usuario", super_admin=True))
    assert novo.super_admin is True
    assert "super_admin" in UserResponse.model_fields
    # ⚠️ E a trava de conta NAO volta pela porta dos fundos: `somente_leitura`
    # saiu do schema em 05/09/2026, e um campo com esse nome reaparecendo aqui
    # significaria que alguem reintroduziu a regra sem reler por que ela saiu.
    assert "somente_leitura" not in UserResponse.model_fields

