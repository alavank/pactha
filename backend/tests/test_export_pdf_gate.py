"""
A porta de TELA do router de exportacao — e a linha que separa gate NOVO de gate VELHO.

`routers/export_pdf.py` e uma segunda porta para dado que ja tem dono: cada PDF
e o conteudo de uma tela, so que em arquivo. Quase todos esses endpoints
checavam o MUNICIPIO e mais nada, entao tirar a tela de alguem na tela de
Usuarios nao tirava o relatorio.

⚠️ ESTE ARQUIVO EXISTE PARA AFIRMAR A FRONTEIRA, e ela nao e "tudo passa em modo
aviso". Sao DUAS travas diferentes convivendo no mesmo endpoint:

  - `services.authz.exigir_tela`  — gate NOVO. Respeita `AUTHZ_MODO`: em aviso
    deixa passar e registra "eu teria negado". E o caso central do Incremento 2.

  - `services.auth.ensure_tela` e `ensure_municipio_access` — travas que JA
    VALIAM antes deste incremento (~128 pontos no repo). NEGAM SEMPRE, nos dois
    modos. Se o modo aviso valesse para elas, essas 128 negativas antigas
    parariam de negar durante a semana de observacao — o sistema ficaria MAIS
    ABERTO justamente no incremento que existe para fecha-lo, e a promessa feita
    ao dono ("em modo aviso, comportamento IDENTICO ao de hoje") viraria o
    oposto do que ele recebeu.

Por isso os testes vem em dois blocos que se contradizem de proposito:
`/convenios` sem a tela PASSA em aviso; `/parlamentares` sem a tela toma 403 nos
DOIS modos, porque la a checagem e a antiga. E qualquer usuario fora do
municipio toma 403 nos dois modos, em todos eles — e esse o teste que prova a
promessa.

Rodar:
    python -m pytest backend/tests/test_export_pdf_gate.py -v
"""
import asyncio

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from routers import export_pdf
from services import authz

MSG_TELA = "Voce nao tem acesso a esta tela"
MSG_MUNICIPIO = "Voce nao tem acesso a este municipio"
MSG_SEM_MUNICIPIO = "Selecione um municipio permitido"

# O municipio 1 esta no escopo do usuario de teste sempre que o assunto for a
# trava de TELA: um usuario que tambem falhasse no municipio misturaria as duas
# negativas na mesma linha. O 99 e o de fora, usado so no bloco do municipio.
MUNICIPIO = 1
MUNICIPIO_DE_FORA = 99


class Usuario:
    """O que o codigo real le do User: id/email/name + os escopos que
    `load_user_scopes` anexa. Nao-admin com o municipio, sem tela nenhuma."""

    def __init__(self, telas=frozenset(), municipios=frozenset({MUNICIPIO})):
        self.id = 7
        self.email = "servidor@montesiao.mg.gov.br"
        self.name = "Servidor"
        self.allowed_telas = set(telas)
        self.allowed_municipio_ids = set(municipios)


class PassouDaPorta(Exception):
    """Sentinela: a requisicao atravessou o gate e foi fazer o trabalho de sempre.

    E o sinal de "passou" mais proximo do comportamento real sem exigir Postgres:
    plantada no primeiro passo DEPOIS da porta. Se a porta tivesse levantado,
    esta excecao nunca apareceria."""


class BancoSentinela:
    """Sessao falsa. Nao imita banco nenhum — e so o marcador de "o fluxo chegou
    ate a consulta"."""

    async def execute(self, *a, **kw):
        raise PassouDaPorta()


@pytest.fixture(autouse=True)
def _isolar(monkeypatch):
    """Sem dedupe herdado (uma linha ja vista some da chamada seguinte, e o teste
    passaria a medir o cache em vez da porta) e sem contexto de requisicao."""
    authz.limpar_dedupe()
    authz.limpar_contexto()
    monkeypatch.delenv("AUTHZ_MODO", raising=False)
    yield
    authz.limpar_dedupe()
    authz.limpar_contexto()


@pytest.fixture
def envios(monkeypatch):
    """Intercepta o agendamento da gravacao — sem isto a trilha tentaria abrir
    sessao de banco de verdade."""
    registrados: list = []
    monkeypatch.setattr(authz, "_enviar",
                        lambda dados: registrados.append(dados) or True)
    return registrados


