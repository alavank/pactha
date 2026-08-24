"""O gate de permissao do Relatorio de Monitoramento — provado pelo que ele NAO faz.

Ate agora, neste router, so o LISTAR conferia alguma coisa (municipio E tela, as
duas de antes do incremento): criar, detalhe, PUT, auto-popular, DELETE e o PDF
aceitavam qualquer sessao valida. O incremento acrescenta o gate de tela em todos
e `authz.ensure_dono` em cada um que recebe `{rid}` — porque permissao de tela
nao impede pegar o RM de OUTRO municipio pelo id.

⚠️ AS DUAS FAMILIAS DE CHECAGEM, E POR QUE O TESTE PRECISA SEPARA-LAS
---------------------------------------------------------------------
`services.auth.ensure_tela` e `ensure_municipio_access` NEGAM SEMPRE, nos dois
modos. Sao as travas que JA VALIAM antes deste incremento, em ~128 pontos do
codigo. Se o modo aviso valesse para elas, essas 128 negativas ANTIGAS parariam
de negar durante a semana de observacao: o sistema ficaria MAIS ABERTO
justamente no incremento que existe para fecha-lo, e o dono recebeu a promessa
oposta — "em modo aviso, comportamento IDENTICO ao de hoje".

`services.authz.exigir_tela` e `exigir_municipio` sao os gates NOVOS, e so eles
respeitam `AUTHZ_MODO`. E por isso que, neste arquivo:

  - o caso central e o usuario que TEM o municipio e nao tem a TELA (a parte
    nova): em aviso passa e vira linha na trilha, em bloqueio toma 403;
  - `listar` nao tem parte nova nenhuma: os dois gates dele (municipio E tela)
    sao anteriores ao incremento, entao ele nega em AVISO exatamente como
    negava ontem. E o endpoint que prova a promessa "identico a hoje";
  - nos endpoints com `{rid}`, a conferencia do municipio DA LINHA
    (`ensure_dono`) e codigo inteiramente novo — la nunca houve checagem
    alguma — entao ela respeita o modo: em aviso o RM da prefeitura vizinha
    continua saindo, como saia ontem, so que agora vira linha na trilha.

Dar SO o municipio errado a um usuario nao exercita o gate de tela em `listar`:
ele para na trava de municipio antes de chegar la. Por isso cada teste escolhe o
perfil que faz a requisicao morrer no gate que ele quer medir.

Rodar:
    python -m pytest backend/tests/test_rm_permissao.py -v
"""
import asyncio
import inspect
from datetime import date

import pytest
from fastapi import HTTPException

from routers import rm
from services import authz
from services.auth import ensure_municipio_access, ensure_tela

DATA = date(2026, 7, 1)

MODOS = ["aviso", "bloqueio"]


class Usuario:
    """O que o codigo real le do User: id/email/name + os escopos que
    `load_user_scopes` anexa. `None` nos escopos = admin (passa em tudo)."""

    def __init__(self, telas=None, municipios=None, id=7,
                 email="servidor@montesiao.mg.gov.br", name="Servidor"):
        self.id = id
        self.email = email
        self.name = name
        self.allowed_telas = telas
        self.allowed_municipio_ids = municipios


# O RM das fixtures e do municipio 99.
# Quem tem exatamente o que o endpoint pede.
COM_TUDO = dict(telas={"rm"}, municipios={99})
# O CASO CENTRAL DO INCREMENTO: trabalha no proprio municipio e nunca recebeu a
# tela `rm` — porque ate hoje nao havia gate que a exigisse. E esta conta que o
# modo aviso existe para descobrir sem derrubar.
SEM_A_TELA = dict(telas=set(), municipios={99})
# Tem a tela e chuta o RM da prefeitura vizinha. Trava de municipio = a antiga.
SEM_O_MUNICIPIO = dict(telas={"rm"}, municipios={1})
# A conta criada com ZERO de tudo.
SEM_NADA = dict(telas=set(), municipios=set())


