"""⭐ O MOLDE: aplicar e COPIAR, e o anti-escalonamento vale aqui tambem.

A REGRA DO DONO que rege este incremento inteiro:

    "as permissoes sao colocadas no usuario da pessoa, INDIVIDUALMENTE. Grupo e
     so ROTULO. Nao da pra limitar dentro de uma prefeitura que todos os
     analistas terao o mesmo acesso, isso e besteira."

Os testes que mais importam neste arquivo, por ordem de estrago se quebrarem:

  1. `test_aplicar_nao_grava_nada` — se `aplicar` gravasse, o administrador
     perderia o ajuste antes do Salvar e o clique por engano ja estaria
     commitado. E existiria uma SEGUNDA porta para escrever permissao, com uma
     segunda copia das quatro guardas.
  2. `test_o_molde_nao_concede_o_que_quem_aplica_nao_tem` — o molde seria a
     porta dos fundos do anti-escalonamento.
  3. `test_o_que_esta_fora_do_meu_alcance_e_PRESERVADO` — aplicar um molde nao
     pode ser o jeito de um administrador sem acesso ao Cofre DESLIGAR o acesso
     de quem tem.
  4. `test_substituir_e_o_default` — somar por engano CONCEDE em silencio.

Rodar:
    python -m pytest backend/tests/test_modelos_permissao.py -v
"""
import asyncio
import inspect

import pytest
from fastapi import HTTPException

from routers import modelos_permissao as router
from routers import permissoes as router_conceder
from services import permissoes


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
    def __init__(self, valor=None, linhas=None):
        self._valor = valor
        self._linhas = linhas

    def fetchall(self):
        return self._linhas or []

    def first(self):
        return self._valor

    def scalar(self):
        return self._valor

    def scalar_one_or_none(self):
        return self._valor


class FakeDb:
    """Fila de respostas, na ordem das consultas.

    `por_trecho` responde por CONTEUDO do SQL em vez de por posicao: quando a
    consulta que interessa vem depois de um numero variavel de escritas (o
    `_modelo_declarado`, no fim do `conceder`), contar posicoes faz o teste
    passar por acidente ou falhar por motivo errado."""

    def __init__(self, respostas=(), por_trecho=None):
        self.respostas = list(respostas)
        self.por_trecho = dict(por_trecho or {})
        self.sql: list = []
        self.params: list = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        texto = " ".join(str(stmt).split())
        self.sql.append(texto)
        self.params.append(params)
        for trecho, resposta in self.por_trecho.items():
            if trecho in texto:
                return resposta
        return self.respostas.pop(0) if self.respostas else _Res(None)

    async def commit(self):
        self.commits += 1


@pytest.fixture
def trilha(monkeypatch):
    linhas: list = []

    async def _falso(db, **kw):
        linhas.append(kw)

    monkeypatch.setattr(router, "registrar_critico", _falso)
    return linhas


@pytest.fixture
def trilha_conceder(monkeypatch):
    linhas: list = []

    async def _falso(db, **kw):
        linhas.append(kw)

    monkeypatch.setattr(router_conceder, "registrar_critico", _falso)
    return linhas


# Linha de `_SELECT_MODELO`: id, nome, descricao, criado_em, criado_por,
# atualizado_em, atualizado_por, autor.name, editor.name
def _linha_modelo(id=7, nome="Cofre e convenios", descricao="d"):
    return (id, nome, descricao, None, 3, None, None, "Autor", None)


def _respostas_carregar(chaves=(), escopos=(), linha=None):
    return [
        _Res(linha or _linha_modelo()),
        _Res(linhas=[(c,) for c in chaves]),
        _Res(linhas=list(escopos)),
    ]


# ===========================================================================
# 1. ⭐⭐ A FUNCAO PURA — aplicar e COPIAR, e a copia respeita o teto de quem aplica
# ===========================================================================
def test_substituir_troca_o_conjunto_inteiro():
    conta = permissoes.aplicar_modelo(
        do_modelo=["rm.ver", "rm.editar"],
        do_alvo=["gestao.ver", "rm.ver"],
        pode_conceder=permissoes.TODAS)
    assert conta["permissoes"] == ["rm.editar", "rm.ver"]
    assert conta["vai_conceder"] == ["rm.editar"]
    assert conta["vai_retirar"] == ["gestao.ver"]


def test_somar_nao_desmarca_nada():
    conta = permissoes.aplicar_modelo(
        do_modelo=["rm.ver"], do_alvo=["gestao.ver"],
        pode_conceder=permissoes.TODAS, modo="somar")
    assert conta["permissoes"] == ["gestao.ver", "rm.ver"]
    assert conta["vai_retirar"] == []


