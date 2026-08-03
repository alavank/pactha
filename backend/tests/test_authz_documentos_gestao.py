"""
O gate de Documentos e Gestao Interna — testado pelo que ele NAO pode fazer.

Estes dois modulos sao o pior caso do incremento: `GET /gestao/anotacoes/{id}/
anexo/{idx}` devolve o ARQUIVO anexado direto do banco, e `DELETE /documentos/
{id}` apaga documento de qualquer prefeitura. Nenhum dos dois checava nada alem
de estar logado.

Mas a exigencia mais dura NAO e "barrar": e que, em `AUTHZ_MODO=aviso`, quem
trabalha hoje continue recebendo EXATAMENTE o que recebia ontem — mesma
resposta, nenhum 403 novo, nenhuma excecao escapando nem quando a propria
gravacao da trilha falha. Um incremento que existe para nao quebrar nada nao
pode quebrar por causa do proprio log.

⚠️ DUAS FAMILIAS DE GATE, E O TESTE SO SERVE SE SOUBER DISTINGUI-LAS
--------------------------------------------------------------------
O modo aviso NAO vale para tudo, e isso e deliberado:

  GATE NOVO (`authz.exigir_tela`, `authz.exigir_municipio`, `authz.ensure_dono`)
      Nasceu neste incremento. Respeita `AUTHZ_MODO`: em aviso registra "eu
      teria negado" e deixa passar; em bloqueio levanta 403.

  CHECAGEM QUE JA EXISTIA (`services.auth.ensure_tela`,
  `services.auth.ensure_municipio_access`)
      NEGA SEMPRE, nos DOIS modos. Aqui sao so duas: `GET /api/documentos` e
      `GET /api/gestao/anotacoes` — as unicas rotas dos dois routers que ja
      checavam alguma coisa antes. Roteá-las pelo modo aviso faria uma negativa
      ANTIGA parar de negar durante a semana de observacao: o sistema ficaria
      MAIS ABERTO justamente no incremento feito para fecha-lo, e o dono
      recebeu a promessa oposta ("em modo aviso, comportamento identico ao de
      hoje").

Por isso o caso central deste arquivo nao e a conta zerada, e sim o usuario que
TEM o municipio e NAO TEM a tela: e ele que atravessa a checagem antiga e chega
ao gate novo. A conta que nao alcanca o municipio nunca chega la — leva o 403
de sempre, nos dois modos, e o teste (c) afirma exatamente isso.

A espinha e uma tabela com TODOS os endpoints dos dois routers (`CHAMADAS`),
cada um marcado com a familia do seu gate, e os testes percorrem o recorte que
lhes cabe.

Os endpoints sao chamados como funcoes, com uma sessao de mentira: o que esta
sob teste e o gate, nao o SQL nem o roteamento do FastAPI.

Rodar:
    python -m pytest backend/tests/test_authz_documentos_gestao.py -v
"""
import asyncio
import inspect
from typing import Any, Callable, NamedTuple, Optional

import pytest
from fastapi import HTTPException

from services import authz
from routers import documentos, gestao

MSG_TELA = "Voce nao tem acesso a esta tela"
MSG_MUNICIPIO = "Voce nao tem acesso a este municipio"
MSG_SEM_MUNICIPIO = "Selecione um municipio permitido"
MSG_MUNICIPIO_INVALIDO = "Municipio invalido"

# O municipio das linhas de mentira.
MUNICIPIO_DA_LINHA = 7
# Um municipio que existe no cadastro de alguem, mas nao e o das linhas — e o
# que faz `ensure_dono` ter algo a dizer.
OUTRO_MUNICIPIO = 1


class Usuario:
    """Bate com o que o codigo real le do User: id/email/name + os escopos que
    `load_user_scopes` anexa. `None` nos escopos = admin (passa em tudo)."""

    def __init__(self, telas=None, municipios=None, id=7,
                 email="servidor@montesiao.mg.gov.br", name="Servidor"):
        self.id = id
        self.email = email
        self.name = name
        self.role = "user"
        self.allowed_telas = telas
        self.allowed_municipio_ids = municipios


