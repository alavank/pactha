"""A CONFIGURACAO do alcance: o que a tela grava, o que ela nao consegue gravar,
e a linha que sobra na trilha.

O dono pediu que a escolha morasse "no painel de administracao, no modulo de
usuarios" — ou seja, no mesmo lugar e no mesmo clique das caixinhas. Entao ela
viaja no MESMO endpoint (`PUT /api/permissoes/usuario/{id}`), na MESMA transacao
e na MESMA linha de auditoria: "pode editar, e so os que ele criou" e uma frase
so, e dois eventos separados obrigariam o auditor a cruzar dois registros para
entender um unico Salvar.

⚠️ O TESTE QUE MAIS IMPORTA AQUI e `test_pedido_sem_o_campo_nao_apaga_a_config`:
o frontend que ainda nao conhece o campo `escopos` nao pode zerar a restricao que
o administrador acabou de configurar so porque foi implantado antes da tela nova.

Rodar:
    python -m pytest backend/tests/test_escopo_concessao.py -v
"""
import asyncio
import inspect

import pytest
from fastapi import HTTPException

from routers import permissoes as router
from services import authz, permissoes


class Usuario:
    def __init__(self, id=1, role="admin", super_admin=False, escopos=None,
                 permissoes_=None, name="Fulano", email="f@x.gov.br"):
        self.id = id
        self.role = role
        self.name = name
        self.email = email
        self.active = True
        self.super_admin = super_admin
        self.somente_leitura = False
        self.kiosk = False
        self.allowed_permissoes = permissoes_ if permissoes_ is not None else []
        self.allowed_escopos = escopos or {}


class _Res:
    def __init__(self, valor=None):
        self._valor = valor

    def fetchall(self):
        return self._valor or []

    def scalar_one_or_none(self):
        return self._valor


class FakeDb:
    def __init__(self, respostas=()):
        self.respostas = list(respostas)
        self.sql: list = []
        self.params: list = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        self.sql.append(" ".join(str(stmt).split()))
        self.params.append(params)
        return self.respostas.pop(0) if self.respostas else _Res(None)

    async def commit(self):
        self.commits += 1


@pytest.fixture
def trilha(monkeypatch):
    """Intercepta `registrar_critico` — sem isto o teste escreveria na trilha de
    verdade. Guarda o payload inteiro, que e o objeto do item (F)."""
    linhas: list = []

    async def _falso(db, **kw):
        linhas.append(kw)

    monkeypatch.setattr(router, "registrar_critico", _falso)
    return linhas


# ===========================================================================
# 1. `_validar_escopos` — o vocabulario, e o que ele recusa
# ===========================================================================
def test_so_o_que_restringe_vira_linha():
    """`todos` e a AUSENCIA de linha — ha um unico jeito de dizer "sem
    restricao" no banco, e ele e o mesmo que a migration deixou."""
    assert router._validar_escopos({"gestao": "proprios", "rm": "todos"}) \
        == {"gestao": "proprios"}


def test_normaliza_caixa_e_espaco():
    assert router._validar_escopos({" GESTAO ": " Proprios "}) == {"gestao": "proprios"}


def test_modulo_desconhecido_e_400():
    """400 e nao 403: nao e permissao que falta, e pedido malformado. E a recusa
    importa mais aqui do que nas caixinhas — `gestaoo` seria uma restricao que o
    administrador jura ter configurado e que nunca se aplica."""
    with pytest.raises(HTTPException) as e:
        router._validar_escopos({"gestaoo": "proprios"})
    assert e.value.status_code == 400
    assert "gestaoo" in e.value.detail


def test_modulo_sem_alcance_e_400():
    """`cofre` tem CRUD, mas a tabela dele nao guarda quem criou a linha."""
    with pytest.raises(HTTPException) as e:
        router._validar_escopos({"cofre": "proprios"})
    assert e.value.status_code == 400


@pytest.mark.parametrize("valor", ["proprio", "PROPIOS", "sim", "", None, 1, True])
def test_valor_invalido_e_400(valor):
    with pytest.raises(HTTPException) as e:
        router._validar_escopos({"gestao": valor})
    assert e.value.status_code == 400


