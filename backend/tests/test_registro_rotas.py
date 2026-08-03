"""
⭐ O REGISTRO QUE FALHA FECHADO — a autorizacao deixa de ser OPT-IN.

Foi assim que 55 dos 171 endpoints ficaram abertos: autorizar era LEMBRAR, e
nada no sistema notava a ausencia. Este arquivo prova que agora o sistema nota.

O QUE ESTES TESTES PROTEGEM, em ordem de importancia:

  1. QUE A VARREDURA ENXERGUE AS ROTAS. E o teste mais importante e o menos
     obvio: a partir do FastAPI 0.141 `include_router` NAO copia mais as rotas
     para `app.routes` — guarda um `_IncludedRouter` que aponta para o router
     original. Uma varredura ingenua acha 4 rotas (as do /docs), conclui feliz
     que nao ha nada pendente e vira decoracao. Registro fail-closed que nao
     enxerga rota nenhuma e PIOR que registro nenhum: parece que funciona.

  2. QUE O MODO ESTRITO DERRUBE O BOOT em desenvolvimento. E o degrau que
     impede o problema de chegar em producao.

  3. QUE PRODUCAO NAO CAIA. Rota nova esquecida devolve 403 NAQUELA rota; o
     resto do sistema continua de pe.

Rodar:
    python -m pytest backend/tests/test_registro_rotas.py -v
"""
import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

import main
from services import authz, registro_rotas as registro
from services.auth import get_current_user
from services.registro_rotas import (Livre, RegistroIncompleto, declarado,
                                     exige, motivo_livre, varrer)


class Usuario:
    def __init__(self, permissoes=None, super_admin=False):
        self.id = 7
        self.email = "servidor@montesiao.mg.gov.br"
        self.name = "Servidor"
        self.role = "usuario"
        self.active = True
        self.kiosk = False
        self.super_admin = super_admin
        self.somente_leitura = False
        self.allowed_permissoes = permissoes
        self.allowed_telas = set()
        self.allowed_municipio_ids = set()


