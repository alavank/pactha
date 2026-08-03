"""
O gate das telas de CONSULTA — SIGCON (detalhe), Diario Oficial MG, FNS e SIMEC.

O que estes testes protegem NAO e a capacidade de barrar: e a de NAO barrar. Os
quatro routers aqui atendem gente que trabalha em Monte Siao HOJE, e parte deles
ganhou checagem que nunca existiu.

⚠️ SAO DUAS FAMILIAS DE GATE, e confundi-las e justamente o que estes testes
existem para impedir:

  GATE NOVO — `authz.exigir_tela`, `authz.exigir_municipio` e o
  `authz.ensure_dono` (que delega ao segundo). Nasceram no Incremento 2, entao
  em todo lugar onde aparecem NAO havia checagem nenhuma antes. So estes
  respeitam `AUTHZ_MODO`:

      modo aviso     -> a chamada SEGUE (o teste prova que a execucao passou do
                        gate) e vira linha na trilha;
      modo bloqueio  -> 403 com a MESMA mensagem de sempre.

  CHECAGEM PRE-EXISTENTE — `services.auth.ensure_tela` e
  `ensure_municipio_access`, chamadas diretamente pelo router. Elas NEGAM NOS
  DOIS MODOS. Ja eram chamadas em ~128 pontos ANTES do Incremento 2, e cada um
  e uma trava que JA VALE hoje: roteá-las pelo modo aviso faria essas 128
  negativas ANTIGAS pararem de negar durante a semana de observacao — o sistema
  ficaria MAIS ABERTO exatamente no incremento que existe para fecha-lo, e o
  dono recebeu a promessa oposta ("em modo aviso, comportamento IDENTICO ao de
  hoje"). Negativa antiga tambem nao vira linha na trilha: ela sai como sempre
  saiu.

Os quatro routers deste arquivo caem dos dois lados, e e por isso que "de outro
municipio" tem resposta DIFERENTE em cada um:

    SIGCON `/estadual/{id}`  -> nao conferia nada; o dono da linha e
                                `ensure_dono` (novo) -> em aviso PASSA;
    SIMEC e FNS `/buscar`    -> ja conferiam municipio -> 403 NOS DOIS MODOS.

Consequencia pratica para quem le os testes abaixo: nos endpoints que tem os
DOIS gates, o teste de "em aviso segue" da o municipio ao usuario. Sem isso a
checagem antiga barra primeiro e o gate novo nunca chega a ser exercitado — o
teste passaria pelo motivo errado.

A prova de "seguiu" e um sentinela: a primeira coisa que o endpoint faz depois do
gate e trocada por algo que levanta uma excecao so nossa. Se ela sobe, a execucao
chegou la — sem tocar na rede do Jornal MG nem na do FNS.

Rodar:
    python -m pytest backend/tests/test_gate_consultas.py -v
"""
import asyncio
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services import authz
from routers import convenios as r_convenios
from routers import dou_mg as r_dou
from routers import fns as r_fns
from routers import simec as r_simec

MSG_TELA = "Voce nao tem acesso a esta tela"
MSG_MUNICIPIO = "Voce nao tem acesso a este municipio"


class Usuario:
    """Igual ao do test_authz: id/email/name + os escopos que `load_user_scopes`
    anexa. `None` nos dois = admin (passa em tudo)."""

    def __init__(self, telas=None, municipios=None, id=7,
                 email="servidor@montesiao.mg.gov.br", name="Servidor"):
        self.id = id
        self.email = email
        self.name = name
        self.allowed_telas = telas
        self.allowed_municipio_ids = municipios


SEM_NADA = dict(telas=set(), municipios=set())      # conta com ZERO permissao
ADMIN = dict(telas=None, municipios=None)


def com_tela(tela, municipios=frozenset({1})):
    """Tem a tela, mas so enxerga o municipio 1 — o caso que separa o gate de
    VERBO (`ensure_tela`) do gate de LINHA (`ensure_dono`)."""
    return Usuario(telas={tela}, municipios=set(municipios))