SEM_NADA = dict(telas=set(), municipios=set())      # conta com ZERO permissao
ADMIN = dict(telas=None, municipios=None)


def _sem_tela():
    """O CASO CENTRAL do incremento: alcanca o municipio das linhas, mas nao tem
    a tela do modulo. E o unico usuario que passa pela checagem ANTIGA e chega
    ao gate NOVO — com ele, e so com ele, da para ver o modo aviso agindo."""
    return Usuario(telas=set(), municipios={MUNICIPIO_DA_LINHA})


def _com_tela(tela):
    """Tem a tela do modulo, mas so alcanca OUTRO municipio. E o caso que so o
    recorte de municipio pega: permissao de verbo nao diz nada sobre a linha."""
    return Usuario(telas={tela}, municipios={OUTRO_MUNICIPIO})


def _completo(tela):
    return Usuario(telas={tela}, municipios={MUNICIPIO_DA_LINHA})


# ---------------------------------------------------------------------------
# Sessao de mentira
# ---------------------------------------------------------------------------
DOC_LINHA = (12, MUNICIPIO_DA_LINHA, "plano_sustentabilidade", "Plano X", {},
             "rascunho", 3, None, None)
DOC_LINHA_EXPORT = (12, MUNICIPIO_DA_LINHA, "plano_sustentabilidade", "Plano X", {})
DOC_CONTEXTO = (MUNICIPIO_DA_LINHA, "plano_sustentabilidade", "Plano X", "rascunho")

ANEXOS = [{"nome": "oficio.pdf", "mime": "application/pdf",
           "dados_b64": "YQ==", "tamanho": 1}]
ANOT_LINHA = (5, MUNICIPIO_DA_LINHA, "sigcon", "1481000677/2026", "1481000677/2026",
              "Em analise interna", None, "prot-1", None, "obs", ANEXOS, 3, None, None)
ANOT_CONTEXTO = (MUNICIPIO_DA_LINHA, "sigcon", "1481000677/2026",
                 "1481000677/2026", "Em analise interna")
ANOT_ANEXO = (ANEXOS, MUNICIPIO_DA_LINHA, "sigcon", "1481000677/2026")


class _Resultado:
    def __init__(self, linhas=(), rowcount=1):
        self._linhas = list(linhas)
        self.rowcount = rowcount

    def first(self):
        return self._linhas[0] if self._linhas else None

    def fetchall(self):
        return list(self._linhas)

    def scalar(self):
        return self._linhas[0][0] if self._linhas else None

    def scalar_one_or_none(self):
        return self._linhas[0] if self._linhas else None


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeDb:
    """So o que estes endpoints usam. Responde por SUBSTRING do SQL — o
    suficiente para o gate rodar de ponta a ponta sem banco."""

    def __init__(self):
        self.consultas: list = []

    def begin_nested(self):
        return _Savepoint()

    def add(self, _entry):
        pass

    async def commit(self):
        pass

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.consultas.append(sql)
        # `ensure_dono` — uma coluna so, sem virgula depois de municipio_id.
        if sql.startswith("SELECT municipio_id FROM "):
            return _Resultado([(MUNICIPIO_DA_LINHA,)])
        if sql.startswith("SELECT municipio_id, tipo"):          # _doc_contexto
            return _Resultado([DOC_CONTEXTO])
        if sql.startswith("SELECT municipio_id, fonte"):         # _anotacao_contexto
            return _Resultado([ANOT_CONTEXTO])
        if sql.startswith("SELECT id, municipio_id, tipo, titulo, dados,"):
            return _Resultado([DOC_LINHA])
        if sql.startswith("SELECT id, municipio_id, tipo, titulo, dados FROM"):
            return _Resultado([DOC_LINHA_EXPORT])
        if sql.startswith("SELECT id, municipio_id, fonte"):
            return _Resultado([ANOT_LINHA])
        if sql.startswith("SELECT anexos,"):
            return _Resultado([ANOT_ANEXO])
        if sql.startswith("SELECT fonte_ref, COUNT"):
            return _Resultado([("1481000677/2026", 2)])
        if sql.startswith("INSERT INTO"):
            return _Resultado([(99,)])
        return _Resultado()          # UPDATE/DELETE (rowcount=1) e o resto


