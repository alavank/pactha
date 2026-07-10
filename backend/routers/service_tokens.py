"""
Gerenciamento de Service Tokens (admin only).

Tokens sao mostrados em claro APENAS uma vez - na criacao.
Depois disso so o hash fica no banco.
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
from models.service_token import ServiceToken
from services.auth import get_current_user
from services.service_auth import hash_token
from services.audit import log_event

router = APIRouter(prefix="/api/admin/service-tokens", tags=["admin"])


SUPER_ADMIN_EMAIL = "admin@pactha.com.br"


def _require_admin(user: User):
    # Service Tokens sao credenciais longevas poderosas -> so o admin principal.
    if (user.email or "").lower() != SUPER_ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Acesso restrito ao administrador principal")


class CreateTokenRequest(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    scopes: List[str]  # ex: ["secret:read:fns"]
    description: Optional[str] = None
    expires_at: Optional[datetime] = None


class TokenInfo(BaseModel):
    id: int
    name: str
    token_prefix: Optional[str]
    scopes: List[str]
    description: Optional[str]
    active: bool
    last_used_at: Optional[datetime]
    last_used_ip: Optional[str]
    expires_at: Optional[datetime]
    created_at: Optional[datetime]


@router.get("", response_model=List[TokenInfo])
async def list_tokens(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_admin(user)
    res = await db.execute(select(ServiceToken).order_by(ServiceToken.created_at.desc()))
    return [
        TokenInfo(
            id=t.id, name=t.name, token_prefix=t.token_prefix,
            scopes=t.scopes or [], description=t.description, active=t.active,
            last_used_at=t.last_used_at, last_used_ip=t.last_used_ip,
            expires_at=t.expires_at, created_at=t.created_at,
        ) for t in res.scalars().all()
    ]


@router.post("")
async def create_token(
    req: CreateTokenRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_admin(user)

    # Verifica nome unico
    exists = await db.execute(select(ServiceToken).where(ServiceToken.name == req.name))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Nome ja em uso")

    # Gera token raw com prefixo identificavel
    raw = "pactha_st_" + pysecrets.token_urlsafe(40)
    th = hash_token(raw)
    prefix = raw[:12]

    token = ServiceToken(
        name=req.name,
        token_hash=th,
        token_prefix=prefix,
        scopes=req.scopes,
        description=req.description,
        active=True,
        expires_at=req.expires_at,
        created_by_user_id=user.id,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)

    await log_event(
        db, action="service_token.create", user=user, request=request,
        target_type="service_token", target_id=token.id,
        details={"name": token.name, "scopes": token.scopes},
    )

    # Retorna em claro APENAS UMA VEZ
    return {
        "id": token.id,
        "name": token.name,
        "token": raw,  # MOSTRA SO AGORA
        "scopes": token.scopes,
        "warning": "Anote esse token. Ele NAO sera mostrado novamente.",
    }


@router.post("/{token_id}/revoke")
async def revoke_token(
    token_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_admin(user)
    token = await db.get(ServiceToken, token_id)
    if not token:
        raise HTTPException(status_code=404, detail="Token nao encontrado")
    token.active = False
    await db.commit()
    await log_event(
        db, action="service_token.revoke", user=user, request=request,
        target_type="service_token", target_id=token_id,
        details={"name": token.name},
    )
    return {"status": "revoked"}


@router.post("/{token_id}/rotate")
async def rotate_token(
    token_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Gera novo token raw para o mesmo registro (mantem scopes/nome).
    Retorna o token novo APENAS uma vez."""
    _require_admin(user)
    token = await db.get(ServiceToken, token_id)
    if not token:
        raise HTTPException(status_code=404, detail="Token nao encontrado")

    raw = "pactha_st_" + pysecrets.token_urlsafe(40)
    token.token_hash = hash_token(raw)
    token.token_prefix = raw[:12]
    token.active = True
    token.last_used_at = None
    token.last_used_ip = None
    await db.commit()

    await log_event(
        db, action="service_token.rotate", user=user, request=request,
        target_type="service_token", target_id=token.id,
        details={"name": token.name},
    )
    return {
        "id": token.id, "name": token.name, "token": raw,
        "warning": "Token rotacionado. Atualize o scraper IMEDIATAMENTE."
    }
