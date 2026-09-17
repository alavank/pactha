"""A saude da sessao gov.br vira fato no banco, e nao so linha de log.

Ate 31/08/2026 o resultado do keepalive so existia no log do container, que e
efemero: "ha quantas horas a sessao esta viva ou morta" era uma pergunta sem
resposta possivel no banco. A auditoria mediu a sessao morta 297,5h de 720h
(41%) sem que nada no produto dissesse isso.

⚠️ E `cofre_senhas.updated_at` nao servia de sinal: o keepalive re-salva os
cookies MESMO quando a navegacao caiu no idp, entao o carimbo subia com a sessao
morta.
"""
import os

import pytest

from ingestion.govbr_renew import (HEARTBEAT_MIN, SOURCE_SESSAO,
                                   _status_sessao)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_os_tres_SPs_vivos_e_sucesso():
    st, vivos, frase = _status_sessao(True, True, True)
    assert (st, vivos) == ("success", 3)
    assert "private=vivo" in frase and "execucao=vivo" in frase and "prestacao=vivo" in frase


def test_nenhum_vivo_e_erro():
    st, vivos, _ = _status_sessao(False, False, False)
    assert (st, vivos) == ("erro", 0)


def test_parcial_e_o_estado_QUE_FALTAVA():
    """⚠️ O caso que motivou tudo: `execucao` vivo e `prestacao` caido. Foi
    exatamente por os dois aparecerem como um so que as NEs morriam em silencio
    com o keepalive reportando "execucao=vivo"."""
    st, vivos, frase = _status_sessao(True, True, False)
    assert (st, vivos) == ("parcial", 2)
    assert "prestacao=CAIU" in frase
    st, vivos, _ = _status_sessao(True, False, False)
    assert (st, vivos) == ("parcial", 1)


def test_os_tres_SPs_aparecem_SEPARADOS_na_frase():
    """Somar os tres num numero so foi o defeito original. A frase tem de dizer
    QUAL caiu, senao o diagnostico volta a ser adivinhacao."""
    _, _, frase = _status_sessao(False, True, False)
    assert frase.count("=") == 3
    assert "private=CAIU" in frase
    assert "execucao=vivo" in frase
    assert "prestacao=CAIU" in frase


def test_o_vocabulario_e_o_que_o_frescor_JA_entende():
    """⚠️ 'success' | 'parcial' | 'erro', e nao 'alive'/'vivo'. Inventar
    vocabulario obrigaria a mexer no freshness E no watchdog — o custo de um nome
    bonito seriam dois lugares a mais para errar."""
    estados = {_status_sessao(a, b, c)[0]
               for a in (True, False) for b in (True, False) for c in (True, False)}
    assert estados == {"success", "parcial", "erro"}


def test_a_fonte_entra_no_painel_de_frescor():
    from routers.freshness import _SOURCES
    fontes = [s for s in _SOURCES if s[2] == SOURCE_SESSAO]
    assert len(fontes) == 1, "a sessao gov.br precisa aparecer no Status dos Dados"
    rotulo, sql, _ = fontes[0]
    assert "gov.br" in rotulo
    # ⚠️ Fonte SEM tabela propria: a sessao nao produz linha, ela HABILITA a
    # coleta da fatia atras do login. A consulta le o proprio ingestion_log.
    assert "ingestion_log" in sql and SOURCE_SESSAO in sql


def test_o_heartbeat_evita_afogar_o_painel():
    """⚠️ O keepalive roda de 10 em 10 minutos = 144 linhas/dia. O painel mostra
    as ~80 mais recentes; sem a janela, a sessao apagaria o historico de TODAS as
    outras fontes. Grava so quando o estado MUDA ou quando a ultima venceu."""
    assert HEARTBEAT_MIN >= 30, "janela curta demais volta a afogar o painel"
    import inspect

    from ingestion import govbr_renew as m
    # A regra mora no `_grava_estado`, que o registro dos SPs e o do login usam.
    assert "_grava_estado(" in inspect.getsource(m._registra_sessao)
    src = inspect.getsource(m._grava_estado)
    assert "ORDER BY id DESC LIMIT 1" in src, "sem ler a ultima linha nao ha como comparar"
    assert "HEARTBEAT_MIN" in src


def test_o_registro_NUNCA_derruba_o_keepalive():
    """⚠️ Best-effort de verdade. Este e um registro de OBSERVACAO: derrubar a
    coleta por causa da contabilidade da coleta seria trocar o remedio pela
    doenca."""
    import inspect

    from ingestion import govbr_renew as m
    src = inspect.getsource(m._grava_estado)
    assert "except Exception" in src
    assert "coleta segue" in src
