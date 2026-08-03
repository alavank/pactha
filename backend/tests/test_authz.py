"""A trava de permissao em MODO AVISO — testada pelo que ela NAO pode fazer.

Sao DUAS familias de checagem, e confundi-las e o erro caro deste incremento:

  * `services.auth.ensure_tela` / `ensure_municipio_access` sao as travas que JA
    EXISTIAM (~128 pontos antes do Incremento 2). NEGAM SEMPRE, nos dois modos,
    e nao passam por `services/authz.py`. Se o modo aviso valesse para elas, as
    128 negativas antigas parariam de negar durante a semana de observacao: o
    sistema ficaria MAIS ABERTO justamente no incremento que existe para
    fecha-lo, e o dono recebeu a promessa oposta — "em modo aviso, comportamento
    IDENTICO ao de hoje".

  * `services.authz.exigir_tela` / `exigir_municipio` / `ensure_dono` sao os
    gates NOVOS, escritos agora sobre endpoints que nao checavam NADA. So estes
    respeitam `AUTHZ_MODO`: em aviso deixam passar e registram "eu teria
    negado"; em bloqueio levantam o mesmo 403 de sempre.

Entao os testes que mais importam aqui nao sao os que provam que a trava barra:
sao (1) os que provam que o gate NOVO, em modo aviso, NAO barra, NAO levanta e
NAO deixa escapar a propria falha de log; e (2) os que provam que a trava ANTIGA
continua barrando do mesmo jeito nos dois modos.

Rodar:
    python -m pytest backend/tests/test_authz.py -v
"""
import asyncio

import pytest
from fastapi import HTTPException

from services import authz
from services.auth import ensure_municipio_access, ensure_tela

MSG_TELA = "Voce nao tem acesso a esta tela"
MSG_MUNICIPIO = "Voce nao tem acesso a este municipio"


class Usuario:
    """Bate com o que o codigo real le do User: id/email/name + os escopos que
    `load_user_scopes` anexa. `None` nos escopos = admin (passa em tudo)."""

    def __init__(self, telas=None, municipios=None, id=7,
                 email="servidor@montesiao.mg.gov.br", name="Servidor"):
        self.id = id
        self.email = email
        self.name = name
        self.allowed_telas = telas
        self.allowed_municipio_ids = municipios


SEM_NADA = dict(telas=set(), municipios=set())          # conta com ZERO permissao
ADMIN = dict(telas=None, municipios=None)

MODOS = ["aviso", "bloqueio"]


@pytest.fixture(autouse=True)
def _isolar(monkeypatch):
    """Cada teste comeca com a memoria zerada e sem contexto de requisicao."""
    authz.limpar_dedupe()
    authz.limpar_contexto()
    monkeypatch.delenv("AUTHZ_MODO", raising=False)
    yield
    authz.limpar_dedupe()
    authz.limpar_contexto()


@pytest.fixture
def envios(monkeypatch):
    """Intercepta o agendamento da gravacao. Sem isto o teste tentaria abrir
    sessao de banco de verdade."""
    registrados: list = []

    def _falso(dados):
        registrados.append(dados)
        return True

    monkeypatch.setattr(authz, "_enviar", _falso)
    return registrados


# ---------------------------------------------------------------------------
# Modo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("valor", [None, "", "  ", "aviso", "AVISO", "bloquear",
                                   "bloqueiop", "block", "1", "true", "off"])
def test_default_e_o_que_nao_quebra(monkeypatch, valor):
    """Qualquer coisa que nao seja exatamente 'bloqueio' e modo aviso.

    Fail-OPEN e a escolha certa AQUI: 'fechar por engano' e o apagao de
    segunda-feira que este modulo existe para evitar."""
    if valor is None:
        monkeypatch.delenv("AUTHZ_MODO", raising=False)
    else:
        monkeypatch.setenv("AUTHZ_MODO", valor)
    assert authz.modo() == authz.MODO_AVISO