class _Sentinela(Exception):
    """Marca 'a execucao passou do gate'. Nao herda de HTTPException de
    proposito: se herdasse, um 403 do gate poderia ser confundido com ela."""


# ---------------------------------------------------------------------------
# Banco de mentira
# ---------------------------------------------------------------------------
class _Resultado:
    def __init__(self, linha=None, objeto=None, linhas=None):
        self._linha = linha
        self._objeto = objeto
        self._linhas = linhas or []

    def first(self):
        return self._linha

    def scalar_one_or_none(self):
        return self._objeto

    def fetchall(self):
        return self._linhas


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeDb:
    """So o que estes endpoints usam: begin_nested(), execute() e commit()."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.consultas: list = []
        self.commits = 0

    def begin_nested(self):
        return _Savepoint()

    async def execute(self, stmt, params=None):
        self.consultas.append((str(stmt), params))
        return self.respostas.pop(0) if self.respostas else _Resultado()

    async def commit(self):
        self.commits += 1


def convenio_falso(municipio_id=1):
    """O bastante para `get_convenio_estadual_detail` montar a resposta."""
    return SimpleNamespace(
        id=42, municipio_id=municipio_id, raw_data={"nr_proposta": "001030/2026"},
        nr_sigcon="1481000677/2026", nr_siafi="123456", nr_plano_trabalho="98765",
        situacao="EM VIGOR", dt_assinatura=date(2026, 1, 5),
        dt_publicacao=date(2026, 1, 10), dt_vigencia_inicial=date(2026, 1, 10),
        dt_vigencia_atual=date(2026, 12, 31), dt_vigencia_final=date(2026, 12, 31),
        objeto="Pavimentacao", objetivo="Melhoria viaria",
        orgao_concedente="SEINFRA", convenente_nome="MUNICIPIO DE MONTE SIAO",
        valor_concedente=100, valor_contrapartida=10, valor_total=110,
        qt_alteracoes=0, ano=2026, tp_instrumento="CONVENIO", fonte="SIGCON-MG",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def envios(monkeypatch):
    """Intercepta o agendamento da gravacao (senao o teste abriria sessao de
    banco de verdade) e zera a memoria de dedupe entre os testes."""
    registrados: list = []

    def _falso(dados):
        registrados.append(dados)
        return True

    monkeypatch.setattr(authz, "_enviar", _falso)
    authz.limpar_dedupe()
    authz.limpar_contexto()
    monkeypatch.delenv("AUTHZ_MODO", raising=False)
    yield registrados
    authz.limpar_dedupe()
    authz.limpar_contexto()


@pytest.fixture
def aviso(monkeypatch):
    monkeypatch.setenv("AUTHZ_MODO", "aviso")


@pytest.fixture
def bloqueio(monkeypatch):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")


@pytest.fixture(params=[authz.MODO_AVISO, authz.MODO_BLOQUEIO])
def qualquer_modo(request, monkeypatch):
    """Roda o mesmo teste NOS DOIS MODOS.

    Para tudo o que nao pode depender do modo: admin passa, checagem
    pre-existente nega, pedido malformado nega. Um teste so em `bloqueio` nao
    prova nada sobre a semana de observacao, que roda em `aviso`."""
    monkeypatch.setenv("AUTHZ_MODO", request.param)
    return request.param


def negado(excecao) -> None:
    assert excecao.value.status_code == 403


# ===========================================================================
# SIGCON — detalhe por id (`GET /api/convenios/estadual/{conv_id}`)
# ===========================================================================
def _detalhe(db, usuario, conv_id=42):
    return asyncio.run(
        r_convenios.get_convenio_estadual_detail(conv_id=conv_id, db=db,
                                                 current=usuario))


def test_detalhe_sigcon_sem_tela_bloqueia(bloqueio):
    with pytest.raises(HTTPException) as e:
        _detalhe(FakeDb(), Usuario(**SEM_NADA))
    negado(e)
    assert e.value.detail == MSG_TELA


def test_detalhe_sigcon_sem_tela_nem_consulta_o_banco(bloqueio):
    """O gate vem antes de qualquer leitura: nada de gastar consulta para
    depois negar."""
    db = FakeDb()
    with pytest.raises(HTTPException):
        _detalhe(db, Usuario(**SEM_NADA))
    assert db.consultas == []


def test_detalhe_sigcon_de_outro_municipio_bloqueia(bloqueio):
    """O buraco que `ensure_tela` NAO fecha: tem a tela do SIGCON, mas o id e de
    um convenio de outro municipio."""
    db = FakeDb(_Resultado(linha=(99,)))          # a linha pertence ao mun. 99
    with pytest.raises(HTTPException) as e:
        _detalhe(db, com_tela("convenios"))
    negado(e)
    assert e.value.detail == MSG_MUNICIPIO


def test_detalhe_sigcon_de_outro_municipio_em_aviso_responde_igual(aviso, envios):
    """A EXIGENCIA MAIS DURA: em modo aviso a resposta e a de hoje, inteira.

    ⚠️ E POR QUE AQUI E "PASSA" e no SIMEC (la embaixo) e "403 nos dois modos"?
    Porque a checagem e de familia diferente. Este endpoint nao conferia NADA
    alem de estar logado — quem soubesse o id lia o convenio de qualquer
    municipio. O dono da LINHA e conferido por `authz.ensure_dono`, que nao
    existia antes do Incremento 2 e por isso delega ao gate NOVO
    (`authz.exigir_municipio`), que respeita o modo. Exigir 403 aqui em modo
    aviso seria estrear uma negativa nova durante a semana de observacao — o
    apagao de segunda-feira que o incremento existe para evitar.

    No SIMEC a mesma pergunta e respondida por `ensure_municipio_access`, que ja
    negava antes: la o modo nao alcanca, e o 403 sai nos dois."""
    db = FakeDb(_Resultado(linha=(99,)), _Resultado(objeto=convenio_falso(99)))
    saida = _detalhe(db, com_tela("convenios"))
    assert saida["id"] == 42
    assert saida["titulo"] == "Pavimentacao"
    assert [e["acao"] for e in envios] == [authz.ACAO_NEGARIA]
    # O municipio da LINHA, e nao o do pedido — e a trilha diz de ONDE veio a
    # negativa, senao "apagou RM de outro municipio" e "pediu tela de outro
    # municipio" sairiam identicas na Auditoria.
    assert envios[0]["municipio_id"] == 99
    assert envios[0]["detalhes"]["origem"] == {
        "tabela": "convenios_estadual", "coluna": "id", "id": "42"}


def test_detalhe_sigcon_sem_tela_mas_com_o_municipio_segue_em_aviso(aviso, envios):
    """O CASO CENTRAL do incremento, no endpoint que tem os DOIS gates.

    O usuario enxerga o municipio do convenio, entao passa pela checagem antiga e
    esbarra so no gate NOVO de tela (`authz.exigir_tela`). Em modo aviso a
    resposta e a de hoje, inteira, e o esbarrao vira linha na trilha.

    E por isso que o municipio 1 aparece nos dois lados: com um usuario sem
    municipio nenhum, `ensure_dono` barraria antes e o gate novo nunca seria
    exercitado."""
    db = FakeDb(_Resultado(linha=(1,)), _Resultado(objeto=convenio_falso(1)))
    saida = _detalhe(db, Usuario(telas=set(), municipios={1}))
    assert saida["id"] == 42
    assert saida["titulo"] == "Pavimentacao"
    assert [e["acao"] for e in envios] == [authz.ACAO_NEGARIA]
    assert envios[0]["detalhes"]["exigido"] == "convenios"


def test_detalhe_sigcon_sem_tela_mas_com_o_municipio_bloqueia(bloqueio, envios):
    """O mesmo usuario do teste acima, com a trava ligada: 403 da tela, e a
    trilha registra a negativa de verdade (`authz.negou`)."""
    db = FakeDb(_Resultado(linha=(1,)), _Resultado(objeto=convenio_falso(1)))
    with pytest.raises(HTTPException) as excecao:
        _detalhe(db, Usuario(telas=set(), municipios={1}))
    negado(excecao)
    assert excecao.value.detail == MSG_TELA
    assert [e["acao"] for e in envios] == [authz.ACAO_NEGOU]


def test_detalhe_sigcon_do_proprio_municipio_nao_faz_ruido(bloqueio, envios):
    db = FakeDb(_Resultado(linha=(1,)), _Resultado(objeto=convenio_falso(1)))
    assert _detalhe(db, com_tela("convenios"))["id"] == 42
    assert envios == []


def test_detalhe_sigcon_inexistente_continua_404_e_nao_403(bloqueio):
    """Quem responde por 'nao achei' e o endpoint. `ensure_dono` nao inventa
    403 para registro que nao existe — senao a trilha diria 'sem permissao'
    onde a verdade e 'id errado'."""
    db = FakeDb(_Resultado(linha=None), _Resultado(objeto=None))
    with pytest.raises(HTTPException) as e:
        _detalhe(db, com_tela("convenios"))
    assert e.value.status_code == 404


def test_detalhe_sigcon_admin_passa_sem_ruido(qualquer_modo, envios):
    """Admin (`allowed_* = None`) atravessa os dois gates nos dois modos, e nao
    gera aviso — senao a trilha da semana de observacao viria cheia de linhas de
    quem sempre pode tudo."""
    db = FakeDb(_Resultado(linha=(99,)), _Resultado(objeto=convenio_falso(99)))
    assert _detalhe(db, Usuario(**ADMIN))["id"] == 42
    assert envios == []


def test_detalhe_sigcon_falha_de_leitura_do_dono_nao_derruba(aviso):
    """`ensure_dono` sem leitura nao decide — e nao levanta. O endpoint segue e
    esbarra no proprio problema na consulta dele."""
    class DbQuebrado(FakeDb):
        async def execute(self, stmt, params=None):
            self.consultas.append((str(stmt), params))
            if len(self.consultas) == 1:
                raise RuntimeError("relation nao existe")
            return _Resultado(objeto=convenio_falso(1))

    assert _detalhe(DbQuebrado(), com_tela("convenios"))["id"] == 42


# ===========================================================================
# SIGCON — disparo de coleta (`POST /api/convenios/refresh-sigcon`)
# ===========================================================================
def _refresh(db, usuario, monkeypatch):
    async def _nada(*a, **k):
        return True

    monkeypatch.setattr(r_convenios, "registrar", _nada)
    return asyncio.run(r_convenios.refresh_sigcon(request=None, db=db,
                                                  current=usuario))


def test_refresh_sigcon_sem_tela_bloqueia(bloqueio, monkeypatch):
    with pytest.raises(HTTPException) as e:
        _refresh(FakeDb(), Usuario(**SEM_NADA), monkeypatch)
    negado(e)
    assert e.value.detail == MSG_TELA


def test_refresh_sigcon_sem_tela_nao_enfileira_nada(bloqueio, monkeypatch):
    """Coleta pesada: negar DEPOIS de enfileirar nao adiantaria nada."""
    db = FakeDb()
    with pytest.raises(HTTPException):
        _refresh(db, Usuario(**SEM_NADA), monkeypatch)
    assert db.consultas == [] and db.commits == 0


def test_refresh_sigcon_em_aviso_enfileira_como_hoje(aviso, monkeypatch, envios):
    db = FakeDb(_Resultado(linha=(5,)))
    saida = _refresh(db, Usuario(**SEM_NADA), monkeypatch)
    assert saida["status"] == "triggered" and saida["job_id"] == 5
    assert envios[0]["acao"] == authz.ACAO_NEGARIA


def test_refresh_sigcon_com_a_tela_nao_faz_ruido(bloqueio, monkeypatch, envios):
    db = FakeDb(_Resultado(linha=(5,)))
    assert _refresh(db, com_tela("convenios"), monkeypatch)["status"] == "triggered"
    assert envios == []


# ===========================================================================
# Diario Oficial MG — a tela `dou` que o servidor nunca conferia
# ===========================================================================
def _buscar_dou(usuario):
    return asyncio.run(r_dou.buscar(
        texto="convenio", data_inicial="2026-01-01", data_final="2026-01-31",
        diario_executivo=True, diario_municipios=False, diario_terceiros=False,
        edicao_extra=False, pagina=1, tamanho=20, current=usuario))


@pytest.fixture
def dou_sem_rede(monkeypatch):
    """Troca a primeira coisa que o endpoint faz depois do gate. Serve de prova
    de que a execucao chegou la — e mantem o teste fora da rede."""
    def _boom(*a, **k):
        raise _Sentinela()

    monkeypatch.setattr(r_dou, "_get_token", _boom)


def test_dou_buscar_sem_tela_bloqueia(bloqueio, dou_sem_rede):
    with pytest.raises(HTTPException) as e:
        _buscar_dou(Usuario(**SEM_NADA))
    negado(e)
    assert e.value.detail == MSG_TELA


def test_dou_buscar_em_aviso_segue_e_registra(aviso, dou_sem_rede, envios):
    with pytest.raises(_Sentinela):
        _buscar_dou(Usuario(**SEM_NADA))
    assert envios[0]["acao"] == authz.ACAO_NEGARIA
    assert envios[0]["detalhes"]["exigido"] == "dou"


def test_dou_buscar_com_a_tela_nao_faz_ruido(bloqueio, dou_sem_rede, envios):
    with pytest.raises(_Sentinela):
        _buscar_dou(com_tela("dou"))
    assert envios == []


def test_dou_publicacao_sem_tela_bloqueia(bloqueio, dou_sem_rede):
    """Endpoint SINCRONO (`def`): o gate vale igual, e o download do PDF nem
    comeca."""
    with pytest.raises(HTTPException) as e:
        r_dou.publicacao(id_jornal=123, download=True,
                         current=Usuario(**SEM_NADA))
    negado(e)
    assert e.value.detail == MSG_TELA


def test_dou_publicacao_em_aviso_segue(aviso, dou_sem_rede, envios):
    """Sincrono e em modo aviso: nao levanta 403 e nao explode ao tentar
    registrar de fora do event loop."""
    with pytest.raises(_Sentinela):
        r_dou.publicacao(id_jornal=123, download=False,
                         current=Usuario(**SEM_NADA))
    assert envios[0]["detalhes"]["exigido"] == "dou"


def test_dou_publicacao_admin_passa_sem_ruido(qualquer_modo, dou_sem_rede, envios):
    with pytest.raises(_Sentinela):
        r_dou.publicacao(id_jornal=123, current=Usuario(**ADMIN))
    assert envios == []


# ===========================================================================
# FNS — /municipios: a copia que esqueceu de filtrar
# ===========================================================================
LINHAS_MUN = [(1, "MONTE SIAO", "3143302", "MG"),
              (2, "ARAUJOS", "3103900", "MG"),
              (3, "TOLEDO", "3169109", "MG")]


def _municipios(usuario, linhas=None):
    db = FakeDb(_Resultado(linhas=linhas if linhas is not None else LINHAS_MUN))
    return asyncio.run(r_fns.municipios_pacta(db=db, current=usuario))


def test_fns_municipios_sem_tela_bloqueia(bloqueio):
    with pytest.raises(HTTPException) as e:
        _municipios(Usuario(**SEM_NADA))
    negado(e)
    assert e.value.detail == MSG_TELA


def test_fns_municipios_em_aviso_devolve_a_lista_inteira(aviso, envios):
    """Comportamento IDENTICO ao de hoje: os tres municipios saem, inclusive os
    dois que nao sao dessa pessoa — e os dois viram linha na trilha."""
    saida = _municipios(com_tela("fns"))
    assert [m["id"] for m in saida] == [1, 2, 3]
    assert [e["municipio_id"] for e in envios] == [2, 3]
    assert all(e["acao"] == authz.ACAO_NEGARIA for e in envios)


def test_fns_municipios_em_bloqueio_filtra_em_vez_de_403(bloqueio, envios):
    """O gate de uma LISTAGEM e o filtro. Um 403 aqui derrubaria a tela de quem
    tem escopo legitimo — o oposto do que este incremento quer."""
    saida = _municipios(com_tela("fns"))
    assert [m["id"] for m in saida] == [1]


def test_fns_municipios_admin_ve_tudo_sem_ruido(qualquer_modo, envios):
    saida = _municipios(Usuario(**ADMIN))
    assert [m["id"] for m in saida] == [1, 2, 3]
    assert envios == []


def test_fns_municipios_no_escopo_completo_nao_faz_ruido(aviso, envios):
    saida = _municipios(Usuario(telas={"fns"}, municipios={1, 2, 3}))
    assert [m["id"] for m in saida] == [1, 2, 3]
    assert envios == []


def test_fns_municipios_tem_teto_de_linhas(aviso, envios):
    """Cada linha e uma tarefa de fundo com sessao PROPRIA. Numa assessoria com
    dezenas de municipios, abrir a tela nao pode abrir dezenas de conexoes."""
    muitos = [(i, f"MUN {i}", f"31000{i:02d}", "MG") for i in range(1, 41)]
    saida = _municipios(com_tela("fns"), linhas=muitos)
    assert len(saida) == 40                       # a resposta continua inteira
    assert len(envios) == r_fns._TETO_AVISO_MUNICIPIOS


def test_fns_municipios_a_forma_da_resposta_nao_muda(aviso, envios):
    """O `cod_ibge` continua sendo o IBGE cortado em 6 digitos — o gate nao
    encostou no corpo da resposta."""
    assert _municipios(com_tela("fns"))[0] == {
        "id": 1, "nome": "MONTE SIAO", "cod_ibge": "314330", "uf": "MG"}


def test_fns_municipios_falha_da_trilha_nao_derruba(aviso, monkeypatch):
    """A garantia mais dura do incremento, vista do endpoint: se o registro
    quebrar, a requisicao sai igual. Um gate que existe para NAO quebrar nada
    nao pode quebrar por causa do proprio log."""
    def _explode(*a, **k):
        raise RuntimeError("banco de auditoria fora do ar")

    monkeypatch.setattr(authz, "_observar", _explode)
    assert [m["id"] for m in _municipios(com_tela("fns"))] == [1, 2, 3]


# ===========================================================================
# FNS — anos, detalhe da proposta, e os dois que JA tinham gate
# ===========================================================================
@pytest.fixture
def fns_sem_rede(monkeypatch):
    async def _boom(*a, **k):
        raise _Sentinela()

    monkeypatch.setattr(r_fns, "_get_cookies", _boom)


def test_fns_anos_sem_tela_bloqueia(bloqueio, fns_sem_rede):
    with pytest.raises(HTTPException) as e:
        asyncio.run(r_fns.anos(db=FakeDb(), current=Usuario(**SEM_NADA)))
    negado(e)
    assert e.value.detail == MSG_TELA


def test_fns_anos_em_aviso_segue(aviso, fns_sem_rede, envios):
    with pytest.raises(_Sentinela):
        asyncio.run(r_fns.anos(db=FakeDb(), current=Usuario(**SEM_NADA)))
    assert envios[0]["detalhes"]["exigido"] == "fns"


def test_fns_proposta_sem_tela_bloqueia(bloqueio, fns_sem_rede):
    with pytest.raises(HTTPException) as e:
        asyncio.run(r_fns.detalhe_proposta(nu_proposta="123", db=FakeDb(),
                                           current=Usuario(**SEM_NADA)))
    negado(e)
    assert e.value.detail == MSG_TELA


def test_fns_proposta_em_aviso_segue(aviso, fns_sem_rede, envios):
    with pytest.raises(_Sentinela):
        asyncio.run(r_fns.detalhe_proposta(nu_proposta="123", db=FakeDb(),
                                           current=Usuario(**SEM_NADA)))
    assert envios[0]["acao"] == authz.ACAO_NEGARIA


def test_fns_buscar_continua_com_o_gate_que_ja_tinha(bloqueio):
    """`/buscar` nunca esteve aberto: `_ensure_fns_municipio` checa tela E
    municipio desde sempre. O teste existe para ninguem 'completar' o que ja
    estava completo e acabar checando duas vezes."""
    with pytest.raises(HTTPException) as e:
        asyncio.run(r_fns.buscar(municipio="MONTE SIAO", ano=2026, uf="MG",
                                 nr_proposta=None, tipo_emenda=None, pagina=1,
                                 tamanho=50, db=FakeDb(),
                                 current=Usuario(**SEM_NADA)))
    negado(e)
    assert e.value.detail == MSG_TELA


def test_fns_listar_individuais_continua_com_o_gate_que_ja_tinha(bloqueio):
    with pytest.raises(HTTPException) as e:
        asyncio.run(r_fns.listar_individuais(
            municipio="MONTE SIAO", ano=2026, uf="MG",
            tipo_proposta="EQUIPAMENTO", tipo_recurso="EMENDA INDIVIDUAL",
            db=FakeDb(), current=Usuario(**SEM_NADA)))
    negado(e)
    assert e.value.detail == MSG_TELA


def test_fns_buscar_nega_a_tela_tambem_em_aviso(aviso, envios):
    """`_ensure_fns_municipio` chama `services.auth.ensure_tela`, que e
    PRE-EXISTENTE: nega nos dois modos. O modo aviso nao alcanca gate que ja
    existia — se alcancasse, `/buscar` (que nunca esteve aberto) passaria a
    responder para quem nao tem a tela durante a semana de observacao."""
    with pytest.raises(HTTPException) as e:
        asyncio.run(r_fns.buscar(municipio="MONTE SIAO", ano=2026, uf="MG",
                                 nr_proposta=None, tipo_emenda=None, pagina=1,
                                 tamanho=50, db=FakeDb(),
                                 current=Usuario(**SEM_NADA)))
    negado(e)
    assert e.value.detail == MSG_TELA
    assert envios == []


@pytest.mark.parametrize("modo_do_teste", ["aviso", "bloqueio"])
def test_fns_municipio_fora_do_escopo_continua_negado(monkeypatch, modo_do_teste,
                                                      envios):
    """Tem a tela, mas pediu municipio que nao e dela. A mensagem e a de
    `_ensure_fns_municipio`, que e propria dele — nao passa pelo authz, e por
    isso nega NOS DOIS MODOS, sem linha na trilha."""
    monkeypatch.setenv("AUTHZ_MODO", modo_do_teste)
    db = FakeDb(_Resultado(linhas=[("MONTE SIAO", "3143302")]))
    with pytest.raises(HTTPException) as e:
        asyncio.run(r_fns.buscar(municipio="ARAUJOS", ano=2026, uf="MG",
                                 nr_proposta=None, tipo_emenda=None, pagina=1,
                                 tamanho=50, db=db, current=com_tela("fns")))
    negado(e)
    assert e.value.detail == MSG_MUNICIPIO
    assert envios == []


# ===========================================================================
# SIMEC — o unico do grupo que ja estava inteiro
# ===========================================================================
@pytest.mark.parametrize("chamada", [
    lambda db, u: r_simec.dimensoes(municipio_id=1, db=db, current=u),
    lambda db, u: r_simec.liberacoes(municipio_id=1, ano=None, programa=None,
                                     db=db, current=u),
    lambda db, u: r_simec.resumo(municipio_id=1, db=db, current=u),
])
def test_simec_ja_checava_tela_e_municipio(bloqueio, chamada):
    """Os tres endpoints do SIMEC ja tinham os dois gates. Nada foi acrescentado
    la — este teste e a trava contra alguem 'completar' o que ja estava
    completo."""
    with pytest.raises(HTTPException) as e:
        asyncio.run(chamada(FakeDb(), Usuario(telas=set(), municipios={1})))
    negado(e)
    assert e.value.detail == MSG_TELA


@pytest.mark.parametrize("chamada", [
    lambda db, u: r_simec.dimensoes(municipio_id=99, db=db, current=u),
    lambda db, u: r_simec.liberacoes(municipio_id=99, ano=None, programa=None,
                                     db=db, current=u),
    lambda db, u: r_simec.resumo(municipio_id=99, db=db, current=u),
])
def test_simec_municipio_fora_do_escopo_nega_tambem_em_aviso(aviso, chamada, envios):
    """SEM ALARGAMENTO — este e o teste que prova a promessa "identico a hoje".

    O SIMEC ja negava municipio fora do escopo por `ensure_municipio_access`, e
    essa checagem nao passa pelo modo. Se ela passasse, ligar o modo aviso (que e
    o DEFAULT) abriria as liberacoes e o PAR do municipio 99 para quem so
    enxerga o 1 — uma negativa que valia ontem deixando de valer hoje, no
    incremento feito para fechar o sistema.

    Sem linha na trilha, tambem: a resposta e a mesma de antes do incremento."""
    with pytest.raises(HTTPException) as excecao:
        asyncio.run(chamada(FakeDb(_Resultado(linhas=[]), _Resultado(linhas=[])),
                            com_tela("simec")))
    negado(excecao)
    assert excecao.value.detail == MSG_MUNICIPIO
    assert envios == []


@pytest.mark.parametrize("chamada", [
    lambda db, u: r_simec.dimensoes(municipio_id=1, db=db, current=u),
    lambda db, u: r_simec.liberacoes(municipio_id=1, ano=None, programa=None,
                                     db=db, current=u),
    lambda db, u: r_simec.resumo(municipio_id=1, db=db, current=u),
])
def test_simec_sem_a_tela_nega_tambem_em_aviso(aviso, chamada, envios):
    """A outra metade: com o municipio no escopo, quem barra e o `ensure_tela`
    do SIMEC — tambem pre-existente, tambem negando nos dois modos."""
    with pytest.raises(HTTPException) as excecao:
        asyncio.run(chamada(FakeDb(), Usuario(telas=set(), municipios={1})))
    negado(excecao)
    assert excecao.value.detail == MSG_TELA
    assert envios == []


@pytest.mark.parametrize("modo_do_teste", ["aviso", "bloqueio"])
@pytest.mark.parametrize("valor,mensagem", [
    (None, "Selecione um municipio permitido"),
    ("nao-numerico", "Municipio invalido"),
])
def test_simec_pedido_malformado_nega_nos_dois_modos(monkeypatch, modo_do_teste,
                                                     valor, mensagem, envios):
    """Municipio ausente ou nao-numerico NAO e permissao que falta: e pedido
    malformado, e nenhuma correcao de cadastro o torna valido. Observa-lo nao
    ensinaria nada, e deixa-lo passar trocaria um 403 honesto por um 500 (o None
    desce ate a consulta) ou por um SELECT sem filtro devolvendo o tenant
    inteiro."""
    monkeypatch.setenv("AUTHZ_MODO", modo_do_teste)
    with pytest.raises(HTTPException) as excecao:
        asyncio.run(r_simec.dimensoes(municipio_id=valor, db=FakeDb(),
                                      current=com_tela("simec")))
    negado(excecao)
    assert excecao.value.detail == mensagem
    assert envios == []
