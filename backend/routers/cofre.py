"""
Cofre de Senhas — armazenamento criptografado (AES-GCM).

Politicas:
- Listing nao expoe senha em claro (mascara).
- Endpoint dedicado /reveal exige role admin/gestor + registra auditoria.
- CRUD restrito a role in (admin, gestor).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import logging

from database import get_db
from models.cofre import CofreSenha
from models.user import User
from services.auth import get_current_user
from services import crypto

router = APIRouter(prefix="/api/cofre", tags=["cofre"])
logger = logging.getLogger("cofre.audit")

ALLOWED_ROLES_WRITE = {"admin", "gestor"}
ALLOWED_ROLES_REVEAL = {"admin", "gestor"}


def _require_role(user: User, allowed: set[str]):
    if (user.role or "").lower() not in allowed:
        raise HTTPException(status_code=403, detail="Acao restrita a administradores")


class CofreCreate(BaseModel):
    municipio_id: int
    sistema: str
    url: Optional[str] = None
    usuario: Optional[str] = None
    senha: Optional[str] = None
    observacao: Optional[str] = None
    categoria: Optional[str] = None


class CofreUpdate(BaseModel):
    sistema: Optional[str] = None
    url: Optional[str] = None
    usuario: Optional[str] = None
    senha: Optional[str] = None
    observacao: Optional[str] = None
    categoria: Optional[str] = None


class CofreResponse(BaseModel):
    id: int
    municipio_id: int
    sistema: str
    url: Optional[str] = None
    usuario: Optional[str] = None
    senha_mascarada: Optional[str] = None
    observacao: Optional[str] = None
    categoria: Optional[str] = None

    class Config:
        from_attributes = True


def _to_response(item: CofreSenha) -> CofreResponse:
    senha_clear = crypto.decrypt(item.senha_encrypted) if item.senha_encrypted else ""
    return CofreResponse(
        id=item.id,
        municipio_id=item.municipio_id,
        sistema=item.sistema,
        url=item.url,
        usuario=item.usuario,
        senha_mascarada=crypto.mask(senha_clear),
        observacao=item.observacao,
        categoria=item.categoria,
    )


@router.get("", response_model=list[CofreResponse])
async def list_senhas(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(CofreSenha)
    if municipio_id:
        q = q.where(CofreSenha.municipio_id == municipio_id)
    q = q.order_by(CofreSenha.categoria, CofreSenha.sistema)
    result = await db.execute(q)
    items = result.scalars().all()
    return [_to_response(i) for i in items]


@router.get("/{item_id}/reveal")
async def reveal_senha(
    item_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Retorna a senha em claro. Restrito a admin/gestor + auditoria."""
    _require_role(user, ALLOWED_ROLES_REVEAL)
    item = await db.get(CofreSenha, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Senha nao encontrada")
    ip = request.client.host if request.client else "?"
    logger.warning(
        "COFRE_REVEAL user_id=%s email=%s item_id=%s sistema=%s ip=%s",
        user.id, user.email, item.id, item.sistema, ip,
    )
    return {"senha": crypto.decrypt(item.senha_encrypted) if item.senha_encrypted else ""}


@router.post("", response_model=CofreResponse)
async def create_senha(
    data: CofreCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_role(user, ALLOWED_ROLES_WRITE)
    item = CofreSenha(
        municipio_id=data.municipio_id,
        sistema=data.sistema,
        url=data.url,
        usuario=data.usuario,
        senha_encrypted=crypto.encrypt(data.senha) if data.senha else None,
        observacao=data.observacao,
        categoria=data.categoria,
        atualizado_por_id=user.id,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _to_response(item)


@router.put("/{item_id}", response_model=CofreResponse)
async def update_senha(
    item_id: int,
    data: CofreUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_role(user, ALLOWED_ROLES_WRITE)
    item = await db.get(CofreSenha, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Senha nao encontrada")

    fields = data.model_dump(exclude_unset=True)
    if "senha" in fields:
        senha = fields.pop("senha")
        item.senha_encrypted = crypto.encrypt(senha) if senha else None
    for k, v in fields.items():
        setattr(item, k, v)
    item.atualizado_por_id = user.id

    await db.commit()
    await db.refresh(item)
    return _to_response(item)


@router.delete("/{item_id}")
async def delete_senha(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_role(user, ALLOWED_ROLES_WRITE)
    item = await db.get(CofreSenha, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Senha nao encontrada")
    await db.delete(item)
    await db.commit()
    return {"status": "deleted"}
