"""
O gate de tela do Painel de Indicadores (`routers/bi.py::_gate_bi`).

Ate este incremento NENHUM endpoint de /api/bi/* checava tela: o unico gate era
o escopo de municipio. Estes testes cobrem as duas coisas que podem dar errado
ao fechar esse buraco, e as duas sao operacionais:

  1. em MODO AVISO o gate NOVO (a tela `bi`) nao pode mudar nada — nenhum 403
     novo, nem quando a propria gravacao da trilha falha;
  2. o QUIOSQUE (TV do gabinete, `/t/<slug>`, `/m/<slug>`) nao pode ser barrado
     nem em modo bloqueio — ele nao tem tela, tem allowlist.

⚠️ E cobrem tambem a metade que se perde com facilidade: o que o modo aviso NAO
alcanca. O gate de MUNICIPIO do Painel (`resolve_scope` -> `ensure_municipio_access`)
JA EXISTIA antes deste incremento, e continua negando NOS DOIS MODOS. Foi por
isso que `services.auth.ensure_tela`/`ensure_municipio_access` ficaram FORA do
modo aviso: sao ~128 travas que ja valem hoje, e rotea-las deixaria o sistema
MAIS ABERTO durante a semana de observacao — o oposto da promessa feita ao dono
("em modo aviso, comportamento IDENTICO ao de hoje"). Gate NOVO usa
`authz.exigir_tela`/`exigir_municipio`, e so ele respeita `AUTHZ_MODO`.

Ha ainda um teste de INVENTARIO: endpoint novo neste router nasce gateado ou
declarado como auto-escopado aqui. Sem ele, o proximo /api/bi/* entra sem
checagem exatamente como os 55 que originaram este trabalho.

Rodar:
    python -m pytest backend/tests/test_bi_gate.py -v
"""
import asyncio
import inspect

import pytest
from fastapi import HTTPException

from routers import bi
from services import authz
from services.auth import KIOSK_GET_PERMITIDOS, get_current_user

MSG_TELA = "Voce nao tem acesso a esta tela"
MSG_MUNICIPIO = "Voce nao tem acesso a este municipio"
MSG_MUNICIPIO_INVALIDO = "Municipio invalido"
MSG_SEM_ESCOPO = "Voce nao tem municipios no escopo"

MODOS = ["aviso", "bloqueio"]


class Usuario:
    """Bate com o que o codigo real le do User: escopos anexados por
    `load_user_scopes` (None = admin) + a marca `kiosk` da coluna do banco."""

    def __init__(self, telas=None, municipios=None, kiosk=False, id=7,
                 email="secretario@montesiao.mg.gov.br", name="Secretario"):
        self.id = id
        self.email = email
        self.name = name
        self.allowed_telas = telas
        self.allowed_municipio_ids = municipios
        self.kiosk = kiosk


SEM_NADA = dict(telas=set(), municipios=set())
ADMIN = dict(telas=None, municipios=None)
# O CASO CENTRAL DO INCREMENTO: a pessoa TEM o municipio (o gate antigo deixa
# passar, como sempre deixou) e NAO tem a tela `bi` (o gate novo). E o unico
# recorte em que o modo aviso muda alguma coisa — em todos os outros o
# comportamento tem de ser identico ao de hoje.
COM_MUNICIPIO_SEM_TELA = dict(telas={"dashboard", "rm"}, municipios={31})
# Como a conta de quiosque nasce hoje se a linha de `user_telas` faltar: viewer
# com municipio e sem tela nenhuma. E o cenario que nao pode derrubar a TV.
QUIOSQUE = dict(telas=set(), municipios={31}, kiosk=True)


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
    """Intercepta o agendamento da gravacao — sem isto o teste tentaria abrir
    sessao de banco de verdade.

    AUTOUSE de proposito: os testes de endpoint rodam dentro de um laco real
    (`asyncio.run`), e ali o authz agendaria tarefa de fundo com sessao propria.
    O teste passaria mesmo assim, mas deixaria conexao pendurada e ruido de
    "task was destroyed" no relatorio."""
    registrados: list = []

    def _falso(dados):
        registrados.append(dados)
        return True

    monkeypatch.setattr(authz, "_enviar", _falso)
    return registrados


