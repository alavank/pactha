"""A sessao gov.br do servidor nao pode ser derrubada por NOS (21/09/2026).

Quedas simultaneas nos seis tenants, com tempos de vida de 20h a 79h (agosto:
79h, 20h, 63h, 48h) — variavel demais para teto do SSO. O mecanismo estava no
codigo (que ele tenha matado cada sessao em producao e hipotese): a extensao espelhava o jar do Chrome do dono para os seis
Cofres em toda navegacao em gov.br (inclusive a tela de login) e a cada 12 min,
sem saber se o Chrome estava logado; o endpoint gravava por cima da sessao viva
conferindo so `len(cookie) >= 10`; e o keepalive regravava o jar mesmo com tudo
caido no login.

As guardas, e o que cada teste segura:
  - captura com a sessao VIVA vira CANDIDATA (a viva nao e tocada);
  - o worker so PROMOVE a candidata que autentica; falha (rede, banco, linha que
    mudou no meio) nao e veredito; grava ANTES de apagar; DELETE versionado;
  - login provado vivo no keepalive liga a guarda na hora; renew com falha de
    rede e inconclusivo (timeout nao vira "SSO expirou");
  - sessao MORTA: a captura grava direto, na hora (a recaptura nao pode esperar);
  - keepalive so regrava com prova de vida; jar que nao carrega aborta sem gravar;
  - rodada que leu o jar velho nao engole a captura nova (`visto_em`);
  - a extensao nao dispara na tela de login, e as 4 portas sao as do servidor.
"""
import asyncio
import json
import re
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from ingestion import govbr_renew as gr
from routers import session_capture as sc

RAIZ = Path(__file__).resolve().parent.parent
EXT = RAIZ.parent / "extension"


# ------------------------------------------------------------ funcoes puras --
def test_viva_e_success_recente_e_so_isso():
    assert sc.sessao_esta_viva("success", 5) is True
    assert sc.sessao_esta_viva("success", sc.SESSAO_VIVA_MIN) is True
    assert sc.sessao_esta_viva("success", sc.SESSAO_VIVA_MIN + 1) is False, "renew parado ha horas nao prova vida"
    assert sc.sessao_esta_viva("erro", 5) is False
    assert sc.sessao_esta_viva(None, None) is False, "nunca medido: comportamento antigo (grava direto)"
    assert sc.sessao_esta_viva("success", None) is False


def test_os_nomes_batem_entre_a_api_e_o_worker():
    """As duas metades da guarda moram em processos diferentes e se falam pelo
    banco: a chave da linha e a fonte do ingestion_log tem de ser as MESMAS."""
    assert sc.CHAVE_CANDIDATA == gr.CHAVE_CANDIDATA
    assert sc.SOURCE_SSO == gr.SOURCE_SSO
    assert sc.CHAVE_CANDIDATA != sc.CHAVE_GOVBR, "os leitores filtram por igualdade em 'govbr'"


def test_resumo_de_saude_so_cobra_recaptura_com_medicao():
    viva = sc.resumo_saude(("success", 12.4, None), ("success", 3.0, None), False)
    assert viva["login"] == "vivo" and viva["precisa_recapturar"] is False
    assert viva["modulos"] == "private=vivo, execucao=vivo, prestacao=vivo"
    caiu = sc.resumo_saude(("erro", 40.0, gr.FRASE_SSO_EXPIROU),
                           ("erro", 8.0, "private=CAIU, execucao=CAIU, prestacao=CAIU"), False)
    assert caiu["login"] == "caiu" and caiu["precisa_recapturar"] is True
    assert "CAIU" in caiu["modulos"]
    # tenant que NUNCA capturou nao cobra recaptura (a disciplina do vigia)
    nunca = sc.resumo_saude(("erro", 40.0, gr.FRASE_SEM_SESSAO), (None, None, None), False)
    assert nunca["precisa_recapturar"] is False and nunca["login"] == "sem_medicao"
    sem = sc.resumo_saude((None, None, None), (None, None, None), True)
    assert sem["precisa_recapturar"] is False and sem["candidata_pendente"] is True
    # success VELHO (renew parado) nao e "vivo", mas tambem nao e "caiu"
    velho = sc.resumo_saude(("success", 999.0, None), (None, None, None), False)
    assert velho["login"] == "sem_medicao" and velho["precisa_recapturar"] is False


def test_prova_de_vida():
    assert gr.tem_prova_de_vida(False, False, False, False) is False
    assert gr.tem_prova_de_vida(True, False, False, False) is True
    assert gr.tem_prova_de_vida(False, False, True, False) is True, "SP vivo com SSO morto ja foi medido (agosto)"


# ------------------------------------------------------- o endpoint de captura --
class _Res:
    def __init__(self, obj=None, row=None):
        self._obj, self._row = obj, row

    def scalar_one_or_none(self):
        return self._obj

    def scalars(self):
        return self

    def first(self):
        return self._obj if self._row is None else self._row


class FakeDb:
    """Roteia pelo SQL compilado: ingestion_log / linha 'govbr' / linha candidata."""

    def __init__(self, principal=None, candidata=None, sso=None):
        self.principal, self.candidata, self.sso = principal, candidata, sso
        self.adicionados, self.commits, self.savepoints = [], 0, 0
        self.log_quebrado = False

    async def execute(self, stmt, params=None):
        try:
            s = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        except Exception:
            s = str(stmt)
        if "ingestion_log" in s:
            if self.log_quebrado:
                raise RuntimeError('relation "ingestion_log" does not exist')
            return _Res(row=self.sso) if self.sso else _Res(row=None, obj=None)
        if sc.CHAVE_CANDIDATA in s:
            return _Res(obj=self.candidata)
        return _Res(obj=self.principal)

    def begin_nested(self):
        # `_ultima_medicao` consulta em SAVEPOINT (query que falha nao pode
        # abortar a transacao da captura).
        db = self

        class _Savepoint:
            async def __aenter__(self):
                db.savepoints += 1

            async def __aexit__(self, *a):
                return False
        return _Savepoint()

    def add(self, obj):
        obj.id = 99
        self.adicionados.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        pass


@pytest.fixture()
def captura(monkeypatch):
    eventos, raspou = [], []

    async def _log_event(db, action, **kw):
        eventos.append((action, kw.get("target_id")))

    monkeypatch.setattr(sc, "log_event", _log_event)
    monkeypatch.setattr(sc.crypto, "encrypt", lambda s: "CIFRADO:" + s[:40])
    monkeypatch.delenv("SESSION_CAPTURE_AUTO_SCRAPE", raising=False)
    monkeypatch.setitem(sc._AUTO_SCRAPE, "rodando", False)
    monkeypatch.setitem(sc._AUTO_SCRAPE, "ultimo", 0.0)
    stub = types.ModuleType("ingestion.transferegov_voluntarias")

    async def _run():
        raspou.append(True)
    stub.run = _run
    monkeypatch.setitem(sys.modules, "ingestion.transferegov_voluntarias", stub)

    def _chama(db, key="govbr", municipio_id=None, cookies=None):
        payload = sc.CapturedSession(
            automation_key=key, municipio_id=municipio_id, cookie="JSESSIONID=abc; outro=def",
            cookies_full=cookies or [sc.CookieFull(name="JSESSIONID", value="abc", domain=".gov.br")],
            url_atual="auto:navigation@www.gov.br", domain_capturado="www.gov.br")
        principal = sc._CapturePrincipal(user_id=None, label="service:extensao", via="service_token")

        async def _go():
            r = await sc.capture_session(payload, request=None, db=db, principal=principal)
            await asyncio.sleep(0)      # deixa o auto-scrape (create_task) rodar
            return r
        return asyncio.run(_go())
    return SimpleNamespace(chama=_chama, eventos=eventos, raspou=raspou)


