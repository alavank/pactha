"""Prazo do link externo: por dias, ate uma data, ou sem prazo.

Por que testar isto: o link externo abre o painel SEM LOGIN. O prazo e a unica
trava automatica que existe — se ele nascer errado, o acesso sobra para alguem
que ja saiu da prefeitura, e ninguem descobre por conta propria.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from routers.bi import TelaLinkIn, _prazo_do_link, _DIAS_MAX_LINK


def _agora():
    return datetime.now(timezone.utc)


def test_por_dias_marca_a_data_e_o_token_com_o_mesmo_prazo():
    expira, dias = _prazo_do_link(TelaLinkIn(expira="dias", dias=3))
    assert dias == 3
    assert timedelta(days=2, hours=23) < (expira - _agora()) <= timedelta(days=3)


def test_sem_prazo_grava_NULO():
    """`expira_em = None` e o que o resolvedor publico entende como sem prazo:
    ele so compara a data quando ela existe."""
    expira, dias = _prazo_do_link(TelaLinkIn(expira="nunca"))
    assert expira is None
    # O TOKEN, esse, continua com validade — assinar por tempo infinito seria pior.
    assert dias == _DIAS_MAX_LINK


def test_ate_uma_data_vale_o_dia_INTEIRO():
    """Quem escolhe "10 de agosto" quer o dia 10 todo. Cortar a meia-noite do
    dia 9 seria entregar um dia a menos do que a tela prometeu."""
    alvo = (_agora() + timedelta(days=5)).date()
    expira, _ = _prazo_do_link(TelaLinkIn(expira="data", data_expiracao=alvo))
    assert expira.date() == alvo
    assert (expira.hour, expira.minute) == (23, 59)


def test_data_no_passado_e_recusada():
    """Sem isto o link nasceria morto e o gestor so descobriria ao entregar."""
    with pytest.raises(HTTPException) as e:
        _prazo_do_link(TelaLinkIn(expira="data", data_expiracao=date(2020, 1, 1)))
    assert e.value.status_code == 400


def test_data_ausente_e_recusada():
    with pytest.raises(HTTPException) as e:
        _prazo_do_link(TelaLinkIn(expira="data"))
    assert e.value.status_code == 400


@pytest.mark.parametrize("pedido,esperado", [
    (0, 1),                     # zero dia nao existe: minimo e 1
    (-5, 1),
    (99_999, _DIAS_MAX_LINK),   # teto
])
def test_dias_absurdos_caem_na_faixa(pedido, esperado):
    _, dias = _prazo_do_link(TelaLinkIn(expira="dias", dias=pedido))
    assert dias == esperado


def test_modo_desconhecido_cai_em_dias_e_NAO_vira_sem_prazo():
    """Falha fechada: um modo que o servidor nao entende tem de virar o
    comportamento COM prazo. Cair em "nunca" transformaria erro de digitacao em
    acesso permanente."""
    expira, _ = _prazo_do_link(TelaLinkIn(expira="qualquer-coisa", dias=7))
    assert expira is not None
