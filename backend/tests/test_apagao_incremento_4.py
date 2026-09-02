"""O APAGAO QUE O BACKFILL NAO ALCANCA: as contas que nascem DEPOIS do deploy.

No instante em que `role == "admin"` deixa de zerar os limites, todo mundo passa
a valer exatamente o que houver em `user_telas`/`user_municipios`. A migration
deste incremento cobre quem JA EXISTIA no dia do deploy — e `tests/
test_migration_role_vira_rotulo.py` cerca essa parte, statement a statement.

Este arquivo cerca o RESTO, que backfill nenhum pode alcancar: os tres caminhos
que criam usuario ou municipio EM TEMPO DE EXECUCAO. Todos eram inofensivos
enquanto o papel abria tudo, e cada um vira um apagao (ou um vazamento) depois
que ele deixou de abrir:

  1. `routers/control.py::control_sso` — o usuario de SUPORTE da Alavank nasce
     `role="admin"` e sem escopo nenhum. O e-mail e `alavank-sso.<local>@…`, que
     NAO esta em SUPER_ADMIN_EMAILS. Tecnico novo (ou tenant novo) entra pelo
     SSO e nao ve nada — e e justamente quem conserta o acesso dos outros.
  2. `routers/control.py::upsert_municipio` — cidade nova nao tem linha para
     ninguem, e municipio sem linha responde 403 para o cliente inteiro.
  3. `routers/bi.py::_ensure_kiosk_user` — a conta do link publico de TV nao
     pode GANHAR nada: nem escrita, nem municipio do dono que ela nao espelha.

Mais a varredura final: sobrou papel CONCEDENDO acesso em algum lugar?

Le o FONTE de proposito — nao ha Postgres aqui, e o que precisa ser garantido e
a forma do codigo que vai rodar.

Rodar:
    python -m pytest backend/tests/test_apagao_incremento_4.py -v
"""
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent


def _fonte(rel: str) -> str:
    return (BACKEND / rel).read_text(encoding="utf-8")


def _codigo(fonte: str) -> str:
    """O fonte SEM comentario de linha.

    Existe porque este incremento deixou, de proposito, o codigo antigo citado
    nos comentarios ("aqui estava `owner.role == \"admin\"`") — e uma varredura
    que procura papel concedendo acesso encontraria justamente a explicacao de
    que ele parou de conceder. Cortar no `#` pode encurtar uma string que
    contenha o caractere, e nunca esconder codigo: o que vem ANTES do `#` fica."""
    return "\n".join(ln.split("#")[0] for ln in fonte.splitlines())


def _corpo(rel: str, inicio: str, fim: str) -> str:
    """O trecho entre duas ancoras do arquivo, ja sem comentario."""
    fonte = _fonte(rel)
    trecho = fonte[fonte.index(inicio):]
    return _codigo(trecho[:trecho.index(fim)])


# ---------------------------------------------------------------------------
# 0. "ACESSO TOTAL" TEM DE SER UMA LISTA SO
# ---------------------------------------------------------------------------
# Ate aqui "tudo" era a AUSENCIA de limite: `allowed_telas = None`. Virando dado,
# "tudo" passa a ser uma LISTA — e lista escrita em dois lugares diverge em
# silencio. `TELAS_TODAS` (que o suporte recebe) e o bloco `catalogo(tela)` da
# migration (que os admins receberam) tem de ser a mesma coisa, e as duas tem de
# ser o que a tela de Usuarios desenha.
def _telas_do_frontend() -> list[str]:
    f = REPO / "frontend" / "src" / "lib" / "telas.ts"
    if not f.exists():  # backend empacotado sozinho
        pytest.skip("frontend nao esta neste checkout")
    return re.findall(r'key:\s*"([a-z_]+)"', f.read_text(encoding="utf-8"))


def _telas_da_migration() -> list[str]:
    sql = (BACKEND / "migrations" / "add_role_vira_rotulo.sql").read_text(encoding="utf-8")
    bloco = sql[sql.index("catalogo(tela) AS ("):sql.index("INSERT INTO user_telas")]
    return re.findall(r"\('([a-z_]+)'\)", bloco)


def test_telas_todas_e_a_mesma_lista_do_backfill():
    from services.telas_catalog import TELAS_TODAS

    assert sorted(TELAS_TODAS) == sorted(_telas_da_migration()), (
        "dois 'acesso total' diferentes no mesmo sistema: o que a migration deu "
        "aos admins e o que o suporte da Alavank recebe"
    )
    assert len(TELAS_TODAS) == len(set(TELAS_TODAS))


