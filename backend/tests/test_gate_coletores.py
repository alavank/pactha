"""
O gate dos COLETORES (CAUC, Acordo FES, SISMOB, TransfereGov) — testado pelo
que ele NAO pode fazer em modo aviso.

Os disparos de coleta (`/refresh`, `/run-scraper`) e os endpoints administrativos
do TransfereGov nao checavam nada alem de "esta logado": qualquer conta — inclusive
uma criada com ZERO telas — baixava planilha do estado inteiro, reescrevia tabela
do tenant e lia o estado da sessao gov.br guardada no Cofre. Numa VPS burstable
(~0,6 vCPU) isso e alavanca de indisponibilidade, nao so de confidencialidade.

O que estes testes provam, endpoint a endpoint:

  (a) EM MODO AVISO O COMPORTAMENTO E IDENTICO AO DE HOJE. Nos gates NOVOS
      (`authz.exigir_tela` no /refresh do CAUC e do Acordo FES, no plano-acao e
      no sessao-status) a coleta roda, a resposta e a mesma, nenhum 403 novo —
      so fica a linha na trilha. E a exigencia mais dura do incremento, e a
      unica que, se quebrar, quebra Monte Siao numa segunda-feira.
  (a2) "IDENTICO A HOJE" TEM O OUTRO LADO, e ele e igualmente obrigatorio: o
      que JA NEGAVA continua negando em modo aviso. `services.auth.ensure_tela`
      e `ensure_municipio_access` NAO passam pelo modo — o /refresh do SISMOB
      (que ja exigia a tela antes deste incremento) e o /admin/run-scraper (que
      ja exigia o municipio) barram nos DOIS modos. Se o modo aviso valesse
      para elas, as ~128 travas antigas parariam de negar durante a semana de
      observacao e o sistema ficaria MAIS ABERTO justamente no incremento feito
      para fecha-lo.
  (b) EM MODO BLOQUEIO a negativa vem ANTES do trabalho caro: sem ingestao, sem
      chamada de saida, sem consulta ao Cofre. Um gate que barra depois de gastar
      a CPU nao protege de nada.
  (c) FALHA DA PROPRIA TRILHA NAO DERRUBA A REQUISICAO — nem no endpoint, nem a
      ponto de mudar o 403 de quem foi barrado de verdade.

Rodar:
    python -m pytest backend/tests/test_gate_coletores.py -v
"""
import asyncio

import httpx
import pytest
from fastapi import HTTPException

import ingestion.acordofes_ingest as acordofes_ingest
import ingestion.cauc_ingest as cauc_ingest
import ingestion.sismob_obras as sismob_obras
from routers import acordofes, cauc, sismob, transferegov
from services import authz

MSG_TELA = "Voce nao tem acesso a esta tela"
MSG_MUNICIPIO = "Voce nao tem acesso a este municipio"
MSG_SEM_MUNICIPIO = "Selecione um municipio permitido"


class Usuario:
    """Espelha o que o codigo real le do User: id/email/name + os escopos que
    `load_user_scopes` anexa. `None` = admin (passa em tudo)."""

    def __init__(self, telas=None, municipios=None, id=7,
                 email="servidor@montesiao.mg.gov.br", name="Servidor"):
        self.id = id
        self.email = email
        self.name = name
        self.allowed_telas = telas
        self.allowed_municipio_ids = municipios


def sem_nada():
    """A conta do enunciado: criada com ZERO telas e ZERO municipios, e que hoje
    dispara coleta pesada do sistema inteiro."""
    return Usuario(telas=set(), municipios=set())


def com_municipio_sem_tela(municipio=1):
    """O caso CENTRAL do incremento: a pessoa e do municipio (o gate antigo, se
    houver, deixa passar) e nao tem a tela (o gate NOVO e quem decide). E o unico
    recorte em que o modo de fato muda o resultado."""
    return Usuario(telas=set(), municipios={municipio})


@pytest.fixture(autouse=True)
def _isolar(monkeypatch):
    authz.limpar_dedupe()
    authz.limpar_contexto()
    monkeypatch.delenv("AUTHZ_MODO", raising=False)
    yield
    authz.limpar_dedupe()
    authz.limpar_contexto()