# ---------------------------------------------------------------------------
# Modo aviso: registra e DEIXA PASSAR (so o gate NOVO)
# ---------------------------------------------------------------------------
def test_aviso_nao_levanta_e_registra_a_tela_bi(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    assert bi._gate_bi(Usuario(**SEM_NADA)) is None
    assert len(envios) == 1
    assert envios[0]["acao"] == authz.ACAO_NEGARIA
    assert envios[0]["detalhes"]["exigencia"] == "tela"
    assert envios[0]["detalhes"]["exigido"] == "bi"


def test_aviso_quem_so_tem_dashboard_aparece_na_trilha(monkeypatch, envios):
    """⚠️ O achado que o dono TEM de ler antes de ligar o bloqueio.

    Com `BI_MODULE` ligado, `/dashboard` E o Painel — e a equivalencia so vale
    numa direcao (`bi` implica `dashboard`, nunca o contrario). Entao quem tem
    so `dashboard` le o Painel hoje e vira linha `authz.negaria` na semana de
    observacao. Ligar `AUTHZ_MODO=bloqueio` sem conceder `bi` a essas contas
    apaga a home do sistema para elas."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    assert bi._gate_bi(Usuario(**COM_MUNICIPIO_SEM_TELA)) is None
    assert envios[0]["acao"] == authz.ACAO_NEGARIA
    assert envios[0]["detalhes"]["exigido"] == "bi"
    assert envios[0]["detalhes"]["possui"] == ["dashboard", "rm"]


# ---------------------------------------------------------------------------
# Modo bloqueio: o MESMO 403 de sempre
# ---------------------------------------------------------------------------
def test_bloqueio_levanta_o_403_de_tela(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    with pytest.raises(HTTPException) as e:
        bi._gate_bi(Usuario(**SEM_NADA))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_TELA
    assert envios[0]["acao"] == authz.ACAO_NEGOU


def test_bloqueio_alcanca_quem_tem_o_municipio_e_nao_tem_a_tela(monkeypatch, envios):
    """O outro lado do caso central: em bloqueio, ter o municipio deixa de
    bastar. E exatamente a conta que o dono precisa ter corrigido antes de virar
    a chave — a que hoje abre a home e amanha nao abriria."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    with pytest.raises(HTTPException) as e:
        bi._gate_bi(Usuario(**COM_MUNICIPIO_SEM_TELA))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_TELA
    assert envios[0]["acao"] == authz.ACAO_NEGOU


@pytest.mark.parametrize("modo_env", MODOS)
def test_quem_tem_a_tela_bi_passa_calado(monkeypatch, envios, modo_env):
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    assert bi._gate_bi(Usuario(telas={"bi"}, municipios={31})) is None
    assert envios == []


@pytest.mark.parametrize("modo_env", MODOS)
def test_admin_passa_calado(monkeypatch, envios, modo_env):
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    assert bi._gate_bi(Usuario(**ADMIN)) is None
    assert envios == []


# ---------------------------------------------------------------------------
# O ENDPOINT INTEIRO — gate NOVO (tela) e gate ANTIGO (municipio) juntos
# ---------------------------------------------------------------------------
# `/api/bi/semaforo` e o formato de todos os endpoints de dado deste router:
#     _gate_bi(current)                      <- gate NOVO, respeita AUTHZ_MODO
#     await resolve_scope(db, current, mid)  <- gate ANTIGO, nega nos dois modos
# Testar o par junto e o que prova a promessa: o modo aviso solta a tela e NAO
# solta o municipio. No unitario de `_gate_bi` essa metade some.
SEMAFORO = {"cauc": "ok"}


@pytest.fixture
def cauc(monkeypatch):
    """Substitui a leitura de banco que vem DEPOIS dos dois gates. Se ela for
    chamada, os gates deixaram passar; se nao for, alguem barrou antes."""
    chamadas: list = []

    async def _falso(db, municipio_id):
        chamadas.append(municipio_id)
        return SEMAFORO

    monkeypatch.setattr(bi, "fetch_cauc_situacao", _falso)
    return chamadas


def _semaforo(usuario, municipio_id=31):
    """Chama o endpoint direto (sem HTTP): `db=None` porque nenhum caminho
    exercitado aqui chega a tocar a sessao."""
    return asyncio.run(bi.semaforo(municipio_id=municipio_id, db=None,
                                   current=usuario))


def test_aviso_entrega_o_painel_a_quem_tem_o_municipio_e_nao_tem_a_tela(
        monkeypatch, envios, cauc):
    """O caso central, ponta a ponta: nada muda para quem trabalha hoje, e o
    fato vira linha na trilha."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    assert _semaforo(Usuario(**COM_MUNICIPIO_SEM_TELA)) == SEMAFORO
    assert cauc == [31]
    assert [e["acao"] for e in envios] == [authz.ACAO_NEGARIA]
    assert envios[0]["detalhes"]["exigido"] == "bi"


def test_bloqueio_barra_o_mesmo_pedido_antes_de_ler_o_banco(
        monkeypatch, envios, cauc):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    with pytest.raises(HTTPException) as e:
        _semaforo(Usuario(**COM_MUNICIPIO_SEM_TELA))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_TELA
    assert cauc == [], "o dado foi lido depois do 403"


@pytest.mark.parametrize("modo_env", MODOS)
def test_municipio_fora_do_escopo_e_403_NOS_DOIS_MODOS(
        monkeypatch, envios, cauc, modo_env):
    """⚠️ O teste que prova "em modo aviso, comportamento identico ao de hoje".

    Quem pede um municipio que nao e seu leva 403 hoje, e tem de levar 403
    durante a semana de observacao tambem. Se este teste cair, o incremento que
    existe para FECHAR o sistema o abriu: `ensure_municipio_access` voltou a ser
    roteada pelo modo aviso e ~128 travas antigas pararam de negar.

    O usuario tem a tela `bi` de proposito — sem ela o gate NOVO responderia
    primeiro e o gate antigo nunca seria exercitado."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    with pytest.raises(HTTPException) as e:
        _semaforo(Usuario(telas={"bi"}, municipios={31}), municipio_id=99)
    assert e.value.status_code == 403
    assert e.value.detail == MSG_MUNICIPIO
    assert cauc == [], "entregou dado de municipio fora do escopo"


@pytest.mark.parametrize("modo_env", MODOS)
def test_o_aviso_da_tela_nao_destrava_o_municipio(monkeypatch, envios, cauc,
                                                  modo_env):
    """Sem a tela E sem o municipio: em aviso o gate novo deixa passar e
    REGISTRA, mas o gate antigo barra logo em seguida. O 403 e o mesmo nos dois
    modos; so muda a mensagem em bloqueio, onde a tela responde primeiro."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    with pytest.raises(HTTPException) as e:
        _semaforo(Usuario(telas=set(), municipios={31}), municipio_id=99)
    assert e.value.status_code == 403
    assert e.value.detail == (MSG_TELA if modo_env == "bloqueio" else MSG_MUNICIPIO)
    assert cauc == []


@pytest.mark.parametrize("modo_env", MODOS)
def test_municipio_nao_numerico_e_403_nos_dois_modos(monkeypatch, envios, cauc,
                                                     modo_env):
    """Pedido MALFORMADO nao e permissao que falta: nenhuma correcao de cadastro
    faz `municipio_id=abc` virar valido. Deixa-lo passar trocaria um 403 honesto
    por um 500 (o valor desce ate a consulta) ou por uma consulta sem filtro."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    with pytest.raises(HTTPException) as e:
        _semaforo(Usuario(telas={"bi"}, municipios={31}), municipio_id="abc")
    assert e.value.status_code == 403
    assert e.value.detail == MSG_MUNICIPIO_INVALIDO
    assert cauc == []


@pytest.mark.parametrize("modo_env", MODOS)
def test_nao_admin_sem_municipio_nenhum_continua_barrado(monkeypatch, envios,
                                                         cauc, modo_env):
    """O consolidado (`municipio_id` ausente) para nao-admin sem escopo e uma
    negativa de `resolve_scope`, que nao passa pelo authz — logo nao muda de
    comportamento em modo aviso."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    with pytest.raises(HTTPException) as e:
        _semaforo(Usuario(telas={"bi"}, municipios=set()), municipio_id=None)
    assert e.value.status_code == 403
    assert e.value.detail == MSG_SEM_ESCOPO
    assert cauc == []


@pytest.mark.parametrize("modo_env", MODOS)
def test_admin_atravessa_os_dois_gates_sem_gerar_aviso(monkeypatch, envios,
                                                       cauc, modo_env):
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    assert _semaforo(Usuario(**ADMIN), municipio_id=99) == SEMAFORO
    assert cauc == [99]
    assert envios == []


# ---------------------------------------------------------------------------
# QUIOSQUE — a TV do gabinete
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("modo_env", MODOS)
def test_quiosque_passa_sem_tela_nos_dois_modos(monkeypatch, envios, modo_env):
    """Se este teste cair, o modo bloqueio mata a TV do gabinete.

    A conta de quiosque e um `viewer` sintetico, criada por `_ensure_kiosk_user`
    e nao por um administrador; quem a limita e `KIOSK_GET_PERMITIDOS` (allowlist
    por igualdade de caminho, dentro do proprio `get_current_user`), que e mais
    estreita que qualquer tela. E ela falha em SILENCIO: o slideshow engole o
    erro no `.catch()` e a tela so para de atualizar."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    assert bi._gate_bi(Usuario(**QUIOSQUE)) is None
    # E nao gera ruido: uma TV pollando o dia inteiro encheria a trilha da
    # semana de observacao com um fato que nao e achado de permissao.
    assert envios == []


@pytest.mark.parametrize("modo_env", MODOS)
def test_quiosque_nao_ganha_municipio_alheio(monkeypatch, envios, cauc, modo_env):
    """Passar sem tela nao e passar sem escopo. O usuario sintetico espelha os
    municipios de quem publicou o link, e o gate antigo continua valendo para
    ele nos dois modos — senao o slug de 12 caracteres viraria acesso ao tenant
    inteiro."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    with pytest.raises(HTTPException) as e:
        _semaforo(Usuario(**QUIOSQUE), municipio_id=99)
    assert e.value.status_code == 403
    assert e.value.detail == MSG_MUNICIPIO
    assert cauc == []


def test_allowlist_de_quiosque_aponta_para_rotas_que_existem():
    """Renomear uma rota de /api/bi/* sem mexer na allowlist derruba a TV.

    A allowlist e por IGUALDADE de caminho — um `/api/bi/documentos` que vire
    `/api/bi/documentacao` passa a bater no 403 de quiosque, e ninguem descobre
    ate a TV do gabinete parar."""
    caminhos = {r.path for r in bi.router.routes if "GET" in r.methods}
    do_bi = {p for p in KIOSK_GET_PERMITIDOS if p.startswith("/api/bi/")}
    assert do_bi, "a allowlist de quiosque perdeu os caminhos do Painel"
    assert do_bi <= caminhos, f"allowlist aponta para rota inexistente: {do_bi - caminhos}"


# ---------------------------------------------------------------------------
# A falha da trilha NAO escapa
# ---------------------------------------------------------------------------
def _explode(_dados):
    raise RuntimeError("banco fora do ar no meio da gravacao da trilha")


def test_falha_do_registro_nao_derruba_o_painel(monkeypatch):
    """Um gate que existe para NAO quebrar nada nao pode quebrar por causa do
    proprio log — e aqui o que quebraria e a home de quem esta trabalhando."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    monkeypatch.setattr(authz, "_enviar", _explode)
    assert bi._gate_bi(Usuario(**SEM_NADA)) is None


def test_falha_do_registro_nao_muda_a_resposta_do_endpoint(monkeypatch, cauc):
    """A mesma garantia com a resposta na mao: o payload sai igual ao de um dia
    em que a trilha grava normalmente."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    monkeypatch.setattr(authz, "_enviar", _explode)
    assert _semaforo(Usuario(**COM_MUNICIPIO_SEM_TELA)) == SEMAFORO
    assert cauc == [31]


def test_falha_do_registro_nao_vira_500_no_bloqueio(monkeypatch):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    monkeypatch.setattr(authz, "_enviar", _explode)
    with pytest.raises(HTTPException) as e:
        bi._gate_bi(Usuario(**SEM_NADA))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_TELA


# ---------------------------------------------------------------------------
# INVENTARIO — endpoint novo nasce gateado ou declarado
# ---------------------------------------------------------------------------
# Auto-escopados: leem/gravam a PROPRIA linha do usuario (chaveada por `user_id`
# ou `owner_id` na propria consulta). Nao levam gate de tela de proposito —
# esta declarado no docstring/comentario de cada um.
AUTO_ESCOPADOS = {
    ("GET", "/api/bi/tela-filtros"),          # filtro do proprio usuario
    ("PUT", "/api/bi/tela-filtros"),          # idem, e chamado por TODO usuario do Painel
    ("GET", "/api/bi/tela-links"),            # links do proprio dono
    ("DELETE", "/api/bi/tela-links/{slug}"),  # revogar o proprio link: nunca negar
    ("DELETE", "/api/bi/push/subscribe"),     # cancelar a propria inscricao
    ("GET", "/api/bi/preferencias"),          # preferencias de notificacao do usuario
    ("PUT", "/api/bi/preferencias"),
}

# Gate PROPRIO, mais forte que `bi` — completar seria duplicar.
GATE_PROPRIO = {("POST", "/api/bi/tela-links"): 'ensure_tela(current, "bi_link")'}

# Publico por desenho: nao depende de `get_current_user`, nao ha quem gatear.
# O `/meta` revela ESTRITAMENTE MENOS que a resolucao ao lado: so cidade e modo,
# para a previa de WhatsApp — sem token, sem dado de painel e sem tocar no
# quiosque. Quem tem o slug ja alcanca o painel inteiro.
PUBLICOS = {("GET", "/api/bi/tela-pub/{slug}"),
            ("GET", "/api/bi/tela-pub/{slug}/meta")}


def _rotas():
    for r in bi.router.routes:
        for metodo in sorted(r.methods):
            if metodo in ("HEAD", "OPTIONS"):
                continue
            yield metodo, r.path, inspect.getsource(r.endpoint)


def _rota_de(metodo, caminho):
    for r in bi.router.routes:
        if r.path == caminho and metodo in r.methods:
            return r
    raise AssertionError(f"{metodo} {caminho} nao existe mais em /api/bi/*")


def _injetadas(rota):
    """Tudo que o FastAPI resolve ANTES de chamar o endpoint, inclusive as
    dependencias das dependencias."""
    vistos, pilha = set(), [rota.dependant]
    while pilha:
        d = pilha.pop()
        if d.call is not None:
            vistos.add(d.call)
        pilha.extend(d.dependencies)
    return vistos


def test_todo_endpoint_de_dado_passa_pelo_gate():
    """Endpoint novo em /api/bi/* nasce gateado — ou entra numa das listas acima
    com o motivo escrito. E a rede que impede o buraco de reabrir sozinho."""
    faltando = [
        f"{m} {p}" for m, p, src in _rotas()
        if (m, p) not in AUTO_ESCOPADOS and (m, p) not in GATE_PROPRIO
        and (m, p) not in PUBLICOS and "_gate_bi(current)" not in src
    ]
    assert not faltando, f"sem gate de tela e sem classificacao: {faltando}"


def test_a_classificacao_de_auto_escopado_nao_ficou_desatualizada():
    """Se um dia um auto-escopado GANHAR gate, a lista acima tem de deixar de
    menti-lo — senao o inventario deixa de valer para ele."""
    contradizem = [f"{m} {p}" for m, p, src in _rotas()
                   if (m, p) in AUTO_ESCOPADOS and "_gate_bi(current)" in src]
    assert not contradizem, f"declarado auto-escopado mas gateado: {contradizem}"


def test_gate_proprio_continua_no_lugar():
    for (metodo, caminho), trecho in GATE_PROPRIO.items():
        src = next(s for m, p, s in _rotas() if (m, p) == (metodo, caminho))
        assert trecho in src, f"{metodo} {caminho} perdeu o gate proprio {trecho}"
        assert "_gate_bi(current)" not in src, (
            f"{metodo} {caminho} passou a duplicar gate de tela")


def test_rota_publica_nao_pede_usuario():
    """O gate publico e o prazo do link, nao a sessao. Se um dia ela passar a
    exigir `get_current_user`, a TV para de resolver o proprio token.

    Olha o GRAFO DE DEPENDENCIAS que o FastAPI resolve, e nao o texto da funcao:
    a versao textual deste teste acusava o proprio docstring do endpoint, que
    EXPLICA por que nao ha `get_current_user` ali. Comentario que fala do gate
    nao e gate — e a checagem por dependencia ainda pega o caso que a textual
    perderia (a rota herdar a sessao de um `Depends` aninhado)."""
    for metodo, caminho in PUBLICOS:
        assert get_current_user not in _injetadas(_rota_de(metodo, caminho))


def test_a_deteccao_de_dependencia_de_sessao_funciona():
    """Guarda-costas do teste acima. Se `get_current_user` mudar de identidade
    (embrulho, decorador, reimport), aquele teste passaria por nunca encontrar
    NADA. Aqui uma rota que comprovadamente exige sessao tem de acusar."""
    assert get_current_user in _injetadas(_rota_de("GET", "/api/bi/vapid-public-key"))