# ⚠️ A UNICA CHAVE QUE PODE ESTAR SO NO BACKEND, e a excecao e documentada na
# fonte. `dashboard` SAIU do catalogo do frontend em 10/08/2026, a pedido do
# dono: desde a fusao de 29/07 o Painel de Indicadores E o /dashboard, e as duas
# entradas no modal de permissoes ("Dashboard" e "Painel de Indicadores")
# concediam a MESMA home — so confundiam quem da permissao. Ver o comentario no
# topo de `frontend/src/lib/telas.ts`.
#
# Ela CONTINUA em `TELAS_TODAS` porque essa lista e o "acesso total" do suporte
# da Alavank, e concessoes antigas gravadas com a chave `dashboard` seguem
# valendo — ela so nao e mais OFERECIDA como opcao nova.
#
# Este teste comparava as duas listas por igualdade e falhava desde aquele dia:
# uma decisao de produto aparecia como suite vermelha, e falha permanente e
# ruido — some no meio das outras e ensina a ignorar o arquivo. A excecao vira
# LISTA NOMEADA para que uma divergencia NOVA continue quebrando o teste.
SO_NO_BACKEND = {"dashboard"}


def test_telas_todas_e_a_mesma_lista_da_tela_de_usuarios():
    from services.telas_catalog import TELAS_TODAS

    backend, frontend = set(TELAS_TODAS), set(_telas_do_frontend())
    assert frontend - backend == set(), (
        "tela oferecida no frontend que o 'acesso total' do suporte nao cobre — "
        "quem administra veria uma caixinha que nem o suporte da Alavank tem")
    assert backend - frontend == SO_NO_BACKEND, (
        f"divergencia NOVA entre o catalogo do backend e o do frontend: "
        f"{sorted((backend - frontend) - SO_NO_BACKEND)}. Uma tela so no backend "
        f"e permissao que ninguem consegue conceder pela tela de Usuarios")


def test_telas_todas_contem_o_catalogo_oferecido_ao_cliente():
    """`TELAS_CATALOG` (o que o Console oferece) e SUBCONJUNTO: ele omite de
    proposito cofre/sessoes e as telas que nasceram depois dele. Uma chave que
    existisse so la seria uma permissao que o 'acesso total' nao cobre."""
    from services.telas_catalog import CATALOG_KEYS, TELAS_TODAS

    assert CATALOG_KEYS <= set(TELAS_TODAS)


# ---------------------------------------------------------------------------
# 1. A CONTA DE SUPORTE DA ALAVANK — a que ninguem lembra de conferir
# ---------------------------------------------------------------------------
def _corpo_sso() -> str:
    return _corpo("routers/control.py", "async def control_sso", "create_sso_token")


def test_o_usuario_de_suporte_recebe_escopo_escrito():
    """Sem isto o tecnico entra pelo SSO e ve menu vazio com 403 em tudo. O
    backfill da migration so alcancou as contas de suporte que ja existiam no
    dia do deploy; cada tecnico novo — e cada tenant novo — cria a sua depois."""
    corpo = _corpo_sso()
    assert "TELAS_TODAS" in corpo
    assert "INSERT INTO user_telas" in corpo
    assert "INSERT INTO user_municipios" in corpo


def test_o_usuario_de_suporte_nao_vira_super_admin():
    """Repor o que o papel concedia — nao mais que isso. `super_admin` daria ao
    suporte Sessoes, Service Tokens e poder sobre as contas donas da plataforma,
    que ele nao tinha ontem."""
    corpo = _corpo_sso()
    assert "super_admin" not in corpo.lower()


def test_o_escopo_do_suporte_e_reposto_a_cada_sessao():
    """Fora do `if u is None`: municipio cadastrado depois da ultima sessao de
    suporte tem de entrar sozinho na proxima. Conta sintetica nao tem dono
    humano para ajustar permissao, entao repor nao desfaz decisao de ninguem."""
    corpo = _corpo_sso()
    assert corpo.index("INSERT INTO user_telas") > corpo.index("elif not u.active:") > corpo.index("u = User(")