def test_payload_que_nao_e_objeto_e_400():
    with pytest.raises(HTTPException) as e:
        router._validar_escopos(["gestao"])
    assert e.value.status_code == 400


def test_vazio_e_nenhuma_restricao():
    assert router._validar_escopos({}) == {}
    assert router._validar_escopos(None) == {}


# ===========================================================================
# 2. A resposta legivel — o default explicito
# ===========================================================================
def test_a_api_devolve_todo_modulo_com_o_default_explicito():
    """O banco guarda so o que restringe; a API nao pode obrigar a tela a saber
    que "ausente" quer dizer `todos`."""
    completo = router._escopos_completos({"gestao": "proprios"})
    assert set(completo) == set(permissoes.ESCOPO_RECURSOS)
    assert completo["gestao"] == "proprios"
    assert completo["rm"] == "todos" and completo["documentos"] == "todos"


def test_a_frase_do_alcance_e_em_portugues():
    assert router._frase_escopo("gestao", "proprios") == \
        "Gestao Interna: Somente os que ele criou"


def test_o_catalogo_da_api_traz_o_vocabulario_do_alcance():
    """O frontend nao reescreve nenhuma parte disto — regra 1 do catalogo."""
    cat = permissoes.catalogo_para_api()
    assert cat["escopos"]["default"] == "todos"
    assert [o["valor"] for o in cat["escopos"]["opcoes"]] == ["todos", "proprios"]
    assert set(cat["escopos"]["recursos"]) == set(permissoes.ESCOPO_RECURSOS)


def test_o_catalogo_diz_QUAIS_caixinhas_o_alcance_modifica():
    """A regra do dono: a escolha "so aparece se ele tiver editar OU excluir
    naquele modulo — sem isso a escolha nao significa nada e vira ruido"."""
    grupos = {g["recurso"]: g
              for s in permissoes.por_secao() for g in s["recursos"]}
    assert grupos["gestao"]["escopavel"] is True
    assert grupos["gestao"]["escopo_permissoes"] == ["gestao.editar", "gestao.excluir"]
    assert grupos["cofre"]["escopavel"] is False
    assert grupos["cofre"]["escopo_permissoes"] == []


# ===========================================================================
# 3. ⭐ Anti-escalonamento
# ===========================================================================
def test_quem_alcanca_tudo_pode_configurar():
    router._barrar_escalonamento_escopo(Usuario(), {}, {"gestao": "proprios"})


def test_administrador_restrito_nao_solta_o_alcance_de_ninguem():
    """Seria conceder por procuracao o que a tela lhe nega."""
    restrito = Usuario(escopos={"gestao": "proprios"})
    with pytest.raises(HTTPException) as e:
        router._barrar_escalonamento_escopo(restrito, {"gestao": "proprios"}, {})
    assert e.value.status_code == 403
    assert "Gestao Interna" in e.value.detail


def test_administrador_restrito_tambem_nao_APERTA_o_alcance():
    """A simetria e deliberada, como no anti-escalonamento das caixinhas: um
    administrador restrito que pudesse apertar o alcance dos colegas derrubaria
    a operacao do setor inteiro sem nunca ter tido esse poder."""
    restrito = Usuario(escopos={"gestao": "proprios"})
    with pytest.raises(HTTPException):
        router._barrar_escalonamento_escopo(restrito, {}, {"gestao": "proprios"})


def test_a_trava_vale_so_para_o_que_MUDOU():
    """Barrar pelo CONJUNTO impediria o administrador restrito de mexer no
    alcance de OUTRO modulo, num pedido em que ele nem tocou naquele."""
    restrito = Usuario(escopos={"gestao": "proprios"})
    router._barrar_escalonamento_escopo(
        restrito, {"gestao": "proprios"}, {"gestao": "proprios", "rm": "proprios"})


def test_super_admin_passa():
    router._barrar_escalonamento_escopo(
        Usuario(super_admin=True, escopos={"gestao": "proprios"}),
        {}, {"gestao": "proprios"})