def _rodar(coro):
    return asyncio.run(coro)


def _sem_trilha_de_export(monkeypatch):
    """Neutraliza `_registrar_export` nos testes que percorrem o endpoint inteiro:
    a trilha de exportacao abre sessao propria e nao e o objeto aqui."""
    async def _nada(*a, **kw):
        return None
    monkeypatch.setattr(export_pdf, "_registrar_export", _nada)


# ---------------------------------------------------------------------------
# O par endpoint -> tela
# ---------------------------------------------------------------------------
# Uma linha por PDF, com a chave que o router da tela ja exige. E a tabela que se
# le quando alguem perguntar "por que este relatorio parou de sair": par errado
# aqui inventa uma permissao que nenhum administrador concedeu e tira o arquivo
# de quem sempre o teve.
def _chamar_convenios(user, db):
    return export_pdf.export_convenios_pdf(
        request=None, municipio_id=MUNICIPIO, db=db, current=user)


def _chamar_voluntarias(user, db):
    return export_pdf.export_voluntarias_pdf(
        request=None, municipio_id=MUNICIPIO, categoria=None, situacao=None,
        orgao=None, search=None, parlamentar=None, situacao_contratacao=None,
        vigencia=None, vig_fim_de=None, vig_fim_ate=None, db=db, current=user)


def _chamar_plano_acao(user, db):
    return export_pdf.export_plano_acao_pdf(
        request=None, municipio_id=MUNICIPIO, situacao=None, programa=None,
        parlamentar=None, emenda=None, objeto=None, db=db, current=user)


def _chamar_emendas(user, db):
    return export_pdf.export_emendas_pdf(
        request=None, municipio_id=MUNICIPIO, db=db, current=user)


def _chamar_dou(user, db):
    return export_pdf.export_dou_pdf(
        request=None, municipio_id=MUNICIPIO, edicoes=["2026-08-01"],
        titulos=["Extrato de convenio"], db=db, current=user)


def _chamar_parlamentares(user, db, municipio_id=MUNICIPIO):
    return export_pdf.export_parlamentares_pdf(
        request=None, municipio_id=municipio_id, q=None, ano=None, db=db,
        current=user)


# GATES NOVOS: aqui a tela e cobrada por `authz.exigir_tela`, que respeita o
# modo. Os quatro leem o municipio no banco logo depois da porta, entao a
# `BancoSentinela` prova "passou" sem Postgres.
TABELA = [
    ("convenios", "convenios", _chamar_convenios),
    ("voluntarias", "transferegov", _chamar_voluntarias),
    ("plano-acao", "transferegov", _chamar_plano_acao),
    ("emendas", "emendas", _chamar_emendas),
]
IDS = [r for r, _, _ in TABELA]

# GATE PRE-EXISTENTE: `/parlamentares` ja chamava `services.auth.ensure_tela`
# antes do Incremento 2, e continua chamando. NAO entra na tabela acima — o
# comportamento dele e o oposto: nega nos dois modos. Fica numa linha propria
# para que, no dia em que alguem trocar aquele `ensure_tela` por
# `authz.exigir_tela` "para uniformizar", um teste caia dizendo o que foi
# perdido.
PRE_EXISTENTE = ("parlamentares", "parlamentares", _chamar_parlamentares)

# Todo endpoint que cobra tela, sem distincao de qual porta cobra: usado onde a
# afirmacao vale para os dois tipos (admin passa, a chave certa libera).
TODOS = TABELA + [PRE_EXISTENTE]
IDS_TODOS = [r for r, _, _ in TODOS]


# ---------------------------------------------------------------------------
# (a) modo aviso — o gate NOVO deixa passar quem nao tem a tela
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rota,tela,chamar", TABELA, ids=IDS)
def test_aviso_deixa_passar(monkeypatch, envios, rota, tela, chamar):
    """A exigencia mais dura do incremento: nenhum 403 NOVO.

    Quem nao tem a tela segue ate o trabalho de sempre — provado pela sentinela,
    que so e levantada DEPOIS da porta. O usuario tem o municipio de proposito:
    sem ele a trava ANTIGA morderia antes e este teste mediria outra coisa."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    with pytest.raises(PassouDaPorta):
        _rodar(chamar(Usuario(), BancoSentinela()))


def test_aviso_dou_entrega_o_pdf(monkeypatch, envios):
    """O DOU nao consulta banco (e real-time e vem pronto do frontend), entao
    aqui a prova de "passou" e o proprio arquivo: em modo aviso o PDF sai."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    _sem_trilha_de_export(monkeypatch)
    resp = _rodar(_chamar_dou(Usuario(), None))
    assert isinstance(resp, StreamingResponse)
    assert resp.media_type == "application/pdf"