def test_substituir_e_o_default():
    """⚠️ A decisao do item (B), e ela e sobre quem clica no molde POR ENGANO
    num usuario ja configurado.

    Somar por engano CONCEDE em silencio: as caixinhas ja marcadas continuam
    marcadas, as do molde aparecem marcadas junto, e nada distingue uma da
    outra. Substituir por engano TIRA — e isso e VISIVEL na tela, antes de
    salvar, e Cancelar desfaz. O campo omitido nao pode ser o mais permissivo."""
    assert permissoes.normalizar_modo_aplicacao(None) == permissoes.MODO_SUBSTITUIR
    assert permissoes.normalizar_modo_aplicacao("") == permissoes.MODO_SUBSTITUIR
    assert permissoes.normalizar_modo_aplicacao("SOMAR") == permissoes.MODO_SOMAR
    # Valor torto NAO pode virar `somar` por acidente.
    assert permissoes.normalizar_modo_aplicacao("somarr") == \
        permissoes.MODO_SUBSTITUIR
    assert router.AplicarRequest(user_id=1).modo is None


def test_o_molde_nao_concede_o_que_quem_aplica_nao_tem():
    """⭐ O item (C), na funcao pura. Um molde com `cofre.revelar` aplicado por
    quem nao tem `cofre.revelar` NAO pode dar essa chave — senao o molde seria a
    porta dos fundos do anti-escalonamento da tela de Usuarios."""
    conta = permissoes.aplicar_modelo(
        do_modelo=["cofre.ver", "cofre.revelar"],
        do_alvo=[],
        pode_conceder=["cofre.ver"])
    assert conta["permissoes"] == ["cofre.ver"]
    # E a tela TEM de dizer isso: molde aplicado pela metade em silencio faria o
    # administrador jurar que concedeu o que nao concedeu.
    assert conta["nao_aplicadas"] == ["cofre.revelar"]


def test_o_que_esta_fora_do_meu_alcance_e_PRESERVADO():
    """⭐ A trava vale nos DOIS sentidos. Aplicar um molde nao pode ser o jeito
    de um administrador sem acesso ao Cofre DESLIGAR o acesso de quem tem — a
    mesma acao que `_barrar_escalonamento` recusa caixinha a caixinha."""
    conta = permissoes.aplicar_modelo(
        do_modelo=["rm.ver"],
        do_alvo=["cofre.revelar", "gestao.ver"],
        pode_conceder=["rm.ver", "gestao.ver"])
    assert "cofre.revelar" in conta["permissoes"]
    assert conta["preservadas"] == ["cofre.revelar"]
    assert conta["vai_retirar"] == ["gestao.ver"]


def test_chave_fora_do_catalogo_e_descartada_em_silencio():
    """Molde antigo com chave que saiu do catalogo nao pode virar erro na cara
    do administrador — a mesma regra da funcao pura de resolucao."""
    conta = permissoes.aplicar_modelo(
        do_modelo=["rm.ver", "xpto.voar"], do_alvo=[],
        pode_conceder=permissoes.TODAS)
    assert conta["permissoes"] == ["rm.ver"]


def test_o_alcance_do_molde_substitui_dentro_do_que_eu_alcanco():
    conta = permissoes.aplicar_modelo_escopos(
        do_modelo={"gestao": "proprios"},
        do_alvo={"rm": "proprios"},
        pode_definir=["gestao", "rm", "documentos"])
    assert conta["escopos"] == {"gestao": "proprios"}
    assert sorted(conta["alterados"]) == ["gestao", "rm"]


def test_o_alcance_de_modulo_fora_do_meu_nao_e_tocado():
    conta = permissoes.aplicar_modelo_escopos(
        do_modelo={"gestao": "proprios", "rm": "proprios"},
        do_alvo={"documentos": "proprios"},
        pode_definir=["gestao"])
    assert conta["escopos"] == {"gestao": "proprios", "documentos": "proprios"}
    # `documentos` aparece junto de `rm` de proposito: em `substituir` o molde
    # diz «todos» para todo modulo que ele nao restringe, e essa intencao
    # tambem nao foi aplicada — a pessoa continua restrita em Documentos. A tela
    # precisa dizer as duas coisas, senao o administrador acha que soltou o que
    # nao soltou.
    assert conta["nao_aplicados"] == ["documentos", "rm"]


def test_somar_NAO_mexe_no_alcance():
    """⚠️ Alcance e um RADIO, e nao existe soma de dois radios. Qualquer regra
    inventada aqui ("o mais restritivo vence") seria uma regra que ninguem
    consegue prever olhando a tela."""
    conta = permissoes.aplicar_modelo_escopos(
        do_modelo={"gestao": "proprios"}, do_alvo={"rm": "proprios"},
        pode_definir=["gestao", "rm"], modo="somar")
    assert conta["escopos"] == {"rm": "proprios"}
    assert conta["alterados"] == []
    assert conta["nao_aplicados"] == ["gestao"]


