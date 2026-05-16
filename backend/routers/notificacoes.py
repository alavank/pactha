"""Endpoint de notificacoes push (deltas detectados pelos scrapers)."""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional
from database import get_db
from services.auth import get_current_user

router = APIRouter(prefix="/api/notificacoes", tags=["notificacoes"])


@router.get("")
async def list_notificacoes(
    municipio_id: Optional[int] = None,
    apenas_nao_lidas: bool = False,
    tipo: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    where = ["1=1"]
    params: dict = {"limit": limit}
    if municipio_id:
        where.append("municipio_id = :mun")
        params["mun"] = municipio_id
    if apenas_nao_lidas:
        where.append("lida = false")
    if tipo:
        where.append("tipo = :tipo")
        params["tipo"] = tipo

    r = await db.execute(text(f"""
        SELECT id, tipo, municipio_id, convenio_estadual_id, convenio_federal_id,
               titulo, mensagem, severidade, payload, lida, created_at
        FROM notificacoes
        WHERE {" AND ".join(where)}
        ORDER BY created_at DESC
        LIMIT :limit
    """), params)
    items = [dict(row._mapping) for row in r.all()]

    # Conta nao-lidas total (independente do filtro)
    count_where = ["lida = false"]
    count_params = {}
    if municipio_id:
        count_where.append("municipio_id = :mun")
        count_params["mun"] = municipio_id
    r2 = await db.execute(text(f"SELECT count(*) FROM notificacoes WHERE {' AND '.join(count_where)}"), count_params)
    nao_lidas = r2.scalar() or 0

    return {"items": items, "nao_lidas": nao_lidas, "total": len(items)}


@router.post("/{notif_id}/marcar-lida")
async def marcar_lida(
    notif_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    r = await db.execute(text(
        "UPDATE notificacoes SET lida = true, lida_em = NOW(), lida_por_user_id = :uid WHERE id = :id RETURNING id"
    ), {"id": notif_id, "uid": user.id})
    row = r.first()
    if not row:
        raise HTTPException(404, "Notificacao nao encontrada")
    await db.commit()
    return {"ok": True}


@router.post("/marcar-todas-lidas")
async def marcar_todas(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    where = "lida = false"
    params = {"uid": user.id}
    if municipio_id:
        where += " AND municipio_id = :mun"
        params["mun"] = municipio_id
    r = await db.execute(text(
        f"UPDATE notificacoes SET lida = true, lida_em = NOW(), lida_por_user_id = :uid WHERE {where}"
    ), params)
    await db.commit()
    return {"ok": True, "atualizadas": r.rowcount}