@pytest.fixture(autouse=True)
def _isolar(monkeypatch):
    """Cada teste comeca com a memoria de deduplicacao zerada, sem contexto de
    requisicao e sem gerar PDF de verdade (o que esta sob teste e o gate)."""
    authz.limpar_dedupe()
    authz.limpar_contexto()
    monkeypatch.delenv("AUTHZ_MODO", raising=False)
    monkeypatch.setattr(documentos, "gerar_pdf", lambda *a, **k: b"%PDF-falso")
    monkeypatch.setattr(documentos, "gerar_docx", lambda *a, **k: b"docx-falso")
    yield
    authz.limpar_dedupe()
    authz.limpar_contexto()


@pytest.fixture
def envios(monkeypatch):
    """Intercepta o agendamento da gravacao — sem isto o teste tentaria abrir
    sessao de banco de verdade."""
    registrados: list = []

    def _falso(dados):
        registrados.append(dados)
        return True

    monkeypatch.setattr(authz, "_enviar", _falso)
    return registrados


# ---------------------------------------------------------------------------
# A tabela: TODO endpoint dos dois routers, com a tela e a FAMILIA do gate
# ---------------------------------------------------------------------------
NOVO = "novo"        # authz.* — respeita AUTHZ_MODO
ANTIGO = "antigo"    # services.auth.* — nega sempre, nos dois modos


class Chamada(NamedTuple):
    chamar: Callable[[Any, Any], Any]
    tela: str
    gate_tela: str                  # NOVO ou ANTIGO
    gate_municipio: Optional[str]   # NOVO, ANTIGO ou None (nao ha o que recortar)
    dono: bool                      # passa por `authz.ensure_dono` (id no caminho)


