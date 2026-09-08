"""O servidor MCP de leitura: autenticação, escopo e as ferramentas.

⚠️ POR QUE ESTE ARQUIVO. O MCP entrega dado de município a um assistente de IA
externo. O que o protege é sempre a MESMA coisa em três lugares: o token é um
usuário (não uma chave-mestra), o escopo é a interseção (nunca a escolha do
pedido), e toda ferramenta começa pelo choke point. Cada teste aqui trava uma
dessas — se um cair, é acesso a mais, não a menos.

Não há Postgres no teste (ver CLAUDE.md); então aqui se prova a LÓGICA de auth e
escopo. A comparação de um número com a TELA é feita em produção, com um token
real, e está registrada no relatório do PR — é o único elo que exige dado vivo.
"""
import asyncio
import types
from pathlib import Path

from services.mcp_auth import (
    escopo_municipios, verificar_token, identidade_do_contexto,
    definir_usuario, limpar_usuario, MCPNaoAutenticado)
import mcp_app as M


def _user(**kw):
    """Um User de mentira só com o que auth/escopo leem."""
    base = dict(id=1, email="a@b.c", active=True, super_admin=False,
                allowed_municipio_ids={10, 20, 30})
    base.update(kw)
    return types.SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# §3 — escopo_municipios: interseção, nunca escolha
# ---------------------------------------------------------------------------
def test_escopo_sem_pedido_devolve_o_conjunto():
    assert escopo_municipios(_user(), None) == [10, 20, 30]


def test_escopo_pedido_dentro_devolve_so_ele():
    assert escopo_municipios(_user(), 20) == [20]


def test_escopo_pedido_FORA_devolve_VAZIO_nao_erro_nao_tudo():
    # O coração do §3: um id fora do escopo NÃO vira erro e NÃO vira "todos".
    assert escopo_municipios(_user(), 999) == []


def test_escopo_pedido_malformado_fecha():
    assert escopo_municipios(_user(), "abc") == []
    assert escopo_municipios(_user(), None) == [10, 20, 30]  # "" tratado como sem pedido


def test_escopo_super_admin_sem_pedido_e_todos():
    # allowed_municipio_ids None = super-admin = None (sem filtro).
    assert escopo_municipios(_user(allowed_municipio_ids=None), None) is None


def test_escopo_super_admin_com_pedido_e_so_ele():
    assert escopo_municipios(_user(allowed_municipio_ids=None), 7) == [7]


def test_escopo_conjunto_vazio_nao_e_todos():
    # Quem não tem município não vira super-admin: sem pedido → [], não None.
    assert escopo_municipios(_user(allowed_municipio_ids=set()), None) == []


# ---------------------------------------------------------------------------
# §1 — verificar_token: falha FECHADO em toda falha, None idêntico
# ---------------------------------------------------------------------------
class _Res:
    def __init__(self, obj): self._obj = obj
    def scalar_one_or_none(self): return self._obj


class _FakeDB:
    """DB de mentira: devolve resultados na ordem em que verificar_token pergunta
    (1º o token, 2º o user). commit/rollback são no-op."""
    def __init__(self, *resultados): self._q = list(resultados)
    async def execute(self, *a, **k): return _Res(self._q.pop(0) if self._q else None)
    async def commit(self): pass
    async def rollback(self): pass


def _tok(**kw):
    base = dict(user_id=1, active=True, revoked_at=None, last_used_at=None)
    base.update(kw); return types.SimpleNamespace(**base)


def test_verificar_token_curto_ou_vazio_nega():
    assert asyncio.run(verificar_token(_FakeDB(), "")) is None
    assert asyncio.run(verificar_token(_FakeDB(), "curto")) is None


def test_verificar_token_desconhecido_nega():
    db = _FakeDB(None)  # hash não achou nada
    assert asyncio.run(verificar_token(db, "x" * 40)) is None


def test_verificar_token_revogado_nega():
    from datetime import datetime, timezone
    db = _FakeDB(_tok(active=False), )
    assert asyncio.run(verificar_token(db, "x" * 40)) is None
    db = _FakeDB(_tok(revoked_at=datetime.now(timezone.utc)))
    assert asyncio.run(verificar_token(db, "x" * 40)) is None


def test_verificar_token_dono_inativo_nega():
    db = _FakeDB(_tok(), _user(active=False))
    assert asyncio.run(verificar_token(db, "x" * 40)) is None


def test_verificar_token_ok_devolve_user_com_escopo_superadmin():
    # Super-admin: load_user_scopes retorna cedo (não consulta o banco).
    u = _user(super_admin=True)
    db = _FakeDB(_tok(), u)
    got = asyncio.run(verificar_token(db, "x" * 40))
    assert got is u
    assert got.allowed_municipio_ids is None  # anexado por load_user_scopes