def test_so_o_que_restringe_sai_da_funcao_pura():
    """Ha um unico jeito de dizer "sem restricao" no banco, e e a ausencia."""
    conta = permissoes.aplicar_modelo_escopos(
        do_modelo={"gestao": "todos"}, do_alvo={"gestao": "proprios"},
        pode_definir=["gestao"])
    assert conta["escopos"] == {}


# ===========================================================================
# 2. O vocabulario servido pela API (o frontend nao reescreve nada)
# ===========================================================================
def test_o_catalogo_traz_o_vocabulario_do_molde():
    cat = permissoes.catalogo_para_api()
    assert cat["modelos"]["default"] == "substituir"
    assert [m["valor"] for m in cat["modelos"]["modos"]] == ["substituir", "somar"]


def test_o_catalogo_traz_a_frase_que_a_tela_e_OBRIGADA_a_mostrar():
    """"APLICAR = COPIAR, e a tela tem de DIZER isso." Sem a frase, o
    administrador acha que e vinculo e vai editar o modelo esperando corrigir a
    pessoa — e nao vai corrigir nada."""
    aviso = permissoes.catalogo_para_api()["modelos"]["aviso"]
    assert "COPIA" in aviso
    assert "editáveis" in aviso.lower()
    assert "não mexe mais" in aviso.lower()


def test_a_caixinha_de_gerenciar_modelos_existe_e_e_de_escrita():
    ficha = permissoes.CATALOGO["usuarios.modelos"]
    assert ficha.secao == "usuarios"
    # POST/PUT/DELETE: o guard de somente-leitura barra. Marcar FALSE aqui
    # desenharia um botao que devolve 403.
    assert ficha.escrita is True


# ===========================================================================
# 3. ⭐ O CRUD — as guardas e a trilha
# ===========================================================================
def _criar(current, req, nome_ocupado=None):
    db = FakeDb([_Res(nome_ocupado), _Res(7)])
    return db, asyncio.run(router.criar(req=req, request=None, db=db,
                                        current=current))


def test_criar_grava_conteudo_e_alcance(trilha):
    req = router.ModeloRequest(nome="  Analista  do   setor ",
                               descricao="teste",
                               permissoes=["rm.ver", "rm.editar"],
                               escopos={"rm": "proprios"})
    db, resp = _criar(Usuario(super_admin=True), req)
    assert resp["nome"] == "Analista do setor"      # espaco colapsado
    assert resp["permissoes"] == ["rm.editar", "rm.ver"]
    assert resp["escopos"]["rm"] == "proprios"
    assert any("INSERT INTO modelo_permissoes" in s for s in db.sql)
    assert any("INSERT INTO modelo_escopos" in s for s in db.sql)
    assert db.commits == 1


