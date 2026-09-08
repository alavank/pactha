"""
Canais de saída do watchdog da coleta — Telegram (canal 4) e o pulso externo.

⭐ O QUE ESTE ARQUIVO EXISTE PARA IMPEDIR

O watchdog passou de 11/08 a 08/09/2026 **detectando e não avisando ninguém**:
`WATCHDOG_WEBHOOK_URL` estava vazia nos cinco workers, então ele media coleta
parada e escrevia num lugar que ninguém abria. Foi assim que a regularidade
estadual ficou 6 dias travada sem ninguém notar (CONTINUAR.md §1.18). Em
08/09/2026 o dono escolheu o Telegram, e este arquivo guarda as três formas de
o canal novo repetir a mesma história — todas silenciosas:

1. **O `_` do nome da fonte matando o alerta.** A mensagem carrega `*negrito*` e
   crase do tempo do Markdown legado. Se alguém "melhorar" mandando
   `parse_mode`, um `_` solto — e as fontes se chamam `transferegov_opendata`,
   `sigcon_scraper`, `simec_par` — faz a API devolver 400 «can't parse entities»
   e o alerta some. Um vigia não pode falhar em função do nome do que vigia.
2. **Falha de um canal derrubando os outros.** O alerta já é a notícia ruim; não
   pode virar duas.
3. **O pulso invertido.** Rodada saudável é a mais comum: se ela não pulsar, o
   vigia externo alarma justamente nos dias em que está tudo bem.

Rodar:
    python -m pytest backend/tests/test_watchdog_canais.py -v
"""
import json

import pytest

from ingestion import watchdog_coleta


class RespostaFalsa:
    """O bastante do retorno de `urlopen` para o `with ... as r: r.status`."""

    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def capturar(monkeypatch):
    """Intercepta `urlopen` e devolve a lista do que foi enviado.

    O módulo importa `urllib.request` DENTRO de cada função, então trocar o
    atributo no módulo real é o que alcança as duas chamadas.
    """
    import urllib.request

    enviados = []

    def falso(req, timeout=None):
        if isinstance(req, str):
            enviados.append({"url": req, "corpo": None})
        else:
            corpo = req.data.decode("utf-8") if req.data else None
            enviados.append({"url": req.full_url,
                             "corpo": json.loads(corpo) if corpo else None})
        return RespostaFalsa()

    monkeypatch.setattr(urllib.request, "urlopen", falso)
    return enviados


def _envs_telegram(monkeypatch, token="123:ABC", chat="555"):
    monkeypatch.setenv("WATCHDOG_TELEGRAM_TOKEN", token)
    monkeypatch.setenv("WATCHDOG_TELEGRAM_CHAT_ID", chat)


# --------------------------------------------------------------------------
# 1. Sem env, o canal é inerte — é o que permite ligar num tenant só.
# --------------------------------------------------------------------------