CHAMADAS = {
    # --- Documentos ---------------------------------------------------------
    "documentos.schemas": Chamada(
        lambda db, u: documentos.schemas(current=u),
        "documentos", NOVO, None, False),
    "documentos.schema_de": Chamada(
        lambda db, u: documentos.schema_de("plano_sustentabilidade", current=u),
        "documentos", NOVO, None, False),
    # A UNICA rota de Documentos que ja checava algo antes do incremento: as
    # DUAS travas dela sao antigas e negam nos dois modos.
    "documentos.listar": Chamada(
        lambda db, u: documentos.listar(municipio_id=MUNICIPIO_DA_LINHA, tipo=None,
                                        db=db, current=u),
        "documentos", ANTIGO, ANTIGO, False),
    "documentos.criar": Chamada(
        lambda db, u: documentos.criar(
            documentos.DocCreate(municipio_id=MUNICIPIO_DA_LINHA,
                                 tipo="plano_sustentabilidade"),
            request=None, db=db, user=u),
        "documentos", NOVO, NOVO, False),
    "documentos.detalhe": Chamada(
        lambda db, u: documentos.detalhe(12, db=db, current=u),
        "documentos", NOVO, NOVO, True),
    "documentos.atualizar": Chamada(
        lambda db, u: documentos.atualizar(
            12, documentos.DocUpdate(titulo="Outro titulo"), request=None,
            db=db, current=u),
        "documentos", NOVO, NOVO, True),
    "documentos.remover": Chamada(
        lambda db, u: documentos.remover(12, request=None, db=db, current=u),
        "documentos", NOVO, NOVO, True),
    "documentos.exportar": Chamada(
        lambda db, u: documentos.exportar(12, request=None, formato="pdf",
                                          db=db, current=u),
        "documentos", NOVO, NOVO, True),
    # --- Gestao Interna -----------------------------------------------------
    "gestao.status_opcoes": Chamada(
        lambda db, u: gestao.status_opcoes(current=u),
        "gestao", NOVO, None, False),
    # A UNICA rota de Gestao que ja checava algo antes do incremento.
    "gestao.listar": Chamada(
        lambda db, u: gestao.listar(municipio_id=MUNICIPIO_DA_LINHA, fonte=None,
                                    status=None, db=db, current=u),
        "gestao", ANTIGO, ANTIGO, False),
    "gestao.listar_item": Chamada(
        lambda db, u: gestao.listar_item(fonte="sigcon", fonte_ref="1481000677/2026",
                                         db=db, current=u),
        "gestao", NOVO, NOVO, False),
    "gestao.contagens": Chamada(
        lambda db, u: gestao.contagens(
            gestao.ContagensIn(fonte="sigcon", refs=["1481000677/2026"]),
            db=db, current=u),
        "gestao", NOVO, None, False),
    "gestao.detalhe": Chamada(
        lambda db, u: gestao.detalhe(5, db=db, current=u),
        "gestao", NOVO, NOVO, True),
    "gestao.criar": Chamada(
        lambda db, u: gestao.criar(
            gestao.AnotacaoCreate(municipio_id=MUNICIPIO_DA_LINHA, fonte="sigcon",
                                  fonte_ref="1481000677/2026"),
            request=None, db=db, user=u),
        "gestao", NOVO, NOVO, False),
    "gestao.atualizar": Chamada(
        lambda db, u: gestao.atualizar(
            5, gestao.AnotacaoUpdate(protocolo="123"), request=None, db=db,
            current=u),
        "gestao", NOVO, NOVO, True),
    "gestao.remover": Chamada(
        lambda db, u: gestao.remover(5, request=None, db=db, current=u),
        "gestao", NOVO, NOVO, True),
    "gestao.download_anexo": Chamada(
        lambda db, u: gestao.download_anexo(5, 0, request=None, db=db, current=u),
        "gestao", NOVO, NOVO, True),
}

TODOS = sorted(CHAMADAS)
# Gate NOVO de tela: sao estes que o modo aviso deixa passar.
NOVOS = sorted(k for k, c in CHAMADAS.items() if c.gate_tela == NOVO)
# Checagem que JA EXISTIA: negam nos dois modos, e e essa a promessa.
ANTIGOS = sorted(k for k, c in CHAMADAS.items() if c.gate_tela == ANTIGO)
# Recorte de municipio que ja existia (o pedido traz `municipio_id`).
MUNICIPIO_ANTIGO = sorted(k for k, c in CHAMADAS.items()
                          if c.gate_municipio == ANTIGO)
COM_ID = sorted(k for k, c in CHAMADAS.items() if c.dono)

def _rodar(nome, usuario, db=None):
    return CHAMADAS[nome].chamar(db or FakeDb(), usuario)


def _executar(nome, usuario, db=None):
    return asyncio.run(_rodar(nome, usuario, db))


def _comparavel(resposta):
    """Forma comparavel da resposta. `Response`/`StreamingResponse` nao sao
    iguais entre si nem quando carregam o mesmo arquivo, entao comparamos o que
    o navegador enxerga: tipo, media type e o cabecalho do anexo."""
    if isinstance(resposta, (dict, list, str, int, type(None))):
        return resposta
    return (type(resposta).__name__, getattr(resposta, "media_type", None),
            dict(getattr(resposta, "headers", {})).get("content-disposition"))