@pytest.mark.parametrize("qual", ["ai_relatorio", "ai"])
def test_aviso_ai_ainda_devolve_o_400_de_corpo_vazio(monkeypatch, envios, qual):
    """Nos dois endpoints de IA a porta entrou ANTES da validacao do corpo.

    Em modo aviso ela nao levanta, entao o erro que sai continua sendo o 400 de
    sempre — e nao um 403 que ninguem via ontem."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    fn = (export_pdf.export_ai_relatorio if qual == "ai_relatorio"
          else export_pdf.export_ai_pdf)
    with pytest.raises(HTTPException) as e:
        _rodar(fn(request=None, payload={"conteudo": "  "}, db=None,
                  current=Usuario()))
    assert e.value.status_code == 400
    assert e.value.detail == "conteudo vazio"


# ---------------------------------------------------------------------------
# (a2) modo aviso — o gate VELHO continua negando, e e isso que foi prometido
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("modo", ["aviso", "bloqueio"])
def test_gate_de_tela_pre_existente_nega_nos_dois_modos(monkeypatch, envios, modo):
    """`/parlamentares` cobra a tela por `services.auth.ensure_tela`, que ja
    valia antes do incremento — e trava que ja vale NAO afrouxa na semana de
    observacao.

    O `envios == []` e metade do teste: nao basta o 403 sair, ele tem de sair
    pela porta ANTIGA. Se um dia esta negativa comecar a aparecer na trilha do
    authz, e porque alguem roteou `ensure_tela` pelo modo aviso — e naquele dia
    as ~128 travas antigas do repo inteiro param de negar junto."""
    monkeypatch.setenv("AUTHZ_MODO", modo)
    with pytest.raises(HTTPException) as e:
        _rodar(_chamar_parlamentares(Usuario(), BancoSentinela()))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_TELA
    assert envios == []


# ---------------------------------------------------------------------------
# (b) modo bloqueio — a porta fecha, e fecha na tela certa
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rota,tela,chamar", TABELA, ids=IDS)
def test_bloqueio_barra_antes_do_trabalho(monkeypatch, envios, rota, tela, chamar):
    """403 com a mensagem de sempre, e ANTES do trabalho: nao adianta barrar o
    download depois de ter lido a base inteira."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    with pytest.raises(HTTPException) as e:
        _rodar(chamar(Usuario(), BancoSentinela()))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_TELA
    assert [d["acao"] for d in envios] == [authz.ACAO_NEGOU]


@pytest.mark.parametrize("rota,tela,chamar", TODOS, ids=IDS_TODOS)
@pytest.mark.parametrize("modo", ["aviso", "bloqueio"])
def test_a_tela_certa_libera(monkeypatch, envios, modo, rota, tela, chamar):
    """A prova de que a chave exigida e a DA TELA, e nao um nome novo: concedida
    ela, o mesmo usuario passa — nos dois modos, pelas duas portas."""
    monkeypatch.setenv("AUTHZ_MODO", modo)
    with pytest.raises(PassouDaPorta):
        _rodar(chamar(Usuario(telas={tela}), BancoSentinela()))
    assert envios == []