@pytest.fixture(autouse=True)
def envios(monkeypatch):
    """Intercepta o agendamento da gravacao.

    AUTOUSE de proposito: estes testes rodam dentro de um event loop de verdade
    (`asyncio.run`), entao sem isto o authz agendaria tarefa de fundo abrindo
    sessao de banco real — o teste passaria mesmo assim, mas deixaria conexao
    pendurada e ruido de "task was destroyed" no relatorio."""
    registrados: list = []

    def _falso(dados):
        registrados.append(dados)
        return True

    monkeypatch.setattr(authz, "_enviar", _falso)
    return registrados


# ---------------------------------------------------------------------------
# Dublês
# ---------------------------------------------------------------------------
class _Contador:
    """Ingestao de mentira: conta quantas vezes foi disparada."""

    def __init__(self, retorno=42):
        self.chamadas = 0
        self.retorno = retorno

    def __call__(self, *a, **kw):
        self.chamadas += 1
        return self.retorno


class _Resultado:
    def __init__(self, linha):
        self._linha = linha

    def first(self):
        return self._linha


class FakeDb:
    """So o que os endpoints deste grupo usam: execute() -> .first()."""

    def __init__(self, linha=None):
        self.linha = linha
        self.consultas: list = []

    async def execute(self, stmt, params=None):
        self.consultas.append((str(stmt), params))
        return _Resultado(self.linha)


class _RespostaFalsa:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _cliente_falso(registro: list):
    """Substitui httpx.AsyncClient para nenhum teste sair para a internet — e
    para dar como PROVAR que, em bloqueio, nenhuma chamada de saida acontece."""

    class ClienteFalso:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            registro.append(url)
            return _RespostaFalsa({"eco": url})

    return ClienteFalso


# ---------------------------------------------------------------------------
# POST /api/cauc/refresh — antes: so login. Agora: tela `cauc`.
# ---------------------------------------------------------------------------
def test_cauc_refresh_em_aviso_roda_exatamente_como_hoje(monkeypatch, envios):
    """A coleta ACONTECE para quem nao tem a tela, a resposta e a mesma de
    sempre, e o unico efeito novo e a linha na trilha."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    ingest = _Contador(retorno=853)
    monkeypatch.setattr(cauc_ingest, "ingest", ingest)

    assert asyncio.run(cauc.refresh(current=sem_nada())) == {
        "ok": True, "municipios": 853}
    assert ingest.chamadas == 1
    assert envios[0]["acao"] == authz.ACAO_NEGARIA
    assert envios[0]["detalhes"]["exigido"] == "cauc"


def test_cauc_refresh_em_bloqueio_nega_antes_de_gastar_a_vps(monkeypatch, envios):
    """Gate que barra DEPOIS de baixar o CSV do Tesouro nao protege a maquina."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    ingest = _Contador()
    monkeypatch.setattr(cauc_ingest, "ingest", ingest)

    with pytest.raises(HTTPException) as e:
        asyncio.run(cauc.refresh(current=sem_nada()))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_TELA
    assert ingest.chamadas == 0


@pytest.mark.parametrize("modo_env,barra", [("aviso", False), ("bloqueio", True)])
def test_cauc_refresh_com_o_municipio_e_sem_a_tela(monkeypatch, envios, modo_env, barra):
    """O CASO CENTRAL do incremento, isolado da checagem de municipio.

    Quem e do municipio ja passava por qualquer trava antiga; o que decide aqui e
    o gate NOVO de tela — e so ele obedece ao modo. Em aviso a coleta acontece e
    fica a linha; em bloqueio vem o 403. Se este par de casos parar de divergir,
    ou o modo aviso deixou de existir ou a trava nunca ligou."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    ingest = _Contador(retorno=5)
    monkeypatch.setattr(cauc_ingest, "ingest", ingest)
    usuario = com_municipio_sem_tela()

    if barra:
        with pytest.raises(HTTPException) as e:
            asyncio.run(cauc.refresh(current=usuario))
        assert e.value.status_code == 403
        assert e.value.detail == MSG_TELA
        assert ingest.chamadas == 0
        assert envios[0]["acao"] == authz.ACAO_NEGOU
    else:
        assert asyncio.run(cauc.refresh(current=usuario)) == {
            "ok": True, "municipios": 5}
        assert ingest.chamadas == 1
        assert envios[0]["acao"] == authz.ACAO_NEGARIA
    assert envios[0]["detalhes"]["exigido"] == "cauc"


@pytest.mark.parametrize("modo_env", ["aviso", "bloqueio"])
def test_cauc_refresh_com_a_tela_passa_calado(monkeypatch, envios, modo_env):
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    ingest = _Contador(retorno=1)
    monkeypatch.setattr(cauc_ingest, "ingest", ingest)

    assert asyncio.run(cauc.refresh(current=Usuario(telas={"cauc"}, municipios={1})))
    assert ingest.chamadas == 1
    assert envios == []


def test_cauc_refresh_nao_quebra_se_a_trilha_falhar(monkeypatch, envios):
    """A garantia mais dura do incremento, verificada no endpoint e nao so na
    funcao: um gate que existe para NAO quebrar nada nao pode quebrar por causa
    do proprio log."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")

    def _explode(_dados):
        raise RuntimeError("banco fora do ar no meio da gravacao da trilha")

    monkeypatch.setattr(authz, "_enviar", _explode)
    ingest = _Contador(retorno=7)
    monkeypatch.setattr(cauc_ingest, "ingest", ingest)

    assert asyncio.run(cauc.refresh(current=sem_nada())) == {
        "ok": True, "municipios": 7}
    assert ingest.chamadas == 1


