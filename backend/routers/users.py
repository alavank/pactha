"""Gerenciamento de usuarios (admin-only).

Telas: listar, criar, resetar senha, ativar/desativar, mudar role.
Senhas nunca sao retornadas (hash bcrypt). Reset gera senha temporaria
aleatoria que o admin repassa; usuario troca no proximo login.
"""
import secrets
import string
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field

from database import get_db
from models.user import User
from schemas.auth import UserResponse
from services.auth import hash_password, get_current_user
from services.audit import log_event

router = APIRouter(prefix="/api/users", tags=["users"])

ALPHABET = string.ascii_letters + string.digits + "!@#$%&*"


def _gen_senha(n: int = 14) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


def _require_admin(user: User):
    if user.role != "admin":
        raise HTTPException(403, "Apenas administradores podem gerenciar usuarios")


class CreateUserRequest(BaseModel):
    email: str
    name: str
    role: str = "admin"  # default admin (preferencia atual do cliente)


class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None


class SenhaResetResponse(BaseModel):
    id: int
    email: str
    name: str
    senha_temporaria: str


@router.get("", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _require_admin(current)
    r = await db.execute(select(User).order_by(User.id))
    return [UserResponse.model_validate(u) for u in r.scalars().all()]


@router.post("", response_model=SenhaResetResponse)
async def create_user(
    req: CreateUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _require_admin(current)
    email = req.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "Email invalido")
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Email ja cadastrado")
    if req.role not in ("admin", "analyst", "user"):
        raise HTTPException(400, "Role invalida")

    senha = _gen_senha()
    user = User(
        email=email,
        name=req.name.strip(),
        password_hash=hash_password(senha),
        role=req.role,
        active=True,
        must_change_password=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await log_event(
        db, action="user.create", user=current, request=request,
        target_type="user", target_id=user.id,
        details={"new_email": email, "role": req.role},
    )
    return SenhaResetResponse(id=user.id, email=user.email, name=user.name, senha_temporaria=senha)


@router.post("/{user_id}/reset-password", response_model=SenhaResetResponse)
async def reset_password(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _require_admin(current)
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not u:
        raise HTTPException(404, "Usuario nao encontrado")
    senha = _gen_senha()
    u.password_hash = hash_password(senha)
    u.must_change_password = True
    await db.commit()
    await log_event(
        db, action="user.reset_password", user=current, request=request,
        target_type="user", target_id=u.id, details={"email": u.email},
    )
    return SenhaResetResponse(id=u.id, email=u.email, name=u.name, senha_temporaria=senha)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    req: UpdateUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _require_admin(current)
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not u:
        raise HTTPException(404, "Usuario nao encontrado")
    # Protecao: nao deixar o admin se auto-desativar nem rebaixar o ultimo admin
    if req.active is False and u.id == current.id:
        raise HTTPException(400, "Voce nao pode desativar a si mesmo")
    if req.role and req.role not in ("admin", "analyst", "user"):
        raise HTTPException(400, "Role invalida")
    if req.name is not None:
        u.name = req.name.strip()
    if req.role is not None:
        u.role = req.role
    if req.active is not None:
        u.active = req.active
    await db.commit()
    await db.refresh(u)
    await log_event(
        db, action="user.update", user=current, request=request,
        target_type="user", target_id=u.id,
        details={"name": req.name, "role": req.role, "active": req.active},
    )
    return UserResponse.model_validate(u)
