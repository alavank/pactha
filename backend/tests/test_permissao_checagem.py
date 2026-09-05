"""
`authz.exigir(user, "rm.excluir")` — a checagem de permissao por ACAO.

Ela e a TERCEIRA trava do sistema, e as tres respondem perguntas diferentes:

    ensure_tela / exigir_tela   ->  a pessoa enxerga este MODULO?
    ensure_municipio / dono     ->  ela alcanca ESTE municipio / ESTA linha?
    exigir(...)  (aqui)         ->  ela pode FAZER ISTO?

As tres valem juntas: a permissao diz O QUE, o municipio diz ONDE. Um endpoint
de escrita escopado continua precisando das duas linhas.

⚠️ E ela respeita `AUTHZ_MODO` como o resto do incremento — em `aviso` deixa
passar e registra "eu teria negado", em `bloqueio` levanta 403. E o mesmo motivo
de sempre: ligar 66 permissoes novas de uma vez, num sistema onde ninguem nunca
teve nenhuma, e o apagao de segunda-feira.

Rodar:
    python -m pytest backend/tests/test_permissao_checagem.py -v
"""
import pytest
from fastapi import HTTPException

from services import authz
from services.permissoes import CATALOGO, TODAS

MSG = "Voce nao tem permissao para esta acao"


class Usuario:
    """O que o codigo real le do User depois de `load_user_scopes`."""

    def __init__(self, permissoes=None, super_admin=False, somente_leitura=False,
                 kiosk=False, active=True, role="usuario",
                 email="servidor@montesiao.mg.gov.br", id=7, name="Servidor"):
        self.id = id
        self.email = email
        self.name = name
        self.role = role
        self.active = active
        self.kiosk = kiosk
        self.super_admin = super_admin
        self.somente_leitura = somente_leitura
        self.allowed_permissoes = permissoes
        self.allowed_telas = set()
        self.allowed_municipio_ids = set()


@pytest.fixture(autouse=True)
def _isolar(monkeypatch):
    authz.limpar_dedupe()
    authz.limpar_contexto()
    monkeypatch.delenv("AUTHZ_MODO", raising=False)
    yield
    authz.limpar_dedupe()
    authz.limpar_contexto()


@pytest.fixture
def envios(monkeypatch):
    """Intercepta o agendamento da gravacao — senao o teste abriria sessao de
    banco de verdade."""
    registrados: list = []
    monkeypatch.setattr(authz, "_enviar", lambda dados: registrados.append(dados) or True)
    return registrados


@pytest.fixture
def aviso(monkeypatch):
    monkeypatch.setenv("AUTHZ_MODO", "aviso")


@pytest.fixture
def bloqueio(monkeypatch):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")


@pytest.fixture(params=["aviso", "bloqueio"])
def qualquer_modo(request, monkeypatch):
    monkeypatch.setenv("AUTHZ_MODO", request.param)
    return request.param


# ===========================================================================
# O caso central
# ===========================================================================
def test_quem_tem_a_permissao_passa_sem_ruido(qualquer_modo, envios):
    authz.exigir(Usuario(permissoes={"rm.excluir"}), "rm.excluir")
    assert envios == []


def test_quem_nao_tem_e_barrado_em_bloqueio(bloqueio, envios):
    with pytest.raises(HTTPException) as e:
        authz.exigir(Usuario(permissoes={"rm.ver"}), "rm.excluir")
    assert e.value.status_code == 403
    assert e.value.detail == MSG
    assert [x["acao"] for x in envios] == [authz.ACAO_NEGOU]
    assert envios[0]["detalhes"]["exigido"] == "rm.excluir"
    assert envios[0]["detalhes"]["exigencia"] == "permissao"


def test_em_aviso_passa_e_registra(aviso, envios):
    """A promessa do incremento: em modo aviso a resposta e a de hoje, inteira.
    O esbarrao vira linha na trilha para o dono corrigir o cadastro ANTES de
    ligar a trava."""
    authz.exigir(Usuario(permissoes={"rm.ver"}), "rm.excluir")   # nao levanta
    assert [x["acao"] for x in envios] == [authz.ACAO_NEGARIA]
    assert envios[0]["detalhes"]["possui"] == ["rm.ver"]


def test_a_mensagem_e_de_ACAO_e_nao_de_tela(bloqueio):
    """Quem le "Voce nao tem acesso a esta tela" depois de clicar em Excluir
    procura o erro no lugar errado — e o administrador concede a tela inteira
    quando faltava uma caixinha."""
    with pytest.raises(HTTPException) as e:
        authz.exigir(Usuario(permissoes=set()), "rm.excluir")
    assert e.value.detail != "Voce nao tem acesso a esta tela"
    assert e.value.detail == MSG


# ===========================================================================
# Super-admin: a regra do dono
# ===========================================================================
@pytest.mark.parametrize("chave", sorted(CATALOGO))
def test_super_admin_pode_tudo(bloqueio, chave):
    """"Esses tem tudo, fazem tudo no sistema... eles sao tipo ROOT" — sem
    caixinha marcada, em todas as 66 permissoes."""
    authz.exigir(Usuario(super_admin=True, permissoes=None), chave)


def test_super_admin_pela_ALLOWLIST_de_email_tambem_passa(bloqueio):
    """A coluna e a autoridade, mas a lista de e-mails continua valendo como
    reforco: banco sem a coluna (migracao pendente, tenant novo) nao pode
    trancar a Alavank fora do proprio produto."""
    dono = Usuario(super_admin=False, permissoes=set(),
                   email="alavank.tecnologia@gmail.com")
    authz.exigir(dono, "cofre.revelar")


