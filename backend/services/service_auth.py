"""
Autenticacao para Service Tokens (scrapers/workers).
Token enviado em header X-Service-Token.
"""
import hashlib
from datetime import datetime, timezone
from typing import Optional

from fastapi import Header, HTTPException, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.service_token import ServiceToken
from database import get_db


def hash_token(raw_token: str) -> str:
    """SHA-256 hex do token raw. Usado p/ guardar no DB e comparar."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


async def get_service_token(
    request: Request,
    x_service_token: Optional[str] = Header(None, alias="X-Service-Token"),
    db: AsyncSession = Depends(get_db),
) -> ServiceToken:
    """Valida X-Service-Token e retorna o ServiceToken correspondente."""
    if not x_service_token:
        raise HTTPException(status_code=401, detail="X-Service-Token obrigatorio")

    if len(x_service_token) < 32:
        raise HTTPException(status_code=401, detail="Token invalido")

    th = hash_token(x_service_token)
    result = await db.execute(select(ServiceToken).where(ServiceToken.token_hash == th))
    token = result.scalar_one_or_none()

    if not token or not token.active:
        raise HTTPException(status_code=401, detail="Token invalido ou revogado")

    # Simetria com control_auth: um control token apresentado como X-Service-Token
    # e rejeitado (defense-in-depth — "vazamento de um nao escala ao outro").
    if (getattr(token, "kind", "scraper") or "scraper") != "scraper":
        raise HTTPException(status_code=401, detail="Token invalido")

    if token.expires_at and token.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Token expirado")

    # Atualiza ultimo uso
    token.last_used_at = datetime.now(timezone.utc)
    if request.client:
        token.last_used_ip = request.client.host
    await db.commit()
    return token


def require_scope(token: ServiceToken, scope: str):
    """Verifica se o token tem o scope necessario."""
    scopes = token.scopes or []
    if scope in scopes or "*" in scopes:
        return True
    # wildcard parcial: "secret:read:*" cobre "secret:read:fns"
    for s in scopes:
        if s.endswith(":*") and scope.startswith(s[:-1]):
            return True
    raise HTTPException(status_code=403, detail=f"Token sem scope necessario: {scope}")
