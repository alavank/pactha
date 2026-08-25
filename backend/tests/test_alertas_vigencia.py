"""
`GET /api/convenios/alertas` — quem pede SEM `municipio_id`.

⭐ O DEFEITO QUE ESTE ARQUIVO TRAVA (medido no freitas em 24/08/2026)

O botao «Vigencias <=120d» do Painel de Indicadores pede a carteira INTEIRA
(`components/bi/VigenciasModal.tsx` chama sem `municipio_id`, de proposito). Mas
o handler abria com `ensure_municipio_access(current, municipio_id)`, e essa
guarda levanta 403 quando o municipio vem None e o usuario nao e super-admin —
nos DOIS modos de AUTHZ_MODO. O 403 chegava ANTES da checagem de permissao.

Consequencia: conceder `vigencias.ver` (ou ate `convenios.ver`) nao mudava nada
na tela, porque o modal traduz 403 em «voce nao tem acesso». O administrador
marcava a caixinha e a pessoa continuava sem ver — sem erro em lugar nenhum que
ligasse uma coisa a outra. Funcionava so para o super-admin, que e quem testa.

No log do freitas-api:
    GET /api/convenios/alertas?dias=120 -> 403 Forbidden   (o modal)
    GET /api/bi/alertas?municipio_id=8  -> 200 OK          (o que passa municipio)

Os dois primeiros testes sao a regressao. Os outros tres existem para que a
correcao nao vire um alargamento: municipio alheio continua barrado, carteira
vazia nao lista nada, e quem nao tem NENHUMA das duas chaves continua negado.

Rodar:
    python -m pytest backend/tests/test_alertas_vigencia.py -v
"""
import asyncio

import pytest
from fastapi import HTTPException

from routers import convenios
from services import authz


class Usuario:
    """O que o handler le do User depois de `load_user_scopes`."""

    def __init__(self, permissoes=None, municipios=None, telas=None,
                 super_admin=False):
        self.id = 7
        self.email = "marcia@freitas.com.br"
        self.name = "Marcia"
        self.role = "usuario"
        self.active = True
        self.kiosk = False
        self.super_admin = super_admin
        self.somente_leitura = False
        self.allowed_permissoes = permissoes
        self.allowed_telas = set() if telas is None else telas
        # ⚠️ None = super-admin (ver services/auth.py::load_user_scopes). Para
        # todo o resto e um conjunto, e era ele que fazia a guarda negar.
        self.allowed_municipio_ids = municipios


@pytest.fixture(autouse=True)
def _isolar(monkeypatch):
    authz.limpar_dedupe()
    authz.limpar_contexto()
    # `bloqueio` e o que roda no freitas: garante que negativa aqui e negativa
    # de verdade, e nao um falso verde do modo aviso.
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    yield
    authz.limpar_dedupe()
    authz.limpar_contexto()


@pytest.fixture
def nucleo(monkeypatch):
    """Captura o recorte com que o handler chama o nucleo (sem tocar no banco)."""
    chamadas = []

    async def falso(db, municipio_id, dias, anos, municipio_ids=None):
        chamadas.append({"municipio_id": municipio_id, "dias": dias,
                         "municipio_ids": municipio_ids})
        return []

    monkeypatch.setattr(convenios, "query_alertas_vigencia", falso)
    return chamadas


def chamar(user, municipio_id=None, dias=120):
    # Chamada direta: os defaults da assinatura sao objetos `Query`, entao todo
    # argumento vai explicito. `db=None` e seguro porque o nucleo esta mockado e
    # a busca de nomes so acontece quando ha alertas.
    return asyncio.run(convenios.alertas_vigencia(
        municipio_id=municipio_id, dias=dias, ano=None, anos=None,
        db=None, current=user))


# ---------------------------------------------------------------- regressao
def test_sem_municipio_com_vigencias_ver_nao_e_barrada(nucleo):
    """O caso do botao: carteira restrita, caixinha nova, SEM municipio."""
    u = Usuario(permissoes={"vigencias.ver"}, municipios={8})
    assert chamar(u) == []
    # Passou — e passou recortado na carteira dela, nao no tenant inteiro.
    assert nucleo[0]["municipio_ids"] == [8]


def test_sem_municipio_com_convenios_ver_tambem_passa(nucleo):
    """Quem ja tinha o modulo inteiro tambem estava sendo barrado pelo mesmo 403."""
    u = Usuario(permissoes={"convenios.ver"}, municipios={8},
                telas={"convenios"})
    assert chamar(u) == []
    assert nucleo[0]["municipio_ids"] == [8]


# ------------------------------------------------- a correcao nao alargou nada
def test_municipio_fora_da_carteira_continua_barrado(nucleo):
    """A guarda so deixou de rodar com None — nomeando municipio ela vale igual."""
    u = Usuario(permissoes={"vigencias.ver"}, municipios={8})
    with pytest.raises(HTTPException) as e:
        chamar(u, municipio_id=99)
    assert e.value.status_code == 403
    assert not nucleo, "nao pode consultar municipio que a pessoa nao alcanca"


def test_carteira_vazia_nao_lista_nada(nucleo):
    u = Usuario(permissoes={"vigencias.ver"}, municipios=set())
    assert chamar(u) == []
    assert not nucleo, "carteira vazia nao chega a consultar"


def test_sem_nenhuma_das_duas_chaves_nega(nucleo):
    u = Usuario(permissoes=set(), municipios={8})
    with pytest.raises(HTTPException) as e:
        chamar(u)
    assert e.value.status_code == 403
    assert not nucleo


def test_super_admin_continua_vendo_o_tenant_inteiro(nucleo):
    """`municipio_ids=None` = sem recorte. Comportamento de antes, preservado."""
    u = Usuario(permissoes=None, municipios=None, super_admin=True)
    assert chamar(u) == []
    assert nucleo[0]["municipio_ids"] is None