def test_cauc_refresh_em_bloqueio_nega_igual_se_a_trilha_falhar(monkeypatch, envios):
    """O outro lado da mesma garantia: a trilha nao pode DERRUBAR a requisicao,
    e tambem nao pode SALVA-LA. Se o registro do `authz.negou` explodir, o 403
    sai igual — senao uma falha de banco viraria porta aberta no dia em que a
    trava estivesse valendo."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")

    def _explode(_dados):
        raise RuntimeError("banco fora do ar no meio da gravacao da trilha")

    monkeypatch.setattr(authz, "_enviar", _explode)
    ingest = _Contador()
    monkeypatch.setattr(cauc_ingest, "ingest", ingest)

    with pytest.raises(HTTPException) as e:
        asyncio.run(cauc.refresh(current=sem_nada()))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_TELA
    assert ingest.chamadas == 0


# ---------------------------------------------------------------------------
# POST /api/acordofes/refresh — antes: so login. Agora: tela `acordofes`.
# ---------------------------------------------------------------------------
def test_acordofes_refresh_em_aviso_roda_exatamente_como_hoje(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    ingest = _Contador(retorno=1402)
    monkeypatch.setattr(acordofes_ingest, "ingest", ingest)

    assert asyncio.run(acordofes.refresh(current=sem_nada())) == {
        "ok": True, "credores": 1402}
    assert ingest.chamadas == 1
    assert envios[0]["detalhes"]["exigido"] == "acordofes"


def test_acordofes_refresh_em_bloqueio_nega_antes_do_excel(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    ingest = _Contador()
    monkeypatch.setattr(acordofes_ingest, "ingest", ingest)

    with pytest.raises(HTTPException) as e:
        asyncio.run(acordofes.refresh(current=sem_nada()))
    assert e.value.status_code == 403
    assert ingest.chamadas == 0


# ---------------------------------------------------------------------------
# POST /api/sismob/refresh — ja exigia a tela ANTES deste incremento, e por isso
# NAO passa pelo modo aviso: usa `services.auth.ensure_tela`, que nega sempre.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("modo_env", ["aviso", "bloqueio"])
def test_sismob_refresh_continua_exigindo_a_tela_nos_dois_modos(
        monkeypatch, envios, modo_env):
    """Regressao dupla, e a segunda metade e a que este incremento quase perdeu.

    (1) Este era o unico /refresh do grupo que ja tinha gate — ninguem pode
        'padronizar' os quatro e apagar o que ja funcionava.
    (2) O gate dele e o ANTIGO (`ensure_tela`), entao NEGA TAMBEM EM MODO AVISO.
        Rotea-lo pelo modo faria uma trava que vale hoje parar de valer durante a
        semana de observacao — o oposto do que foi prometido ao dono, e no
        incremento feito para FECHAR o sistema.

    E como a negativa e real (nao hipotetica), nao ha linha `authz.negaria`: a
    trilha do modo aviso e para o que TERIA sido barrado, nao para o que foi."""
    import os

    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    ingest = _Contador()
    monkeypatch.setattr(sismob_obras, "ingest", ingest)

    with pytest.raises(HTTPException) as e:
        asyncio.run(sismob.refresh(current=sem_nada()))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_TELA
    assert ingest.chamadas == 0
    assert envios == []
    # A env de negocio nao pode ter sido tocada por uma chamada que nem passou
    # do gate — ela e ligada DEPOIS, e removida no finally.
    assert os.getenv("SISMOB_FORCE") is None


@pytest.mark.parametrize("modo_env", ["aviso", "bloqueio"])
def test_sismob_refresh_com_a_tela_roda_e_limpa_a_env(monkeypatch, envios, modo_env):
    """Para quem TEM a tela a coleta acontece igual nos dois modos — inclusive o
    SISMOB_FORCE, que e logica de negocio e nao pode ficar pendurada no processo
    (o proximo ciclo automatico voltaria a ignorar o auto-throttle)."""
    import os

    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    ingest = _Contador(retorno=12)
    monkeypatch.setattr(sismob_obras, "ingest", ingest)

    assert asyncio.run(sismob.refresh(
        current=Usuario(telas={"sismob"}, municipios={1}))) == {
        "ok": True, "obras": 12}
    assert ingest.chamadas == 1
    assert os.getenv("SISMOB_FORCE") is None
    assert envios == []


# ---------------------------------------------------------------------------
# GET /api/transferegov/plano-acao/{id} — antes: so login. Agora: tela.
# ---------------------------------------------------------------------------
def test_plano_acao_em_aviso_responde_igual_e_sai_para_a_rede(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    saidas: list = []
    monkeypatch.setattr(httpx, "AsyncClient", _cliente_falso(saidas))

    resp = asyncio.run(transferegov.detalhe(plano_acao_id=99, current=sem_nada()))
    assert set(resp) == {"plano", "resumo", "extrato"}
    assert len(saidas) == 3                      # detalhe + resumo + extrato
    assert envios[0]["detalhes"]["exigido"] == "transferegov"


def test_plano_acao_em_bloqueio_nao_sai_para_a_rede(monkeypatch, envios):
    """Sem gate, uma conta sem telas usava a API como proxy: tres requisicoes de
    saida de 30s cada, por chamada."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    saidas: list = []
    monkeypatch.setattr(httpx, "AsyncClient", _cliente_falso(saidas))

    with pytest.raises(HTTPException) as e:
        asyncio.run(transferegov.detalhe(plano_acao_id=99, current=sem_nada()))
    assert e.value.status_code == 403
    assert saidas == []


