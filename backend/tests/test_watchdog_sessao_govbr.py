"""O vigia avisa quando o LOGIN gov.br expira.

⭐ O QUE ESTE ARQUIVO EXISTE PARA IMPEDIR

De 14 a 17/09/2026 a sessao gov.br morreu nos SEIS tenants e ninguem soube por ~2
dias. O `govbr-renew` escrevia `needs_recapture` de hora em hora — so no log do
container. O `govbr_sessao` que ja estava no banco mede o /private/ das
mandatarias, caido quase sempre mesmo com o login bom, entao nao servia de
gatilho. Sem sessao param detalhe, NEs, Termos de Notificacao, Projeto Basico e
os anexos do TransfereGov, e so uma pessoa resolve (o login tem reCAPTCHA).

Rodar:
    python -m pytest backend/tests/test_watchdog_sessao_govbr.py -v
"""
import inspect
import re

import pytest

from ingestion import govbr_renew, watchdog_coleta as W


class CursorFalso:
    """Devolve as respostas na ordem das consultas e guarda o SQL executado."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.sqls = []

    def execute(self, sql, params=None):
        self.sqls.append(sql)

    def fetchone(self):
        return self.respostas.pop(0)


def test_sem_nenhuma_linha_nao_alarma():
    """Tenant sem a task `govbr-renew` nao grava nada — nao e sessao caida."""
    assert W._sessao_govbr_caida(CursorFalso(None)) == []


def test_ultima_renovacao_ok_nao_alarma():
    assert W._sessao_govbr_caida(CursorFalso(("success", None))) == []


def test_tenant_que_nunca_capturou_nao_e_cobrado():
    """Cobrar recaptura de quem nunca capturou e alarme eterno."""
    cur = CursorFalso(("erro", W.FRASE_SEM_SESSAO))
    assert W._sessao_govbr_caida(cur) == []


def test_queda_curta_ainda_nao_alarma():
    """Uma renovacao falha pode ser o portal fora do ar por minutos."""
    cur = CursorFalso(("erro", "SSO expirou"), (1.5, "16/09 22:00", True))
    assert W._sessao_govbr_caida(cur) == []


def test_sessao_caida_ha_59h_alarma_com_o_que_fazer():
    cur = CursorFalso(("erro", "SSO expirou"), (59.2, "14/09 11:04", True))
    [a] = W._sessao_govbr_caida(cur)
    assert a["tipo"] == "sessao_govbr_caida"
    assert a["chave"] == "govbr_sso"
    assert "59h" in a["detalhe"]
    assert "14/09 11:04" in a["detalhe"]
    # O alarme tem de dizer a ACAO, nao so o sintoma.
    assert "extensao do PACTHA" in a["detalhe"]
    assert "anexos" in a["detalhe"]


def test_sem_nenhum_sucesso_ainda_alarma_pela_primeira_linha():
    """⚠️ O caso do DEPLOY deste vigia: em 17/09/2026 os seis ja estavam sem
    sessao, entao `govbr_sso` nasce sem um unico success. Exigir sucesso anterior
    deixaria o alarme mudo exatamente quando ele foi pedido."""
    cur = CursorFalso(("erro", "SSO expirou"), (4.0, "17/09 00:00", False))
    [a] = W._sessao_govbr_caida(cur)
    assert "desde que o vigia passou a medir" in a["detalhe"]


def test_o_sql_e_postgres_valido():
    pglast = pytest.importorskip("pglast")
    cur = CursorFalso(("erro", "x"), (10.0, "01/01 00:00", True))
    W._sessao_govbr_caida(cur)
    for sql in cur.sqls:
        pglast.parse_sql(re.sub(r"%s", "NULL", sql))


def test_nome_e_frase_iguais_nos_dois_lados():
    """O vigia repete as constantes para nao importar Playwright/crypto. Se um
    lado mudar sozinho, o alarme fica mudo ou vira eterno — calado."""
    assert W.SOURCE_SSO == govbr_renew.SOURCE_SSO
    assert W.FRASE_SEM_SESSAO == govbr_renew.FRASE_SEM_SESSAO


@pytest.mark.parametrize("resultado,status,frase", [
    ("reconnected", "success", None),
    ("needs_recapture", "erro", govbr_renew.FRASE_SSO_EXPIROU),
    ("no_session", "erro", govbr_renew.FRASE_SEM_SESSAO),
])
def test_renew_grava_o_resultado(monkeypatch, resultado, status, frase):
    gravado = []
    monkeypatch.setattr(govbr_renew, "_grava_estado",
                        lambda src, st, n, erro: gravado.append((src, st, erro)))
    govbr_renew._registra_sso(resultado)
    assert gravado == [("govbr_sso", status, frase)]


def test_o_renew_de_verdade_chama_o_registro():
    """Sem esta linha no `__main__`, a fonte nunca ganha linha e o vigia fica mudo."""
    src = inspect.getsource(govbr_renew)
    principal = src[src.index('if __name__ == "__main__":'):]
    assert "_registra_sso(" in principal


def test_cooldown_proprio_e_mais_longo_que_o_padrao():
    """So uma pessoa resolve: repetir a cada 3h nos seis tenants enche o canal."""
    assert W.SESSAO_COOLDOWN_MIN > 180
    assert "SESSAO_COOLDOWN_MIN" in inspect.getsource(W.main)


def test_o_main_consulta_a_sessao():
    assert "_sessao_govbr_caida(cur)" in inspect.getsource(W.main)