# ---------------------------------------------------------------------------
# Dublês
# ---------------------------------------------------------------------------
class _Res:
    """Resultado de `db.execute` com o minimo que estes endpoints leem."""

    def __init__(self, valor=None, rowcount=1):
        self._valor = valor
        self.rowcount = rowcount

    def first(self):
        return self._valor

    def fetchall(self):
        return self._valor or []

    def scalar(self):
        return self._valor

    def scalar_one_or_none(self):
        return self._valor


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeDb:
    """Devolve respostas enfileiradas e guarda o SQL que passou por ela.

    Guardar o SQL e o que permite afirmar "o DELETE nem chegou a sair" e "em
    aviso as consultas sao exatamente as mesmas de quem tem permissao"."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.sql: list = []
        self.commits = 0

    def begin_nested(self):
        return _Savepoint()

    async def execute(self, stmt, params=None):
        self.sql.append(" ".join(str(stmt).split()))
        return self.respostas.pop(0) if self.respostas else _Res(None)

    async def commit(self):
        self.commits += 1


class _Municipio:
    nome = "Monte Siao"
    uf = "MG"


# ⚠️ ESTAS TUPLAS ESPELHAM SELECT LIDOS POR ÍNDICE — e têm de crescer JUNTO.
#
# É a armadilha nº 1 deste repositório, e ela mordeu aqui: quando `escopo` e
# `anos` entraram nos SELECT de rm.py, estas tuplas ficaram para trás e 33 testes
# passaram a morrer com `IndexError: tuple index out of range` — não por defeito
# de produção, mas por fixture desatualizada. Com o gate vermelho, ninguém
# conseguia distinguir regressão nova de ruído antigo.
#
# Ao mexer num SELECT de rm.py, confira o comprimento aqui:
#   LINHA_DETALHE -> SELECT do `detalhe`   (rm.py, 15 colunas: row[13]=nome, row[14]=uf)
#   LINHA_PDF     -> SELECT do `pdf`       (rm.py,  9 colunas: row[8]=escopo)
LINHA_DETALHE = (1, 99, DATA, "Monte Siao/MG", "RM de julho", "rodape",
                 "rascunho", {"partes": []}, 7, None, None,
                 "completo", [], "Monte Siao", "MG")
LINHA_PDF = (DATA, "Monte Siao/MG", "RM de julho", "rodape", {"partes": []},
             "Monte Siao", "MG", 99, "completo")
LINHA_CTX = (99, "RM de julho", DATA, "rascunho")
DONO = (99,)          # o que `ensure_dono` le: o municipio_id da linha


@pytest.fixture(autouse=True)
def _isolar(monkeypatch):
    """Memoria de dedupe zerada, sem contexto de requisicao e sem env herdada."""
    authz.limpar_dedupe()
    authz.limpar_contexto()
    monkeypatch.delenv("AUTHZ_MODO", raising=False)
    yield
    authz.limpar_dedupe()
    authz.limpar_contexto()


@pytest.fixture(autouse=True)
def envios(monkeypatch):
    """Intercepta o agendamento da trilha: sem isto o teste abriria sessao de
    banco de verdade dentro de uma tarefa de fundo.

    Autouse de proposito — um teste que esquecesse de pedir a fixture sairia
    batendo no Postgres de verdade a partir de uma tarefa solta."""
    registrados: list = []

    def _falso(dados):
        registrados.append(dados)
        return True

    monkeypatch.setattr(authz, "_enviar", _falso)
    return registrados


@pytest.fixture(autouse=True)
def _sem_efeitos(monkeypatch):
    """Neutraliza o que nao e objeto deste teste: a trilha de auditoria do
    proprio router, a montagem do conteudo e os geradores de arquivo."""
    async def _registrar(*a, **k):
        return None

    async def _montar(*a, **k):
        return {"partes": []}

    monkeypatch.setattr(rm, "registrar", _registrar)
    monkeypatch.setattr(rm, "montar_conteudo", _montar)
    monkeypatch.setattr(rm, "gerar_pdf", lambda *a, **k: b"%PDF")
    monkeypatch.setattr(rm, "gerar_resumido_pdf", lambda *a, **k: b"%PDF")
    monkeypatch.setattr(rm, "gerar_totalizado_pdf", lambda *a, **k: b"%PDF")
    monkeypatch.setattr(rm, "gerar_totalizado_xlsx", lambda *a, **k: b"PK")


# ---------------------------------------------------------------------------
# Cada endpoint do router: as respostas que o banco daria e como chama-lo.
# ---------------------------------------------------------------------------
# A 1a resposta dos que recebem `{rid}` e a leitura do `ensure_dono` (o
# municipio_id da linha) — por isso ela aparece antes da consulta de negocio.
CENARIOS = {
    "listar": (
        lambda: [_Res([])],
        lambda db, u: rm.listar(municipio_id=99, db=db, current=u),
        {"items": [], "total": 0},
    ),
    "criar": (
        lambda: [_Res(_Municipio()), _Res(None), _Res(7)],
        lambda db, u: rm.criar(
            body=rm.RmCreate(municipio_id=99, data_referencia=DATA,
                             auto_popular=False),
            request=None, db=db, user=u),
        {"id": 7, "created": True},
    ),
    "detalhe": (
        lambda: [_Res(DONO), _Res(LINHA_DETALHE)],
        lambda db, u: rm.detalhe(rid=1, db=db, current=u),
        None,
    ),
    "atualizar": (
        lambda: [_Res(DONO), _Res(LINHA_CTX), _Res(None)],
        lambda db, u: rm.atualizar(rid=1, body=rm.RmUpdate(titulo="novo"),
                                   request=None, db=db, current=u),
        {"updated": True},
    ),
    "auto_popular": (
        lambda: [_Res(DONO), _Res((99, DATA, "RM de julho", "completo", [])), _Res(None)],
        lambda db, u: rm.repopular(rid=1, request=None, db=db, current=u),
        {"ok": True, "partes": 0, "itens": 0},
    ),
    "remover": (
        lambda: [_Res(DONO), _Res(LINHA_CTX), _Res(None, rowcount=1)],
        lambda db, u: rm.remover(rid=1, request=None, db=db, current=u),
        {"deleted": True},
    ),
    "pdf": (
        lambda: [_Res(DONO), _Res(LINHA_PDF)],
        lambda db, u: rm.pdf(rid=1, request=None, tipo="completo",
                             formato="pdf", db=db, current=u),
        None,
    ),
    # Era "pdf_xlsx" (totalizado em Excel), DESCONTINUADO no PR #273 — o endpoint
    # agora recusa `tipo=totalizado` com 400. O cenario passa a exercitar o
    # RESUMIDO, que e a outra variante que existe de verdade: o que este arquivo
    # testa e o GATE de permissao, e ele precisa de duas variantes vivas.
    "pdf_resumido": (
        lambda: [_Res(DONO), _Res(LINHA_PDF)],
        lambda db, u: rm.pdf(rid=1, request=None, tipo="resumido",
                             formato="pdf", db=db, current=u),
        None,
    ),
}

NOMES = sorted(CENARIOS)

# Os que recebem `{rid}`: ganharam gate de tela NOVO e mais o `ensure_dono`, que
# confere o municipio DA LINHA. Os dois sao codigo novo, e os dois respeitam o
# modo — aqui nunca houve checagem nenhuma para preservar.
COM_ID = ["atualizar", "auto_popular", "detalhe", "pdf", "pdf_resumido", "remover"]

# Onde o gate de TELA nasceu neste incremento (`authz.exigir_tela`). `listar`
# fica de fora: a tela dele ja era exigida antes, por `ensure_tela`.
TELA_NOVA = COM_ID + ["criar"]

# Onde a trava de MUNICIPIO ja existia antes do incremento e por isso nega nos
# DOIS modos. So `listar`, que chama `ensure_municipio_access` direto. `criar`
# (municipio do corpo, via `exigir_municipio`) e os de `{rid}` (municipio da
# linha, via `ensure_dono`) sao gate novo: respeitam o modo.
MUNICIPIO_ANTIGO = ["listar"]

# Nome do cenario -> funcao do router (para as varreduras de codigo-fonte).
FUNCAO = {
    "listar": rm.listar, "criar": rm.criar, "detalhe": rm.detalhe,
    "atualizar": rm.atualizar, "auto_popular": rm.repopular,
    "remover": rm.remover, "pdf": rm.pdf, "pdf_resumido": rm.pdf,
}


def _rodar(nome, usuario):
    respostas, chamada, _ = CENARIOS[nome]
    db = FakeDb(respostas())
    return db, asyncio.run(chamada(db, usuario))


def _modo(monkeypatch, valor):
    monkeypatch.setenv("AUTHZ_MODO", valor)


# ---------------------------------------------------------------------------
# (a) O GATE NOVO: em aviso fala, em bloqueio morde
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nome", TELA_NOVA)
def test_aviso_nao_muda_nada_para_quem_so_falta_a_tela(monkeypatch, envios, nome):
    """O caso central do incremento, endpoint a endpoint: quem trabalha no
    proprio municipio e nunca recebeu a tela `rm` continua recebendo a MESMA
    resposta e disparando as MESMAS consultas de quem tem tudo. Nenhum 403 novo.

    O usuario TEM o municipio de proposito. Sem ele a requisicao esbarraria
    tambem na conferencia de municipio (`ensure_dono` nos de `{rid}`,
    `exigir_municipio` no criar), e o teste mediria os dois gates de uma vez —
    inclusive o irmao em bloqueio, que passaria a receber o 403 de municipio
    achando que provou o de tela."""
    _modo(monkeypatch, "aviso")
    db_sem, resp_sem = _rodar(nome, Usuario(**SEM_A_TELA))
    authz.limpar_dedupe()
    db_com, resp_com = _rodar(nome, Usuario(**COM_TUDO))

    assert db_sem.sql == db_com.sql
    assert db_sem.commits == db_com.commits
    esperado = CENARIOS[nome][2]
    if esperado is not None:
        assert resp_sem == esperado
    assert type(resp_sem) is type(resp_com)


@pytest.mark.parametrize("nome", TELA_NOVA)
def test_aviso_registra_o_que_teria_negado(monkeypatch, envios, nome):
    """Deixar passar em silencio seria so uma trava desligada. O valor da semana
    de observacao esta na linha da trilha."""
    _modo(monkeypatch, "aviso")
    _rodar(nome, Usuario(**SEM_A_TELA))
    assert envios, f"{nome} passou sem registrar nada"
    assert all(e["acao"] == authz.ACAO_NEGARIA for e in envios)
    assert {"tela"} <= {e["detalhes"]["exigencia"] for e in envios}
    # A linha tem de dizer o que faltou e o que a pessoa tem hoje — e o que o
    # dono le para decidir a correcao de cadastro.
    tela = [e for e in envios if e["detalhes"]["exigencia"] == "tela"][0]
    assert tela["exigido"] == "rm"
    assert tela["detalhes"]["possui"] == []
    assert tela["detalhes"]["modo"] == "aviso"


@pytest.mark.parametrize("nome", TELA_NOVA)
def test_bloqueio_barra_quem_nao_tem_a_tela(monkeypatch, envios, nome):
    """Mesma conta do teste anterior, so que com a trava ligada: agora nega, com
    a mensagem que o sistema sempre deu, e a negativa vira `authz.negou`."""
    _modo(monkeypatch, "bloqueio")
    with pytest.raises(HTTPException) as e:
        _rodar(nome, Usuario(**SEM_A_TELA))
    assert e.value.status_code == 403
    assert e.value.detail == "Voce nao tem acesso a esta tela"
    assert [x["acao"] for x in envios] == [authz.ACAO_NEGOU]


def test_criar_tem_os_dois_gates_novos_entao_o_municipio_tambem_espera(
        monkeypatch, envios):
    """No `criar` o municipio vem do CORPO (o RM ainda nao existe, entao nao ha
    linha de onde tirar dono) e passa pelo gate NOVO `exigir_municipio`. Logo,
    em aviso, ele deixa passar tambem quem esta fora do municipio — ao contrario
    do `listar`, cuja trava de municipio e anterior ao incremento e nega
    sempre. Os dois convivem no mesmo router, e a diferenca e proposital."""
    _modo(monkeypatch, "aviso")
    _, resp = _rodar("criar", Usuario(**SEM_O_MUNICIPIO))
    assert resp == {"id": 7, "created": True}
    assert [e["detalhes"]["exigencia"] for e in envios] == ["municipio"]
    assert envios[0]["municipio_id"] == 99

    envios.clear()
    authz.limpar_dedupe()
    _modo(monkeypatch, "bloqueio")
    with pytest.raises(HTTPException) as e:
        _rodar("criar", Usuario(**SEM_O_MUNICIPIO))
    assert e.value.status_code == 403
    assert e.value.detail == "Voce nao tem acesso a este municipio"


@pytest.mark.parametrize("modo", MODOS)
@pytest.mark.parametrize("nome", NOMES)
def test_quem_tem_a_permissao_passa_calado(monkeypatch, envios, nome, modo):
    """Nem um pingo de ruido na trilha para quem esta em ordem — senao a semana
    de observacao vira mil linhas e ninguem le nenhuma."""
    _modo(monkeypatch, modo)
    _rodar(nome, Usuario(**COM_TUDO))
    assert envios == []


@pytest.mark.parametrize("modo", MODOS)
@pytest.mark.parametrize("nome", NOMES)
def test_admin_passa_calado(monkeypatch, envios, nome, modo):
    """Admin = `allowed_* is None`. Passa nos dois modos e nao gera aviso."""
    _modo(monkeypatch, modo)
    _rodar(nome, Usuario(telas=None, municipios=None))
    assert envios == []


@pytest.mark.parametrize("nome", TELA_NOVA)
def test_falha_da_trilha_nao_derruba_o_endpoint_em_aviso(monkeypatch, nome):
    """Se a gravacao explodir, a requisicao segue E a resposta e a mesma. Um
    incremento feito para nao quebrar nada nao pode quebrar por causa do
    proprio log."""
    _modo(monkeypatch, "aviso")

    def _explode(_dados):
        raise RuntimeError("banco fora do ar no meio da gravacao da trilha")

    monkeypatch.setattr(authz, "_enviar", _explode)
    _, resp = _rodar(nome, Usuario(**SEM_A_TELA))
    esperado = CENARIOS[nome][2]
    if esperado is not None:
        assert resp == esperado


@pytest.mark.parametrize("nome", TELA_NOVA)
def test_falha_da_trilha_nao_engole_o_403_em_bloqueio(monkeypatch, nome):
    """O outro lado da mesma garantia: trilha quebrada nao pode DESLIGAR a
    trava. Se a gravacao falha, o 403 sai igual."""
    _modo(monkeypatch, "bloqueio")

    def _explode(_dados):
        raise RuntimeError("banco fora do ar no meio da gravacao da trilha")

    monkeypatch.setattr(authz, "_enviar", _explode)
    with pytest.raises(HTTPException) as e:
        _rodar(nome, Usuario(**SEM_A_TELA))
    assert e.value.status_code == 403


# ---------------------------------------------------------------------------
# (b) O QUE NAO MUDA: "em modo aviso, identico ao de hoje"
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("modo", MODOS)
@pytest.mark.parametrize("nome", MUNICIPIO_ANTIGO)
def test_sem_o_municipio_e_403_nos_dois_modos(monkeypatch, envios, nome, modo):
    """A promessa do incremento, no unico endpoint deste router que ja travava
    municipio antes dele: `listar` chama `ensure_municipio_access`, que NAO passa
    pelo modo aviso. Quem hoje leva 403 por pedir municipio fora do escopo
    continua levando amanha.

    Se este teste virasse "em aviso passa", o incremento estaria ALARGANDO o
    acesso — o oposto do que existe para fazer. E o alargamento sairia caro:
    `ensure_municipio_access` e chamada em dezenas de pontos do sistema, todos
    travas que ja valem hoje."""
    _modo(monkeypatch, modo)
    with pytest.raises(HTTPException) as e:
        _rodar(nome, Usuario(**SEM_O_MUNICIPIO))
    assert e.value.status_code == 403
    assert e.value.detail == "Voce nao tem acesso a este municipio"


@pytest.mark.parametrize("modo", MODOS)
def test_listar_continua_negando_a_tela_nos_dois_modos(monkeypatch, envios, modo):
    """`listar` e o endpoint que nao ganhou nada: os dois gates dele sao
    anteriores ao incremento. Entao ele nega em AVISO exatamente como negava
    ontem — inclusive a tela, que aqui passa por `services.auth.ensure_tela`.

    Se um dia alguem trocar essa chamada por `authz.exigir_tela` "para ficar
    igual aos outros", este teste cai — e e para cair: seria uma trava viva
    virando aviso."""
    _modo(monkeypatch, modo)
    with pytest.raises(HTTPException) as e:
        _rodar("listar", Usuario(**SEM_A_TELA))
    assert e.value.status_code == 403
    assert e.value.detail == "Voce nao tem acesso a esta tela"


@pytest.mark.parametrize("modo", MODOS)
@pytest.mark.parametrize("nome", MUNICIPIO_ANTIGO)
def test_a_conta_sem_nada_para_onde_ja_havia_trava(monkeypatch, envios,
                                                   nome, modo):
    """A conta criada com ZERO telas e ZERO municipios. Onde havia trava, ela
    continua parando — nos dois modos."""
    _modo(monkeypatch, modo)
    with pytest.raises(HTTPException) as e:
        _rodar(nome, Usuario(**SEM_NADA))
    assert e.value.status_code == 403


@pytest.mark.parametrize("nome", NOMES)
def test_a_conta_sem_nada_nao_alcanca_nada_com_a_trava_ligada(monkeypatch,
                                                              envios, nome):
    """Ligada a trava, essa mesma conta perde o router inteiro — que e o estado
    final que o incremento persegue."""
    _modo(monkeypatch, "bloqueio")
    with pytest.raises(HTTPException) as e:
        _rodar(nome, Usuario(**SEM_NADA))
    assert e.value.status_code == 403


# ---------------------------------------------------------------------------
# (b2) O dono da LINHA: gate 100% novo, entao respeita o modo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nome", COM_ID)
def test_bloqueio_barra_o_rm_de_outro_municipio(monkeypatch, envios, nome):
    """O buraco que permissao de VERBO nao resolve: a pessoa TEM a tela `rm` e o
    proprio municipio, e chuta o id do relatorio da prefeitura vizinha."""
    _modo(monkeypatch, "bloqueio")
    with pytest.raises(HTTPException) as e:
        _rodar(nome, Usuario(**SEM_O_MUNICIPIO))
    assert e.value.status_code == 403
    assert e.value.detail == "Voce nao tem acesso a este municipio"


@pytest.mark.parametrize("nome", COM_ID)
def test_aviso_ainda_entrega_o_rm_de_outro_municipio_mas_denuncia(
        monkeypatch, envios, nome):
    """O preco declarado da semana de observacao, afirmado sem rodeio.

    Antes deste incremento, `{rid}` era so um numero: qualquer sessao valida
    baixava e apagava o RM de qualquer prefeitura, e NENHUMA checagem existia
    aqui para preservar. Entao `ensure_dono` e gate novo, respeita o modo, e em
    aviso o acesso indevido continua acontecendo — identico a ontem. O que muda
    e que agora ele deixa rastro, dizendo de qual tabela e de qual id veio.

    Nao e conformismo: e a diferenca entre um buraco invisivel e um buraco com
    nome, endereco e data, que o dono fecha ligando `AUTHZ_MODO=bloqueio`."""
    _modo(monkeypatch, "aviso")
    db_fora, resp_fora = _rodar(nome, Usuario(**SEM_O_MUNICIPIO))
    authz.limpar_dedupe()
    envios.clear()
    db_dono, resp_dono = _rodar(nome, Usuario(**COM_TUDO))

    assert db_fora.sql == db_dono.sql        # nada mudou na execucao
    assert type(resp_fora) is type(resp_dono)
    assert envios == []                      # e quem e do municipio nao gera ruido

    authz.limpar_dedupe()
    _rodar(nome, Usuario(**SEM_O_MUNICIPIO))
    assert [e["detalhes"]["exigencia"] for e in envios] == ["municipio"]
    linha = envios[0]
    assert linha["acao"] == authz.ACAO_NEGARIA
    assert linha["municipio_id"] == 99
    # Sem a origem, "apagou RM de outro municipio" e "pediu tela de outro
    # municipio" sairiam identicas na trilha.
    assert linha["detalhes"]["origem"] == {"tabela": "rm_relatorios",
                                           "coluna": "id", "id": "1"}


@pytest.mark.parametrize("modo", MODOS)
def test_pedido_malformado_e_negado_nos_dois_modos(monkeypatch, envios, modo):
    """Municipio AUSENTE nao e permissao que falta: nenhuma correcao de cadastro
    faz um pedido sem municipio virar valido. Deixa-lo passar trocaria um 403
    honesto por uma consulta sem filtro devolvendo o tenant inteiro."""
    _modo(monkeypatch, modo)
    db = FakeDb([_Res([])])
    with pytest.raises(HTTPException) as e:
        asyncio.run(rm.listar(municipio_id=None, db=db,
                              current=Usuario(**COM_TUDO)))
    assert e.value.status_code == 403
    assert e.value.detail == "Selecione um municipio permitido"
    assert db.sql == [], "nao pode ter consultado nada antes de negar"


@pytest.mark.parametrize("modo", MODOS)
@pytest.mark.parametrize("valor,detalhe", [
    (None, "Selecione um municipio permitido"),
    ("todos", "Municipio invalido"),
])
def test_gate_novo_de_municipio_tambem_recusa_pedido_malformado(
        monkeypatch, envios, modo, valor, detalhe):
    """Mesmo no gate NOVO — o unico que respeita o modo — pedido malformado
    levanta nos dois modos, e nao vira linha de observacao (nao ha o que
    observar: nao e cadastro que falta)."""
    _modo(monkeypatch, modo)
    with pytest.raises(HTTPException) as e:
        authz.exigir_municipio(Usuario(**COM_TUDO), valor)
    assert e.value.status_code == 403
    assert e.value.detail == detalhe
    assert envios == []


def test_bloqueio_nao_chega_a_apagar(monkeypatch, envios):
    """O gate vem ANTES da escrita: em bloqueio o DELETE nem sai."""
    _modo(monkeypatch, "bloqueio")
    db = FakeDb([_Res(DONO), _Res(LINHA_CTX), _Res(None, rowcount=1)])
    with pytest.raises(HTTPException):
        asyncio.run(rm.remover(rid=1, request=None, db=db,
                               current=Usuario(**SEM_O_MUNICIPIO)))
    assert not any("DELETE" in s.upper() for s in db.sql)
    assert db.commits == 0


def test_bloqueio_nao_chega_a_escrever_no_update(monkeypatch, envios):
    _modo(monkeypatch, "bloqueio")
    db = FakeDb([_Res(DONO), _Res(LINHA_CTX), _Res(None)])
    with pytest.raises(HTTPException):
        asyncio.run(rm.atualizar(rid=1, body=rm.RmUpdate(titulo="novo"),
                                 request=None, db=db,
                                 current=Usuario(**SEM_O_MUNICIPIO)))
    assert not any("UPDATE" in s.upper() for s in db.sql)
    assert db.commits == 0


def test_em_aviso_a_ordem_do_gate_e_a_mesma_do_bloqueio(monkeypatch, envios):
    """A posicao do gate nao pode depender do modo: se em aviso ele ficasse
    DEPOIS do DELETE, ligar `AUTHZ_MODO=bloqueio` mudaria a ordem das operacoes,
    e a semana de observacao teria medido um caminho de codigo diferente do que
    vai para producao. Em aviso o DELETE sai (comportamento de hoje), mas a
    negativa foi avaliada ANTES dele."""
    _modo(monkeypatch, "aviso")
    db = FakeDb([_Res(DONO), _Res(LINHA_CTX), _Res(None, rowcount=1)])
    resp = asyncio.run(rm.remover(rid=1, request=None, db=db,
                                  current=Usuario(**SEM_O_MUNICIPIO)))
    assert resp == {"deleted": True}
    assert any("DELETE" in s.upper() for s in db.sql)
    assert envios and envios[0]["detalhes"]["exigencia"] == "municipio"
    # A leitura do dono e a PRIMEIRA consulta — o gate foi avaliado antes de
    # qualquer escrita, mesmo tendo deixado passar.
    assert db.sql[0].upper().startswith("SELECT MUNICIPIO_ID FROM RM_RELATORIOS")


@pytest.mark.parametrize("modo", MODOS)
def test_rm_inexistente_continua_404_e_nao_vira_403(monkeypatch, envios, modo):
    """`ensure_dono` nao inventa negativa: sem linha, nao ha decisao, e quem
    decide o 404 continua sendo o endpoint."""
    _modo(monkeypatch, modo)
    db = FakeDb([_Res(None), _Res(None)])
    with pytest.raises(HTTPException) as e:
        asyncio.run(rm.detalhe(rid=999, db=db,
                               current=Usuario(**SEM_O_MUNICIPIO)))
    assert e.value.status_code == 404


# ---------------------------------------------------------------------------
# (c) As duas familias, medidas na origem
# ---------------------------------------------------------------------------
# Os testes acima medem o efeito pelos endpoints. Estes quatro fixam a regra na
# raiz, para ninguem "uniformizar" as quatro funcoes achando que sao a mesma
# coisa — a diferenca entre elas e a promessa feita ao dono.
@pytest.mark.parametrize("modo", MODOS)
def test_ensure_tela_da_auth_nega_sempre_e_nao_observa(monkeypatch, envios, modo):
    """A checagem que JA EXISTIA em ~128 pontos. Nao passa pelo modo aviso."""
    _modo(monkeypatch, modo)
    with pytest.raises(HTTPException) as e:
        ensure_tela(Usuario(**SEM_A_TELA), "rm")
    assert e.value.status_code == 403
    assert e.value.detail == "Voce nao tem acesso a esta tela"
    assert envios == []
    assert ensure_tela(Usuario(telas=None), "rm") is None      # admin passa


@pytest.mark.parametrize("modo", MODOS)
def test_ensure_municipio_access_da_auth_nega_sempre_e_nao_observa(
        monkeypatch, envios, modo):
    _modo(monkeypatch, modo)
    with pytest.raises(HTTPException) as e:
        ensure_municipio_access(Usuario(**SEM_O_MUNICIPIO), 99)
    assert e.value.status_code == 403
    assert e.value.detail == "Voce nao tem acesso a este municipio"
    assert envios == []
    assert ensure_municipio_access(Usuario(municipios=None), 99) is None


def test_exigir_tela_do_authz_respeita_o_modo(monkeypatch, envios):
    """O gate NOVO: em aviso volta sem levantar e registra; em bloqueio levanta
    o MESMO 403, com a MESMA mensagem de `ensure_tela` — trocar a mensagem aqui
    mudaria a resposta de producao no dia em que a trava ligasse."""
    _modo(monkeypatch, "aviso")
    assert authz.exigir_tela(Usuario(**SEM_A_TELA), "rm") is None
    assert [e["acao"] for e in envios] == [authz.ACAO_NEGARIA]

    envios.clear()
    authz.limpar_dedupe()
    _modo(monkeypatch, "bloqueio")
    with pytest.raises(HTTPException) as e:
        authz.exigir_tela(Usuario(**SEM_A_TELA), "rm")
    assert e.value.status_code == 403
    assert e.value.detail == "Voce nao tem acesso a esta tela"
    assert [x["acao"] for x in envios] == [authz.ACAO_NEGOU]


def test_exigir_municipio_do_authz_respeita_o_modo(monkeypatch, envios):
    _modo(monkeypatch, "aviso")
    assert authz.exigir_municipio(Usuario(**SEM_O_MUNICIPIO), 99) is None
    assert [e["acao"] for e in envios] == [authz.ACAO_NEGARIA]

    envios.clear()
    authz.limpar_dedupe()
    _modo(monkeypatch, "bloqueio")
    with pytest.raises(HTTPException) as e:
        authz.exigir_municipio(Usuario(**SEM_O_MUNICIPIO), 99)
    assert e.value.status_code == 403
    assert e.value.detail == "Voce nao tem acesso a este municipio"
    assert [x["acao"] for x in envios] == [authz.ACAO_NEGOU]


def test_modo_desconhecido_cai_em_aviso(monkeypatch, envios):
    """Fail-OPEN de proposito: digitar `bloqueiop` na env nao pode LIGAR a trava
    sem ninguem ter pedido. O default e o que NAO quebra."""
    _modo(monkeypatch, "bloqueiop")
    assert authz.modo() == "aviso"
    _, resp = _rodar("detalhe", Usuario(**SEM_A_TELA))
    assert resp["id"] == 1


# ---------------------------------------------------------------------------
# (d) Cobertura: endpoint novo nao pode nascer sem gate
# ---------------------------------------------------------------------------
# Este router ja teve 6 dos 7 endpoints sem checagem nenhuma. O jeito de isso
# nao voltar a acontecer e o proprio teste varrer as rotas registradas, em vez
# de uma lista escrita a mao que envelhece.
def _rotas():
    return [(r.path, r.endpoint) for r in rm.router.routes
            if getattr(r, "endpoint", None) is not None]


def test_o_router_tem_as_rotas_que_este_teste_acha_que_tem():
    """Se alguem acrescentar um endpoint, este numero muda e o desenvolvedor e
    obrigado a olhar o arquivo — que e exatamente o ponto."""
    assert len(_rotas()) == 7


def _fonte(funcao) -> str:
    """A fonte do endpoint MAIS a do helper de gate que ele chama.

    Os tres endpoints de escrita passaram a delegar os gates a
    `rm._exigir_escrita` no Incremento 6 (alcance por linha): o nome da tabela
    vira literal de SQL, e uma copia divergente e uma checagem que deixa de
    checar sem ninguem notar. Sem seguir a chamada, estes testes leriam so
    `await _exigir_escrita(...)` e concluiriam que o gate sumiu — e, o que e
    pior, continuariam passando no dia em que alguem esvaziasse o helper."""
    fonte = inspect.getsource(funcao)
    if "_exigir_escrita(" in fonte:
        fonte += "\n" + inspect.getsource(rm._exigir_escrita)
    return fonte


@pytest.mark.parametrize("caminho,funcao", _rotas())
def test_todo_endpoint_exige_a_tela_rm(caminho, funcao):
    fonte = _fonte(funcao)
    # Aceita as DUAS formas, e a diferenca entre elas nao e cosmetica:
    # `ensure_tela` e a checagem que JA EXISTIA e nega sempre, nos dois modos;
    # `authz.exigir_tela` e o gate NOVO, que respeita `AUTHZ_MODO` e por isso
    # so avisa durante a semana de observacao. Qual e qual, os dois testes
    # seguintes fixam endpoint a endpoint.
    assert ("ensure_tela(" in fonte or "exigir_tela(" in fonte) and '"rm"' in fonte, \
        f"{caminho} nao exige a tela `rm`"


@pytest.mark.parametrize("nome", sorted(set(TELA_NOVA)))
def test_gate_de_tela_novo_usa_a_funcao_que_respeita_o_modo(nome):
    """Gate ACRESCENTADO agora usa `authz.exigir_tela`. Usar `ensure_tela` aqui
    negaria ja em modo aviso — o apagao de segunda-feira que o incremento
    inteiro existe para nao causar."""
    fonte = _fonte(FUNCAO[nome])
    assert "exigir_tela(" in fonte, f"{nome} deveria usar authz.exigir_tela"
    assert "ensure_tela(" not in fonte, \
        f"{nome} e gate novo: `ensure_tela` negaria ja em modo aviso"


def test_gate_de_tela_pre_existente_continua_negando_sempre():
    """E o inverso: a checagem que ja valia nao pode ser rebaixada a aviso."""
    fonte = inspect.getsource(rm.listar)
    assert "ensure_tela(" in fonte and "exigir_tela(" not in fonte, \
        "a tela do listar ja era exigida antes; rebaixa-la a aviso alarga acesso"
    assert "ensure_municipio_access(" in fonte and "exigir_municipio(" not in fonte, \
        "o municipio do listar ja era exigido antes"


@pytest.mark.parametrize("caminho,funcao",
                         [(c, f) for c, f in _rotas() if "{rid}" in c])
def test_endpoint_com_id_confere_o_dono_da_linha(caminho, funcao):
    """Permissao de tela nao impede pegar o RM de outro municipio pelo id."""
    fonte = _fonte(funcao)
    assert "ensure_dono(" in fonte, f"{caminho} nao confere o municipio da linha"


@pytest.mark.parametrize("caminho,funcao",
                         [(c, f) for c, f in _rotas() if "{rid}" not in c])
def test_endpoint_sem_id_confere_o_municipio_pedido(caminho, funcao):
    """Sem `{rid}` nao ha linha de onde tirar dono: o municipio vem da query
    (listar) ou do corpo (criar), e e ele que precisa estar no escopo."""
    fonte = inspect.getsource(funcao)
    assert ("ensure_municipio_access(" in fonte or "exigir_municipio(" in fonte), \
        f"{caminho} nao confere o municipio pedido"
