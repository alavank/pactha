"""
Superficie de CONTROL-PLANE que a instancia expoe ao Console Alavank.
Tudo sob /api/control/*, autenticado por X-Control-Token (kind='control', scope control:*).
Enderecamento por CHAVE ESTAVEL (ibge_code), nunca pelo id autoincrement interno.

Municipio NAO tem delecao (decisao do usuario) — no maximo desativar via PATCH.
"""
import os
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from database import get_db
from models import Municipio
from models.user import User
from services.control_auth import require_control_scope, ControlPrincipal
from services.auth import hash_password
from services import users_admin
from services.telas_catalog import TELAS_CATALOG
from services.audit import log_event

router = APIRouter(prefix="/api/control", tags=["control"])


def _mun(m: Municipio) -> dict:
    return {"ibge_code": m.ibge_code, "nome": m.nome, "uf": m.uf, "active": bool(m.active)}


class MunicipioIn(BaseModel):
    ibge_code: str
    nome: str
    uf: str | None = "MG"


class MunicipioPatch(BaseModel):
    nome: str | None = None
    uf: str | None = None
    active: bool | None = None


# --- Municipios ---
@router.get("/municipios")
async def list_municipios(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:municipios:read")),
):
    """Lista TODOS os municipios, inclusive inativos (difere do GET de usuario)."""
    rows = (await db.execute(select(Municipio).order_by(Municipio.nome))).scalars().all()
    return [_mun(m) for m in rows]


@router.post("/municipios")
async def upsert_municipio(
    body: MunicipioIn, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:municipios:write")),
):
    """Upsert por ibge_code (reativa se estiver inativo)."""
    ibge = (body.ibge_code or "").strip()
    nome = (body.nome or "").strip()
    uf = (body.uf or "MG").strip().upper()[:2]
    if len(ibge) != 7 or not ibge.isdigit():
        raise HTTPException(status_code=400, detail="ibge_code deve ter 7 digitos")
    if not nome:
        raise HTTPException(status_code=400, detail="nome obrigatorio")

    m = (await db.execute(select(Municipio).where(Municipio.ibge_code == ibge))).scalar_one_or_none()
    created = m is None
    if m is None:
        m = Municipio(nome=nome, ibge_code=ibge, uf=uf, active=True)
        db.add(m)
    else:
        m.nome = nome
        m.uf = uf
        m.active = True
    await db.commit()
    await db.refresh(m)
    await log_event(db, action="control.municipio.upsert", request=request,
                    target_type="municipio", target_id=ibge,
                    details={"nome": nome, "uf": uf, "created": created, "token": p.name})
    return _mun(m)


@router.patch("/municipios/{ibge_code}")
async def patch_municipio(
    ibge_code: str, body: MunicipioPatch, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:municipios:write")),
):
    """Renomear / mudar UF / ativar-desativar. Municipio NAO deleta (sem DELETE)."""
    m = (await db.execute(select(Municipio).where(Municipio.ibge_code == ibge_code))).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Municipio nao encontrado")
    changed = []
    if body.nome is not None and body.nome.strip():
        m.nome = body.nome.strip(); changed.append("nome")
    if body.uf is not None and body.uf.strip():
        m.uf = body.uf.strip().upper()[:2]; changed.append("uf")
    if body.active is not None:
        m.active = bool(body.active); changed.append("active")
    await db.commit()
    await db.refresh(m)
    await log_event(db, action="control.municipio.patch", request=request,
                    target_type="municipio", target_id=ibge_code,
                    details={"changed": changed, "active": m.active, "token": p.name})
    return _mun(m)


# --- Status/identidade (o Console confirma que fala com o tenant certo) ---
@router.get("/status")
async def control_status(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:status:read")),
):
    async def _count(sql: str):
        try:
            return (await db.execute(text(sql))).scalar()
        except Exception:
            await db.rollback()
            return None

    return {
        "instance_slug": os.getenv("INSTANCE_SLUG", ""),
        "env": os.getenv("ENV", ""),
        "db_ok": True,
        "counts": {
            "municipios": await _count("SELECT COUNT(*) FROM municipios"),
            "municipios_ativos": await _count("SELECT COUNT(*) FROM municipios WHERE active = true"),
            "users": await _count("SELECT COUNT(*) FROM users"),
            "convenios_estadual": await _count("SELECT COUNT(*) FROM convenios_estadual"),
            "transferegov_propostas": await _count("SELECT COUNT(*) FROM transferegov_propostas"),
        },
        "control_token": p.name,
    }