# ---------------------------------------------------------------------------
# 2. MUNICIPIO NOVO — cadastrar cidade nao pode nascer invisivel
# ---------------------------------------------------------------------------
def test_municipio_novo_alcanca_quem_tinha_a_carteira_inteira():
    """Antes, `role == "admin"` zerava o limite e a cidade nova aparecia no
    primeiro F5. Agora ela precisa de LINHA — e o criterio nao volta a ser o
    papel: e COBERTURA (quem ja tinha todos os OUTROS continua com todos)."""
    corpo = _corpo("routers/control.py", "async def upsert_municipio", "@router.patch")
    assert "if created:" in corpo, "reconceder a cada upsert desfaz revogacao"
    assert "INSERT INTO user_municipios" in corpo
    assert "NOT u.kiosk" in corpo, "link publico de TV nao pode crescer sozinho"
    assert "EXISTS (SELECT 1 FROM user_municipios um WHERE um.user_id = u.id)" in corpo, (
        "sem isto, 'tem todos os outros' e verdade VAZIA para quem nao tem nada "
        "e uma conta sem acesso ganharia a cidade nova"
    )
    assert "u.role" not in corpo, "o papel nao volta a conceder por aqui"


# ---------------------------------------------------------------------------
# 3. O QUIOSQUE — o link publico de TV nao pode GANHAR nada
# ---------------------------------------------------------------------------
def _corpo_kiosk() -> str:
    return _corpo("routers/bi.py", "async def _ensure_kiosk_user", '@router.get("/tela-filtros")')


def test_o_quiosque_nasce_marcado_e_somente_leitura():
    """`users.kiosk` e o que aplica `KIOSK_GET_PERMITIDOS` (PR #112) e
    `somente_leitura` e a trava de escrita a partir deste incremento. As duas
    eram preenchidas SO por backfill de boot: um link publicado as 10h ficava
    solto ate o proximo restart, com um token de 365 dias que circula em
    WhatsApp. Conta criada em runtime tem de nascer com o que a barra."""
    corpo = _corpo_kiosk()
    criacao = corpo[corpo.index("INSERT INTO users"):corpo.index("RETURNING id")]
    assert "kiosk" in criacao and "somente_leitura" in criacao
    reuso = corpo[corpo.index("UPDATE users SET"):corpo.index("WHERE id = :u")]
    assert "kiosk = true" in reuso and "somente_leitura = true" in reuso


def test_o_quiosque_espelha_o_dono_e_nao_o_papel_dele():
    """Aqui morava `owner.role == "admin"` -> "todos os municipios ativos".
    Valia enquanto o admin de fato enxergava todos; com o papel virado rotulo,
    um admin limitado a dois municipios publicaria uma TV com a carteira
    inteira — o link publico enxergando MAIS que quem o gerou."""
    corpo = _corpo_kiosk()
    assert 'owner.role == "admin"' not in corpo
    assert "is_super_admin(owner)" in corpo
    from routers import bi  # o import tem de existir, senao a rota quebra em runtime

    assert callable(bi.is_super_admin)


# ---------------------------------------------------------------------------
# 4. VARREDURA FINAL — sobrou papel CONCEDENDO em algum lugar?
# ---------------------------------------------------------------------------
# `role` pode continuar decidindo ACAO (quem administra a tela de Usuarios, o
# Cofre, o Status dos Dados) — isso e o Incremento 5. O que nao pode e decidir
# ESCOPO: o que a pessoa enxerga e ate onde ela alcanca.
GATES_DE_ACAO_PERMITIDOS = {
    "routers/users.py",       # _require_admin + guarda de auto-rebaixamento
    "routers/auth.py",        # /register
    "routers/freshness.py",   # Status dos Dados
    "routers/telegram.py",    # vinculo de bot
    "routers/cofre.py",       # credencial gov.br do cliente (sai no Incremento 5)
    "routers/control.py",     # contagem de admins ativos do canal do Console
    "services/auth.py",       # coberto pelos testes de load_user_scopes
}


@pytest.mark.parametrize("rel", [
    p.relative_to(BACKEND).as_posix()
    for p in sorted((BACKEND / "routers").glob("*.py")) + sorted((BACKEND / "services").glob("*.py"))
])
def test_nenhum_lugar_novo_usa_papel_para_conceder_escopo(rel):
    if rel in GATES_DE_ACAO_PERMITIDOS:
        pytest.skip("gate de ACAO conhecido — muda no Incremento 5")
    linhas = [
        ln for ln in _codigo(_fonte(rel)).splitlines()
        # `role` de mensagem de IA ("user"/"assistant") nao e papel de usuario
        if re.search(r'\.role\s*[!=]=\s*"(admin|prefeito|viewer|analyst|usuario)"', ln)
    ]
    assert not linhas, f"{rel}: papel decidindo acesso — {linhas}"