def test_escrever_molde_SEM_a_caixinha_e_403_mesmo_em_modo_aviso(monkeypatch):
    """⚠️ A caixinha `usuarios.modelos` NEGA SEMPRE, e o teste existe porque a
    forma obvia de escreve-la nao funcionava.

    O `exige("usuarios.modelos")` do decorador DECLARA a rota, mas com
    `AUTHZ_MODO=aviso` — o default, e o que esta valendo em Monte Siao durante a
    semana de observacao — ele so REGISTRA e deixa passar. Sem `_exigir_gerir`,
    qualquer `role='admin'` escrevia molde apesar de o proprio servidor responder
    `pode_gerenciar: false` na listagem e de a tela esconder os botoes por causa
    dessa resposta: o servidor ficava mais frouxo do que ele mesmo dizia ser.

    Mesmo argumento de `_barrar_escalonamento`: escrever molde e funcao NOVA,
    nao ha comportamento antigo a preservar, e uma trava que so avisa e a
    ausencia da trava."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    sem_a_chave = Usuario(permissoes_=["usuarios.conceder", "rm.ver"])
    req = router.ModeloRequest(nome="Feito sem a caixinha", permissoes=["rm.ver"])

    for chamada in (
        lambda: _criar(sem_a_chave, req),
        lambda: _editar(sem_a_chave, 7, req, chaves=["rm.ver"]),
        lambda: _apagar(sem_a_chave, chaves=["rm.ver"]),
    ):
        with pytest.raises(HTTPException) as e:
            chamada()
        assert e.value.status_code == 403
        assert "Gerenciar modelos" in e.value.detail


def test_APLICAR_continua_liberado_para_quem_so_concede(monkeypatch):
    """⚠️ A trava de cima fecha a RECEITA, e nao o uso dela. Fechar os dois
    mataria a funcao para exatamente quem ela existe para ajudar: o motivo do
    incremento e operacional (cadastrar servidor virou marcar 66 caixas), e
    aplicar nao concede poder nenhum — continua limitado ao que quem aplica
    tem."""
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    so_concede = Usuario(permissoes_=["usuarios.conceder", "rm.ver"])
    alvo = Usuario(id=5, role="usuario")
    _, resp = _aplicar(so_concede, alvo, router.AplicarRequest(user_id=5),
                       do_modelo=["rm.ver"])
    assert resp["permissoes"] == ["rm.ver"]
    assert resp["gravado"] is False


def test_a_listagem_e_o_servidor_dao_a_MESMA_resposta_sobre_quem_pode_gerir():
    """A tela desenha os botoes a partir de `pode_gerenciar`. Se a rota de
    escrita aceitasse quem a listagem diz que nao pode, a divergencia so
    apareceria para quem chamasse a API por fora da tela — que e justamente
    quem nao deveria passar."""
    assert inspect.getsource(router.criar).count("_exigir_gerir") == 1
    assert inspect.getsource(router.editar).count("_exigir_gerir") == 1
    assert inspect.getsource(router.apagar).count("_exigir_gerir") == 1
    # A listagem responde pela MESMA funcao que a trava usa.
    assert 'authz.pode(current, "usuarios.modelos")' in inspect.getsource(router.listar)


def test_criar_sem_nome_e_400():
    with pytest.raises(HTTPException) as e:
        _criar(Usuario(super_admin=True),
               router.ModeloRequest(nome="   ", permissoes=[]))
    assert e.value.status_code == 400


def test_nome_repetido_e_409_mesmo_com_caixa_diferente():
    """O molde e escolhido PELO NOME: "Cofre" e "cofre" lado a lado fariam o
    administrador aplicar um achando que era o outro."""
    with pytest.raises(HTTPException) as e:
        _criar(Usuario(super_admin=True),
               router.ModeloRequest(nome="cofre", permissoes=[]),
               nome_ocupado=(3,))
    assert e.value.status_code == 409


def test_permissao_inexistente_no_molde_e_400():
    """400 e nao 403: nao e permissao que falta, e pedido malformado. A FK
    tambem recusaria, mas ali o erro sairia como 500 sem dizer qual chave."""
    with pytest.raises(HTTPException) as e:
        _criar(Usuario(super_admin=True),
               router.ModeloRequest(nome="X", permissoes=["rm.voar"]))
    assert e.value.status_code == 400
    assert "rm.voar" in e.value.detail


def test_criar_molde_com_o_que_eu_nao_tenho_e_403():
    """⭐ Item (C) no CRUD. Sem esta trava, um administrador escreveria um molde
    com `cofre.revelar` que ele nao tem — e o proximo administrador, que TEM,
    aplicaria confiando no nome do molde."""
    limitado = Usuario(permissoes_=["rm.ver", "usuarios.modelos"])
    with pytest.raises(HTTPException) as e:
        _criar(limitado, router.ModeloRequest(
            nome="X", permissoes=["rm.ver", "cofre.revelar"]))
    assert e.value.status_code == 403
    assert "porta dos fundos" in e.value.detail
    assert "Revelar a senha" in e.value.detail


def test_criar_molde_com_alcance_de_modulo_que_eu_nao_alcanco_e_403():
    # ⚠️ `usuarios.modelos` entra na lista de proposito: sem ela o 403 viria de
    # `_exigir_gerir` e este teste passaria sem nunca exercitar a trava de
    # ALCANCE, que e a que ele existe para provar.
    restrito = Usuario(permissoes_=["gestao.ver", "usuarios.modelos"],
                       escopos={"gestao": "proprios"})
    with pytest.raises(HTTPException) as e:
        _criar(restrito, router.ModeloRequest(
            nome="X", permissoes=["gestao.ver"], escopos={"gestao": "proprios"}))
    assert e.value.status_code == 403
    assert "alcance" in e.value.detail


def test_criar_vira_linha_na_trilha(trilha):
    req = router.ModeloRequest(nome="Cofre", permissoes=["cofre.ver"])
    _criar(Usuario(super_admin=True), req)
    linha = trilha[0]
    assert linha["action"] == "modelo_permissao.criar"
    assert linha["target_type"] == "modelo_permissao"
    assert linha["alvo_nome"] == "Cofre"
    assert linha["valor_depois"]["permissoes"] == ["cofre.ver"]
    # Na MESMA transacao da gravacao: ou as duas entram, ou nenhuma.
    assert linha["commit"] is False


def _editar(current, modelo_id, req, chaves=(), escopos=(), nome_ocupado=None):
    db = FakeDb(_respostas_carregar(chaves, escopos) + [_Res(nome_ocupado)])
    return db, asyncio.run(router.editar(modelo_id=modelo_id, req=req,
                                         request=None, db=db, current=current))


def test_editar_troca_o_conteudo_inteiro(trilha):
    req = router.ModeloRequest(nome="Cofre e convenios",
                               permissoes=["cofre.ver", "cofre.criar"])
    db, resp = _editar(Usuario(super_admin=True), 7, req, chaves=["cofre.ver"])
    assert resp["permissoes"] == ["cofre.criar", "cofre.ver"]
    assert any("UPDATE modelos_permissao" in s for s in db.sql)
    assert trilha[0]["details"]["acrescentadas"] == ["cofre.criar"]


def test_editar_sem_o_campo_de_alcance_nao_apaga_o_alcance(trilha):
    """Mesma assimetria de `ConcederRequest`: campo AUSENTE e "nao mexi", e nao
    "sem restricao". Um cliente que ainda nao conheca o campo nao pode zerar o
    alcance do molde ao salvar so as caixinhas."""
    req = router.ModeloRequest(nome="Op", permissoes=["gestao.ver"])
    assert req.escopos is None
    db, resp = _editar(Usuario(super_admin=True), 7, req,
                       chaves=["gestao.ver"], escopos=[("gestao", "proprios")])
    assert resp["escopos"]["gestao"] == "proprios"


def test_editar_avisa_na_trilha_que_NAO_muda_quem_ja_recebeu(trilha):
    """⭐ A consequencia da regra do dono, escrita onde o auditor a le: alterar o
    molde nao corrige ninguem — aplicar COPIOU as caixinhas naquele instante."""
    _editar(Usuario(super_admin=True), 7,
            router.ModeloRequest(nome="X", permissoes=[]))
    assert "NÃO altera quem já o recebeu" in trilha[0]["details"]["efeito"]


def test_editar_modelo_inexistente_e_404():
    db = FakeDb([_Res(None)])
    with pytest.raises(HTTPException) as e:
        asyncio.run(router.editar(modelo_id=9, req=router.ModeloRequest(
            nome="X", permissoes=[]), request=None, db=db,
            current=Usuario(super_admin=True)))
    assert e.value.status_code == 404


def test_editar_nao_deixa_TIRAR_o_que_eu_nao_tenho():
    """A simetria e deliberada: quem nao alcanca o Cofre nao decide o que os
    moldes do Cofre fazem — nem para pôr, nem para tirar."""
    limitado = Usuario(permissoes_=["rm.ver", "usuarios.modelos"])
    with pytest.raises(HTTPException) as e:
        _editar(limitado, 7, router.ModeloRequest(nome="X", permissoes=["rm.ver"]),
                chaves=["rm.ver", "cofre.revelar"])
    assert e.value.status_code == 403


def _apagar(current, chaves=(), escopos=(), linha=None):
    db = FakeDb(_respostas_carregar(chaves, escopos, linha))
    return db, asyncio.run(router.apagar(modelo_id=7, request=None, db=db,
                                         current=current))


def test_apagar_remove_o_molde_e_avisa_que_ninguem_perde_acesso(trilha):
    """⭐ A prova mais limpa de que o molde nao e grupo: as permissoes que ele
    copiou continuam nos cadastros das pessoas."""
    db, resp = _apagar(Usuario(super_admin=True), chaves=["cofre.ver"])
    assert resp["apagado"] is True
    assert any("DELETE FROM modelos_permissao" in s for s in db.sql)
    linha = trilha[0]
    assert linha["action"] == "modelo_permissao.excluir"
    # O conteudo apagado e o unico lugar onde ele ainda existe depois do commit.
    assert linha["valor_antes"]["permissoes"] == ["cofre.ver"]
    assert "Ninguém perde acesso" in linha["details"]["efeito"]


def test_apagar_molde_com_chave_fora_do_meu_alcance_e_403():
    """Apagar e retirar o molde inteiro. Sem esta trava, um administrador sem
    acesso ao Cofre derrubaria o molde do Cofre — a mesma acao que a trava
    recusa quando ele tenta esvazia-lo caixinha a caixinha."""
    limitado = Usuario(permissoes_=["rm.ver", "usuarios.modelos"])
    with pytest.raises(HTTPException) as e:
        _apagar(limitado, chaves=["cofre.revelar"])
    assert e.value.status_code == 403


# ===========================================================================
# 4. ⭐⭐ APLICAR — calcula, e NAO grava
# ===========================================================================
def _aplicar(current, alvo, req, do_modelo=(), escopos_modelo=(),
             do_alvo=(), escopos_alvo=()):
    db = FakeDb(
        _respostas_carregar(do_modelo, escopos_modelo)
        + [_Res(alvo),
           _Res(linhas=[(c,) for c in do_alvo]),
           _Res(linhas=list(escopos_alvo))]
    )
    return db, asyncio.run(router.aplicar(modelo_id=7, req=req, db=db,
                                          current=current))


def test_aplicar_nao_grava_nada():
    """⭐⭐ O TESTE MAIS IMPORTANTE DESTE ARQUIVO.

    Se `aplicar` gravasse, (1) o administrador perderia o ajuste antes do Salvar
    que o dono pediu, e o clique por engano ja estaria commitado; e (2) o
    sistema teria uma SEGUNDA porta para escrever permissao, com uma segunda
    copia do anti-escalonamento, do `_guard_target`, da trilha e da transacao."""
    alvo = Usuario(id=5, role="usuario")
    db, resp = _aplicar(Usuario(super_admin=True), alvo,
                        router.AplicarRequest(user_id=5),
                        do_modelo=["rm.ver"])
    escritas = [s for s in db.sql
                if any(v in s for v in ("INSERT", "UPDATE", "DELETE"))]
    assert escritas == []
    assert db.commits == 0
    assert resp["gravado"] is False


def test_aplicar_devolve_as_caixinhas_que_a_tela_deve_marcar():
    alvo = Usuario(id=5, role="usuario")
    _, resp = _aplicar(Usuario(super_admin=True), alvo,
                       router.AplicarRequest(user_id=5),
                       do_modelo=["rm.ver", "rm.editar"],
                       do_alvo=["gestao.ver"])
    assert resp["permissoes"] == ["rm.editar", "rm.ver"]
    assert resp["atuais"] == ["gestao.ver"]
    assert resp["vai_retirar"] == ["gestao.ver"]
    assert resp["modo"] == "substituir"


def test_aplicar_traz_o_alcance_completo_com_o_default_explicito():
    alvo = Usuario(id=5, role="usuario")
    _, resp = _aplicar(Usuario(super_admin=True), alvo,
                       router.AplicarRequest(user_id=5),
                       escopos_modelo=[("gestao", "proprios")])
    assert set(resp["escopos"]) == set(permissoes.ESCOPO_RECURSOS)
    assert resp["escopos"]["gestao"] == "proprios"
    assert resp["escopos"]["rm"] == "todos"
    assert resp["alcance_alterado"] == ["Gestao Interna: Somente os que ele criou"]


def test_aplicar_respeita_o_anti_escalonamento_no_SERVIDOR():
    """⭐ Item (C): "Trate no SERVIDOR, nao so na tela." A tela nao pode nem
    PROPOR a caixinha que o `PUT` vai recusar — o administrador salvaria, levaria
    403 e nao entenderia o que fez de errado."""
    limitado = Usuario(permissoes_=["usuarios.conceder", "cofre.ver"])
    alvo = Usuario(id=5, role="usuario")
    _, resp = _aplicar(limitado, alvo, router.AplicarRequest(user_id=5),
                       do_modelo=["cofre.ver", "cofre.revelar"])
    assert resp["permissoes"] == ["cofre.ver"]
    assert resp["nao_aplicadas"] == ["cofre.revelar"]


def test_aplicar_preserva_o_que_o_aplicador_nao_alcanca():
    limitado = Usuario(permissoes_=["usuarios.conceder", "rm.ver"])
    alvo = Usuario(id=5, role="usuario")
    _, resp = _aplicar(limitado, alvo, router.AplicarRequest(user_id=5),
                       do_modelo=["rm.ver"], do_alvo=["cofre.revelar"])
    assert "cofre.revelar" in resp["permissoes"]
    assert resp["preservadas"] == ["cofre.revelar"]


def test_aplicar_devolve_a_frase_de_que_e_COPIA():
    alvo = Usuario(id=5, role="usuario")
    _, resp = _aplicar(Usuario(super_admin=True), alvo,
                       router.AplicarRequest(user_id=5))
    assert "COPIA" in resp["aviso"]


def test_aplicar_em_usuario_inexistente_e_404():
    db = FakeDb(_respostas_carregar() + [_Res(None)])
    with pytest.raises(HTTPException) as e:
        asyncio.run(router.aplicar(modelo_id=7,
                                   req=router.AplicarRequest(user_id=99),
                                   db=db, current=Usuario(super_admin=True)))
    assert e.value.status_code == 404


def test_aplicar_em_conta_de_dono_da_plataforma_e_barrado():
    """`_guard_target` importado de routers/users.py, e nao reescrito: a
    resposta e o retrato das permissoes de outra pessoa."""
    dono = Usuario(id=2, role="admin", super_admin=True)
    db = FakeDb(_respostas_carregar() + [_Res(dono)])
    with pytest.raises(HTTPException) as e:
        asyncio.run(router.aplicar(
            modelo_id=7, req=router.AplicarRequest(user_id=2), db=db,
            current=Usuario(permissoes_=["usuarios.conceder"])))
    assert e.value.status_code == 403


# ===========================================================================
# 5. ⭐ A TRILHA da APLICACAO (item F) — no Salvar, que e onde ela tem efeito
# ===========================================================================
def _conceder(current, alvo, req, concedidas=(), escopos=(), modelo=None):
    db = FakeDb(
        [
            _Res(alvo),                               # select(User)
            _Res(linhas=[(c,) for c in concedidas]),  # _concedidas
            _Res(linhas=list(escopos)),               # _escopos_atuais
        ],
        # `_modelo_declarado` roda no FIM, depois de um numero variavel de
        # INSERTs/DELETEs — por isso responde por conteudo, e nao por posicao.
        por_trecho={"FROM modelos_permissao": _Res(modelo)},
    )
    return db, asyncio.run(router_conceder.conceder(
        user_id=alvo.id, req=req, request=None, db=db, current=current))


def test_o_salvar_sem_modelo_nao_inventa_linha_de_aplicacao(trilha_conceder):
    alvo = Usuario(id=5, role="usuario")
    req = router_conceder.ConcederRequest(permissoes=["rm.ver"])
    _conceder(Usuario(super_admin=True), alvo, req)
    assert [l["action"] for l in trilha_conceder] == ["usuarios.conceder"]


def test_o_salvar_com_modelo_vira_DUAS_linhas(trilha_conceder):
    """⭐ Item (F). Sao duas porque respondem duas perguntas diferentes:

      `usuarios.conceder`        o que esta pessoa passou a poder (medido:
                                 valor-antes/valor-depois)
      `modelo_permissao.aplicar` ONDE este molde foi aplicado — pergunta de
                                 REVISAO DE ACESSO ("quem recebeu o molde do
                                 Cofre neste semestre?"), que filtrar a primeira
                                 nao responde.

    E o mesmo motivo pelo qual `usuarios.conceder` foi separada de
    `user.update`. As duas entram na MESMA transacao."""
    alvo = Usuario(id=5, role="usuario", name="Maria")
    req = router_conceder.ConcederRequest(
        permissoes=["rm.ver"], modelo_id=7, modelo_modo="somar")
    _conceder(Usuario(super_admin=True), alvo, req, modelo=("Cofre e convenios",))

    assert [l["action"] for l in trilha_conceder] == [
        "usuarios.conceder", "modelo_permissao.aplicar"]
    conceder, aplicar = trilha_conceder
    # O nome do molde vem do BANCO — o cliente so declara um id.
    assert conceder["details"]["modelo_aplicado"]["nome"] == "Cofre e convenios"
    assert aplicar["details"]["modelo"]["modo"] == "somar"
    # O alvo e a PESSOA: e por ela que o auditor filtra.
    assert aplicar["target_type"] == "user" and aplicar["target_id"] == 5
    assert all(l["commit"] is False for l in trilha_conceder)


def test_modelo_apagado_entre_aplicar_e_salvar_NAO_derruba_o_salvar(trilha_conceder):
    """⚠️ A concessao e completa e autoritativa sozinha. Recusar a gravacao
    porque um RÓTULO sumiu seria o rabo abanando o cachorro: o administrador
    perderia o trabalho por causa de um campo que existe so para a trilha."""
    alvo = Usuario(id=5, role="usuario")
    req = router_conceder.ConcederRequest(permissoes=["rm.ver"], modelo_id=99)
    _, resp = _conceder(Usuario(super_admin=True), alvo, req, modelo=None)
    assert resp["permissoes"] == ["rm.ver"]
    assert resp["modelo_aplicado"]["nome"] is None
    assert "não existe mais" in resp["modelo_aplicado"]["observacao"]


def test_o_modelo_declarado_NAO_e_tratado_como_promessa_de_igualdade():
    """O servidor nao confere se as caixinhas salvas batem com as do molde — e
    elas NAO devem bater: o dono pediu que ficassem editaveis. A autoridade da
    trilha continua sendo o valor-antes/valor-depois, que e MEDIDO."""
    fonte = inspect.getsource(router_conceder.conceder)
    assert "modelo_aplicado" in fonte
    # Nenhuma comparacao entre o conjunto salvo e o conteudo do molde.
    assert "modelo_permissoes" not in fonte


# ===========================================================================
# 6. ⭐ O molde nao virou grupo — nem no codigo
# ===========================================================================
def test_nao_existe_vinculo_persistente_entre_usuario_e_modelo():
    """A regra do dono. Procure por uma escrita que ligue os dois: nao ha, e a
    ausencia e a feature. Se um dia aparecer um `user_modelos`, "o que esta
    pessoa pode?" deixa de ter resposta olhando a pessoa."""
    fonte = inspect.getsource(router)
    assert "user_modelos" not in fonte
    assert "modelo_usuarios" not in fonte
    # O `aplicar` nao escreve em `user_permissoes` nem em `user_escopos`: quem
    # grava e o PUT de `routers/permissoes.py`.
    assert "INSERT INTO user_permissoes" not in fonte
    assert "INSERT INTO user_escopos" not in fonte


def test_as_guardas_sao_importadas_e_nao_reescritas():
    """Uma segunda implementacao de regra de permissao e como as copias
    divergem — e a divergencia nao aparece na tela, aparece no acesso de
    alguem."""
    assert router._barrar_escalonamento is router_conceder._barrar_escalonamento
    assert router._validar is router_conceder._validar
    assert router._validar_escopos is router_conceder._validar_escopos
    from routers.users import _guard_target, _require_admin
    assert router._guard_target is _guard_target
    assert router._require_admin is _require_admin


# ===========================================================================
# ⭐ O ESTADO DA TELA — por que o endpoint aceita, e por que isso e seguro
# ===========================================================================
# O modal e EDITAVEL antes de aplicar: o administrador abre as permissoes de
# alguem, mexe em duas caixinhas e so entao escolhe um molde. Calculando so
# contra o banco, a conta ignoraria essas duas caixinhas e a tela mostraria "a
# marcar 7" quando sao 5 — numero errado na cara de quem esta decidindo.
#
# Aceitar isso do cliente NAO abre brecha, e a razao e estrutural: esta rota nao
# grava. Quem grava e o `PUT`, e la o anti-escalonamento compara contra o BANCO.
# Um cliente que mentisse aqui receberia um plano que o PUT recusa com 403.
def test_aplicar_usa_o_estado_da_TELA_quando_ele_vem():
    alvo = Usuario(id=5, role="usuario")
    db, resp = _aplicar(
        Usuario(super_admin=True), alvo,
        router.AplicarRequest(user_id=5, estado_atual=["cofre.ver"]),
        do_modelo=["rm.ver"],
        do_alvo=["gestao.ver"],   # o que esta GRAVADO, e que deve ser ignorado
    )
    assert resp["atuais"] == ["cofre.ver"], "usou o banco em vez da tela"
    assert "gestao.ver" not in resp["atuais"]


def test_com_o_estado_da_tela_o_banco_nem_e_consultado():
    """Nao e so o resultado: a consulta nao deve nem sair. Ler e descartar
    gastaria uma ida ao banco por tecla — o modal recalcula a cada respiro."""
    db, _ = _aplicar(
        Usuario(super_admin=True), Usuario(id=5, role="usuario"),
        router.AplicarRequest(user_id=5, estado_atual=[], escopos_atual={}),
        do_modelo=["rm.ver"],
    )
    assert not any("user_permissoes" in s for s in db.sql)
    assert not any("user_escopos" in s for s in db.sql)


def test_lista_VAZIA_nao_e_o_mesmo_que_campo_ausente():
    """⚠️ A assimetria que a `ConcederRequest` ja tinha. `[]` e um estado
    legitimo — "esta pessoa nao tem nada marcado" — e nao pode virar "nao
    opinei", que mandaria o servidor ler o cadastro gravado e devolver um plano
    contra um estado que a tela nao esta mostrando."""
    _, vazio = _aplicar(
        Usuario(super_admin=True), Usuario(id=5, role="usuario"),
        router.AplicarRequest(user_id=5, estado_atual=[]),
        do_modelo=["rm.ver"], do_alvo=["gestao.ver"])
    assert vazio["atuais"] == []

    _, ausente = _aplicar(
        Usuario(super_admin=True), Usuario(id=5, role="usuario"),
        router.AplicarRequest(user_id=5),
        do_modelo=["rm.ver"], do_alvo=["gestao.ver"])
    assert ausente["atuais"] == ["gestao.ver"]


def test_o_estado_da_tela_passa_pela_MESMA_validacao_de_chave():
    """Chave inventada vinda da tela e 400, e nao um plano calculado sobre
    lixo: e a mesma `_validar` que o `PUT` usa."""
    with pytest.raises(HTTPException) as e:
        _aplicar(Usuario(super_admin=True), Usuario(id=5, role="usuario"),
                 router.AplicarRequest(user_id=5,
                                       estado_atual=["cofre.revellar"]),
                 do_modelo=["rm.ver"])
    assert e.value.status_code == 400