# ---------------------------------------------------------------------------
# §2 — identidade_do_contexto: o choke point
# ---------------------------------------------------------------------------
def test_identidade_le_do_contextvar_quando_o_gate_ja_verificou():
    u = _user()
    tok = definir_usuario(u)
    try:
        ctx = types.SimpleNamespace(headers={})  # sem header — vem do contextvar
        assert asyncio.run(identidade_do_contexto(ctx)) is u
    finally:
        limpar_usuario(tok)


def test_identidade_sem_nada_lanca():
    ctx = types.SimpleNamespace(headers={})
    try:
        asyncio.run(identidade_do_contexto(ctx))
        assert False, "devia ter lançado"
    except MCPNaoAutenticado:
        pass


def test_identidade_fallback_pelo_header(monkeypatch):
    u = _user()
    async def _fake_verif(db, raw):
        return u if raw == "boa" else None
    monkeypatch.setattr("services.mcp_auth.verificar_token", _fake_verif)
    ctx = types.SimpleNamespace(headers={"authorization": "Bearer boa"})
    assert asyncio.run(identidade_do_contexto(ctx)) is u
    ctx_ruim = types.SimpleNamespace(headers={"authorization": "Bearer ruim"})
    try:
        asyncio.run(identidade_do_contexto(ctx_ruim)); assert False
    except MCPNaoAutenticado:
        pass


# ---------------------------------------------------------------------------
# Ferramentas — roteamento de escopo (§3) e formatação (§4), via _um_municipio
# ---------------------------------------------------------------------------
def test_um_municipio_dentro_do_escopo():
    mid, err = asyncio.run(M._um_municipio(_user(), 20))
    assert mid == 20 and err is None


def test_um_municipio_fora_do_escopo_e_mensagem_nao_id():
    mid, err = asyncio.run(M._um_municipio(_user(), 999))
    assert mid is None and "Nenhum município" in err


def test_um_municipio_unico_sem_pedido_usa_ele():
    mid, err = asyncio.run(M._um_municipio(_user(allowed_municipio_ids={42}), None))
    assert mid == 42 and err is None


def test_um_municipio_varios_sem_pedido_pede_id():
    mid, err = asyncio.run(M._um_municipio(_user(), None))
    assert mid is None and "municipio_id" in err


def test_formatacao_reais_pt_br():
    assert M._reais(1234567.89) == "R$ 1.234.567,89"
    assert M._reais(0) == "R$ 0,00"
    assert M._reais(None) == "R$ 0,00"


# ---------------------------------------------------------------------------
# Guarda estrutural: TODA ferramenta começa pelo choke point (§2)
# ---------------------------------------------------------------------------
def test_toda_ferramenta_chama_o_choke_point():
    """Se uma ferramenta esquecer `identidade_do_contexto`, ela roda sem saber de
    quem é o dado — o vazamento que o choke point existe para impedir. Varre a
    fonte: cada corpo de @mcp_server.tool tem de citar a função."""
    src = (Path(M.__file__)).read_text(encoding="utf-8")
    import re
    corpos = re.split(r"@mcp_server\.tool\(", src)[1:]
    assert corpos, "nenhuma ferramenta encontrada — o teste está cego"
    for corpo in corpos:
        # corta no próximo decorator/def de topo para isolar a ferramenta
        corpo = re.split(r"\n@mcp_server\.tool\(|\nmcp_starlette =", corpo)[0]
        assert "identidade_do_contexto" in corpo, (
            "uma ferramenta MCP não chama identidade_do_contexto — "
            "roda sem escopo")


# ---------------------------------------------------------------------------
# §7 — sem token → 401 no gate HTTP, antes de qualquer protocolo MCP
# ---------------------------------------------------------------------------
def test_gate_sem_token_responde_401():
    scope = {"type": "http", "method": "POST", "path": "/", "headers": []}
    sent = []
    async def receive(): return {"type": "http.request", "body": b"", "more_body": False}
    async def send(msg): sent.append(msg)
    asyncio.run(M.mcp_asgi(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 401
    # WWW-Authenticate presente, e nada revela QUAL foi a falha (token ausente,
    # revogado ou dono inativo respondem igual — §1).
    hdrs = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    assert "www-authenticate" in hdrs


def test_gate_bearer_invalido_tambem_401():
    # Bearer curto: rejeitado pela guarda de tamanho (len<32) SEM tocar o banco.
    scope = {"type": "http", "method": "POST", "path": "/",
             "headers": [(b"authorization", b"Bearer curto")]}
    sent = []
    async def receive(): return {"type": "http.request", "body": b"", "more_body": False}
    async def send(msg): sent.append(msg)
    asyncio.run(M.mcp_asgi(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 401