def _linha(id_, conteudo="ORIGINAL"):
    return SimpleNamespace(id=id_, senha_encrypted=conteudo, observacao="obs antiga",
                           atualizado_por_id=None, municipio_id=None)


def test_sessao_VIVA_nao_e_tocada__a_captura_vira_candidata(captura):
    principal = _linha(7)
    db = FakeDb(principal=principal, candidata=None, sso=("success", 12.0, None))
    r = captura.chama(db)
    assert r["status"] == "candidata" and r["auto_scrape_started"] is False
    assert principal.senha_encrypted == "ORIGINAL" and principal.observacao == "obs antiga", \
        "a sessao viva foi tocada"
    assert len(db.adicionados) == 1
    nova = db.adicionados[0]
    assert nova.automation_key == sc.CHAVE_CANDIDATA and nova.municipio_id is None
    assert captura.eventos == [("session.candidata", 99)]
    assert captura.raspou == [], "candidata nao dispara scraper: nada mudou na sessao em uso"


def test_candidata_que_ja_existe_e_atualizada_e_nao_duplicada(captura):
    principal, cand = _linha(7), _linha(8, "CANDIDATA VELHA")
    db = FakeDb(principal=principal, candidata=cand, sso=("success", 1.0, None))
    r = captura.chama(db)
    assert r["status"] == "candidata" and r["id"] == 8 and not db.adicionados
    assert cand.senha_encrypted.startswith("CIFRADO:") and principal.senha_encrypted == "ORIGINAL"


@pytest.mark.parametrize("sso", [
    ("erro", 30.0, "SSO gov.br expirou"),     # caiu: e a RECAPTURA, vale na hora
    None,                                      # nunca medido: comportamento de sempre
    ("success", 999.0, None),                  # renew parado ha horas: nao prova vida
])
def test_sessao_MORTA_ou_sem_medicao_grava_direto_na_hora(captura, sso):
    principal = _linha(7)
    db = FakeDb(principal=principal, sso=sso)
    r = captura.chama(db)
    assert r["status"] == "ok" and r["id"] == 7
    assert principal.senha_encrypted.startswith("CIFRADO:"), "a recaptura nao gravou"
    assert not db.adicionados
    assert captura.eventos == [("session.update", 7)]
    assert captura.raspou == [] and r["auto_scrape_started"] is False, \
        "o scraper NAO roda mais dentro da API por padrao — derrubou os seis em 21/09"


def test_medicao_que_FALHA_nao_derruba_a_captura__e_roda_em_savepoint(captura):
    """No Postgres a query que falha ABORTA a transacao: sem o savepoint, o commit
    da captura (mesma sessao) levantaria InFailedSQLTransaction — a recaptura
    viraria 500 por causa de uma consulta "best-effort"."""
    principal = _linha(7)
    db = FakeDb(principal=principal, sso=("success", 1.0, None))
    db.log_quebrado = True
    r = captura.chama(db)
    assert r["status"] == "ok", "sem medicao = 'nao sei' = grava direto (a recaptura nao pode esperar)"
    assert principal.senha_encrypted.startswith("CIFRADO:")
    assert db.savepoints >= 1, "a consulta ao ingestion_log saiu do savepoint"


def test_o_scraper_dentro_da_API_e_DESLIGADO_por_padrao_e_um_por_vez_quando_ligado(captura, monkeypatch):
    """Em 21/09/2026 uma recaptura pelas 4 portas gerou ~20 rodadas do scraper
    por tenant em uma hora, DENTRO do processo da API: as seis responderam 503.
    Default desligado; com a env, um por vez e com intervalo minimo."""
    assert sc.pode_auto_scrape() is False
    monkeypatch.setenv("SESSION_CAPTURE_AUTO_SCRAPE", "1")
    assert sc.pode_auto_scrape() is True
    r1 = captura.chama(FakeDb(principal=_linha(7), sso=None))
    assert r1["auto_scrape_started"] is True and captura.raspou == [True]
    # a segunda captura, segundos depois (porta 2, cookie trocado...): NAO dispara
    r2 = captura.chama(FakeDb(principal=_linha(7), sso=None))
    assert r2["auto_scrape_started"] is False and captura.raspou == [True]
    # rodando: nunca dois ao mesmo tempo, mesmo com o intervalo vencido
    monkeypatch.setitem(sc._AUTO_SCRAPE, "rodando", True)
    assert sc.pode_auto_scrape(agora=sc._AUTO_SCRAPE["ultimo"] + sc.AUTO_SCRAPE_INTERVALO_S + 1) is False
    monkeypatch.setitem(sc._AUTO_SCRAPE, "rodando", False)
    assert sc.pode_auto_scrape(agora=sc._AUTO_SCRAPE["ultimo"] + sc.AUTO_SCRAPE_INTERVALO_S + 1) is True


def test_primeira_captura_e_outras_chaves_seguem_como_sempre(captura):
    # sem linha 'govbr' ainda: cria a principal, mesmo com success no log
    db = FakeDb(principal=None, sso=("success", 1.0, None))
    r = captura.chama(db)
    assert r["status"] == "ok" and db.adicionados[0].automation_key == "govbr"
    # FNS nao passa pela guarda
    fns = _linha(3)
    db2 = FakeDb(principal=fns, sso=("success", 1.0, None))
    assert captura.chama(db2, key="fns")["status"] == "ok"
    assert fns.senha_encrypted.startswith("CIFRADO:")


# ------------------------------------------------------ o worker e a candidata --
class _Page:
    """`destinos` = para onde cada `goto` leva, em ordem (uma excecao = a
    navegacao nao completou). Sem `destinos`, a pagina fica em `url`."""

    def __init__(self, url, body, falha_goto=False, destinos=None):
        self.url, self._body, self._falha = url, body, falha_goto
        self._destinos = list(destinos) if destinos is not None else None

    async def goto(self, *a, **k):
        if self._falha:
            raise TimeoutError("net::ERR_TIMED_OUT")
        if self._destinos is not None:
            d = self._destinos.pop(0) if self._destinos else self.url
            if isinstance(d, Exception):
                raise d
            if isinstance(d, tuple):          # (url, corpo) — pagina com corpo proprio
                d, self._body = d
            self.url = d

    async def wait_for_timeout(self, ms):
        pass

    async def evaluate(self, js):
        return self._body


class _Ctx:
    def __init__(self, page, ruins=()):
        self._page, self._ruins, self.carregados = page, set(ruins), []

    async def add_cookies(self, cookies):
        if any(c["name"] in self._ruins for c in cookies):
            raise ValueError("Invalid cookie fields")
        self.carregados.extend(c["name"] for c in cookies)

    async def new_page(self):
        return self._page

    async def cookies(self):
        return [{"name": "JSESSIONID", "value": "novo", "domain": "discricionarias.transferegov.sistema.gov.br"}]


