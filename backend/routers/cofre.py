from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from database import get_db
from models.cofre import CofreSenha
from services.auth import get_current_user
from models.user import User

router = APIRouter(prefix="/api/cofre", tags=["cofre"])


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
    senha: Optional[str] = None
    observacao: Optional[str] = None
    categoria: Optional[str] = None

    class Config:
        from_attributes = True


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
    return [
        CofreResponse(
            id=i.id, municipio_id=i.municipio_id, sistema=i.sistema,
            url=i.url, usuario=i.usuario, senha=i.senha_hash,
            observacao=i.observacao, categoria=i.categoria,
        ) for i in items
    ]


@router.post("", response_model=CofreResponse)
async def create_senha(
    data: CofreCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = CofreSenha(
        municipio_id=data.municipio_id,
        sistema=data.sistema,
        url=data.url,
        usuario=data.usuario,
        senha_hash=data.senha,
        observacao=data.observacao,
        categoria=data.categoria,
        atualizado_por_id=user.id,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return CofreResponse(
        id=item.id, municipio_id=item.municipio_id, sistema=item.sistema,
        url=item.url, usuario=item.usuario, senha=item.senha_hash,
        observacao=item.observacao, categoria=item.categoria,
    )


@router.put("/{item_id}", response_model=CofreResponse)
async def update_senha(
    item_id: int,
    data: CofreUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = await db.get(CofreSenha, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Senha nao encontrada")

    fields = data.model_dump(exclude_unset=True)
    if "senha" in fields:
        item.senha_hash = fields.pop("senha")
    for k, v in fields.items():
        setattr(item, k, v)
    item.atualizado_por_id = user.id

    await db.commit()
    await db.refresh(item)
    return CofreResponse(
        id=item.id, municipio_id=item.municipio_id, sistema=item.sistema,
        url=item.url, usuario=item.usuario, senha=item.senha_hash,
        observacao=item.observacao, categoria=item.categoria,
    )


@router.delete("/{item_id}")
async def delete_senha(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = await db.get(CofreSenha, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Senha nao encontrada")
    await db.delete(item)
    await db.commit()
    return {"status": "deleted"}