@pytest.mark.parametrize("modo_env", ["aviso", "bloqueio"])
def test_a_trava_nega_nos_dois_modos(monkeypatch, modo_env):
    """Este endpoint e novo: nao ha comportamento antigo a preservar, e trava de
    escalonamento que "so avisa" e a ausencia da trava."""
    monkeypatch.setenv("AUTHZ_MODO", modo_env)
    with pytest.raises(HTTPException):
        router._barrar_escalonamento_escopo(
            Usuario(escopos={"rm": "proprios"}), {}, {"rm": "proprios"})


# ===========================================================================
# 4. A gravacao — so a diferenca
# ===========================================================================
def test_grava_so_o_que_mudou():
    """`definido_em`/`definido_por` sao a resposta barata para "de onde veio
    esta linha?". Reescreve-las a cada Salvar faria a restricao imposta ha um
    ano por outra pessoa passar a dizer que fui eu, hoje."""
    db = FakeDb()
    asyncio.run(router._gravar_escopos(
        db, 5, {"gestao": "proprios", "rm": "proprios"},
        {"gestao": "proprios", "documentos": "proprios"}, autor_id=1))
    assert len(db.sql) == 2
    assert "DELETE FROM user_escopos" in db.sql[0]
    assert db.params[0] == {"u": 5, "r": "rm"}
    assert "INSERT INTO user_escopos" in db.sql[1]
    assert db.params[1]["r"] == "documentos"
    assert db.params[1]["por"] == 1


def test_voltar_para_todos_APAGA_a_linha():
    """Ha um unico jeito de dizer "sem restricao" no banco, e e a ausencia."""
    db = FakeDb()
    asyncio.run(router._gravar_escopos(db, 5, {"gestao": "proprios"}, {}, autor_id=1))
    assert len(db.sql) == 1 and "DELETE" in db.sql[0]


def test_nada_a_fazer_nao_toca_no_banco():
    db = FakeDb()
    asyncio.run(router._gravar_escopos(
        db, 5, {"gestao": "proprios"}, {"gestao": "proprios"}, autor_id=1))
    assert db.sql == []


# ===========================================================================
# 5. ⭐⭐ O endpoint inteiro
# ===========================================================================
def _conceder(current, alvo, req, concedidas=(), escopos=()):
    db = FakeDb([
        _Res(alvo),                                  # select(User)
        _Res([(c,) for c in concedidas]),            # _concedidas
        _Res([(r, e) for r, e in escopos]),          # _escopos_atuais
    ])
    return db, asyncio.run(router.conceder(
        user_id=alvo.id, req=req, request=None, db=db, current=current))


def test_pedido_sem_o_campo_nao_apaga_a_config(trilha):
    """⭐ O frontend antigo manda so `permissoes`. Se `escopos` ausente zerasse a
    restricao, este incremento teria criado um jeito de AFROUXAR permissao sem
    ninguem pedir — e o clique que faz isso seria "salvar as caixinhas"."""
    alvo = Usuario(id=5, role="usuario")
    req = router.ConcederRequest(permissoes=["gestao.ver"])
    assert req.escopos is None
    db, resp = _conceder(Usuario(super_admin=True), alvo, req,
                         escopos=[("gestao", "proprios")])
    assert not any("user_escopos" in s and ("DELETE" in s or "INSERT" in s)
                   for s in db.sql), "mexeu no alcance sem ninguem pedir"
    assert resp["escopos"]["gestao"] == "proprios"


def test_o_pedido_com_o_campo_manda_o_estado_completo(trilha):
    """Igual a `permissoes`: modulo omitido DENTRO do dicionario volta para
    `todos`. Delta produziria soma silenciosa entre dois administradores."""
    alvo = Usuario(id=5, role="usuario")
    req = router.ConcederRequest(permissoes=["gestao.ver"],
                                 escopos={"rm": "proprios"})
    db, resp = _conceder(Usuario(super_admin=True), alvo, req,
                         escopos=[("gestao", "proprios")])
    # ⚠️ A RESPOSTA TRAZ TODO RECURSO ESCOPAVEL, e nao so os do pedido — e e
    # exatamente esse o comportamento que este teste guarda. Por isso a lista
    # cresce quando um modulo escopavel novo entra (02/09/2026: `agendamentos`).
    # Derivar de ESCOPO_RECURSOS aqui faria o teste concordar consigo mesmo e
    # deixaria de acusar um modulo que sumisse da resposta.
    assert resp["escopos"] == {"gestao": "todos", "rm": "proprios",
                               "documentos": "todos", "agendamentos": "todos"}
    assert any("DELETE FROM user_escopos" in s for s in db.sql)
    assert any("INSERT INTO user_escopos" in s for s in db.sql)


