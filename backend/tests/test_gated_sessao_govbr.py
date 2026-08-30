"""Sessão gov.br fria: a rodada não pode sair 'success' com a fatia gated vazia.

Origem: auditoria externa (29/08/2026) — *"a sessão ficou inoperante 41% do
tempo; notas de empenho, projeto básico, licitação e cláusula pararam de
atualizar, e o robô registra a rodada com status global de 'sucesso'"*.

A verificação confirmou o MECANISMO e refinou a causa. As guardas contra o "200
veneno" **já existem** (o SAML de visitante não vira `{}` nem apaga dado — os
leitores devolvem `None` corretamente e o COALESCE preserva). O defeito é outro,
e mais estreito: **o status da rodada era montado a partir de duas dimensões
apenas** — município falhou? paginação veio curta? — então a terceira, *"a fatia
atrás do login não respondeu"*, não tinha como virar `parcial`.

Resultado: tudo funcionava como projetado, cada peça devolvia o valor certo, e
mesmo assim o apagão ficava invisível para o monitor de frescor e para o
watchdog — que leem exatamente esta linha do `ingestion_log`.
"""
import pytest

import ingestion.transferegov_voluntarias as m


@pytest.fixture(autouse=True)
def _limpo():
    m._gated_zera()
    yield
    m._gated_zera()


def test_rodada_sem_leitura_gated_NAO_vira_parcial():
    """⚠️ A guarda que impede o pior efeito colateral. Tenant com
    `TG_HTTP_ENRICH`/`TG_NES` desligado nunca pergunta — e não pode nascer
    amarelo permanente por isso. `tentadas == 0` devolve None, nunca uma divisão
    solta."""
    for _ in range(5):
        m._gated_conta(False, False)
    assert m._gated_frase() is None


def test_tudo_respondeu_e_success():
    for _ in range(6):
        m._gated_conta(True, True)
    assert m._gated_frase() is None


def test_METADE_sem_retorno_ja_rebaixa():
    """Uma ou outra falha é ruído do portal; metade é sessão fria."""
    for _ in range(4):
        m._gated_conta(True, True)
    for _ in range(4):
        m._gated_conta(True, False)
    f = m._gated_frase()
    assert f and "sessao gov.br fria" in f and "4/8" in f


def test_abaixo_da_metade_nao_rebaixa():
    """Não transformar ruído em alarme: o watchdog perde o valor se apitar
    sempre."""
    for _ in range(7):
        m._gated_conta(True, True)
    for _ in range(3):
        m._gated_conta(True, False)
    assert m._gated_frase() is None


def test_apagao_TOTAL_e_o_caso_do_relatorio():
    """O cenário da auditoria: a sessão morreu e NENHUMA leitura atrás do login
    respondeu. Antes isso saía 'success'."""
    for _ in range(9):
        m._gated_conta(True, False)
    f = m._gated_frase()
    assert f and "9/9" in f
    assert "NAO atualizou" in f, "a frase tem de dizer o que ficou velho"


def test_o_contador_ZERA_entre_rodadas():
    """⚠️ É contador de MÓDULO (mesmo molde de `_PAGINACAO_INCOMPLETA`). Sem o
    reset, uma rodada ruim contaminaria todas as seguintes do mesmo processo."""
    for _ in range(4):
        m._gated_conta(True, False)
    assert m._gated_frase() is not None
    m._gated_zera()
    assert m._gated_frase() is None


def test_as_duas_rodadas_zeram_o_contador():
    """`run()` (diária) e `run_proximos()` (lote horário) — as duas gravam
    `ingestion_log` e as duas precisam do reset."""
    import inspect
    for fn in (m.run, m.run_proximos):
        assert "_gated_zera()" in inspect.getsource(fn), fn.__name__


def test_o_eixo_gated_entra_nos_DOIS_calculos_de_status():
    """O lote horário é quem de fato atualiza a carteira ao longo do dia — deixar
    o eixo só na diária esconderia o apagão 11 vezes por dia."""
    import inspect
    for fn in (m.run, m.run_proximos):
        assert "_gated_frase()" in inspect.getsource(fn), fn.__name__


def test_o_eixo_NUNCA_rebaixa_erro_para_parcial():
    """⚠️ A ordem dos ramos importa: o teste de 'erro' vem ANTES. Uma rodada em
    que todo município falhou continua 'erro' mesmo com a sessão fria — o eixo
    gated só ACRESCENTA motivo."""
    import inspect
    for fn in (m.run, m.run_proximos):
        src = inspect.getsource(fn)
        i_erro = src.index('= "erro"')
        i_parc = src.index('= "parcial"')
        assert i_erro < i_parc, fn.__name__


def test_a_frase_usa_o_vocabulario_que_o_frescor_JA_entende():
    """`parcial` já é lido por `freshness._DEGRADADO` e pelo watchdog. Inventar um
    status novo exigiria mexer nas duas telas."""
    import inspect
    for fn in (m.run, m.run_proximos):
        assert '"parcial"' in inspect.getsource(fn), fn.__name__