def _playwright_falso(monkeypatch, page, ruins=()):
    ctx = _Ctx(page, ruins)
    browser = SimpleNamespace()

    async def _new_context(**k):
        return ctx

    async def _close():
        pass
    browser.new_context, browser.close = _new_context, _close

    class _PW:
        async def __aenter__(self):
            async def _launch(**k):
                return browser
            return SimpleNamespace(chromium=SimpleNamespace(launch=_launch))

        async def __aexit__(self, *a):
            return False

    mod = types.ModuleType("playwright.async_api")
    mod.async_playwright = lambda: _PW()
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.async_api", mod)
    return ctx


@pytest.fixture()
def worker(monkeypatch):
    """O worker com o BANCO falso. `passos` guarda a ORDEM do que foi gravado;
    `estado` deixa cada teste dizer o que o banco responde."""
    passos, registros = [], []
    estado = SimpleNamespace(principal_id=7, banco_fora=False, candidata_mudou=False, save_ok=True)

    def _id_em_uso():
        if estado.banco_fora:
            raise OSError("connection timed out")
        return estado.principal_id

    def _save(cid, ck, visto_em=None):
        passos.append(("save", cid, visto_em))
        return estado.save_ok

    def _encerra(cid, veredito, pid, versao=None):
        if estado.candidata_mudou:
            return False
        passos.append(("encerra", cid, veredito, pid, versao))
        return True

    monkeypatch.setattr(gr, "_load_candidata",
                        lambda: (8, [{"name": "JSESSIONID", "value": "x", "domain": ".gov.br"}], "c1"))
    monkeypatch.setattr(gr, "_id_da_sessao_em_uso", _id_em_uso)
    monkeypatch.setattr(gr, "_load_govbr_v", lambda: (7, [{"name": "a", "value": "b", "domain": ".gov.br"}], "v1"))
    monkeypatch.setattr(gr, "_save_cookies", _save)
    monkeypatch.setattr(gr, "_encerra_candidata", _encerra)
    monkeypatch.setattr(gr, "_registra_sso", lambda r: registros.append(("sso", r)))
    monkeypatch.setattr(gr, "_registra_candidata", lambda v, m: registros.append(("candidata", v)))
    monkeypatch.setattr(gr, "_registra_sessao", lambda *a: registros.append(("sessao",) + tuple(a)))
    return SimpleNamespace(passos=passos, registros=registros, estado=estado,
                           salvos=lambda: [p[1:] for p in passos if p[0] == "save"],
                           encerradas=lambda: [p[1:] for p in passos if p[0] == "encerra"])


URL_OK = "https://discricionarias.transferegov.sistema.gov.br/voluntarias/Principal.do"
URL_LOGIN = "https://sso.acesso.gov.br/login?client_id=x"
LOGADO = (URL_OK, "Bem-vindo ... Sair")
LOGIN = (URL_LOGIN, "Identifique-se no gov.br")


def test_candidata_que_AUTENTICA_e_promovida_para_a_sessao_em_uso(monkeypatch, worker):
    _playwright_falso(monkeypatch, _Page(*LOGADO))
    assert asyncio.run(gr.processa_candidata()) == "promovida"
    assert worker.salvos() == [(7, None)], "promocao grava na linha PRINCIPAL, incondicional"
    assert [p[0] for p in worker.passos] == ["save", "encerra"], \
        "GRAVA antes de apagar: falha de banco no meio nao pode jogar fora um login bom"
    cid, veredito, pid, versao = worker.encerradas()[0]
    assert cid == 8 and "promovida" in veredito and pid == 7 and versao == "c1", \
        "o DELETE e VERSIONADO: so apaga a candidata que foi testada"
    # autenticou = login medido vivo AGORA: liga a guarda do endpoint sem esperar o renew
    assert ("sso", "reconnected") in worker.registros and ("candidata", "promovida") in worker.registros


def test_candidata_do_chrome_DESLOGADO_e_recusada_e_a_sessao_viva_fica(monkeypatch, worker):
    _playwright_falso(monkeypatch, _Page(*LOGIN))
    assert asyncio.run(gr.processa_candidata()) == "recusada"
    assert worker.salvos() == [], "jar deslogado chegou na sessao em uso"
    assert worker.encerradas()[0][0] == 8 and "recusada" in worker.encerradas()[0][1]
    assert ("candidata", "recusada") in worker.registros, "a recusa fica no ingestion_log (o log do container some)"
    assert ("sso", "reconnected") not in worker.registros


def test_falha_de_rede_NAO_e_veredito__a_candidata_fica_para_a_proxima(monkeypatch, worker):
    _playwright_falso(monkeypatch, _Page("about:blank", "", falha_goto=True))
    assert asyncio.run(gr.processa_candidata()) == "inconclusivo"
    assert worker.passos == [] and worker.registros == [], "recusar por timeout joga fora um login bom"


def test_banco_FORA_nao_promove_as_cegas__era_assim_que_nasciam_duas_linhas_govbr(monkeypatch, worker):
    """`_load_govbr_v` devolve None tanto para "nao existe" quanto para "nao
    consegui ler". Tratar o segundo como o primeiro fazia a promocao criar uma
    SEGUNDA linha 'govbr' — e o POST de captura respondia 500 dali em diante."""
    worker.estado.banco_fora = True
    cur = _Cur(rowcount=1)
    monkeypatch.setattr(gr.psycopg2, "connect", lambda *a, **k: _ConnCtx(cur))
    monkeypatch.setattr(gr.crypto, "encrypt", lambda s: "CIFRADO")
    _playwright_falso(monkeypatch, _Page(*LOGADO))
    assert asyncio.run(gr.processa_candidata()) == "inconclusivo"
    assert worker.passos == [] and cur.sql == [], "INSERT de uma linha 'govbr' sem saber se ja existe uma"


def test_sem_linha_govbr_a_candidata_que_autentica_NASCE_como_a_sessao_em_uso(monkeypatch, worker):
    """Aqui a consulta RESPONDEU "nao existe" — diferente de banco fora."""
    worker.estado.principal_id = None
    cur = _Cur(rowcount=1)
    monkeypatch.setattr(gr.psycopg2, "connect", lambda *a, **k: _ConnCtx(cur))
    monkeypatch.setattr(gr.crypto, "encrypt", lambda s: "CIFRADO")
    _playwright_falso(monkeypatch, _Page(*LOGADO))
    assert asyncio.run(gr.processa_candidata()) == "promovida"
    assert len(cur.sql) == 1 and "INSERT INTO cofre_senhas" in cur.sql[0][0] and "'govbr'" in cur.sql[0][0]
    assert worker.salvos() == [] and worker.encerradas()[0][0] == 8


def test_captura_nova_durante_o_teste_NAO_e_apagada_junto(monkeypatch, worker):
    """O endpoint ATUALIZA a mesma linha candidata a cada captura. Recusar a velha
    apagando por id levaria junto a "Captura completa" que chegou no meio."""
    worker.estado.candidata_mudou = True
    _playwright_falso(monkeypatch, _Page(*LOGIN))
    assert asyncio.run(gr.processa_candidata()) == "inconclusivo"
    assert worker.registros == [], "veredito registrado para uma candidata que nao foi a testada"


