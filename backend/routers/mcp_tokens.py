"""Gerência dos MCP Tokens — a credencial de LEITURA que a pessoa dá a um
assistente de IA (Claude, ChatGPT) para consultar os dados dela pela API MCP.

Quem pode agir (§6 do desenho):
  - CADA pessoa administra os SEUS tokens (criar, listar, revogar) — como trocar
    a própria senha, não exige permissão de tela.
  - Um ADMINISTRADOR (dono da plataforma, ou quem tem a tela «Usuários», que é
    onde a permissão já é decidida) administra os de QUALQUER pessoa. Criar
    credencial de máquina no nome de alguém é ato de administrador, mesmo onde
    conceder permissão é delegado.

⚠️ O valor em claro sai UMA vez, na criação. Não há rota que o devolva de novo —
é isso que faz dele segredo. Revogar NÃO apaga a linha (ela é o registro de que
o acesso existiu). Não se cria token para conta desativada.

⚠️ ESTAS ROTAS ESTÃO EM `services/registro_rotas.py::ROTAS_LIVRES` (auto-
escapadas): a resposta é sobre o PRÓPRIO usuário e o gate de "em nome de outro"
é resolvido no corpo (`_pode_gerir_outros`). Mexeu no gate daqui, reveja lá.
"""
import secrets as pysecrets
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field

from database import get_db
from models.user import User
from models.mcp_token import McpToken
from services.auth import get_current_user, is_super_admin
from services.service_auth import hash_token          # SHA-256 hex, reusado
from services.audit import log_event

router = APIRouter(prefix="/api/mcp-tokens", tags=["mcp"])


def _pode_gerir_outros(user: User) -> bool:
    """Pode criar/listar/revogar token DE OUTRA pessoa? Dono da plataforma, ou
    quem tem a tela «Usuários» — o mesmo portão que já administra as pessoas."""
    if is_super_admin(user):
        return True
    telas = getattr(user, "allowed_telas", None)
    return telas is None or "usuarios" in telas


async def _resolver_alvo(db: AsyncSession, atual: User, user_id: Optional[int]) -> User:
    """De QUEM é o token. Sem `user_id` (ou o próprio) = você. Outro exige poder
    gerir outros. O alvo tem de existir e estar ATIVO — não se cria credencial
    para conta desativada (nasceria morta na verificação, e a tela deve dizer
    por quê em vez de entregar um token inútil)."""
    if user_id is None or user_id == atual.id:
        alvo = atual
    else:
        if not _pode_gerir_outros(atual):
            raise HTTPException(403, "Só um administrador cria token em nome de outra pessoa.")
        alvo = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if alvo is None:
            raise HTTPException(404, "Usuário não encontrado.")
    if not alvo.active:
        raise HTTPException(400, "A conta está desativada — um token dela nasceria morto.")
    return alvo


class CriarTokenReq(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    # Dono do token. Ausente = você mesmo. Preencher exige ser administrador.
    user_id: Optional[int] = None


class McpTokenInfo(BaseModel):
    id: int
    name: str
    token_prefix: Optional[str]
    active: bool
    last_used_at: Optional[datetime]
    created_at: Optional[datetime]
    revoked_at: Optional[datetime]
    user_id: int


@router.get("", response_model=List[McpTokenInfo])
async def listar(
    user_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    atual: User = Depends(get_current_user),
):
    if user_id is not None and user_id != atual.id and not _pode_gerir_outros(atual):
        raise HTTPException(403, "Você só pode ver os seus tokens.")
    alvo_id = user_id if user_id is not None else atual.id
    rows = (await db.execute(
        select(McpToken).where(McpToken.user_id == alvo_id)
        .order_by(McpToken.created_at.desc()))).scalars().all()
    return [McpTokenInfo(
        id=t.id, name=t.name, token_prefix=t.token_prefix, active=t.active,
        last_used_at=t.last_used_at, created_at=t.created_at,
        revoked_at=t.revoked_at, user_id=t.user_id) for t in rows]


@router.post("")
async def criar(
    req: CriarTokenReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
    atual: User = Depends(get_current_user),
):
    alvo = await _resolver_alvo(db, atual, req.user_id)
    # 256 bits de aleatório, com prefixo identificável. Não é senha humana → o
    # hash é SHA-256 (ver services/service_auth.hash_token), não bcrypt.
    raw = "pactha_mcp_" + pysecrets.token_urlsafe(40)
    tok = McpToken(
        user_id=alvo.id, name=req.name.strip(),
        token_prefix=raw[:16], token_hash=hash_token(raw), active=True)
    db.add(tok)
    await db.commit()
    await db.refresh(tok)
    await log_event(
        db, action="mcp_token.create", user=atual, request=request,
        target_type="mcp_token", target_id=tok.id,
        details={"name": tok.name, "owner_id": alvo.id})
    # Em claro APENAS AGORA.
    return {
        "id": tok.id, "name": tok.name, "user_id": alvo.id,
        "token": raw,
        "aviso": "Anote este token agora. Ele NÃO será mostrado de novo.",
    }


@router.post("/{token_id}/revoke")
async def revogar(
    token_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    atual: User = Depends(get_current_user),
):
    tok = await db.get(McpToken, token_id)
    if tok is None:
        raise HTTPException(404, "Token não encontrado.")
    if tok.user_id != atual.id and not _pode_gerir_outros(atual):
        raise HTTPException(403, "Você só pode revogar os seus tokens.")
    if tok.active:
        tok.active = False
        tok.revoked_at = datetime.now(timezone.utc)
        await db.commit()
    await log_event(
        db, action="mcp_token.revoke", user=atual, request=request,
        target_type="mcp_token", target_id=token_id,
        details={"name": tok.name, "owner_id": tok.user_id})
    return {"status": "revoked"}