@pytest.fixture(autouse=True)
def _isolar(monkeypatch):
    authz.limpar_dedupe()
    authz.limpar_contexto()
    monkeypatch.delenv("AUTHZ_MODO", raising=False)
    monkeypatch.delenv("AUTHZ_REGISTRO", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    # Nenhuma linha de trilha sai para banco de verdade neste arquivo.
    monkeypatch.setattr(authz, "_enviar", lambda dados: True)
    yield
    authz.limpar_dedupe()
    authz.limpar_contexto()


def app_de_teste(rotas) -> FastAPI:
    """Monta um app com um router incluido — e nao rotas soltas no app — porque
    e assim que o PACTHA monta, e e justamente a inclusao que a varredura
    precisa saber atravessar."""
    router = APIRouter(prefix="/api/teste")
    for montar in rotas:
        montar(router)
    app = FastAPI(redirect_slashes=False)
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: Usuario({"rm.ver"})
    return app


# ===========================================================================
# 1. A varredura enxerga as rotas
# ===========================================================================
def test_varre_o_app_de_verdade_e_enxerga_todas_as_rotas():
    """⚠️ O teste que impede o registro de virar decoracao. O numero exato nao
    importa (o produto cresce); o que importa e que sejam DEZENAS, e nao as
    quatro rotas do /docs."""
    relatorio = varrer(main.app)
    assert len(relatorio.rotas) > 150
    caminhos = {r.caminho for r in relatorio.rotas}
    assert "/api/rm/{rid}" in caminhos          # veio de um router incluido
    assert "/api/health" in caminhos            # veio direto do app


def test_a_varredura_nao_conta_HEAD_nem_OPTIONS():
    """Gerados pelo framework a partir do GET; nao sao superficie propria e nao
    ha o que declarar neles."""
    assert {r.metodo for r in varrer(main.app).rotas} & {"HEAD", "OPTIONS"} == set()


def test_toda_rota_do_app_esta_em_exatamente_um_balde():
    relatorio = varrer(main.app)
    assert (len(relatorio.declaradas) + len(relatorio.livres)
            + len(relatorio.pendentes)) == len(relatorio.rotas)


# ===========================================================================
# 2. Declaracao
# ===========================================================================
def test_exige_declara_e_checa_com_o_mesmo_objeto():
    """As duas coisas com a mesma marca: nao ha como declarar e esquecer de
    checar, nem checar sem declarar."""
    def montar(router):
        @router.delete("/rm/{rid}", dependencies=[exige("rm.excluir")])
        async def remover(rid: int):
            return {"ok": True}

    app = app_de_teste([montar])
    relatorio = varrer(app)
    assert [r.permissoes for r in relatorio.rotas] == [("rm.excluir",)]
    assert relatorio.pendentes == []


def test_exige_barra_em_bloqueio_e_deixa_passar_em_aviso(monkeypatch):
    def montar(router):
        @router.delete("/rm/{rid}", dependencies=[exige("rm.excluir")])
        async def remover(rid: int):
            return {"ok": True}

    cliente = TestClient(app_de_teste([montar]))

    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    resposta = cliente.delete("/api/teste/rm/1")
    assert resposta.status_code == 403
    assert resposta.json()["detail"] == "Voce nao tem permissao para esta acao"

    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    assert cliente.delete("/api/teste/rm/1").status_code == 200


def test_exige_deixa_passar_quem_tem_a_permissao(monkeypatch):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")

    def montar(router):
        @router.get("/rm", dependencies=[exige("rm.ver")])
        async def listar():
            return []

    assert TestClient(app_de_teste([montar])).get("/api/teste/rm").status_code == 200


def test_exige_com_varias_permissoes_cobra_TODAS(monkeypatch):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")

    def montar(router):
        @router.get("/x", dependencies=[exige("rm.ver", "rm.exportar")])
        async def baixar():
            return []

    # O usuario de teste tem so `rm.ver`.
    assert TestClient(app_de_teste([montar])).get("/api/teste/x").status_code == 403


def test_exige_no_ROUTER_inteiro_tambem_e_enxergado():
    """A declaracao pode entrar por `dependencies=` da rota, do router ou do
    `include_router` — a varredura desce a arvore, nao le uma lista."""
    router = APIRouter(prefix="/api/teste", dependencies=[exige("rm.ver")])

    @router.get("/a")
    async def a():
        return []

    app = FastAPI()
    app.include_router(router)
    assert varrer(app).pendentes == []


def test_declarado_marca_sem_checar(monkeypatch):
    """Para o endpoint que decide a permissao no meio do corpo. A rota sai de
    "pendente" sem passar a checar nada aqui — por isso e a unica porta que
    confia em quem escreveu o endpoint."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")

    def montar(router):
        @router.get("/x", dependencies=[declarado("cofre.revelar")])
        async def x():
            return {"ok": True}

    app = app_de_teste([montar])
    assert varrer(app).pendentes == []
    assert TestClient(app).get("/api/teste/x").status_code == 200


@pytest.mark.parametrize("chave", ["rm.excluri", "rm", "", "nao.existe"])
def test_exige_com_chave_inexistente_morre_no_IMPORT(chave):
    """O melhor momento possivel para essa morte. Um typo passaria a varredura
    (a rota esta declarada!) e negaria todo mundo para sempre, inclusive o
    super-admin, sem nada no log dizendo o porque."""
    with pytest.raises(ValueError):
        exige(chave)


def test_exige_sem_argumento_nenhum_e_erro():
    with pytest.raises(ValueError):
        exige()


# ===========================================================================
# 3. A allowlist
# ===========================================================================
def test_a_allowlist_casa_por_IGUALDADE_e_nao_por_prefixo():
    """Precedente de `KIOSK_GET_PERMITIDOS`: com `startswith`, liberar
    `/api/bi/parlamentares/detalhe` abriria `/api/bi/parlamentares` de brinde."""
    assert motivo_livre("GET", "/api/health")
    assert motivo_livre("GET", "/api/health/interno") is None
    assert motivo_livre("GET", "/api/municipios")
    assert motivo_livre("GET", "/api/municipios/{municipio_id}/summary") is None


def test_a_allowlist_casa_por_METODO():
    """`GET /api/auth/me` e livre; um POST no mesmo caminho nao seria."""
    assert motivo_livre("GET", "/api/auth/me")
    assert motivo_livre("POST", "/api/auth/me") is None


def test_o_unico_prefixo_e_o_canal_de_control():
    prefixos = [livre for livre in registro.ROTAS_LIVRES
                if livre.caminho.endswith("/*")]
    assert [p.caminho for p in prefixos] == ["/api/control/*"]
    assert motivo_livre("POST", "/api/control/users")
    assert motivo_livre("GET", "/api/control/cofre/{item_id}/reveal")


def test_toda_linha_da_allowlist_tem_MOTIVO():
    """Allowlist sem motivo vira deposito, e um deposito de rotas livres e o
    buraco de novo — so que agora com aparencia de decisao."""
    for livre in registro.ROTAS_LIVRES:
        assert len(livre.motivo) > 30, livre.caminho


def test_a_allowlist_nao_tem_linha_MORTA():
    """Entrada que nao casa com rota nenhuma e lixo que ninguem vai conferir —
    e, pior, esconde um caminho que mudou de nome (a rota real voltou a ficar
    pendente e a linha continua ali, parecendo que cobre)."""
    relatorio = varrer(main.app)
    reais = {(r.metodo, r.caminho) for r in relatorio.rotas}
    orfas = [livre.caminho for livre in registro.ROTAS_LIVRES
             if not any(registro._casa(livre, metodo, caminho)
                        for metodo, caminho in reais)]
    assert orfas == []


def test_register_NAO_esta_na_allowlist():
    """⚠️ `POST /api/auth/register` cria usuario e ainda decide por
    `role == 'admin'`. Uma entrada `/api/auth/*` o levaria junto sem ninguem
    perceber — por isso as rotas de auth estao listadas UMA A UMA."""
    assert motivo_livre("POST", "/api/auth/register") is None


@pytest.mark.parametrize("metodo,caminho", [
    ("GET", "/api/cofre/{item_id}/reveal"),
    ("DELETE", "/api/rm/{rid}"),
    ("POST", "/api/users"),
    ("PATCH", "/api/users/{user_id}"),
    ("GET", "/api/auditoria/exportar"),
    ("GET", "/api/gestao/anotacoes/{anot_id}/anexo/{idx}"),
])
def test_as_rotas_sensiveis_nunca_sao_livres(metodo, caminho):
    """Trava contra alguem "resolver" um boot estrito acrescentando a rota que
    incomoda a allowlist em vez de declarar a permissao dela."""
    assert motivo_livre(metodo, caminho) is None


# ===========================================================================
# 4. Os modos
# ===========================================================================
def test_modo_default_acompanha_o_AUTHZ_MODO(monkeypatch):
    """Enquanto a trava geral esta em aviso, aqui tambem so se fala: no dia do
    deploy, 130 rotas ainda nao declaradas nao podem comecar a devolver 403 de
    uma vez."""
    assert registro.modo() == registro.MODO_AVISO
    monkeypatch.setenv("AUTHZ_MODO", "aviso")
    assert registro.modo() == registro.MODO_AVISO


def test_com_a_trava_ligada_desenvolvimento_e_ESTRITO(monkeypatch):
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    assert registro.modo() == registro.MODO_ESTRITO


def test_com_a_trava_ligada_producao_e_BLOQUEIO(monkeypatch):
    """⚠️ A decisao explicada no cabecalho do modulo: derrubar a API de uma
    prefeitura por causa de uma rota nova esquecida e trocar um risco por um
    dano garantido."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    monkeypatch.setenv("ENV", "production")
    assert registro.modo() == registro.MODO_BLOQUEIO


def test_AUTHZ_REGISTRO_vence_e_e_a_valvula_de_escape(monkeypatch):
    """Incidente as 9h: destravar a prefeitura tem de ser uma variavel de
    ambiente, nao um build de imagem."""
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTHZ_REGISTRO", "aviso")
    assert registro.modo() == registro.MODO_AVISO


def test_valor_desconhecido_nao_liga_nem_desliga_trava(monkeypatch):
    monkeypatch.setenv("AUTHZ_REGISTRO", "bloqueiop")
    assert registro.modo() == registro.MODO_AVISO
    monkeypatch.setenv("AUTHZ_MODO", "bloqueio")
    assert registro.modo() == registro.MODO_ESTRITO


# ===========================================================================
# 5. O que cada modo FAZ com uma rota pendente
# ===========================================================================
def _app_com_pendente():
    def montar(router):
        @router.get("/esquecida")
        async def esquecida():
            return {"ok": True}

    return app_de_teste([montar])


def test_estrito_derruba_o_boot(monkeypatch):
    monkeypatch.setenv("AUTHZ_REGISTRO", "estrito")
    with pytest.raises(RegistroIncompleto) as erro:
        registro.aplicar(_app_com_pendente())
    # A mensagem tem de dizer O QUE fazer: quem a le esta com o boot quebrado.
    assert "/api/teste/esquecida" in str(erro.value)
    assert "exige(" in str(erro.value)
    assert "ROTAS_LIVRES" in str(erro.value)
    assert "AUTHZ_REGISTRO=aviso" in str(erro.value)


def test_estrito_nao_derruba_quando_esta_tudo_declarado(monkeypatch):
    monkeypatch.setenv("AUTHZ_REGISTRO", "estrito")

    def montar(router):
        @router.get("/ok", dependencies=[exige("rm.ver")])
        async def ok():
            return {"ok": True}

    assert registro.aplicar(app_de_teste([montar])).pendentes == []


def test_aviso_sobe_e_nao_bloqueia_nada(monkeypatch):
    """A transicao: o incremento sobe com 130 rotas ainda nao declaradas e NADA
    pode mudar de comportamento por causa disso."""
    monkeypatch.setenv("AUTHZ_REGISTRO", "aviso")
    app = _app_com_pendente()
    assert len(registro.aplicar(app).pendentes) == 1
    assert TestClient(app).get("/api/teste/esquecida").status_code == 200


def test_bloqueio_sobe_e_devolve_403_SO_na_rota_pendente(monkeypatch):
    """⭐ O comportamento de producao. O estrago fica do tamanho do erro."""
    monkeypatch.setenv("AUTHZ_REGISTRO", "bloqueio")

    def montar(router):
        @router.get("/esquecida")
        async def esquecida():
            return {"ok": True}

        @router.get("/declarada", dependencies=[exige("rm.ver")])
        async def declarada():
            return {"ok": True}

    app = app_de_teste([montar])
    registro.aplicar(app)
    cliente = TestClient(app)

    barrada = cliente.get("/api/teste/esquecida")
    assert barrada.status_code == 403
    assert barrada.json()["detail"] == registro.MENSAGEM_BLOQUEIO
    # E o resto do sistema continua de pe.
    assert cliente.get("/api/teste/declarada").status_code == 200


def test_o_403_do_bloqueio_nao_depende_de_estar_logado(monkeypatch):
    """A negativa entra como PRIMEIRA dependencia: nao abre sessao de banco, nao
    carrega usuario, nao vira 401. E defeito de programacao, nao de cadastro —
    nao ha permissao a conceder que resolva."""
    monkeypatch.setenv("AUTHZ_REGISTRO", "bloqueio")

    router = APIRouter(prefix="/api/teste")

    @router.get("/esquecida")
    async def esquecida(usuario=Depends(get_current_user)):
        return {"ok": True}

    app = FastAPI()
    app.include_router(router)

    def _explode():
        raise HTTPException(status_code=401, detail="Nao autenticado")

    app.dependency_overrides[get_current_user] = _explode
    registro.aplicar(app)
    assert TestClient(app).get("/api/teste/esquecida").status_code == 403


def test_aplicar_nao_bloqueia_a_rota_LIVRE(monkeypatch):
    monkeypatch.setenv("AUTHZ_REGISTRO", "bloqueio")

    livres = registro.ROTAS_LIVRES + (
        Livre("GET", "/api/teste/publica", "Motivo de teste, longo o bastante "
              "para passar pela regra de motivo obrigatorio."),)
    monkeypatch.setattr(registro, "ROTAS_LIVRES", livres)

    def montar(router):
        @router.get("/publica")
        async def publica():
            return {"ok": True}

    app = app_de_teste([montar])
    registro.aplicar(app)
    assert TestClient(app).get("/api/teste/publica").status_code == 200


def test_aplicar_no_app_de_verdade_nao_levanta_no_modo_de_hoje():
    """O incremento sobe HOJE, com as rotas ainda nao declaradas. Se este teste
    quebrar, o deploy quebra junto."""
    relatorio = registro.aplicar(main.app)
    assert len(relatorio.rotas) > 150