def test_promocao_que_nao_grava_nao_apaga_a_candidata(monkeypatch, worker):
    worker.estado.save_ok = False
    _playwright_falso(monkeypatch, _Page(*LOGADO))
    assert asyncio.run(gr.processa_candidata()) == "inconclusivo"
    assert worker.encerradas() == [], "candidata apagada sem o jar ter virado a sessao em uso"


def test_sem_candidata_nem_abre_navegador(monkeypatch):
    monkeypatch.setattr(gr, "_load_candidata", lambda: (None, None, None))
    assert asyncio.run(gr.processa_candidata()) == "sem_candidata"


# ------------------------------------------- keepalive() e renew(), por COMPORTAMENTO --
@pytest.fixture()
def rodada(monkeypatch, worker):
    chamou = []

    async def _cand():
        chamou.append(True)
        return "sem_candidata"
    monkeypatch.setattr(gr, "processa_candidata", _cand)
    worker.chamou_candidata = chamou
    return worker


def test_keepalive_com_TUDO_caido_no_login_NAO_grava_nem_declara_o_login_vivo(monkeypatch, rodada):
    _playwright_falso(monkeypatch, _Page("about:blank", "Identifique-se no gov.br", destinos=[URL_LOGIN] * 4))
    assert asyncio.run(gr.keepalive()) == "private_dead"
    assert rodada.salvos() == [], "keepalive regravou o jar com as quatro navegacoes na tela de login"
    assert ("sso", "reconnected") not in rodada.registros
    assert ("sessao", False, False, False) in rodada.registros
    assert rodada.chamou_candidata == [True], "o keepalive e quem promove rapido a captura nova"


def test_keepalive_VIVO_grava_com_a_versao_lida_e_mede_o_login(monkeypatch, rodada):
    _playwright_falso(monkeypatch, _Page("about:blank", "Bem-vindo Sair", destinos=[URL_OK] * 4))
    assert asyncio.run(gr.keepalive()) == "alive"
    assert rodada.salvos() == [(7, "v1")], "sem `visto_em` a rodada engole a recaptura que chegou no meio"
    # ⭐ e isto que fecha a janela de ate 60 min com a guarda desligada depois de
    # uma recaptura: o login provado vivo vira medicao de govbr_sso no keepalive.
    assert ("sso", "reconnected") in rodada.registros


def test_keepalive_so_com_SP_vivo_grava_mas_NAO_declara_o_login(monkeypatch, rodada):
    # entrada no login, /private/ vivo: ha prova de vida (grava), mas o SSO nao foi provado
    _playwright_falso(monkeypatch, _Page("about:blank", "Identifique-se no gov.br",
                                         destinos=[URL_LOGIN, URL_OK, URL_OK, URL_OK]))
    assert asyncio.run(gr.keepalive()) == "alive"
    assert rodada.salvos() == [(7, "v1")]
    assert ("sso", "reconnected") not in rodada.registros


def test_keepalive_com_jar_que_nao_carrega_aborta_SEM_gravar(monkeypatch, rodada):
    _playwright_falso(monkeypatch, _Page("about:blank", "Bem-vindo Sair", destinos=[URL_OK] * 4), ruins={"a"})
    assert asyncio.run(gr.keepalive()) == "private_dead"
    assert rodada.salvos() == []


def test_renew_vivo_grava_com_a_versao_lida(monkeypatch, rodada):
    _playwright_falso(monkeypatch, _Page("about:blank", "Bem-vindo Sair", destinos=[URL_OK] * 20))
    assert asyncio.run(gr.renew()) == "reconnected"
    assert rodada.salvos() == [(7, "v1")] and rodada.chamou_candidata == [True]


def test_renew_no_login_pede_recaptura_e_nao_grava(monkeypatch, rodada):
    _playwright_falso(monkeypatch, _Page("about:blank", "Identifique-se no gov.br", destinos=[URL_LOGIN]))
    assert asyncio.run(gr.renew()) == "needs_recapture"
    assert rodada.salvos() == []


def test_renew_com_FALHA_DE_REDE_e_inconclusivo__timeout_nao_vira_SSO_expirou(monkeypatch, rodada):
    """Antes: goto falhava, `_is_authenticated('about:blank','')` dava False e um
    TIMEOUT virava "SSO expirou — recapturar" no banco e no Telegram — e desligava
    a guarda do endpoint por uma hora."""
    _playwright_falso(monkeypatch, _Page("about:blank", "", destinos=[TimeoutError("net::ERR_TIMED_OUT")]))
    assert asyncio.run(gr.renew()) == "inconclusivo"
    assert rodada.salvos() == []


def test_veredito_de_TRES_valores__nao_autenticou_NAO_e_caiu_no_login():
    assert gr.veredito_login(URL_OK, "Bem-vindo Sair") == "logado"
    assert gr.veredito_login(URL_LOGIN, "Identifique-se no gov.br") == "login"
    assert gr.veredito_login(gr.ENTRY, "Acesso restrito") == "login"
    # pagina de erro do portal, corpo vazio (evaluate falhou), SAML em transito: NAO SEI
    assert gr.veredito_login(gr.ENTRY, "503 Service Temporarily Unavailable") == "nao_sei"
    assert gr.veredito_login(gr.ENTRY, "") == "nao_sei"
    assert gr.veredito_login(gr.ENTRY, "Acesso restrito", http_status=503) == "nao_sei"


@pytest.mark.parametrize("corpo", ["503 Service Temporarily Unavailable", ""])
def test_renew_com_PAGINA_DE_ERRO_do_portal_e_inconclusivo(monkeypatch, rodada, corpo):
    """`page.goto` NAO levanta para HTTP 5xx. Com o bool de antes, um portal fora
    do ar por minutos virava `govbr_sso=erro` — que DESLIGA a guarda do endpoint e
    reabre a porta para o jar deslogado gravar por cima da sessao viva."""
    _playwright_falso(monkeypatch, _Page("about:blank", corpo, destinos=[gr.ENTRY]))
    assert asyncio.run(gr.renew()) == "inconclusivo"
    assert rodada.salvos() == []


@pytest.mark.parametrize("corpo", ["503 Service Temporarily Unavailable", ""])
def test_candidata_NAO_e_apagada_por_pagina_de_erro_do_portal(monkeypatch, worker, corpo):
    _playwright_falso(monkeypatch, _Page("about:blank", corpo, destinos=[gr.ENTRY]))
    assert asyncio.run(gr.processa_candidata()) == "inconclusivo"
    assert worker.passos == [] and worker.registros == [], \
        "candidata apagada com o diagnostico falso 'jar sem login' — era o portal fora do ar"


def test_candidata_que_nao_se_consegue_testar_nao_prende_a_fila_para_sempre(monkeypatch, worker):
    from datetime import datetime, timedelta, timezone
    velha = datetime.now(timezone.utc) - timedelta(hours=gr.CANDIDATA_MAX_H + 1)
    monkeypatch.setattr(gr, "_load_candidata", lambda: (8, [{"name": "J", "value": "x", "domain": ".gov.br"}], velha))
    _playwright_falso(monkeypatch, _Page("about:blank", "503", destinos=[gr.ENTRY]))
    assert asyncio.run(gr.processa_candidata()) == "recusada"
    assert "nao foi possivel testar" in worker.encerradas()[0][1], "descartada com o motivo de outra coisa"
    assert worker.salvos() == []
    # e a nova (minutos de idade) espera
    nova = datetime.now(timezone.utc) - timedelta(minutes=20)
    assert gr._candidata_velha(nova) is False and gr._candidata_velha("c1") is False


