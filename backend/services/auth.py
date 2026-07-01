"""
Autenticacao JWT (pyjwt) + bcrypt.
Suporta access + refresh tokens com JTI para revogacao.

Cookies httpOnly:
- access_token (TTL curto, ex: 60min)
- refresh_token (TTL maior, ex: 30 dias)
"""
import os
import uuid
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt as pyjwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from models.user import User
from database import get_db
from config import get_settings

settings = get_settings()
security = HTTPBearer(auto_error=False)

REFRESH_TTL_DAYS = int(os.getenv("REFRESH_TTL_DAYS", "30"))
COOKIE_NAME_ACCESS = "pacta_access"
COOKIE_NAME_REFRESH = "pacta_refresh"
COOKIE_NAME_CSRF = "pacta_csrf"

# Blacklist em memoria (suficiente para single-instance; em multi-replica usar Redis)
_REVOKED_JTI: set[str] = set()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _encode(payload: dict, ttl_minutes: int) -> str:
    to_encode = payload.copy()
    now = datetime.now(timezone.utc)
    to_encode.update({
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
        "jti": uuid.uuid4().hex,
        "iss": "pacta-api",
    })
    return pyjwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(data: dict) -> str:
    payload = data.copy()
    if "sub" in payload:
        payload["sub"] = str(payload["sub"])
    payload["typ"] = "access"
    return _encode(payload, settings.JWT_EXPIRE_MINUTES)


def create_refresh_token(user_id: int) -> str:
    return _encode({"sub": str(user_id), "typ": "refresh"}, REFRESH_TTL_DAYS * 24 * 60)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def revoke_jti(jti: str):
    _REVOKED_JTI.add(jti)


def is_revoked(jti: str) -> bool:
    return jti in _REVOKED_JTI


def _decode(token: str, expected_typ: str = "access") -> dict:
    try:
        payload = pyjwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            issuer="pacta-api",
            options={"require": ["exp", "iat", "jti", "iss"]},
        )
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token invalido")

    if payload.get("typ") != expected_typ:
        raise HTTPException(status_code=401, detail="Tipo de token incorreto")
    if is_revoked(payload.get("jti", "")):
        raise HTTPException(status_code=401, detail="Token revogado")
    return payload


def decode_access(token: str) -> dict:
    return _decode(token, "access")


def decode_refresh(token: str) -> dict:
    return _decode(token, "refresh")


def set_auth_cookies(response, access_token: str, refresh_token: str, csrf: str):
    """Seta cookies httpOnly de auth. Em prod usar secure=True + SameSite=Lax."""
    secure = os.getenv("ENV", "").lower() == "production"
    response.set_cookie(
        COOKIE_NAME_ACCESS, access_token,
        httponly=True, secure=secure, samesite="lax",
        max_age=settings.JWT_EXPIRE_MINUTES * 60, path="/",
    )
    response.set_cookie(
        COOKIE_NAME_REFRESH, refresh_token,
        httponly=True, secure=secure, samesite="lax",
        max_age=REFRESH_TTL_DAYS * 24 * 60 * 60, path="/api/auth",
    )
    # CSRF token NAO httpOnly (frontend precisa ler e enviar no header X-CSRF-Token)
    response.set_cookie(
        COOKIE_NAME_CSRF, csrf,
        httponly=False, secure=secure, samesite="lax",
        max_age=settings.JWT_EXPIRE_MINUTES * 60, path="/",
    )


def clear_auth_cookies(response):
    for name in (COOKIE_NAME_ACCESS, COOKIE_NAME_REFRESH, COOKIE_NAME_CSRF):
        response.delete_cookie(name, path="/")
        response.delete_cookie(name, path="/api/auth")


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Aceita tanto Bearer header quanto cookie httpOnly."""
    token = None
    if credentials:
        token = credentials.credentials
    if not token:
        token = request.cookies.get(COOKIE_NAME_ACCESS)
    if not token:
        raise HTTPException(status_code=401, detail="Nao autenticado")

    payload = decode_access(token)
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Token invalido")

    # CSRF check para mutating methods se vier por cookie (nao por Bearer)
    if not credentials and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        csrf_cookie = request.cookies.get(COOKIE_NAME_CSRF)
        csrf_header = request.headers.get("X-CSRF-Token")
        # Permitir bypass se Authorization header presente
        if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
            raise HTTPException(status_code=403, detail="CSRF token invalido")

    user_id = int(user_id_str)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail="Usuario nao encontrado")
    # Escopo de municipios: admin -> None (todos); demais -> set atribuido no cadastro
    if user.role == "admin":
        user.allowed_municipio_ids = None
    else:
        rows = await db.execute(
            text("SELECT municipio_id FROM user_municipios WHERE user_id = :u"),
            {"u": user.id},
        )
        user.allowed_municipio_ids = {r[0] for r in rows.fetchall()}
    return user


def ensure_municipio_access(user: User, municipio_id) -> None:
    """Barra (403) acesso a municipio fora do escopo do usuario.
    Admin (allowed_municipio_ids=None) sempre passa. Nao-admin precisa informar
    um municipio_id que esteja no seu conjunto atribuido."""
    allowed = getattr(user, "allowed_municipio_ids", None)
    if allowed is None:
        return
    if municipio_id is None:
        raise HTTPException(status_code=403, detail="Selecione um municipio permitido")
    try:
        mid = int(municipio_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=403, detail="Municipio invalido")
    if mid not in allowed:
        raise HTTPException(status_code=403, detail="Voce nao tem acesso a este municipio")