def test_telegram_sem_envs_nao_faz_requisicao(monkeypatch, capturar):
    monkeypatch.delenv("WATCHDOG_TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("WATCHDOG_TELEGRAM_CHAT_ID", raising=False)

    watchdog_coleta._telegram("🟠 PACTHA freitas — fonte parada")

    assert enviados_vazios(capturar)


def test_telegram_com_meia_credencial_nao_envia(monkeypatch, capturar):
    """Token sem chat_id (ou o contrário) não é meio canal: é canal nenhum."""
    monkeypatch.setenv("WATCHDOG_TELEGRAM_TOKEN", "123:ABC")
    monkeypatch.delenv("WATCHDOG_TELEGRAM_CHAT_ID", raising=False)

    watchdog_coleta._telegram("🟠 alerta")

    assert enviados_vazios(capturar)


def enviados_vazios(enviados):
    return len(enviados) == 0


# --------------------------------------------------------------------------
# 2. A armadilha do `_` — a regressão que este arquivo existe para travar.
# --------------------------------------------------------------------------

def test_telegram_nao_manda_parse_mode(monkeypatch, capturar):
    """Se voltar `parse_mode`, o alerta some no dia em que a fonte quebra.

    `transferegov_opendata` tem um `_`; no Markdown legado isso abre itálico que
    nunca fecha, e a API responde 400 em vez de entregar.
    """
    _envs_telegram(monkeypatch)

    watchdog_coleta._telegram(
        "🟠 *PACTHA freitas* — fonte parada\n`transferegov_opendata`\n"
        "ultimo success ha 31h (esperado <=30h)")

    assert len(capturar) == 1
    assert "parse_mode" not in capturar[0]["corpo"]


def test_telegram_remove_marcadores_de_markdown(monkeypatch, capturar):
    _envs_telegram(monkeypatch)

    watchdog_coleta._telegram(
        "🟠 *PACTHA freitas* — fonte parada\n`sigcon_scraper`\ndetalhe")

    texto = capturar[0]["corpo"]["text"]
    assert "*" not in texto and "`" not in texto
    # O conteúdo continua todo lá — tirar marcador não é tirar informação.
    assert "PACTHA freitas" in texto and "sigcon_scraper" in texto


def test_telegram_corta_no_limite_da_api(monkeypatch, capturar):
    """4.096 é o teto do sendMessage; a carteira da Freitas tem 44 municípios."""
    _envs_telegram(monkeypatch)

    watchdog_coleta._telegram("x" * 9000)

    assert len(capturar[0]["corpo"]["text"]) <= 4096


def test_telegram_manda_chat_id_e_token_na_url(monkeypatch, capturar):
    _envs_telegram(monkeypatch, token="999:XYZ", chat="777")

    watchdog_coleta._telegram("alerta")

    assert capturar[0]["url"] == "https://api.telegram.org/bot999:XYZ/sendMessage"
    assert capturar[0]["corpo"]["chat_id"] == "777"


# --------------------------------------------------------------------------
# 3. Isolamento entre canais.
# --------------------------------------------------------------------------

def test_falha_no_webhook_nao_impede_o_telegram(monkeypatch, capturar):
    """O alerta já é a notícia ruim; não pode virar duas."""
    import urllib.request

    _envs_telegram(monkeypatch)
    monkeypatch.setenv("WATCHDOG_WEBHOOK_URL", "https://exemplo.invalido/hook")

    original = urllib.request.urlopen

    def falha_no_hook(req, timeout=None):
        alvo = req if isinstance(req, str) else req.full_url
        if "exemplo.invalido" in alvo:
            raise OSError("connection refused")
        return original(req, timeout=timeout)

    monkeypatch.setattr(urllib.request, "urlopen", falha_no_hook)

    watchdog_coleta._alerta("🟠 alerta", cur=None, tipo="fonte_parada", chave="fns")

    assert len(capturar) == 1
    assert "api.telegram.org" in capturar[0]["url"]


def test_telegram_quebrado_nao_derruba_a_rodada(monkeypatch):
    """Canal é best-effort: exceção aqui não pode subir e matar o cron."""
    import urllib.request

    _envs_telegram(monkeypatch)

    def sempre_falha(req, timeout=None):
        raise OSError("timeout")

    monkeypatch.setattr(urllib.request, "urlopen", sempre_falha)

    watchdog_coleta._telegram("alerta")  # não levanta


def test_falha_do_telegram_nao_vaza_o_token_no_log(monkeypatch, caplog):
    """A URL da API CARREGA o token, e o HTTPError põe a URL na mensagem."""
    import urllib.request

    _envs_telegram(monkeypatch, token="123:TOKEN-SECRETO-QUE-NAO-PODE-VAZAR")

    def erro_com_url(req, timeout=None):
        raise OSError(f"HTTP Error 401: {req.full_url} recusou")

    monkeypatch.setattr(urllib.request, "urlopen", erro_com_url)

    with caplog.at_level("WARNING"):
        watchdog_coleta._telegram("alerta")

    assert "TOKEN-SECRETO-QUE-NAO-PODE-VAZAR" not in caplog.text


# --------------------------------------------------------------------------
# 4. O pulso externo.
# --------------------------------------------------------------------------

def test_heartbeat_sem_env_nao_pinga(monkeypatch, capturar):
    monkeypatch.delenv("WATCHDOG_HEARTBEAT_URL", raising=False)

    watchdog_coleta._heartbeat()

    assert enviados_vazios(capturar)


def test_heartbeat_pinga_a_url_configurada(monkeypatch, capturar):
    monkeypatch.setenv("WATCHDOG_HEARTBEAT_URL", "https://hc-ping.com/abc-123")

    watchdog_coleta._heartbeat()

    assert capturar[0]["url"] == "https://hc-ping.com/abc-123"


def test_heartbeat_quebrado_nao_derruba_a_rodada(monkeypatch):
    import urllib.request

    monkeypatch.setenv("WATCHDOG_HEARTBEAT_URL", "https://hc-ping.com/abc-123")
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: (_ for _ in ()).throw(OSError("down")))

    watchdog_coleta._heartbeat()  # não levanta


def test_rodada_saudavel_tambem_pulsa():
    """⚠️ A regressão mais fácil de introduzir: um `return` no ramo saudável.

    Rodada saudável é a mais comum. Se ela sair antes do `_heartbeat()`, o vigia
    externo alarma nos dias em que está tudo bem — alarme invertido, que ensina
    a ignorar o canal. Aqui isso é lido na árvore do `main()`, sem banco.
    """
    import ast
    import inspect

    arvore = ast.parse(inspect.getsource(watchdog_coleta.main))
    # `if not achados`, e não o `if not url` do começo do main() — esse SIM tem
    # `return`, e de propósito: rodada que nem conectou no banco não pulsa.
    ramo = next(n for n in ast.walk(arvore)
                if isinstance(n, ast.If)
                and isinstance(n.test, ast.UnaryOp)
                and isinstance(n.test.op, ast.Not)
                and getattr(n.test.operand, "id", "") == "achados")

    tem_return = any(isinstance(n, ast.Return) for n in ast.walk(ramo))
    assert not tem_return, "ramo saudavel voltou a sair antes do _heartbeat()"

    chamadas = [n for n in ast.walk(arvore)
                if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_heartbeat"]
    assert len(chamadas) == 1, "o pulso deve ter UM ponto de chamada, no fim da rodada"