def test_renew_inconclusivo_NAO_e_mudo__a_rodada_fica_registrada(monkeypatch):
    """Se o layout do portal mudar (sumir o "Sair"), toda rodada vira inconclusiva;
    sem este registro nada diria isso em lugar nenhum."""
    gravou = []
    monkeypatch.setattr(gr, "_grava_estado", lambda *a: gravou.append(a))
    gr._registra_rodada("inconclusivo")
    gr._registra_rodada("reconnected")
    assert [(g[0], g[1]) for g in gravou] == [(gr.SOURCE_RODADA, "partial"), (gr.SOURCE_RODADA, "success")]
    assert gr.SOURCE_RODADA not in (gr.SOURCE_SSO, gr.SOURCE_SESSAO), "nao pode ligar/desligar a guarda"
    src = (RAIZ / "ingestion" / "govbr_renew.py").read_text(encoding="utf-8")
    assert "_registra_rodada(resultado)" in src[src.index('if __name__ == "__main__"'):]


def test_inconclusivo_nao_escreve_no_ingestion_log(monkeypatch):
    conectou = []
    monkeypatch.setattr(gr.psycopg2, "connect", lambda *a, **k: conectou.append(True))
    gr._registra_sso("inconclusivo")
    assert conectou == [], "rodada sem veredito nao pode virar linha de status"


# ------------------------------------------------ a candidata no banco (SQL) --
def test_o_delete_da_candidata_e_versionado_e_avisa_quando_nao_apagou(monkeypatch):
    cur = _Cur(rowcount=0)
    conn = _ConnCtx(cur)
    monkeypatch.setattr(gr.psycopg2, "connect", lambda *a, **k: conn)
    assert gr._encerra_candidata(8, "recusada", 7, versao="c1") is False
    sql, params = cur.sql[0]
    assert "DELETE FROM cofre_senhas" in sql and "AND updated_at=%s" in sql
    assert params == (8, gr.CHAVE_CANDIDATA, "c1")
    assert len(cur.sql) == 1, "sem apagar nao se anota veredito na sessao em uso"


def test_duplicatas_mais_ANTIGAS_da_candidata_vao_junto__a_mais_nova_fica(monkeypatch):
    """O endpoint faz SELECT+INSERT sem trava e a API sobe com 2 workers: dois
    POSTs simultaneos criam DUAS candidatas, e a velha seria promovida depois,
    por cima do jar mais completo."""
    cur = _Cur(rowcount=1)
    monkeypatch.setattr(gr.psycopg2, "connect", lambda *a, **k: _ConnCtx(cur))
    assert gr._encerra_candidata(8, "promovida", None, versao="c1") is True
    assert "WHERE id=%s" in cur.sql[0][0] and cur.sql[0][1] == (8, gr.CHAVE_CANDIDATA, "c1"), \
        "o 1o DELETE continua sendo o da linha TESTADA (o rowcount dele decide o retorno)"
    sql, params = cur.sql[1]
    assert "DELETE FROM cofre_senhas" in sql and "id<>%s" in sql and "updated_at<=%s" in sql
    assert params == (gr.CHAVE_CANDIDATA, 8, "c1")


def test_o_endpoint_e_o_worker_falam_da_MESMA_candidata__a_mais_nova():
    src = (RAIZ / "routers" / "session_capture.py").read_text(encoding="utf-8")
    trecho = src[src.index("CofreSenha.automation_key == CHAVE_CANDIDATA"):][:400]
    assert "order_by(CofreSenha.updated_at.desc())" in trecho