def test_a_tabela_ainda_descreve_os_routers():
    """Tripwire da tabela acima: a divisao entre gate NOVO e checagem ANTIGA e o
    que da sentido a todo o resto do arquivo, e ela mora numa constante — se
    alguem trocar `ensure_tela` por `exigir_tela` num destes routers, os testes
    continuariam verdes afirmando a familia errada.

    Le do CODIGO, nao da tabela: `services.auth.*` e a familia que nega sempre,
    `services.authz.*` e a que respeita o modo."""
    fonte = {
        "documentos": inspect.getsource(documentos),
        "gestao": inspect.getsource(gestao),
    }
    for modulo, texto in fonte.items():
        # Uma unica rota por modulo ainda usa a trava antiga (a lista de
        # `GET /api/<modulo>`), e e dela que o bloco (c) fala.
        assert texto.count("\n    ensure_tela(") == 1, (
            f"routers/{modulo}.py mudou de familia de gate: reveja `CHAMADAS`")
        assert texto.count("\n    ensure_municipio_access(") == 1, (
            f"routers/{modulo}.py mudou de familia de gate: reveja `CHAMADAS`")
    assert ANTIGOS == ["documentos.listar", "gestao.listar"]
    assert MUNICIPIO_ANTIGO == ANTIGOS


# ---------------------------------------------------------------------------
# (a) MODO AVISO no gate NOVO: comportamento IDENTICO ao de hoje
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nome", NOVOS)
def test_aviso_nao_levanta_no_gate_novo(monkeypatch, envios, nome):
    """Quem tem o municipio e nao tem a tela continua trabalhando.

    E o requisito operacional do incremento: e bem possivel que gente em Monte
    Siao esteja trabalhando HOJE justamente porque este gate nunca existiu."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    _executar(nome, _sem_tela())


@pytest.mark.parametrize("nome", NOVOS)
def test_aviso_devolve_o_mesmo_que_o_admin_recebe(monkeypatch, envios, nome):
    """Nao basta nao levantar: a RESPOSTA tem de ser a mesma.

    Filtrar linha fora do escopo "so para ficar seguro" seria o apagao
    silencioso — a tela mostrando menos do que mostrava ontem, sem erro nenhum
    para o usuario reclamar."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    sem_tela = _comparavel(_executar(nome, _sem_tela()))
    authz.limpar_dedupe()
    admin = _comparavel(_executar(nome, Usuario(**ADMIN)))
    assert sem_tela == admin


@pytest.mark.parametrize("nome", NOVOS)
def test_aviso_registra_a_negativa_que_teria_feito(monkeypatch, envios, nome):
    """Passar calado seria pior que barrar: a semana de observacao e a unica
    chance de o dono ver quem trabalha sem permissao antes de a trava ligar."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    _executar(nome, _sem_tela())
    assert envios, f"{nome} passou sem deixar rastro"
    assert {e["acao"] for e in envios} == {authz.ACAO_NEGARIA}
    tela = CHAMADAS[nome].tela
    assert any(e["detalhes"]["exigencia"] == "tela" and e["exigido"] == tela
               for e in envios), f"{nome} nao registrou a tela {tela!r} que exige"


# ---------------------------------------------------------------------------
# (b) MODO BLOQUEIO: o 403 de sempre, com a mensagem de sempre
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nome", NOVOS)
def test_bloqueio_barra_quem_nao_tem_a_tela(monkeypatch, envios, nome):
    """O outro lado do caso central: a mesma chamada que passou em aviso leva
    403 quando o dono liga a trava — e a negativa fica registrada."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    with pytest.raises(HTTPException) as e:
        _executar(nome, _sem_tela())
    assert e.value.status_code == 403
    assert e.value.detail == MSG_TELA
    assert [x["acao"] for x in envios] == [authz.ACAO_NEGOU]