# ===========================================================================
# 6. ⭐ A TRILHA (item F)
# ===========================================================================
def test_a_mudanca_de_alcance_vira_linha_na_trilha(trilha):
    alvo = Usuario(id=5, role="usuario", name="Maria")
    req = router.ConcederRequest(permissoes=[], escopos={"gestao": "proprios"})
    _conceder(Usuario(super_admin=True), alvo, req)

    assert len(trilha) == 1
    linha = trilha[0]
    assert linha["action"] == "usuarios.conceder"
    assert linha["target_type"] == "user" and linha["target_id"] == 5
    # Valor ANTES e DEPOIS, com o default explicito dos dois lados: sem isso o
    # auditor nao sabe DE ONDE a pessoa saiu.
    assert linha["valor_antes"]["escopos"]["gestao"] == "todos"
    assert linha["valor_depois"]["escopos"]["gestao"] == "proprios"
    assert linha["details"]["alcance_alterado"] == \
        ["Gestao Interna: Somente os que ele criou"]
    # Na MESMA transacao da gravacao: ou as duas entram, ou nenhuma.
    assert linha["commit"] is False


def test_a_trilha_registra_a_VOLTA_para_todos(trilha):
    """Soltar a restricao e conceder poder, e tem de aparecer com a mesma
    clareza de impo-la."""
    alvo = Usuario(id=5, role="usuario")
    req = router.ConcederRequest(permissoes=[], escopos={})
    _conceder(Usuario(super_admin=True), alvo, req,
              escopos=[("gestao", "proprios")])
    linha = trilha[0]
    assert linha["valor_antes"]["escopos"]["gestao"] == "proprios"
    assert linha["valor_depois"]["escopos"]["gestao"] == "todos"
    assert linha["details"]["alcance_alterado"] == \
        ["Gestao Interna: Todos os registros"]


def test_sem_mudanca_de_alcance_a_trilha_nao_inventa_alteracao(trilha):
    alvo = Usuario(id=5, role="usuario")
    req = router.ConcederRequest(permissoes=["gestao.ver"])
    _conceder(Usuario(super_admin=True), alvo, req)
    assert trilha[0]["details"]["alcance_alterado"] is None


def test_a_trilha_usa_registrar_critico():
    """Conceder poder nao pode acontecer em silencio: se a trilha falhar, a
    concessao inteira volta atras."""
    fonte = inspect.getsource(router.conceder)
    assert "registrar_critico(" in fonte
    assert "commit=False" in fonte


# ===========================================================================
# 7. O que as rotas de leitura devolvem
# ===========================================================================
def test_minhas_devolve_o_proprio_alcance():
    u = Usuario(id=7, role="usuario", escopos={"gestao": "proprios"})
    resp = asyncio.run(router.minhas(current=u))
    # Mesma razao do teste acima: a resposta traz TODO recurso escopavel com o
    # default explicito, entao a lista cresce quando um modulo novo entra
    # (02/09/2026: `agendamentos`).
    assert resp["escopos"] == {"gestao": "proprios", "rm": "todos",
                               "documentos": "todos", "agendamentos": "todos"}


def test_por_usuario_devolve_o_alcance_de_todo_mundo():
    db = FakeDb([
        _Res([(5, "gestao.ver")]),                    # user_permissoes
        _Res([(5, "gestao", "proprios"), (9, "xpto", "proprios")]),
    ])
    resp = asyncio.run(router.por_usuario(db=db, current=Usuario()))
    assert resp["concedidas"] == {"5": ["gestao.ver"]}
    # So quem TEM restricao aparece — ausencia e `todos`, a mesma convencao do
    # banco. E a linha orfa (`xpto`, modulo que saiu do catalogo) e descartada.
    assert resp["escopos"] == {"5": {"gestao": "proprios"}}


