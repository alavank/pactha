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
from sqlalchemy import select, text
from pydantic import BaseModel

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


# Conta principal do tenant. Sem a guarda abaixo, qualquer admin reseta a senha
# dela para a padrao "1234" e entra no lugar do administrador principal.
SUPER_ADMIN_EMAIL = "admin@pactha.com.br"


def _is_super(user: User) -> bool:
    return (getattr(user, "email", "") or "").strip().lower() == SUPER_ADMIN_EMAIL


def _guard_target(current: User, target: User):
    """Protege contas sensiveis contra quem nao pode altera-las."""
    if _is_super(target) and not _is_super(current):
        raise HTTPException(403, "Somente o administrador principal pode alterar essa conta")
    if target.role == "admin" and current.role != "admin":
        raise HTTPException(403, "Apenas administradores podem alterar contas admin")


class CreateUserRequest(BaseModel):
    email: str
    name: str
    role: str = "admin"  # default admin (preferencia atual do cliente)
    municipio_ids: Optional[list[int]] = None  # municipios que o usuario pode acessar
    telas: Optional[list[str]] = None  # telas/modulos que o usuario pode acessar


class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None
    municipio_ids: Optional[list[int]] = None
    telas: Optional[list[str]] = None


async def _set_user_municipios(db: AsyncSession, user_id: int, ids) -> None:
    """Substitui o conjunto de municipios permitidos do usuario."""
    await db.execute(text("DELETE FROM user_municipios WHERE user_id = :u"), {"u": user_id})
    for mid in (ids or []):
        await db.execute(
            text("INSERT INTO user_municipios (user_id, municipio_id) VALUES (:u, :m) "
                 "ON CONFLICT DO NOTHING"),
            {"u": user_id, "m": int(mid)},
        )


async def _set_user_telas(db: AsyncSession, user_id: int, telas) -> None:
    """Substitui o conjunto de telas/modulos permitidos do usuario."""
    await db.execute(text("DELETE FROM user_telas WHERE user_id = :u"), {"u": user_id})
    for tela in (telas or []):
        t = str(tela).strip()
        if not t:
            continue
        await db.execute(
            text("INSERT INTO user_telas (user_id, tela) VALUES (:u, :t) "
                 "ON CONFLICT DO NOTHING"),
            {"u": user_id, "t": t},
        )


class SenhaResetResponse(BaseModel):
    id: int
    email: str
    name: str
    senha_temporaria: str


@router.get("")
async def list_users(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _require_admin(current)
    # Fora da lista os usuarios sinteticos de quiosque (@painel.local): eles nao
    # sao PESSOAS, sao credencial de um link de TV. Cada link publicado cria um,
    # entao deixa-los aqui encheria a tela de "Quiosque de Fulano" e daria a
    # impressao de que a prefeitura tem 40 usuarios. Quem os administra e o
    # proprio painel (Ajustes -> Link publico da TV, com copiar e revogar).
    r = await db.execute(
        select(User).where(User.email.notlike("%@painel.local")).order_by(User.id)
    )
    users = r.scalars().all()
    mr = await db.execute(text("SELECT user_id, municipio_id FROM user_municipios"))
    by_user: dict[int, list[int]] = {}
    for uid, mid in mr.fetchall():
        by_user.setdefault(uid, []).append(mid)
    tr = await db.execute(text("SELECT user_id, tela FROM user_telas"))
    telas_by_user: dict[int, list[str]] = {}
    for uid, tela in tr.fetchall():
        telas_by_user.setdefault(uid, []).append(tela)
    return [{
        "id": u.id, "email": u.email, "name": u.name, "role": u.role,
        "active": u.active, "must_change_password": u.must_change_password,
        "municipio_ids": by_user.get(u.id, []),
        "telas": sorted(telas_by_user.get(u.id, [])),
    } for u in users]


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
    if req.role not in ("admin", "analyst", "user", "prefeito"):
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
    if req.municipio_ids is not None:
        await _set_user_municipios(db, user.id, req.municipio_ids)
        await db.commit()
    if req.telas is not None:
        await _set_user_telas(db, user.id, req.telas)
        await db.commit()
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
    _guard_target(current, u)
    # Senha padrao "1234" - o usuario sera obrigado a troca-la no primeiro login
    senha = "1234"
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
    _guard_target(current, u)
    # Protecao: nao deixar o admin se auto-desativar nem se auto-rebaixar
    if req.active is False and u.id == current.id:
        raise HTTPException(400, "Voce nao pode desativar a si mesmo")
    if req.role and req.role != "admin" and u.id == current.id and current.role == "admin":
        raise HTTPException(400, "Voce nao pode rebaixar o proprio perfil de administrador (evita se trancar pra fora)")
    if req.role and req.role not in ("admin", "analyst", "user", "prefeito"):
        raise HTTPException(400, "Role invalida")
    if req.name is not None:
        u.name = req.name.strip()
    if req.role is not None:
        u.role = req.role
    if req.active is not None:
        u.active = req.active
    if req.municipio_ids is not None:
        await _set_user_municipios(db, u.id, req.municipio_ids)
    if req.telas is not None:
        await _set_user_telas(db, u.id, req.telas)
    await db.commit()
    await db.refresh(u)
    await log_event(
        db, action="user.update", user=current, request=request,
        target_type="user", target_id=u.id,
        details={"name": req.name, "role": req.role, "active": req.active},
    )
    return UserResponse.model_validate(u)