@pytest.mark.parametrize("nome", TODOS)
def test_bloqueio_barra_a_conta_sem_permissao(monkeypatch, envios, nome):
    """A conta zerada nao alcanca endpoint nenhum dos dois modulos."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    with pytest.raises(HTTPException) as e:
        _executar(nome, Usuario(**SEM_NADA))
    assert e.value.status_code == 403
    assert e.value.detail in (MSG_TELA, MSG_MUNICIPIO)


@pytest.mark.parametrize("modo_env", ["aviso", "bloqueio"])
@pytest.mark.parametrize("nome", TODOS)
def test_quem_tem_a_permissao_passa_calado(monkeypatch, envios, nome, modo_env):
    """Nos dois modos, e sem poluir a trilha: linha para quem TEM a permissao
    ensinaria o dono a ignorar a trilha inteira."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    _executar(nome, _completo(CHAMADAS[nome].tela))
    assert envios == []


@pytest.mark.parametrize("modo_env", ["aviso", "bloqueio"])
@pytest.mark.parametrize("nome", TODOS)
def test_admin_passa_nos_dois_modos_sem_gerar_aviso(monkeypatch, envios, nome, modo_env):
    """Admin (`allowed_* = None`) e o caso em que nem se pergunta: nenhum gate,
    novo ou antigo, tem o que avaliar. Uma linha de trilha aqui seria ruido puro
    — e ruido na semana de observacao e o que faz o dono parar de ler."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    _executar(nome, Usuario(**ADMIN))
    assert envios == []


# ---------------------------------------------------------------------------
# (c) A PROMESSA: o que ja negava continua negando NOS DOIS MODOS
# ---------------------------------------------------------------------------
# Este bloco e o contrapeso do bloco (a). Sem ele, "modo aviso" viraria sinonimo
# de "sistema aberto" e o incremento entregaria o oposto do que prometeu.
@pytest.mark.parametrize("modo_env", ["aviso", "bloqueio"])
@pytest.mark.parametrize("nome", ANTIGOS)
def test_tela_pre_existente_nega_nos_dois_modos(monkeypatch, envios, nome, modo_env):
    """`services.auth.ensure_tela` nao passa pelo modo aviso.

    Estas duas rotas ja exigiam a tela ANTES do incremento. Se o modo aviso
    valesse para elas, a semana de observacao abriria uma porta que estava
    fechada — e ninguem pediu isso."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    with pytest.raises(HTTPException) as e:
        _executar(nome, _sem_tela())
    assert e.value.status_code == 403
    assert e.value.detail == MSG_TELA
    # E nao passa pelo roteador do modo: nao ha "eu teria negado" a registrar
    # quando a negativa e a mesma de ontem.
    assert envios == []


@pytest.mark.parametrize("modo_env", ["aviso", "bloqueio"])
@pytest.mark.parametrize("nome", MUNICIPIO_ANTIGO)
def test_sem_o_municipio_e_403_nos_dois_modos(monkeypatch, envios, nome, modo_env):
    """`services.auth.ensure_municipio_access` tambem nega sempre.

    Quem tem a tela mas pede um municipio fora do seu escopo levava 403 ontem e
    leva 403 hoje, em qualquer modo. E este o teste que prova a promessa
    "identico ao de hoje" pelo lado que importa: o incremento nao ALARGOU
    acesso nenhum."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    with pytest.raises(HTTPException) as e:
        _executar(nome, _com_tela(CHAMADAS[nome].tela))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_MUNICIPIO
    assert envios == []


# ---------------------------------------------------------------------------
# (d) O buraco que permissao de VERBO nao resolve: o dono da LINHA
# ---------------------------------------------------------------------------
# `ensure_dono` e gate NOVO — nenhum destes endpoints checava a linha antes —,
# entao ele SIM respeita o modo. A diferenca para o bloco (c) e a razao de o
# incremento existir: la a negativa e velha (nao pode afrouxar), aqui e nova
# (nao pode endurecer sem aviso).
@pytest.mark.parametrize("nome", COM_ID)
def test_id_de_outro_municipio_e_pego_pelo_dono(monkeypatch, envios, nome):
    """Ter a tela "documentos" nao autoriza apagar o documento da prefeitura
    vizinha. Sem `ensure_dono`, quem tem a tela tem o tenant inteiro."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    with pytest.raises(HTTPException) as e:
        _executar(nome, _com_tela(CHAMADAS[nome].tela))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_MUNICIPIO