@pytest.mark.parametrize("valor", ["bloqueio", "BLOQUEIO", " Bloqueio "])
def test_bloqueio_so_com_a_palavra_exata(monkeypatch, valor):
    monkeypatch.setenv("AUTHZ_MODO", valor)
    assert authz.modo() == authz.MODO_BLOQUEIO


# ---------------------------------------------------------------------------
# (a) A trava ANTIGA nega SEMPRE — a promessa "identico ao de hoje"
# ---------------------------------------------------------------------------
# `services.auth.ensure_tela` e `ensure_municipio_access` ja eram chamadas em
# ~128 pontos ANTES deste incremento. Cada uma delas e uma negativa que ja
# acontece HOJE em producao; nenhuma pode afrouxar durante a semana de
# observacao, porque afrouxar seria o oposto do que este incremento promete.
@pytest.mark.parametrize("modo_env", MODOS)
def test_tela_antiga_nega_nos_dois_modos(monkeypatch, envios, modo_env):
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    with pytest.raises(HTTPException) as e:
        ensure_tela(Usuario(**SEM_NADA), "rm")
    assert e.value.status_code == 403
    assert e.value.detail == MSG_TELA


@pytest.mark.parametrize("modo_env", MODOS)
def test_municipio_antigo_nega_nos_dois_modos(monkeypatch, envios, modo_env):
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    with pytest.raises(HTTPException) as e:
        ensure_municipio_access(Usuario(municipios={1, 2}), 99)
    assert e.value.status_code == 403
    assert e.value.detail == MSG_MUNICIPIO


@pytest.mark.parametrize("modo_env", MODOS)
def test_trava_antiga_nao_passa_pelo_modo_aviso(monkeypatch, envios, modo_env):
    """Nem sequer roteada: a negativa antiga nao vira linha de `authz.negaria`.

    Se um dia ela voltar a passar por aqui, este teste cai — e e exatamente o
    dia em que 128 negativas antigas viraram passagens livres."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    for chamada in (lambda: ensure_tela(Usuario(**SEM_NADA), "rm"),
                    lambda: ensure_municipio_access(Usuario(municipios={1}), 99)):
        with pytest.raises(HTTPException):
            chamada()
    assert envios == []


# ---------------------------------------------------------------------------
# (b) O gate NOVO em modo aviso NAO levanta
# ---------------------------------------------------------------------------
def test_aviso_tela_nao_levanta(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    assert authz.exigir_tela(Usuario(**SEM_NADA), "rm") is None
    assert len(envios) == 1
    assert envios[0]["acao"] == authz.ACAO_NEGARIA


def test_aviso_municipio_nao_levanta(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    assert authz.exigir_municipio(Usuario(municipios={1, 2}), 99) is None
    assert envios[0]["acao"] == authz.ACAO_NEGARIA
    assert envios[0]["municipio_id"] == 99


def test_aviso_registra_o_que_o_dono_precisa_ler(monkeypatch, envios):
    """A linha tem de responder 'o que faltou' e 'o que essa pessoa tem hoje'.

    `possui` vazio e o achado mais util da semana: conta criada sem nenhuma
    permissao que vem trabalhando ha meses porque nunca houve trava."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    authz.exigir_tela(Usuario(**SEM_NADA), "rm")
    detalhes = envios[0]["detalhes"]
    assert detalhes["exigencia"] == "tela"
    assert detalhes["exigido"] == "rm"
    assert detalhes["possui"] == []
    assert detalhes["possui_qtd"] == 0
    assert detalhes["modo"] == "aviso"
    assert envios[0]["usuario"].email == "servidor@montesiao.mg.gov.br"