def test_o_alcance_nao_virou_permissao_do_catalogo():
    """`gestao.editar` responde "esta pessoa edita?"; o alcance responde "QUAIS".
    Junta-las dobraria o catalogo e criaria duas caixinhas que se contradizem.

    O total sobe quando uma permissao NOVA entra no catalogo (Incremento 7
    acrescentou `usuarios.modelos`; 08/2026, `vigencias.exportar`, para o botao
    Exportar do modal de Vigencias; 02/09/2026, as SEIS do modulo AGENDAMENTOS —
    `ver`, `criar`, `editar`, `excluir`, `exportar` e a especial
    `anexo_baixar`; 04/09/2026, UMA — `obrasgov.ver`, a tela de Obras Federais
    do grupo OBRAS do menu, que mostra o que o SISMOB e o SIMEC nao cobrem:
    mobilidade, saneamento, habitacao e a reconstrucao da Defesa Civil. Entrou
    SO com `ver`, e nao com `exportar`/`atualizar`, porque nao ha rota que essas
    duas governariam — a mesma razao ja escrita no InvestSUS).

    ⚠️ E em 05/09/2026 o modulo Telegram foi REMOVIDO e este numero NAO mudou —
    continua 76, e isso e o fato interessante. As duas chaves (`telegram.vincular`
    e `telegram.administrar`) viviam atras de `TELEGRAM_MODULE`, flag que nunca
    foi ligada em tenant nenhum: sem ela o catalogo ja era 76, com ela era 78.
    Enquanto viveram assim, este teste e os de permissao se contradiziam — SEM a
    flag a secao `telegram` ficava sem nenhuma caixinha embaixo (10 testes
    vermelhos), COM a flag este aqui quebrava em 78. Nao havia configuracao em
    que a suite passasse inteira. Catalogo condicional cobra esse preco: o
    proximo canal de avisos (WhatsApp, API oficial da Meta) entra sem flag.

    O que este teste guarda e a ausencia de caixinha de
    ALCANCE — `gestao.editar_proprios` e a forma que foi recusada.

    ⚠️ O NUMERO E TRIPWIRE, e nao a asserção que importa. Ele existe para que
    uma permissao entre no catalogo DE PROPOSITO: quem acrescenta uma chave
    passa por aqui e escreve por que. A guarda de verdade e a linha de baixo —
    nenhuma chave pode conter "propri", porque alcance de linha e outra coisa e
    junta-las criaria duas caixinhas que se contradizem."""
    # 05/09/2026: 76 -> 96. A divisao dos grupos FEDERAIS (1 chave -> 8 telas) e
    # ESTADUAIS (1 chave -> 10 telas) e as abas de Configuracoes que ganharam
    # chave (Telemetria, Parametros) explicam o salto; `usuarios.modelos` saiu
    # com os moldes. Ver o cabecalho de `services/permissoes.py`.
    #
    # 06/09/2026: 96 -> 97. `emendas_federais.ver` — a nona tela do grupo
    # FEDERAIS. E UMA chave e nao tres porque a tela so LE: nao ha rota de
    # exportacao nem de coleta sob demanda para `exportar`/`atualizar`
    # governarem, e permissao que nao governa nada e pior que permissao
    # faltando. `exportar` entra no MESMO PR que criar
    # `GET /api/export-pdf/emendas-federais`.
    #
    # 07/09/2026: 97 -> 98. `parcerias.ver` — a decima tela do grupo FEDERAIS,
    # e a fonte onde a emenda de saude do municipio passou a ser processada de
    # 2024 em diante (144 dos 176 programas do modulo sao Fundo a Fundo da
    # Saude). UMA chave, pela mesma razao ja escrita acima para
    # `emendas_federais.ver` e `obrasgov.ver`: a tela so LE. `exportar` entra
    # no MESMO PR que criar a rota de exportacao — nao antes.
    #
    # 07/09/2026: 98 -> 99. `faf_planos.ver` — o PLANO DE ACAO por tras do
    # repasse fundo a fundo. A tela de `fns` ja conta o dinheiro que entra;
    # esta conta o que o justifica, e a decomposicao que diz quanto daquele
    # repasse veio de emenda. UMA chave, pela mesma razao de sempre: so LE.
    assert len(permissoes.CATALOGO) == 99
    assert not any("propri" in c for c in permissoes.CATALOGO)