def test_a_candidata_e_lida_SEM_piso_de_tamanho(monkeypatch):
    """Jar deslogado e pequeno, e e justamente ele que precisa ser lido para ser
    recusado e sair da fila."""
    cur = _Cur(rowcount=1)
    cur.fetchone = lambda: (8, "CIFRADO", "c1")
    conn = SimpleNamespace(cursor=lambda: cur, commit=lambda: None, close=lambda: None)
    monkeypatch.setattr(gr.psycopg2, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(gr.crypto, "decrypt", lambda s: json.dumps({"cookies": [{"name": "x", "value": "1"}]}))
    assert gr._load_candidata() == (8, [{"name": "x", "value": "1"}], "c1")
    assert "LENGTH" not in cur.sql[0][0].upper() and gr.CHAVE_CANDIDATA in cur.sql[0][1]


def test_lote_de_cookies_que_falha_e_refeito_um_a_um():
    ctx = _Ctx(None, ruins={"quebrado"})
    jar = [{"name": "bom1", "value": "1"}, {"name": "quebrado", "value": "2"}, {"name": "bom2", "value": "3"}]
    assert asyncio.run(gr._add_cookies_tolerante(ctx, jar)) == 2
    assert ctx.carregados == ["bom1", "bom2"]
    assert asyncio.run(gr._add_cookies_tolerante(_Ctx(None), [])) == 0


# --------------------------------------------------- a gravacao condicional --
class _Cur:
    def __init__(self, rowcount):
        self.rowcount, self.sql = rowcount, []

    def execute(self, sql, params=None):
        self.sql.append((sql, params))

    def fetchone(self):
        return None

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _ConnCtx:
    """Conexao usada como `with conn, conn.cursor() as cur:`."""

    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _conexao(monkeypatch, rowcount):
    cur = _Cur(rowcount)
    conn = SimpleNamespace(cursor=lambda: cur, commit=lambda: None, close=lambda: None)
    monkeypatch.setattr(gr.psycopg2, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(gr.crypto, "encrypt", lambda s: "CIFRADO")
    return cur


def test_rodada_que_leu_o_jar_velho_NAO_engole_a_captura_nova(monkeypatch):
    cur = _conexao(monkeypatch, rowcount=0)       # a linha mudou de versao no meio
    assert gr._save_cookies(7, [], visto_em="v1") is False
    sql, params = cur.sql[0]
    assert "AND updated_at=%s" in sql and params == ("CIFRADO", 7, "v1")


def test_sem_versao_grava_incondicional__e_a_promocao(monkeypatch):
    cur = _conexao(monkeypatch, rowcount=1)
    assert gr._save_cookies(7, []) is True
    assert "AND updated_at" not in cur.sql[0][0]


def test_o_keepalive_consulta_a_prova_de_vida_ANTES_de_gravar():
    src = (RAIZ / "ingestion" / "govbr_renew.py").read_text(encoding="utf-8")
    corpo = src[src.index("async def keepalive()"):src.index('if __name__ == "__main__"')]
    i_prova, i_save = corpo.index("tem_prova_de_vida(entry_ok"), corpo.index("_save_cookies(cofre_id, relevant, visto_em)")
    assert i_prova < i_save
    assert "rodada abortada SEM gravar" in corpo, "jar que nao carrega tem de abortar sem gravar"


# ------------------------------------------------------------- a extensao --
def test_as_quatro_portas_da_extensao_sao_as_do_servidor():
    """O servidor mantem viva a sessao que NASCEU na captura: as URLs do botao
    "Captura completa" tem de ser as que o keepalive navega."""
    js = (EXT / "ambientes.js").read_text(encoding="utf-8")
    bloco = js[js.index("const PORTAS_GOVBR"):js.index("function pareceLogin")]
    urls = re.findall(r'url:\s*"([^"]+)"', bloco)
    assert urls == [gr.ENTRY, gr.PRIVATE_ENTRY, gr.EXEC_ENTRY, gr.PRESTACAO_ENTRY]


def test_a_extensao_nao_dispara_captura_no_portal_nem_na_tela_de_login():
    js = (EXT / "background.js").read_text(encoding="utf-8")
    alvos = js[js.index("const TARGETS"):js.index("const TRIGGER_COOKIE_NAMES")]
    for trecho in ('h === "www.gov.br"', 'h === "sso.acesso.gov.br"'):
        i = alvos.index(trecho)
        assert "gatilho: false" in alvos[i:i + 220], f"{trecho} voltou a disparar captura"
    assert "alvo.gatilho !== false" in js and "target.gatilho === false" in js
    # e o keep-alive nao trata a TELA DE LOGIN (HTTP 200) como sessao viva
    assert "r.ok && !pareceLogin(r.url)" in js


def test_a_rota_de_saude_nao_devolve_nada_do_cofre():
    """So estado e horario: a extensao consulta isto de 12 em 12 minutos."""
    d = sc.resumo_saude(("success", 1.0, None), ("success", 1.0, None), False)
    assert set(d) == {"login", "login_medido_ha_min", "modulos", "modulos_medidos_ha_min",
                      "candidata_pendente", "precisa_recapturar",
                      "login_em", "login_ha_h", "vence_previsto_em", "vence_em_h", "vencendo"}
    assert "observacao" not in json.dumps(d)


# ------------------------------------------------ vencimento previsto do login --
from datetime import datetime, timedelta, timezone  # noqa: E402

from services import sessao_govbr as sg  # noqa: E402

OBS = "[SESSION] capturado em 2026-09-23T14:27:18.095649+00:00 | cookies=14 httpOnly=9 | url=https://x"


def test_a_hora_do_login_vem_da_observacao_da_captura():
    assert sg.login_em_da_observacao(OBS) == datetime(2026, 9, 23, 14, 27, 18, 95649, tzinfo=timezone.utc)
    assert sg.login_em_da_observacao(OBS + " || [CANDIDATA] promovida em 2026-09-23 15:00 UTC") \
        == datetime(2026, 9, 23, 14, 27, 18, 95649, tzinfo=timezone.utc)
    assert sg.login_em_da_observacao(None) is None
    assert sg.login_em_da_observacao("[SESSION] promovida de candidata") is None
    assert sg.login_em_da_observacao("[SESSION] capturado em ontem | x") is None


def test_vencimento_previsto__24h_do_login_e_aviso_com_3h_de_folga():
    login = datetime(2026, 9, 23, 14, 27, tzinfo=timezone.utc)
    cedo = sg.vencimento(login, agora=login + timedelta(hours=2))
    assert cedo["vencendo"] is False and cedo["vence_em_h"] == 22.0
    assert cedo["vence_previsto_em"] == (login + timedelta(hours=24)).isoformat()
    aviso = sg.vencimento(login, agora=login + timedelta(hours=21.5))
    assert aviso["vencendo"] is True and aviso["vence_em_h"] == 2.5 and aviso["login_ha_h"] == 21.5
    # SEM teto superior: 24h e padrao medido; sessao que dure 30h continua "vencendo"
    # (o aviso nao pode apagar e voltar a "tudo certo" com o previsto ja passado)
    tarde = sg.vencimento(login, agora=login + timedelta(hours=30))
    assert tarde["vencendo"] is True and tarde["vence_em_h"] == -6.0
    assert sg.vencimento(None)["vencendo"] is False and sg.vencimento(None)["login_em"] is None


def test_a_regua_de_viva_e_uma_so__servico_vigia_e_rota():
    assert sc.sessao_esta_viva is sg.sessao_esta_viva and sc.SESSAO_VIVA_MIN == sg.SESSAO_VIVA_MIN
    assert sg.sessao_esta_viva("SUCCESS", 10) is True and sg.sessao_esta_viva("success", 181) is False


def test_o_aviso_diz_hora_de_brasilia_e_a_ordem_certa__Sair_ANTES_da_captura():
    login = datetime(2026, 9, 23, 14, 27, tzinfo=timezone.utc)      # 11:27 BRT
    t = sg.texto_do_aviso(login, agora=login + timedelta(hours=21))
    assert "11:27 de 23/09" in t and "11:27 de 24/09" in t
    assert "extensao do PACTHA" in t and "Captura completa" in t and "padrao medido" in t
    # Na hora do aviso o portal ainda abre LOGADO: sem o Sair primeiro, a "Captura
    # completa" so recaptura a sessao velha e nada muda.
    assert t.index("Sair") < t.index("Captura completa")
    assert "derruba a sessao dos servidores na hora" in t, "a promessa 'sem derrubar' era falsa"
    depois = sg.texto_do_aviso(login, agora=login + timedelta(hours=30))
    assert "ja passou do previsto" in depois


def test_resumo_de_saude_so_avisa_vencimento_de_login_VIVO():
    login = datetime.now(timezone.utc) - timedelta(hours=22)
    vivo = sc.resumo_saude(("success", 5.0, None), ("success", 1.0, None), False, login_em=login)
    assert vivo["vencendo"] is True and vivo["login_em"] == login.isoformat() and 1.9 <= vivo["vence_em_h"] <= 2.1
    caiu = sc.resumo_saude(("erro", 5.0, gr.FRASE_SSO_EXPIROU), (None, None, None), False, login_em=login)
    assert caiu["vencendo"] is False and caiu["precisa_recapturar"] is True
    assert sc.resumo_saude(("success", 5.0, None), (None, None, None), False)["vence_em_h"] is None


def test_a_sonda_do_sso_navega_SEM_os_cookies_dos_SPs():
    jar = [{"name": "JSESSIONID", "value": "a", "domain": "discricionarias.transferegov.sistema.gov.br"},
           {"name": "JSESSIONID", "value": "b", "domain": "mandatarias.transferegov.sistema.gov.br"},
           {"name": "JSESSIONID", "value": "c", "domain": "idp.transferegov.sistema.gov.br"},
           {"name": "Session_Gov_Br_Prod", "value": "d", "domain": ".sso.acesso.gov.br"},
           {"name": "Govbrid", "value": "e", "domain": ".gov.br"},
           {"name": "x", "value": "f", "domain": ".transferegov.sistema.gov.br"}]
    fica = [c["domain"] for c in gr.cookies_para_roundtrip(jar)]
    assert fica == ["idp.transferegov.sistema.gov.br", ".sso.acesso.gov.br", ".gov.br",
                    ".transferegov.sistema.gov.br"], "sem tirar o JSESSIONID do SP nao ha SAML — a sonda mediria o SP"


def test_o_renew_VIVO_faz_a_sonda_do_sso_e_a_registra_a_parte(monkeypatch, rodada):
    sondas = []
    monkeypatch.setattr(gr, "_registra_roundtrip", lambda v, d: sondas.append(v))
    _playwright_falso(monkeypatch, _Page("about:blank", "Bem-vindo Sair", destinos=[URL_OK] * 20))
    assert asyncio.run(gr.renew()) == "reconnected"
    assert sondas == ["logado"] and rodada.salvos() == [(7, "v1")]


def test_a_sonda_que_cai_no_login_registra_erro_SEM_tocar_o_jar_nem_o_veredito(monkeypatch, rodada):
    registrado = []
    monkeypatch.setattr(gr, "_grava_estado", lambda *a: registrado.append(a))
    # 1a navegacao (jar inteiro): logado; 2a (sem SP): tela de login
    _playwright_falso(monkeypatch, _Page("about:blank", "Bem-vindo Sair",
                                         destinos=[URL_OK, (URL_LOGIN, "Identifique-se no gov.br")]
                                         + [(URL_OK, "Bem-vindo Sair")] * 20))
    assert asyncio.run(gr.renew()) == "reconnected", "a sonda nao pode mudar o veredito do renew"
    assert rodada.salvos() == [(7, "v1")]
    assert [(r[0], r[1]) for r in registrado if r[0] == gr.SOURCE_SSO_RT] == [(gr.SOURCE_SSO_RT, "erro")]
    assert gr.SOURCE_SSO_RT not in (gr.SOURCE_SSO, gr.SOURCE_SESSAO, gr.SOURCE_RODADA), \
        "a sonda nao pode ligar/desligar a guarda do endpoint"


SSO_A = {"name": "Session_Gov_Br_Prod", "value": "AAA", "domain": ".sso.acesso.gov.br", "httpOnly": True}
SSO_B = {"name": "Session_Gov_Br_Prod", "value": "BBB", "domain": "sso.acesso.gov.br", "httpOnly": True}
ING_1 = {"name": "INGRESSCOOKIE", "value": "g1", "domain": "sso.acesso.gov.br", "httpOnly": True}
ING_2 = {"name": "INGRESSCOOKIE", "value": "g2", "domain": "sso.acesso.gov.br", "httpOnly": True}
TS_1 = {"name": "TSd2153684027", "value": "t1", "domain": "sso.acesso.gov.br", "httpOnly": False}
TS_2 = {"name": "TSd2153684027", "value": "t2", "domain": "sso.acesso.gov.br", "httpOnly": False}
IDP_1 = {"name": "JSESSIONID", "value": "i1", "domain": "idp.transferegov.sistema.gov.br"}
IDP_2 = {"name": "JSESSIONID", "value": "i2", "domain": "idp.transferegov.sistema.gov.br"}
SP_1 = {"name": "JSESSIONID", "value": "s1", "domain": "discricionarias.transferegov.sistema.gov.br"}


def test_mesma_sessao_sso__so_os_cookies_do_govbr_decidem():
    assert gr.mesma_sessao_sso([SSO_A, IDP_1, SP_1], [SSO_A, IDP_2]) is True, \
        "IdP e SP rotacionam a cada SAML; a identidade do login e o cookie do gov.br"
    assert gr.mesma_sessao_sso([SSO_A], [SSO_B]) is False, "valor diferente = login novo"
    assert gr.mesma_sessao_sso([IDP_1, SP_1], [SSO_A]) is False, "sem cookie do gov.br nao se sabe: login novo"
    assert gr.mesma_sessao_sso([], []) is False


def test_mesma_sessao_sso__so_httpOnly_e_o_cookie_de_sessao_decide():
    """Medido em 23/09: `TS*` (F5, nao-httpOnly) muda a cada pagina do SSO; se
    entrasse na conta, toda recaptura viraria 'login novo' e o relogio andaria."""
    assert gr.mesma_sessao_sso([SSO_A, TS_1], [SSO_A, TS_2]) is True
    assert gr.mesma_sessao_sso([SSO_A, ING_1], [SSO_A, ING_2]) is True, "o cookie de sessao decide sozinho"
    assert gr.mesma_sessao_sso([ING_1], [ING_1, TS_2]) is True, "sem o de sessao: httpOnly em comum"
    assert gr.mesma_sessao_sso([ING_1], [ING_2]) is False
    assert gr.mesma_sessao_sso([SSO_A], [ING_1]) is False, "nada em comum: nao se sabe -> login novo"
    assert gr.comparar_sessao_sso([SSO_A], [SSO_B]) == (False, ["Session_Gov_Br_Prod"])
    # login NOVO (traz o cookie de sessao) contra jar em uso SEM ele: o INGRESSCOOKIE
    # (afinidade do balanceador) nao pode decidir "mesma sessao"
    assert gr.comparar_sessao_sso([SSO_B, ING_1], [ING_1]) == (False, ["Session_Gov_Br_Prod"])
    # o contrario (captura sem o cookie de sessao — SP zumbi) desempata pelo que ha em comum
    assert gr.mesma_sessao_sso([ING_1], [SSO_A, ING_1]) is True
    # aceita o formato pydantic do POST (atributos) — e o que o endpoint compara
    obj = sc.CookieFull(name="Session_Gov_Br_Prod", value="AAA", domain=".sso.acesso.gov.br", httpOnly=True)
    assert gr.mesma_sessao_sso([obj], [SSO_A]) is True


def test_a_promocao_de_LOGIN_NOVO_copia_a_hora_do_login_da_candidata(monkeypatch, worker):
    copias = []
    monkeypatch.setattr(gr, "_copia_observacao", lambda de, para: copias.append((de, para)) or worker.passos.append(("copia",)))
    monkeypatch.setattr(gr, "_load_candidata", lambda: (8, [SSO_B, SP_1], "c1"))
    monkeypatch.setattr(gr, "_load_govbr_v", lambda: (7, [SSO_A, IDP_1], "v1"))
    _playwright_falso(monkeypatch, _Page(*LOGADO))
    assert asyncio.run(gr.processa_candidata()) == "promovida"
    assert copias == [(8, 7)]
    assert [p[0] for p in worker.passos] == ["save", "copia", "encerra"], \
        "a copia vem DEPOIS de gravar o jar e ANTES de apagar a candidata (senao nao ha de onde copiar)"


def test_recaptura_da_MESMA_sessao_promove_o_jar_mas_NAO_reinicia_o_relogio(monkeypatch, worker):
    """Com o Chrome aberto a extensao captura de novo a cada navegacao/alarme; cada
    captura vira candidata e e promovida. Se cada promocao virasse 'login novo', o
    vencimento previsto andaria para a frente a cada ciclo e o aviso nunca sairia."""
    copias = []
    monkeypatch.setattr(gr, "_copia_observacao", lambda de, para: copias.append((de, para)))
    monkeypatch.setattr(gr, "_load_candidata", lambda: (8, [SSO_A, IDP_2, SP_1], "c1"))
    monkeypatch.setattr(gr, "_load_govbr_v", lambda: (7, [SSO_A, IDP_1], "v1"))
    _playwright_falso(monkeypatch, _Page(*LOGADO))
    assert asyncio.run(gr.processa_candidata()) == "promovida"
    assert copias == [] and worker.salvos() == [(7, None)] and worker.encerradas()[0][0] == 8


def test_a_sonda_sem_cookie_de_sso_nao_diz_que_o_login_venceu(monkeypatch, rodada):
    sondas = []
    monkeypatch.setattr(gr, "_registra_roundtrip", lambda v, d: sondas.append((v, d)))
    monkeypatch.setattr(gr, "_load_govbr_v", lambda: (7, [SP_1], "v1"))       # jar so com o SP
    _playwright_falso(monkeypatch, _Page("about:blank", "Bem-vindo Sair", destinos=[URL_OK] * 20))
    assert asyncio.run(gr.renew()) == "reconnected"
    assert sondas and sondas[0][0] == "nao_sei" and "sem o que medir" in sondas[0][1]


def test_a_sonda_com_URL_de_login_mas_SEM_prova_no_corpo_e_inconclusiva(monkeypatch, rodada):
    """Pagina em transito/erro do IdP em /idp/ sem 'Identifique-se' no corpo nao e
    veredito — um 'erro' falso aqui mandaria o dono dar Sair nos servidores."""
    sondas = []
    monkeypatch.setattr(gr, "_registra_roundtrip", lambda v, d: sondas.append(v))
    _playwright_falso(monkeypatch, _Page("about:blank", "Bem-vindo Sair",
                                         destinos=[URL_OK, ("https://idp.transferegov.sistema.gov.br/idp/profile/SAML2/POST/SSO", "")]
                                         + [(URL_OK, "Bem-vindo Sair")] * 20))
    assert asyncio.run(gr.renew()) == "reconnected"
    assert sondas == ["nao_sei"]


def test_a_sonda_tem_kill_switch_por_env(monkeypatch, rodada):
    sondas = []
    monkeypatch.setattr(gr, "_registra_roundtrip", lambda v, d: sondas.append(v))
    monkeypatch.setenv("GOVBR_SONDA_SSO", "0")
    _playwright_falso(monkeypatch, _Page("about:blank", "Bem-vindo Sair", destinos=[URL_OK] * 20))
    assert asyncio.run(gr.renew()) == "reconnected" and sondas == []
    monkeypatch.delenv("GOVBR_SONDA_SSO")
    assert gr.sonda_ligada() is True


class _DbSaude:
    def __init__(self, linhas):
        self.linhas = linhas

    def begin_nested(self):
        return FakeDb().begin_nested()

    async def execute(self, stmt, params=None):
        if "ingestion_log" in str(stmt):
            return _Res(row=self.linhas.get((params or {}).get("s")))
        return _Res(obj=None)

    async def commit(self):
        pass


def test_a_rota_de_saude_ponta_a_ponta__exige_credencial_e_nao_marca_uso_do_token():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from database import get_db

    app = FastAPI()
    app.include_router(sc.router)
    db = _DbSaude({})
    app.dependency_overrides[get_db] = lambda: db
    cli = TestClient(app)
    assert cli.get("/api/session-capture/saude").status_code in (401, 403), "rota de saude aberta sem credencial"

    app.dependency_overrides[sc.get_capture_principal_leitura] = \
        lambda: sc._CapturePrincipal(user_id=None, label="service:x", via="service_token")
    db.linhas = {"govbr_sso": ("erro", 40.2, gr.FRASE_SSO_EXPIROU),
                 "govbr_sessao": ("erro", 7.0, "private=CAIU, execucao=vivo, prestacao=vivo")}
    d = cli.get("/api/session-capture/saude").json()
    assert d["login"] == "caiu" and d["precisa_recapturar"] is True and "private=CAIU" in d["modulos"]
    db.linhas = {"govbr_sso": ("success", 12.0, None), "govbr_sessao": ("success", 3.0, None)}
    d = cli.get("/api/session-capture/saude").json()
    assert d["login"] == "vivo" and d["precisa_recapturar"] is False

    # ⚠️ A saude e lida de 12 em 12 minutos por seis Chromes: se ela carimbasse
    # `last_used_at`, "o token da extensao foi usado hoje" deixaria de significar
    # "houve captura hoje" — que e como se descobre um tenant fora da captura.
    import inspect
    assert "marcar_uso=False" in inspect.getsource(sc.get_capture_principal_leitura)
    assert "marcar_uso=True" in inspect.getsource(sc.get_capture_principal)
    # e `marcar_uso` nao pode vazar como parametro PUBLICO (query string) da rota
    rota = next(r for r in sc.router.routes if getattr(r, "path", "").endswith("/saude"))
    assert "marcar_uso" not in [p.name for p in rota.dependant.query_params], \
        "`marcar_uso` virou query param: qualquer um desligaria o carimbo"
    for dep in rota.dependant.dependencies:
        assert "marcar_uso" not in [p.name for p in dep.query_params]


def test_o_porteiro_da_extensao_olha_o_CORPO_e_vem_antes_do_debounce():
    """Deslogado, o TransfereGov pode responder 200 NA MESMA URL com o form SAML
    de auto-envio: `pareceLogin(r.url)` sozinho dizia "logado"."""
    amb = (EXT / "ambientes.js").read_text(encoding="utf-8")
    assert "SAMLRequest" in amb and "async function chromeEstaLogado" in amb
    bg = (EXT / "background.js").read_text(encoding="utf-8")
    corpo = bg[bg.index("async function capture("):bg.index("// 1) AUTO-CAPTURA")]
    assert corpo.index("await chromeEstaLogado()") < corpo.index("lastCaptureAt.set(dKey, now)")
    assert 'tab.status !== "complete"' in bg, "o roteiro avancava com o SAML ainda em transito"


# ------------------------------------------- captura DIRETA e a hora do login --
OBS_LOGIN = "[SESSION] capturado em 2026-09-23T14:27:18+00:00 | cookies=14 httpOnly=9 | url=x | ua=y"


@pytest.mark.parametrize("sso_payload, preserva", [
    (SSO_A, True),     # mesma sessao gov.br (worker parado, SP zumbi): nao e login
    (SSO_B, False),    # cookie de sessao do gov.br novo: login NOVO
])
def test_captura_DIRETA_so_reinicia_a_hora_do_login_com_login_NOVO(monkeypatch, captura, sso_payload, preserva):
    principal = SimpleNamespace(id=7, senha_encrypted="JAR", observacao=OBS_LOGIN,
                                atualizado_por_id=None, municipio_id=None)
    monkeypatch.setattr(sc.crypto, "decrypt", lambda s: json.dumps({"format": "cookies_full", "cookies": [SSO_A]}))
    db = FakeDb(principal=principal, sso=("success", 999.0, None))      # medicao velha: grava direto
    r = captura.chama(db, cookies=[sc.CookieFull(**sso_payload)])
    assert r["status"] == "ok" and principal.senha_encrypted.startswith("CIFRADO:"), "o jar tem de ser trocado"
    from services.sessao_govbr import login_em_da_observacao
    hora = login_em_da_observacao(principal.observacao)
    if preserva:
        assert hora.isoformat() == "2026-09-23T14:27:18+00:00" and "recapturado em" in principal.observacao
    else:
        assert hora.isoformat() != "2026-09-23T14:27:18+00:00" and "recapturado em" not in principal.observacao


def test_cookies_meta_nunca_leva_valor_e_aguenta_vencimento_absurdo():
    from routers.control import _cookies_meta
    m = _cookies_meta([{"name": "Session_Gov_Br_Prod", "value": "SEGREDO", "domain": ".sso.acesso.gov.br",
                        "httpOnly": True, "expirationDate": 1e20},
                       {"name": "x", "value": "SEGREDO2", "domain": "d", "expirationDate": 1790000000}])
    assert "SEGREDO" not in json.dumps(m)
    assert m[0]["expira_em"] is None and m[1]["expira_em"].startswith("2026-")
