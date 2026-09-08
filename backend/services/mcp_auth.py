"""Autenticação e escopo do servidor MCP — o token é o usuário.

Três responsabilidades, cada uma num ponto único de propósito:

  1. `verificar_token`  — token raw → `User` com escopo anexado, ou `None`.
     Devolve `None` em TODA falha (token desconhecido, revogado, dono inativo,
     escopo ilegível): quem chama responde a mesma coisa para as três e não
     revela qual foi — §1 do desenho.

  2. `identidade_do_contexto` — o CHOKE POINT (§2). É o ÚNICO lugar que lê a
     autenticação do contexto MCP. Toda ferramenta começa por ele e recebe o
     `User`; nenhuma ferramenta lê o header por conta própria. Lança quando não
     há identidade — rodar sem saber de quem é o dado não pode ser possível.

  3. `escopo_municipios` — o filtro de município (§3): interseção, nunca escolha.
     Toda consulta que toca dado escapado passa por ele; qualquer fallback aqui é
     VAZIO, nunca o parâmetro cru (o cru é o que ainda não foi checado).

⚠️ NADA AQUI ESCREVE DADO DO CLIENTE. A única escrita é `last_used_at` na própria
linha do token — metadado da credencial, não dado do município. O contrato do
servidor é leitura.
"""
from __future__ import annotations

import contextvars
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from database import async_session
from models.mcp_token import McpToken
from models.user import User
from services.auth import load_user_scopes
from services.service_auth import hash_token  # SHA-256 hex — reusado, não reinventado

log = logging.getLogger("mcp_auth")


class MCPNaoAutenticado(Exception):
    """Não há token válido no contexto. O servidor MCP traduz em erro de auth."""


# ⭐ O DONO VERIFICADO DA REQUISIÇÃO ATUAL. O gate ASGI de `/api/mcp`
# (`mcp_app._AuthMCP`) verifica o Bearer UMA vez e guarda o `User` aqui; o choke
# point `identidade_do_contexto` lê daqui. Contextvar (não global) porque cada
# requisição tem o seu, e uma não pode enxergar o dono da outra.
_usuario_atual: contextvars.ContextVar = contextvars.ContextVar(
    "mcp_usuario_atual", default=None)


def definir_usuario(user):
    """Fixa o dono verificado no contexto da requisição. Devolve o token de
    reset, que o gate DEVE passar a `limpar_usuario` no finally."""
    return _usuario_atual.set(user)


def limpar_usuario(token) -> None:
    try:
        _usuario_atual.reset(token)
    except Exception:
        pass


async def verificar_token(db, raw_token: str) -> Optional[User]:
    """Token raw → `User` com escopo anexado (`load_user_scopes`), ou `None`.

    ⚠️ FALHA FECHADO SEMPRE. Qualquer problema — token curto, hash desconhecido,
    `active=false`, revogado, dono inexistente/inativo, escopo ilegível, erro de
    I/O — vira `None`, e o chamador responde 401 idêntico para todos. Nunca cai
    em "sem restrição": um registro quebrado não pode virar acesso total.
    """
    try:
        if not raw_token or len(raw_token) < 32:
            return None
        th = hash_token(raw_token)
        row = (await db.execute(
            select(McpToken).where(McpToken.token_hash == th))).scalar_one_or_none()
        # Um token desativado ou revogado é indistinguível de um desconhecido, de
        # propósito (§1).
        if row is None or not row.active or row.revoked_at is not None:
            return None
        user = (await db.execute(
            select(User).where(User.id == row.user_id))).scalar_one_or_none()
        # Dono inativo/apagado = token morto na hora. Desabilitar alguém não pode
        # deixar o acesso de IA vivo.
        if user is None or not user.active:
            return None
        # Anexa allowed_municipio_ids / allowed_telas / allowed_permissoes. É
        # fail-closed por dentro (permissões vazias em erro, nunca None).
        await load_user_scopes(db, user)
        # Cinto extra: escopo de município que não seja None (super-admin) nem um
        # conjunto é dado corrompido → fecha, não abre.
        amid = getattr(user, "allowed_municipio_ids", set())
        if amid is not None and not isinstance(amid, (set, frozenset)):
            log.warning("escopo de município ilegível p/ user %s — negando", row.user_id)
            return None
        # Marca de último uso. Não crítico: se falhar, não derruba a verificação.
        try:
            row.last_used_at = datetime.now(timezone.utc)
            await db.commit()
        except Exception:
            await db.rollback()
        return user
    except Exception:
        log.warning("verificar_token falhou — negando (fail-closed)", exc_info=True)
        return None


async def identidade_do_contexto(ctx) -> User:
    """O CHOKE POINT (§2): extrai o dono a partir do contexto MCP e o devolve com
    escopo. É o único lugar que lê a autenticação; toda ferramenta começa aqui.

    Lança `MCPNaoAutenticado` quando não há identidade — uma ferramenta rodando
    sem saber de quem é o dado não pode existir.

    Lê primeiro o dono que o gate ASGI já verificou (contextvar); só cai para a
    verificação pelo header do próprio contexto se o contextvar não tiver
    propagado (cinto extra) — nunca abre sem um dos dois.
    """
    u = _usuario_atual.get()
    if u is not None:
        return u
    headers = getattr(ctx, "headers", None) or {}
    # `ctx.headers` é um Mapping[str, str] do transporte HTTP. Tolerante a
    # capitalização porque nem todo transporte normaliza.
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    raw = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
    if not raw:
        raise MCPNaoAutenticado(
            "Falta a credencial. Envie 'Authorization: Bearer <token do PACTHA>'.")
    async with async_session() as db:
        user = await verificar_token(db, raw)
    if user is None:
        raise MCPNaoAutenticado(
            "Token inválido, revogado ou de uma conta desativada.")
    return user


def escopo_municipios(user: User, municipio_pedido=None) -> Optional[list[int]]:
    """(escopo do dono, município pedido) → o filtro de município (§3).

      - sem pedido            → tudo que o escopo permite
                                (`None` = super-admin = todos os municípios)
      - pedido DENTRO do escopo → só ele  → `[id]`
      - pedido FORA do escopo   → `[]`  (lista vazia — NÃO erro, NÃO todos)

    ⚠️ TODA consulta com dado escapado passa por aqui. E todo fallback devolve
    VAZIO (`[]`), nunca o `municipio_pedido` cru — o cru é exatamente o valor que
    ainda não foi checado contra o escopo.

    Retorno: `None` significa "todos os municípios" e só acontece para o
    super-admin sem pedido específico; a ferramenta trata `None` como "sem
    filtro de município". `[]` significa "nada" e a ferramenta responde
    "nada para este filtro".
    """
    try:
        allowed = getattr(user, "allowed_municipio_ids", set())  # None = super-admin
        if municipio_pedido is not None and municipio_pedido != "":
            try:
                rid = int(municipio_pedido)
            except (TypeError, ValueError):
                return []  # pedido malformado → fechado
            if allowed is None or rid in allowed:
                return [rid]
            return []  # fora do escopo → vazio
        # sem pedido específico:
        if allowed is None:
            return None  # super-admin → todos (sem filtro de município)
        return sorted(allowed)
    except Exception:
        log.warning("escopo_municipios falhou — devolvendo vazio", exc_info=True)
        return []