def test_bloqueio_dou_exige_a_tela_dou(monkeypatch, envios):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    _sem_trilha_de_export(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _rodar(_chamar_dou(Usuario(), None))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_TELA
    resp = _rodar(_chamar_dou(Usuario(telas={"dou"}), None))
    assert isinstance(resp, StreamingResponse)


@pytest.mark.parametrize("qual", ["ai_relatorio", "ai"])
def test_bloqueio_ai_barra_antes_da_validacao_do_corpo(monkeypatch, envios, qual):
    """Sem a tela "ai" o corpo nem e olhado: 403, e nao o 400. Quem nao pode usar
    a IA nao aprende, pelo formato do erro, o que a rota espera receber."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    fn = (export_pdf.export_ai_relatorio if qual == "ai_relatorio"
          else export_pdf.export_ai_pdf)
    with pytest.raises(HTTPException) as e:
        _rodar(fn(request=None, payload={"conteudo": ""}, db=None,
                  current=Usuario()))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_TELA


# ---------------------------------------------------------------------------
# (c) o MUNICIPIO nao afrouxa em modo nenhum
#
# E o bloco que prova a promessa feita ao dono: "em modo aviso, comportamento
# identico ao de hoje". A checagem de municipio destes endpoints ja existia
# ANTES do Incremento 2 — quem hoje leva 403 por pedir municipio fora do escopo
# tem de continuar levando durante a semana inteira de observacao. Um PDF e o
# tenant inteiro em anexo: alargar isto "so por uma semana" e vazar dado de
# prefeitura para servidor de outra prefeitura.
# ---------------------------------------------------------------------------
MUNICIPIO_PRIMEIRO = TABELA + [("dou", "dou", _chamar_dou)] + [PRE_EXISTENTE]
IDS_MUNICIPIO = [r for r, _, _ in MUNICIPIO_PRIMEIRO]


@pytest.mark.parametrize("rota,tela,chamar", MUNICIPIO_PRIMEIRO, ids=IDS_MUNICIPIO)
@pytest.mark.parametrize("modo", ["aviso", "bloqueio"])
def test_fora_do_municipio_403_nos_dois_modos(monkeypatch, envios, modo,
                                              rota, tela, chamar):
    """403 nos DOIS modos para quem pede municipio fora do seu escopo.

    O usuario recebe A TELA de proposito: sem ela, em `/parlamentares` a trava
    de tela morderia primeiro e o teste nao chegaria a exercitar a de municipio.
    Com a tela na mao, o unico impedimento possivel e o municipio — e o 403 tem
    de sair igual em aviso e em bloqueio.

    `envios == []` de novo: a negativa e a ANTIGA, direto de
    `services.auth.ensure_municipio_access`, sem passar pelo modo."""
    monkeypatch.setenv("AUTHZ_MODO", modo)
    _sem_trilha_de_export(monkeypatch)
    fora = Usuario(telas={tela}, municipios={MUNICIPIO_DE_FORA})
    with pytest.raises(HTTPException) as e:
        _rodar(chamar(fora, BancoSentinela()))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_MUNICIPIO
    assert envios == []


@pytest.mark.parametrize("rota,tela,chamar", TABELA, ids=IDS)
def test_aviso_nao_deixa_o_gate_novo_encobrir_o_velho(monkeypatch, envios,
                                                      rota, tela, chamar):
    """Sem a tela E sem o municipio, em modo aviso: quem responde e a trava
    ANTIGA, com o 403 do municipio.

    E a armadilha que este incremento tinha de evitar. Se o modo aviso tivesse
    engolido tambem `ensure_municipio_access`, este caso viraria um PDF de outra
    prefeitura entregue a quem nunca teve direito a ele — e ninguem notaria,
    porque "em aviso nada barra" seria a explicacao pronta."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    ninguem = Usuario(telas=frozenset(), municipios={MUNICIPIO_DE_FORA})
    with pytest.raises(HTTPException) as e:
        _rodar(chamar(ninguem, BancoSentinela()))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_MUNICIPIO


@pytest.mark.parametrize("modo", ["aviso", "bloqueio"])
def test_parlamentares_sem_municipio_e_pedido_malformado(monkeypatch, envios, modo):
    """`municipio_id` e OPCIONAL em `/parlamentares`, e nao-admin sem municipio
    ja levava 403 hoje — nos dois modos continua levando.

    Nao e permissao que falta: nenhuma correcao de cadastro faz um pedido sem
    municipio virar valido, e deixa-lo passar aqui geraria o relatorio da
    carteira INTEIRA para um servidor de uma prefeitura so."""
    monkeypatch.setenv("AUTHZ_MODO", modo)
    with pytest.raises(HTTPException) as e:
        _rodar(_chamar_parlamentares(
            Usuario(telas={"parlamentares"}), BancoSentinela(),
            municipio_id=None))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_SEM_MUNICIPIO
    assert envios == []


@pytest.mark.parametrize("modo", ["aviso", "bloqueio"])
def test_ai_relatorio_municipio_fora_do_escopo_403_nos_dois_modos(
        monkeypatch, envios, modo):
    """Em `/ai-relatorio` a tela vem antes do municipio (o `municipio_id` do
    corpo e opcional), mas QUANDO ele vem a trava antiga vale igual: pedir o
    relatorio carimbado com municipio alheio e 403 nos dois modos."""
    monkeypatch.setenv("AUTHZ_MODO", modo)
    with pytest.raises(HTTPException) as e:
        _rodar(export_pdf.export_ai_relatorio(
            request=None,
            payload={"conteudo": "texto", "municipio_id": MUNICIPIO_DE_FORA},
            db=None, current=Usuario(telas={"ai"})))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_MUNICIPIO


def test_aviso_ai_relatorio_com_o_municipio_certo_segue_o_trabalho(monkeypatch, envios):
    """O contraponto: sem a tela "ai" mas COM o municipio, em aviso, o gate novo
    nao levanta e o fluxo chega a consulta de sempre."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    with pytest.raises(PassouDaPorta):
        _rodar(export_pdf.export_ai_relatorio(
            request=None,
            payload={"conteudo": "texto", "municipio_id": MUNICIPIO},
            db=BancoSentinela(), current=Usuario()))
    assert [d["detalhes"]["exigido"] for d in envios] == ["ai"]


# ---------------------------------------------------------------------------
# (d) admin passa em tudo, e sem ruido na trilha
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("modo", ["aviso", "bloqueio"])
@pytest.mark.parametrize("rota,tela,chamar", TODOS, ids=IDS_TODOS)
def test_admin_passa_nos_dois_modos(monkeypatch, envios, modo, rota, tela, chamar):
    """Admin tem `allowed_telas = None` (tudo). Nao pode ser barrado nem gerar
    linha: uma semana de trilha cheia de admin nao ensina nada a ninguem."""
    monkeypatch.setenv("AUTHZ_MODO", modo)
    admin = Usuario()
    admin.allowed_telas = None
    admin.allowed_municipio_ids = None
    with pytest.raises(PassouDaPorta):
        _rodar(chamar(admin, BancoSentinela()))
    assert envios == []


# ---------------------------------------------------------------------------
# (e) falha da trilha NAO derruba a exportacao
# ---------------------------------------------------------------------------
def _trilha_quebrada(monkeypatch):
    def _explode(_dados):
        raise RuntimeError("banco da trilha fora do ar")
    monkeypatch.setattr(authz, "_enviar", _explode)


def test_trilha_quebrada_nao_impede_o_pdf(monkeypatch):
    """Um incremento feito para nao quebrar nada nao pode quebrar por causa do
    proprio log. Com a gravacao explodindo, o usuario sem tela continua chegando
    ao trabalho de sempre."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    _trilha_quebrada(monkeypatch)
    with pytest.raises(PassouDaPorta):
        _rodar(_chamar_convenios(Usuario(), BancoSentinela()))


def test_trilha_quebrada_nao_vira_500_no_bloqueio(monkeypatch):
    """E, no dia do bloqueio, o 403 sai igual mesmo com a trilha caida — nao
    virou RuntimeError (500) por causa do log."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    _trilha_quebrada(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _rodar(_chamar_convenios(Usuario(), BancoSentinela()))
    assert e.value.status_code == 403
    assert e.value.detail == MSG_TELA


# ---------------------------------------------------------------------------
# (f) a linha da trilha diz o que o dono precisa corrigir
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rota,tela,chamar", TABELA, ids=IDS)
def test_a_linha_nomeia_a_tela_que_falta(monkeypatch, envios, rota, tela, chamar):
    """Sem o nome da tela na linha, a semana de observacao vira "alguem esbarrou
    em alguma coisa" — e o dono nao tem o que conceder.

    `possui == []` e o achado mais util da semana: o usuario criado com ZERO
    telas que trabalha ha meses porque nunca houve gate."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    with pytest.raises(PassouDaPorta):
        _rodar(chamar(Usuario(), BancoSentinela()))
    exigidas = [d["detalhes"]["exigido"] for d in envios
                if d["detalhes"]["exigencia"] == "tela"]
    assert exigidas == [tela]
    assert envios[0]["acao"] == authz.ACAO_NEGARIA
    assert envios[0]["detalhes"]["modo"] == "aviso"
    assert envios[0]["detalhes"]["possui"] == []