@pytest.mark.parametrize("nome", COM_ID)
def test_em_aviso_o_dono_so_registra(monkeypatch, envios, nome):
    """O mesmo ato ACONTECE em modo aviso — e fica escrito de que tabela e de
    que linha ele falava."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    _executar(nome, _com_tela(CHAMADAS[nome].tela))
    linhas = [e for e in envios if e["detalhes"]["exigencia"] == "municipio"]
    assert linhas, f"{nome} nao checou o dono da linha"
    assert linhas[0]["acao"] == authz.ACAO_NEGARIA
    assert linhas[0]["exigido"] == MUNICIPIO_DA_LINHA
    assert "tabela" in linhas[0]["detalhes"]["origem"]


def test_o_anexo_e_o_pior_caso_e_esta_coberto(monkeypatch, envios):
    """O anexo sai em base64 direto do banco: era a porta mais aberta do
    modulo. Em bloqueio, quem nao alcanca o municipio da linha nao baixa o
    arquivo; em aviso ele ainda sai — igual a antes —, so que registrado."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    with pytest.raises(HTTPException) as e:
        _executar("gestao.download_anexo", _com_tela("gestao"))
    assert e.value.status_code == 403

    authz.limpar_dedupe()
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    resposta = _executar("gestao.download_anexo", _com_tela("gestao"))
    assert resposta.body == b"a"
    assert envios

    # E o outro lado: quem nao tem a TELA tambem baixa o anexo hoje, porque este
    # gate tambem e novo. E o que a semana de observacao existe para expor.
    authz.limpar_dedupe()
    del envios[:]
    resposta = _executar("gestao.download_anexo", _sem_tela())
    assert resposta.body == b"a"
    assert [e["detalhes"]["exigencia"] for e in envios] == ["tela"]


# ---------------------------------------------------------------------------
# (e) A armadilha do documento SEM municipio
# ---------------------------------------------------------------------------
# `documentos_gerados.municipio_id` e NULL-able e o editor manda `null` quando
# nenhuma prefeitura esta selecionada. Municipio ausente e PEDIDO MALFORMADO,
# negado nos DOIS modos — chamar o gate sem guarda criaria um 403 NOVO ja em
# modo aviso, o unico defeito que este incremento nao pode ter.
@pytest.mark.parametrize("modo_env", ["aviso", "bloqueio"])
def test_criar_documento_sem_municipio_nao_vira_403(monkeypatch, envios, modo_env):
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    body = documentos.DocCreate(municipio_id=None, tipo="plano_sustentabilidade")
    resposta = asyncio.run(documentos.criar(
        body, request=None, db=FakeDb(), user=_completo("documentos")))
    assert resposta == {"id": 99, "created": True}
    assert [e for e in envios if e["detalhes"]["exigencia"] == "municipio"] == []


@pytest.mark.parametrize("modo_env", ["aviso", "bloqueio"])
@pytest.mark.parametrize("pedido, mensagem", [
    (None, MSG_SEM_MUNICIPIO),
    ("nenhum", MSG_MUNICIPIO_INVALIDO),
])
def test_pedido_malformado_e_negado_nos_dois_modos(monkeypatch, envios, modo_env,
                                                   pedido, mensagem):
    """A razao de a guarda acima existir: o gate novo NAO observa pedido
    malformado, nega. Nao e permissao que falta — nenhuma correcao de cadastro
    faz um pedido sem municipio virar valido —, e deixa-lo passar trocaria um
    403 honesto por uma consulta sem filtro devolvendo o tenant inteiro."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    with pytest.raises(HTTPException) as e:
        authz.exigir_municipio(_completo("documentos"), pedido)
    assert e.value.status_code == 403
    assert e.value.detail == mensagem
    assert envios == []


def test_documento_sem_dono_fica_visivel_em_vez_de_virar_403(monkeypatch, envios):
    """Linha com municipio em branco nao vira negativa nova: vira `sem_dono`,
    para o buraco de modelagem aparecer na semana de observacao."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")

    class SemDono(FakeDb):
        async def execute(self, stmt, params=None):
            sql = " ".join(str(stmt).split())
            if sql.startswith("SELECT municipio_id FROM "):
                return _Resultado([(None,)])
            return await super().execute(stmt, params)

    resposta = asyncio.run(documentos.detalhe(
        12, db=SemDono(), current=_com_tela("documentos")))
    assert resposta["id"] == 12
    assert [e["acao"] for e in envios] == [authz.ACAO_SEM_DONO]


