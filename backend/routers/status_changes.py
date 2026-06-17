"""Mudancas de status detectadas nas atualizacoes diarias (trigger log_status_change).

Alimenta o aviso no dashboard: "o que mudou de status desde a ultima vez".
Fonte: tabela status_changes (preenchida por trigger AFTER UPDATE em
transferegov_propostas e convenios_estadual).
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from services.auth import get_current_user

router = APIRouter(prefix="/api/status-changes", tags=["status-changes"])


def _clean(s):
    if not isinstance(s, str):
        return s
    return s.replace("�", "").replace("  ", " ").strip()


@router.get("")
async def listar(
    municipio_id: int = Query(...),
    days: int = Query(30, description="janela em dias"),
    limit: int = Query(100),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Lista as mudancas de status recentes de um municipio (mais novas primeiro)."""
    rows = (await db.execute(text("""
        SELECT id, fonte, tabela, ref, orgao, objeto,
               status_anterior, status_novo, changed_at
        FROM status_changes
        WHERE municipio_id = :m
          AND changed_at >= NOW() - make_interval(days => :days)
        ORDER BY changed_at DESC
        LIMIT :lim
    """), {"m": municipio_id, "days": days, "lim": limit})).fetchall()
    items = [{
        "id": r[0],
        "fonte": r[1],
        "ref": r[3],
        "orgao": _clean(r[4]),
        "objeto": _clean(r[5]),
        "status_anterior": _clean(r[6]),
        "status_novo": _clean(r[7]),
        "changed_at": r[8].isoformat() if r[8] else None,
    } for r in rows]
    return {"items": items, "total": len(items)}