# ---------------------------------------------------------------------------
# GET /api/transferegov/admin/sessao-status — antes: so login. Agora: `sessoes`.
# ---------------------------------------------------------------------------
def test_sessao_status_em_aviso_responde_igual(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    db = FakeDb(linha=None)

    resp = asyncio.run(transferegov.sessao_status(db=db, user=sem_nada()))
    assert resp["has_session"] is False
    assert len(db.consultas) == 1                # a consulta de sempre aconteceu
    assert envios[0]["detalhes"]["exigido"] == "sessoes"


def test_sessao_status_em_bloqueio_nao_toca_no_cofre(monkeypatch, envios):
    """A negativa vem antes da leitura de `cofre_senhas` — o endpoint devolve
    `observacao` da credencial e os claims do gov.br."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    db = FakeDb(linha=None)

    with pytest.raises(HTTPException) as e:
        asyncio.run(transferegov.sessao_status(db=db, user=sem_nada()))
    assert e.value.status_code == 403
    assert db.consultas == []


def test_sessao_status_exige_sessoes_e_nao_transferegov(monkeypatch, envios):
    """A tela e a da pagina que consome isto (/dashboard/sessoes), operacional da
    Alavank — nao a do irmao /admin/run-scraper. Quem tem so `transferegov` nao
    passa a enxergar credencial de portal do governo."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    so_transferegov = Usuario(telas={"transferegov"}, municipios={1})

    with pytest.raises(HTTPException):
        asyncio.run(transferegov.sessao_status(db=FakeDb(), user=so_transferegov))

    authz.limpar_dedupe()
    com_sessoes = Usuario(telas={"sessoes"}, municipios={1})
    assert asyncio.run(
        transferegov.sessao_status(db=FakeDb(linha=None), user=com_sessoes)
    )["has_session"] is False


# ---------------------------------------------------------------------------
# POST /api/transferegov/admin/run-scraper — o irmao que JA tinha os dois gates
# (`ensure_municipio_access` + `ensure_tela`). Nada aqui mudou no incremento, e
# provar isso E o teste: e este endpoint que responde pela promessa "em modo
# aviso, comportamento identico ao de hoje".
# ---------------------------------------------------------------------------
def _espia_agendamento(monkeypatch) -> list:
    """Registra se o scraper chegou a ser agendado.

    O endpoint dispara `asyncio.create_task(_bg())` DEPOIS dos gates; contar
    chamadas do `run`/`run_one` nao serviria de prova, porque a tarefa e
    cancelada no fim do `asyncio.run` antes de dar o primeiro passo. O que
    interessa e se houve agendamento."""
    agendadas: list = []

    def _falso(coro, *a, **kw):
        agendadas.append(coro)
        coro.close()          # sem isto sobra "coroutine was never awaited"
        return None

    monkeypatch.setattr(asyncio, "create_task", _falso)
    return agendadas


@pytest.mark.parametrize("modo_env", ["aviso", "bloqueio"])
def test_run_scraper_sem_o_municipio_nega_nos_dois_modos(monkeypatch, envios, modo_env):
    """A PROMESSA DO INCREMENTO, verificada pelo lado que ninguem olha.

    Quem pede um municipio fora do seu escopo leva 403 HOJE. Se o modo aviso
    valesse para `ensure_municipio_access`, ele passaria a receber os dados
    durante a semana de observacao — alargamento de acesso publicado com a
    etiqueta de 'nao muda nada'. Nega nos dois modos, com a mensagem de sempre."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    agendadas = _espia_agendamento(monkeypatch)
    de_outro_municipio = Usuario(telas={"transferegov"}, municipios={1})

    with pytest.raises(HTTPException) as e:
        asyncio.run(transferegov.run_scraper_manual(
            municipio_id=99, user=de_outro_municipio))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_MUNICIPIO
    assert agendadas == []
    # Negativa que ja existia nao vira linha de "eu teria negado": ela negou.
    assert envios == []


@pytest.mark.parametrize("modo_env", ["aviso", "bloqueio"])
def test_run_scraper_sem_municipio_no_pedido_e_malformado(monkeypatch, envios, modo_env):
    """Pedido sem municipio nao e permissao que falta — e pedido malformado, e
    por isso e negado nos dois modos. Deixa-lo passar em aviso rodaria o scraper
    de TODOS os municipios para uma conta com escopo de um so."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    agendadas = _espia_agendamento(monkeypatch)

    with pytest.raises(HTTPException) as e:
        asyncio.run(transferegov.run_scraper_manual(
            municipio_id=None, user=Usuario(telas={"transferegov"}, municipios={1})))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_SEM_MUNICIPIO
    assert agendadas == []


@pytest.mark.parametrize("modo_env", ["aviso", "bloqueio"])
def test_run_scraper_com_o_municipio_e_sem_a_tela_tambem_nega_nos_dois_modos(
        monkeypatch, envios, modo_env):
    """MESMO recorte de usuario do caso central do CAUC (tem o municipio, nao tem
    a tela) e resultado OPOSTO em modo aviso — porque aqui a tela ja era exigida
    antes do incremento. E a diferenca entre `services.auth.ensure_tela` (nega
    sempre) e `services.authz.exigir_tela` (respeita o modo), vista de fora."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    agendadas = _espia_agendamento(monkeypatch)

    with pytest.raises(HTTPException) as e:
        asyncio.run(transferegov.run_scraper_manual(
            municipio_id=1, user=com_municipio_sem_tela(1)))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_TELA
    assert agendadas == []
    assert envios == []


# ---------------------------------------------------------------------------
# Admin nao pode ter sido barrado por engano em NENHUM deles.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("modo_env", ["aviso", "bloqueio"])
def test_admin_passa_em_todos_os_gates_novos(monkeypatch, envios, modo_env):
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    admin = Usuario(telas=None, municipios=None)
    monkeypatch.setattr(cauc_ingest, "ingest", _Contador(retorno=1))
    monkeypatch.setattr(acordofes_ingest, "ingest", _Contador(retorno=1))
    monkeypatch.setattr(sismob_obras, "ingest", _Contador(retorno=1))
    monkeypatch.setattr(httpx, "AsyncClient", _cliente_falso([]))

    assert asyncio.run(cauc.refresh(current=admin))["ok"] is True
    assert asyncio.run(acordofes.refresh(current=admin))["ok"] is True
    assert asyncio.run(sismob.refresh(current=admin))["ok"] is True
    assert asyncio.run(transferegov.detalhe(plano_acao_id=1, current=admin))
    assert asyncio.run(transferegov.sessao_status(db=FakeDb(), user=admin))
    assert envios == []                          # admin nao gera ruido na trilha