# --- Usuarios do cliente (users do tenant), geridos pela Central via canal ---
class ControlUserIn(BaseModel):
    email: str
    name: str
    role: str = "analyst"                  # default analyst (nao admin/"deus")
    telas: list[str] | None = None         # keys de telas/modulos
    municipios: list[str] | None = None    # ibge_codes do escopo


class ControlUserPatch(BaseModel):
    name: str | None = None
    role: str | None = None
    active: bool | None = None
    telas: list[str] | None = None
    municipios: list[str] | None = None


async def _user_out(db, u: User) -> dict:
    return {
        "email": u.email, "name": u.name, "role": u.role, "active": bool(u.active),
        "must_change_password": bool(u.must_change_password),
        "telas": await users_admin.get_user_telas(db, u.id),
        "municipios": await users_admin.get_user_ibges(db, u.id),
    }


async def _active_admin_count(db) -> int:
    return (await db.execute(text(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = true"))).scalar() or 0


@router.get("/telas-catalog")
async def telas_catalog(p: ControlPrincipal = Depends(require_control_scope("control:users:read"))):
    return {"telas": TELAS_CATALOG}


@router.get("/users")
async def list_control_users(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:users:read")),
):
    rows = (await db.execute(select(User).order_by(User.name))).scalars().all()
    return [await _user_out(db, u) for u in rows]


@router.post("/users")
async def create_control_user(
    body: ControlUserIn, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:users:write")),
):
    email = (body.email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Email invalido")
    if body.role not in users_admin.ROLES:
        raise HTTPException(status_code=400, detail="Role invalida (admin|analyst|user)")
    dup = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=400, detail="Email ja cadastrado")
    senha = users_admin.gen_senha()
    u = User(email=email, name=(body.name or "").strip(), password_hash=hash_password(senha),
             role=body.role, active=True, must_change_password=True)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    if body.telas is not None:
        await users_admin.set_user_telas(db, u.id, body.telas)
    if body.municipios is not None:
        await users_admin.set_user_municipios_by_ibge(db, u.id, body.municipios)
    await db.commit()
    await log_event(db, action="control.user.create", request=request,
                    target_type="user", target_id=email,
                    details={"role": body.role, "token": p.name})
    out = await _user_out(db, u)
    out["senha_temporaria"] = senha
    return out


@router.patch("/users/{email}")
async def patch_control_user(
    email: str, body: ControlUserPatch, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:users:write")),
):
    u = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    if body.role is not None and body.role not in users_admin.ROLES:
        raise HTTPException(status_code=400, detail="Role invalida")
    # Nao deixar o cliente sem NENHUM admin
    demoting = body.role is not None and body.role != "admin" and u.role == "admin"
    deactivating = body.active is False and u.active and u.role == "admin"
    if (demoting or deactivating) and await _active_admin_count(db) <= 1:
        raise HTTPException(status_code=409, detail="Nao e possivel deixar o cliente sem administrador")

    if body.name is not None:
        u.name = body.name.strip()
    if body.role is not None:
        u.role = body.role
    if body.active is not None:
        u.active = body.active
    if body.telas is not None:
        await users_admin.set_user_telas(db, u.id, body.telas)
    if body.municipios is not None:
        await users_admin.set_user_municipios_by_ibge(db, u.id, body.municipios)
    await db.commit()
    await db.refresh(u)
    await log_event(db, action="control.user.patch", request=request,
                    target_type="user", target_id=email, details={"token": p.name})
    return await _user_out(db, u)


@router.post("/users/{email}/reset-password")
async def reset_control_user_password(
    email: str, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:users:write")),
):
    u = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    senha = users_admin.gen_senha()
    u.password_hash = hash_password(senha)
    u.must_change_password = True
    await db.commit()
    await log_event(db, action="control.user.reset_password", request=request,
                    target_type="user", target_id=email, details={"token": p.name})
    return {"email": u.email, "senha_temporaria": senha}