# ---------------------------------------------------------------------------
# (f) `/anotacoes/item`: sem municipio no pedido, o recorte sai das LINHAS
# ---------------------------------------------------------------------------
def test_item_julga_o_municipio_das_linhas_sem_filtrar(monkeypatch, envios):
    """Filtrar a consulta mudaria a resposta — e em modo aviso a resposta tem de
    ser a de hoje. Entao julga-se o que voltou: em aviso vira linha na trilha,
    em bloqueio vira 403. O recorte aqui e NOVO (o pedido nunca trouxe
    municipio), por isso respeita o modo."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    resposta = _executar("gestao.listar_item", _com_tela("gestao"))
    assert resposta["total"] == 1                     # nada foi escondido
    assert resposta["items"][0]["anexos"] == ANEXOS   # nem o anexo
    assert [e["exigido"] for e in envios] == [MUNICIPIO_DA_LINHA]

    authz.limpar_dedupe()
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    with pytest.raises(HTTPException) as e:
        _executar("gestao.listar_item", _com_tela("gestao"))
    assert e.value.detail == MSG_MUNICIPIO


def test_item_sem_linha_nenhuma_nao_inventa_negativa(monkeypatch, envios):
    """Item sem anotacao: nao ha municipio a julgar, e nao ha o que registrar."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")

    class Vazio(FakeDb):
        async def execute(self, stmt, params=None):
            return _Resultado()

    resposta = asyncio.run(gestao.listar_item(
        fonte="sigcon", fonte_ref="nao-existe", db=Vazio(),
        current=_com_tela("gestao")))
    assert resposta == {"items": [], "total": 0}
    assert envios == []


# ---------------------------------------------------------------------------
# (g) A falha da propria trilha NAO escapa
# ---------------------------------------------------------------------------
def _explode(_dados):
    raise RuntimeError("banco fora do ar no meio da gravacao da trilha")


@pytest.mark.parametrize("nome", NOVOS)
def test_falha_da_trilha_nao_derruba_o_endpoint(monkeypatch, nome):
    """A garantia mais dura: um incremento que existe para NAO quebrar nada nao
    pode quebrar por causa do proprio log."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    monkeypatch.setattr(authz, "_enviar", _explode)
    _executar(nome, _sem_tela())


@pytest.mark.parametrize("nome", NOVOS)
def test_falha_da_trilha_nao_muda_a_resposta(monkeypatch, envios, nome):
    """Nem levanta, nem devolve outra coisa: com a trilha no chao a resposta e a
    mesma que com a trilha de pe."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    com_trilha = _comparavel(_executar(nome, _sem_tela()))
    authz.limpar_dedupe()
    monkeypatch.setattr(authz, "_enviar", _explode)
    assert _comparavel(_executar(nome, _sem_tela())) == com_trilha


@pytest.mark.parametrize("nome", TODOS)
def test_falha_da_trilha_nao_vira_500_no_bloqueio(monkeypatch, nome):
    """Em bloqueio, a falha da trilha nao pode transformar o 403 em 500."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    monkeypatch.setattr(authz, "_enviar", _explode)
    with pytest.raises(HTTPException) as e:
        _executar(nome, Usuario(**SEM_NADA))
    assert e.value.status_code == 403
