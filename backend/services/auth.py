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
COOKIE_NAME_ACCESS = "pactha_access"
COOKIE_NAME_REFRESH = "pactha_refresh"
COOKIE_NAME_CSRF = "pactha_csrf"

# Perfis somente-leitura (ex.: prefeito no Painel Executivo). Nao editam NADA do
# sistema operacional; so podem escrever nos endpoints proprios do Painel abaixo.
READONLY_ROLES = {"prefeito", "viewer"}
READONLY_WRITE_ALLOW = ("/api/painel/push", "/api/painel/preferencias")

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
        "iss": "pactha-api",
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


def create_kiosk_token(user_id: int, dias: int = 365) -> str:
    """Access token de LONGA duracao para a TV (quiosque do Painel). typ='access'
    p/ o get_current_user aceitar sem mudanca; o usuario e um 'viewer' escopado ao
    municipio (read-only pelo guard). Revogacao = desativar o usuario viewer."""
    return _encode({"sub": str(user_id), "typ": "access", "role": "viewer", "kiosk": True}, dias * 24 * 60)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _sso_audience() -> str:
    """Identidade DESTA instancia, usada como 'aud' do token SSO. Amarra o token ao
    tenant que o emitiu: um token de A e rejeitado por B mesmo que (por erro de ops)
    dois tenants compartilhem o JWT_SECRET. Sempre nao-vazio p/ evitar aud ambiguo."""
    return settings.INSTANCE_SLUG or settings.FRONTEND_URL or "pactha-instance"


def create_sso_token(user_id: int) -> str:
    """Token de uso único e CURTO (2 min) p/ o SSO da Central: o aceitador o troca
    por uma sessao. typ='sso' impede reuso como access/refresh; aud amarra a instancia."""
    return _encode({"sub": str(user_id), "typ": "sso", "aud": _sso_audience()}, 2)


def decode_sso(token: str) -> dict:
    return _decode(token, "sso", audience=_sso_audience())


def revoke_jti(jti: str):
    _REVOKED_JTI.add(jti)


def is_revoked(jti: str) -> bool:
    return jti in _REVOKED_JTI


def _decode(token: str, expected_typ: str = "access", audience: Optional[str] = None) -> dict:
    # aud so e exigido/validado p/ tokens SSO (audience != None). Access/refresh nao
    # carregam aud e sao decodificados sem audience -> pyjwt nao verifica esse claim.
    require = ["exp", "iat", "jti", "iss"] + (["aud"] if audience is not None else [])
    kwargs = dict(
        algorithms=[settings.JWT_ALGORITHM],
        issuer="pactha-api",
        options={"require": require},
    )
    if audience is not None:
        kwargs["audience"] = audience
    try:
        payload = pyjwt.decode(token, settings.JWT_SECRET, **kwargs)
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
    await load_user_scopes(db, user)

    # Perfil somente-leitura (ex.: prefeito no Painel Executivo): barra qualquer
    # metodo mutavel fora dos endpoints proprios do Painel. Defense-in-depth
    # centralizado — TODO endpoint autenticado passa por aqui, entao vale mesmo
    # que o prefeito descubra a URL de um endpoint de escrita do sistema.
    if user.role in READONLY_ROLES and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if not request.url.path.startswith(READONLY_WRITE_ALLOW):
            raise HTTPException(status_code=403, detail="Perfil somente-leitura")

    return user


async def load_user_scopes(db: AsyncSession, user: User) -> None:
    """Anexa ao user os escopos de acesso: municipios + telas.
    Admin -> None (tudo). Nao-admin -> conjuntos atribuidos (vazio = nenhum)."""
    if user.role == "admin":
        user.allowed_municipio_ids = None
        user.allowed_telas = None
        return
    mrows = await db.execute(
        text("SELECT municipio_id FROM user_municipios WHERE user_id = :u"), {"u": user.id})
    user.allowed_municipio_ids = {r[0] for r in mrows.fetchall()}
    trows = await db.execute(
        text("SELECT tela FROM user_telas WHERE user_id = :u"), {"u": user.id})
    user.allowed_telas = {r[0] for r in trows.fetchall()}


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


def ensure_tela(user: User, tela: str) -> None:
    """403 se o usuario nao tem acesso a tela/modulo (admin sempre passa)."""
    allowed = getattr(user, "allowed_telas", None)
    if allowed is None:
        return
    if tela not in allowed:
        raise HTTPException(status_code=403, detail="Voce nao tem acesso a esta tela")