def test_aviso_lista_as_telas_que_tem(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    authz.exigir_tela(Usuario(telas={"convenios", "cauc"}), "rm")
    assert envios[0]["detalhes"]["possui"] == ["cauc", "convenios"]


# ---------------------------------------------------------------------------
# (c) O gate NOVO em modo bloqueio levanta o MESMO 403 de hoje
# ---------------------------------------------------------------------------
def test_bloqueio_tela_levanta_403_com_a_mensagem_de_hoje(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    with pytest.raises(HTTPException) as e:
        authz.exigir_tela(Usuario(**SEM_NADA), "rm")
    assert e.value.status_code == 403
    assert e.value.detail == MSG_TELA


def test_bloqueio_municipio_levanta_403_com_a_mensagem_de_hoje(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    with pytest.raises(HTTPException) as e:
        authz.exigir_municipio(Usuario(municipios={1}), 99)
    assert e.value.status_code == 403
    assert e.value.detail == MSG_MUNICIPIO


def test_bloqueio_tambem_registra(monkeypatch, envios):
    """Quem liga a trava precisa enxergar quem ela derrubou."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    with pytest.raises(HTTPException):
        authz.exigir_tela(Usuario(**SEM_NADA), "rm")
    assert envios[0]["acao"] == authz.ACAO_NEGOU


# ---------------------------------------------------------------------------
# (d) O caso central do incremento, na ordem real do endpoint
# ---------------------------------------------------------------------------
# Ha endpoint com gate PRE-EXISTENTE e gate NOVO ao mesmo tempo (`rm.listar` ja
# conferia o municipio e ganhou a tela agora). A ordem importa: quem nao alcanca
# o municipio nunca chega ao gate novo.
def _endpoint_gate_velho_e_novo(usuario, municipio_id):
    ensure_municipio_access(usuario, municipio_id)   # trava que JA VALIA hoje
    authz.exigir_tela(usuario, "rm")                 # gate NOVO do incremento
    return "os dados do rm"


def test_com_municipio_e_sem_a_tela_em_aviso_passa_e_registra(monkeypatch, envios):
    """O caso que este incremento existe para descobrir: a pessoa alcanca o
    municipio (a trava antiga deixa passar, como hoje) e NAO tem a tela — que
    ninguem nunca conferiu neste endpoint. Em aviso ela trabalha igual, e o
    dono ganha a linha que diz qual permissao cadastrar."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    usuario = Usuario(telas=set(), municipios={4})
    assert _endpoint_gate_velho_e_novo(usuario, 4) == "os dados do rm"
    assert [e["acao"] for e in envios] == [authz.ACAO_NEGARIA]
    assert envios[0]["detalhes"]["exigencia"] == "tela"
    assert envios[0]["exigido"] == "rm"


def test_com_municipio_e_sem_a_tela_em_bloqueio_toma_403(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    with pytest.raises(HTTPException) as e:
        _endpoint_gate_velho_e_novo(Usuario(telas=set(), municipios={4}), 4)
    assert e.value.status_code == 403
    assert e.value.detail == MSG_TELA
    assert envios[0]["acao"] == authz.ACAO_NEGOU


@pytest.mark.parametrize("modo_env", MODOS)
def test_sem_o_municipio_toma_403_nos_dois_modos(monkeypatch, envios, modo_env):
    """A prova da promessa "identico a hoje": a checagem de municipio destes
    endpoints em muitos casos JA EXISTIA, entao quem pede o municipio da
    prefeitura vizinha continua levando 403 tambem durante a semana de
    observacao. E nem chega ao gate novo — a trava antiga vem antes."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    with pytest.raises(HTTPException) as e:
        _endpoint_gate_velho_e_novo(Usuario(telas=set(), municipios={4}), 9)
    assert e.value.status_code == 403
    assert e.value.detail == MSG_MUNICIPIO
    assert [d["detalhes"]["exigencia"] for d in envios] == []


# --- pedido MALFORMADO continua negado nos DOIS modos ----------------------
# Nao e permissao que falta: nenhuma correcao de cadastro faz um pedido sem
# municipio virar valido. Deixar passar trocaria um 403 honesto por um 500 (o
# None desce ate a consulta) ou por uma consulta sem filtro devolvendo o tenant
# inteiro.
@pytest.mark.parametrize("gate", [authz.exigir_municipio, ensure_municipio_access],
                         ids=["gate_novo", "trava_antiga"])
@pytest.mark.parametrize("modo_env", MODOS)
@pytest.mark.parametrize("valor,mensagem", [
    (None, "Selecione um municipio permitido"),
    ("abc", "Municipio invalido"),
    ([], "Municipio invalido"),
])
def test_municipio_malformado_nega_nos_dois_modos(monkeypatch, envios, gate,
                                                  modo_env, valor, mensagem):
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    with pytest.raises(HTTPException) as e:
        gate(Usuario(municipios={1}), valor)
    assert e.value.status_code == 403
    assert e.value.detail == mensagem
    assert envios == []      # nao e achado de permissao: nao polui a trilha


# ---------------------------------------------------------------------------
# (e) admin passa nos dois modos, nos dois tipos de gate
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("modo_env", MODOS)
def test_admin_passa_nos_dois_modos(monkeypatch, envios, modo_env):
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    admin = Usuario(**ADMIN)
    assert ensure_tela(admin, "qualquer_tela") is None
    assert ensure_municipio_access(admin, 12345) is None
    assert ensure_municipio_access(admin, None) is None
    assert authz.exigir_tela(admin, "qualquer_tela") is None
    assert authz.exigir_municipio(admin, 12345) is None
    assert authz.exigir_municipio(admin, None) is None
    assert envios == []      # admin nao gera ruido na trilha


@pytest.mark.parametrize("modo_env", MODOS)
def test_quem_tem_a_permissao_passa_calado(monkeypatch, envios, modo_env):
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    u = Usuario(telas={"rm"}, municipios={4})
    assert ensure_tela(u, "rm") is None
    assert ensure_municipio_access(u, 4) is None
    assert authz.exigir_tela(u, "rm") is None
    assert authz.exigir_municipio(u, 4) is None
    assert envios == []


# ---------------------------------------------------------------------------
# (f) falha do registro NAO escapa
# ---------------------------------------------------------------------------
def _explode(_dados):
    raise RuntimeError("banco fora do ar no meio da gravacao da trilha")


def test_falha_do_registro_nao_derruba_a_requisicao(monkeypatch):
    """A garantia mais dura deste incremento: um modulo que existe para NAO
    quebrar nada nao pode quebrar por causa do proprio log."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    monkeypatch.setattr(authz, "_enviar", _explode)
    assert authz.exigir_tela(Usuario(**SEM_NADA), "rm") is None


def test_falha_do_registro_nao_muda_o_403_do_bloqueio(monkeypatch):
    """Em bloqueio, a falha da trilha nao pode virar 500: o 403 sai igual."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    monkeypatch.setattr(authz, "_enviar", _explode)
    with pytest.raises(HTTPException) as e:
        authz.exigir_tela(Usuario(**SEM_NADA), "rm")
    assert e.value.status_code == 403
    assert e.value.detail == MSG_TELA


def test_contexto_com_request_quebrado_nao_derruba(monkeypatch, envios):
    """Request de mentira (ou meio construida) nao pode virar excecao nova."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")

    class RequestTorta:
        def __getattr__(self, nome):
            raise RuntimeError("request inutilizavel")

    authz.definir_contexto(RequestTorta(), Usuario(**SEM_NADA))
    assert authz.exigir_tela(Usuario(**SEM_NADA), "rm") is None


def test_definir_contexto_nunca_levanta():
    class UsuarioTorto:
        def __getattr__(self, nome):
            raise RuntimeError("usuario inutilizavel")

    assert authz.definir_contexto(None, UsuarioTorto()) is None


def test_enviar_fora_de_event_loop_nao_levanta(monkeypatch):
    """Sem laco (script, teste, comando de manutencao) a linha simplesmente nao
    e agendada — e ninguem fica sabendo por uma excecao."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    assert authz.exigir_tela(Usuario(**SEM_NADA), "rm") is None


# ---------------------------------------------------------------------------
# (g) anti-inundacao
# ---------------------------------------------------------------------------
def test_dedupe_segura_a_segunda_ocorrencia_igual(monkeypatch, envios):
    """Uma tela dispara uma duzia de chamadas por carregamento. Sem isto, a
    trilha afogaria justamente na semana em que ela precisa ser lida."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    u = Usuario(**SEM_NADA)
    for _ in range(12):
        authz.exigir_tela(u, "rm")
    assert len(envios) == 1


def test_dedupe_nao_esconde_fato_diferente(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    u = Usuario(**SEM_NADA)
    authz.exigir_tela(u, "rm")
    authz.exigir_tela(u, "documentos")                      # outra tela
    authz.exigir_municipio(Usuario(municipios={1}), 99)     # outra exigencia
    assert len(envios) == 3


def test_dedupe_separa_usuarios(monkeypatch, envios):
    """Dois servidores esbarrando na mesma tela sao dois fatos, nao um."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    authz.exigir_tela(Usuario(id=1, **SEM_NADA), "rm")
    authz.exigir_tela(Usuario(id=2, **SEM_NADA), "rm")
    assert len(envios) == 2


def test_a_trilha_registra_quem_foi_julgado(monkeypatch, envios):
    """O contexto traz a request; QUEM foi barrado vem do proprio argumento —
    um endpoint que avalie a permissao de outra pessoa nao pode gravar o nome
    do operador no lugar do dela."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    authz.definir_contexto(None, Usuario(id=1, email="operador@x"))
    authz.exigir_tela(Usuario(id=2, email="avaliado@x", **SEM_NADA), "rm")
    assert envios[0]["usuario"].email == "avaliado@x"
    assert envios[0]["usuario"].id == 2


def test_dedupe_expira_pela_janela(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    u = Usuario(**SEM_NADA)
    authz.exigir_tela(u, "rm")
    monkeypatch.setattr(authz, "_JANELA_SEGUNDOS", 0)
    authz.exigir_tela(u, "rm")
    assert len(envios) == 2


def test_dedupe_tem_teto_de_memoria(monkeypatch, envios):
    """Cache que so cresce dentro de um worker de API e vazamento de memoria."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    monkeypatch.setattr(authz, "_TETO_DEDUPE", 10)
    u = Usuario(**SEM_NADA)
    for i in range(200):
        authz.exigir_tela(u, f"tela_{i}")
    assert len(authz._dedupe) <= 10


# ---------------------------------------------------------------------------
# ensure_dono — o buraco que permissao de VERBO nao resolve
# ---------------------------------------------------------------------------
class _Resultado:
    def __init__(self, linha):
        self._linha = linha

    def first(self):
        return self._linha


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeDb:
    """So o que `ensure_dono` usa: begin_nested() e execute()."""

    def __init__(self, linha=None, erro=None):
        self.linha = linha
        self.erro = erro
        self.consultas: list = []

    def begin_nested(self):
        return _Savepoint()

    async def execute(self, stmt, params=None):
        self.consultas.append((str(stmt), params))
        if self.erro:
            raise self.erro
        return _Resultado(self.linha)


def _dono(db, usuario, id_registro=12, tabela="rm_relatorios", coluna="id"):
    return asyncio.run(
        authz.ensure_dono(db, tabela, coluna, id_registro, usuario))


def test_dono_de_outro_municipio_bloqueia(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    db = FakeDb(linha=(99,))
    with pytest.raises(HTTPException) as e:
        _dono(db, Usuario(municipios={1, 2}))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_MUNICIPIO


def test_dono_de_outro_municipio_so_avisa(monkeypatch, envios):
    """O `DELETE /api/rm/{id}` com id de outro municipio: em modo aviso ele
    ACONTECE, e fica registrado que teria sido barrado.

    `ensure_dono` e gate NOVO — nenhum endpoint conferia o municipio da LINHA
    antes deste incremento — entao ele respeita `AUTHZ_MODO` como os outros
    gates novos, e nao pode delegar para a trava antiga (que negaria ja na
    semana de observacao)."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    db = FakeDb(linha=(99,))
    assert _dono(db, Usuario(municipios={1, 2})) == 99
    assert envios[0]["acao"] == authz.ACAO_NEGARIA
    origem = envios[0]["detalhes"]["origem"]
    assert origem == {"tabela": "rm_relatorios", "coluna": "id", "id": "12"}


def test_dono_do_proprio_municipio_passa(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    assert _dono(FakeDb(linha=(2,)), Usuario(municipios={1, 2})) == 2
    assert envios == []


def test_registro_inexistente_nao_vira_403(monkeypatch, envios):
    """Quem decide o 404 e o endpoint — ele e o unico que sabe se 'nao achei'
    significa 'nao existe' ou 'nao e seu'."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    assert _dono(FakeDb(linha=None), Usuario(municipios={1})) is None
    assert envios == []


def test_id_nulo_nao_consulta_o_banco(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    db = FakeDb(linha=(99,))
    assert _dono(db, Usuario(municipios={1}), id_registro=None) is None
    assert db.consultas == []


def test_linha_sem_municipio_nao_decide_e_fica_visivel(monkeypatch, envios):
    """Linha com municipio em branco nao tem dono. Nao inventamos 403 (seria
    negativa nova); registramos para o buraco de modelagem aparecer."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    assert _dono(FakeDb(linha=(None,)), Usuario(municipios={1})) is None
    assert envios[0]["acao"] == authz.ACAO_SEM_DONO


def test_falha_de_leitura_nao_derruba_o_endpoint(monkeypatch, envios):
    """Sem leitura nao ha decisao — e nao ha excecao nova saindo daqui."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    db = FakeDb(erro=RuntimeError("relation nao existe"))
    assert _dono(db, Usuario(municipios={1})) is None


def test_admin_nem_precisa_do_municipio_da_linha(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    assert _dono(FakeDb(linha=(99,)), Usuario(**ADMIN)) == 99
    assert envios == []


@pytest.mark.parametrize("tabela,coluna", [
    ("rm_relatorios; DROP TABLE users", "id"),
    ("rm_relatorios", "id = 1 OR 1=1"),
    ("", "id"),
    ("rm relatorios", "id"),
    ("1rm", "id"),
])
def test_identificador_torto_e_erro_de_programacao(monkeypatch, envios,
                                                   tabela, coluna):
    """Tabela e coluna sao literais do router, nunca dado do usuario — mas
    interpolar nome em SQL sem validar e o atalho que um dia recebe variavel."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    with pytest.raises(ValueError):
        _dono(FakeDb(linha=(1,)), Usuario(municipios={1}),
              tabela=tabela, coluna=coluna)


def test_consulta_e_parametrizada(monkeypatch, envios):
    """O id vai por bind, nunca concatenado."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    db = FakeDb(linha=(1,))
    _dono(db, Usuario(municipios={1}), id_registro="12 OR 1=1")
    sql, params = db.consultas[0]
    assert "12 OR 1=1" not in sql
    assert params == {"id": "12 OR 1=1"}


# ---------------------------------------------------------------------------
# Catalogo: chave nova sem frase didatica vira jargao na tela do dono
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("chave", [authz.ACAO_NEGARIA, authz.ACAO_NEGOU,
                                   authz.ACAO_SEM_DONO])
def test_acoes_novas_estao_no_catalogo(chave):
    from services.audit_catalog import descrever_acao

    acao = descrever_acao(chave)
    assert acao.conhecida, f"{chave} caiu na derivacao generica"
    assert acao.nota, f"{chave} sem nota: o dono nao sabe o que fazer com a linha"


def test_frase_do_aviso_e_legivel():
    from services.audit_catalog import alvo_legivel, frase_didatica

    alvo = alvo_legivel(authz.ACAO_NEGARIA, "tela", "rm")
    frase = frase_didatica(authz.ACAO_NEGARIA, "Maria Silva", alvo)
    assert frase.startswith("Maria Silva ")
    assert "permiss" in frase