def test_super_admin_nao_faz_ruido_na_trilha(bloqueio, envios):
    authz.exigir(Usuario(super_admin=True), "usuarios.excluir")
    assert envios == []


# ===========================================================================
# As outras flags do usuario
# ===========================================================================
def test_ve_mas_nao_edita_sai_das_CAIXINHAS_e_nao_de_uma_trava_de_conta(bloqueio):
    """⭐ ESTE TESTE MEDIA OUTRA COISA ATE 05/09/2026: a trava de conta «somente
    leitura», que subtraia os verbos de escrita mesmo com a caixinha marcada.
    Ela foi removida por decisao do dono, que preferiu o controle mais fino —
    "prefiro dar permissao de visualizaçao separada pra cada menu ou modulo dai
    eu permito so visualizar sem editar nada".

    A capacidade continua existindo, e e ela que este teste passa a medir: a
    pessoa que tem `rm.ver` e NAO tem `rm.excluir` ve e nao apaga. A diferenca
    pratica e que agora da para ser leitor no Cofre e escritor na Gestao
    Interna, o que a trava de conta nunca permitiu."""
    usuario = Usuario(permissoes={"rm.ver"})
    authz.exigir(usuario, "rm.ver")
    with pytest.raises(HTTPException):
        authz.exigir(usuario, "rm.excluir")


def test_conta_desativada_nao_pode_nada(bloqueio):
    with pytest.raises(HTTPException):
        authz.exigir(Usuario(permissoes={"rm.ver"}, active=False), "rm.ver")


def test_quiosque_so_alcanca_o_painel(bloqueio):
    """⚠️ O link publico de TV e um `viewer` REAL sem linha em
    `user_permissoes`. Sem o conjunto fixo do quiosque, o dia em que o BI
    declarar `bi.ver` seria o dia em que toda TV de gabinete apagou."""
    tv = Usuario(kiosk=True, permissoes=None)
    authz.exigir(tv, "bi.ver")
    with pytest.raises(HTTPException):
        authz.exigir(tv, "cofre.revelar")


def test_quiosque_nao_herda_poder_de_super_admin(bloqueio):
    tv = Usuario(kiosk=True, super_admin=True, permissoes=None)
    with pytest.raises(HTTPException):
        authz.exigir(tv, "usuarios.excluir")


# ===========================================================================
# Erro de programacao x falta de permissao
# ===========================================================================
@pytest.mark.parametrize("errada", ["rm.excluri", "documentos", "", "rm.*",
                                    "nao.existe"])
def test_chave_fora_do_catalogo_levanta_ValueError(qualquer_modo, errada):
    """E erro de PROGRAMACAO num literal do router, e ele tem de gritar. Tratado
    como "sem permissao", viraria um 403 permanente e silencioso: o endpoint
    negaria TODO MUNDO, inclusive o super-admin, e ninguem saberia por que."""
    with pytest.raises(ValueError):
        authz.exigir(Usuario(super_admin=True), errada)


def test_chave_com_caixa_e_espaco_e_normalizada(bloqueio):
    authz.exigir(Usuario(permissoes={"rm.ver"}), "  RM.Ver ")


# ===========================================================================
# `pode` — o gate de LISTAGEM
# ===========================================================================
def test_pode_nao_levanta_e_nao_registra(bloqueio, envios):
    """O gate de uma listagem e o FILTRO, nao o 403: negar a tela inteira de
    quem tem escopo legitimo e o oposto do que este incremento quer."""
    usuario = Usuario(permissoes={"rm.ver"})
    assert authz.pode(usuario, "rm.ver") is True
    assert authz.pode(usuario, "rm.excluir") is False
    assert envios == []


def test_pode_de_chave_inexistente_e_False_e_nao_explode():
    """Diferente de `exigir`: `pode` responde uma pergunta, e a resposta
    fail-closed para uma chave que nao existe e "nao pode"."""
    assert authz.pode(Usuario(super_admin=True), "nao.existe") is False


def test_permissoes_de_devolve_o_conjunto_efetivo():
    assert authz.permissoes_de(Usuario(super_admin=True)) == TODAS
    assert authz.permissoes_de(Usuario(permissoes={"rm.ver"})) == {"rm.ver"}
    assert authz.permissoes_de(Usuario(permissoes=None)) == frozenset()


# ===========================================================================
# A trilha nao pode derrubar a requisicao
# ===========================================================================
def test_falha_da_trilha_nao_derruba_em_aviso(aviso, monkeypatch):
    """A garantia mais dura do incremento: se o registro quebrar, a requisicao
    segue. Um gate feito para NAO quebrar nada nao pode quebrar pelo proprio
    log."""
    def _explode(*a, **k):
        raise RuntimeError("banco de auditoria fora do ar")

    monkeypatch.setattr(authz, "_observar", _explode)
    authz.exigir(Usuario(permissoes=set()), "rm.ver")     # nao levanta


def test_falha_da_trilha_nao_impede_o_403(bloqueio, monkeypatch):
    """Em bloqueio vale o inverso: o 403 sai mesmo que a linha nao entre."""
    def _explode(*a, **k):
        raise RuntimeError("banco de auditoria fora do ar")

    monkeypatch.setattr(authz, "_observar", _explode)
    with pytest.raises(HTTPException):
        authz.exigir(Usuario(permissoes=set()), "rm.ver")


def test_negativas_iguais_sao_deduplicadas(bloqueio, envios):
    """Uma tela dispara varias chamadas por carregamento; sem dedupe a trilha
    afoga na semana em que ela precisa ser lida."""
    usuario = Usuario(permissoes=set())
    for _ in range(5):
        with pytest.raises(HTTPException):
            authz.exigir(usuario, "rm.ver")
    assert len(envios) == 1
