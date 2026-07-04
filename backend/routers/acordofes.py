"""Acordo FES — divida do Fundo Estadual de Saude de MG (SES-MG) com os credores
da saude. Por municipio (fundo municipal de saude) + busca livre por CNPJ/razao.
Dados de `acordofes_credor` (ingestao `ingestion/acordofes_ingest.py`).
"""
from __future__ import annotations
import re
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from services.auth import get_current_user, ensure_municipio_access, ensure_tela
from models.user import User

router = APIRouter(prefix="/api/acordofes", tags=["acordofes"])


def _row(r) -> dict:
    return {
        "cnpj": r[0], "razao_social": r[1],
        "divida_inicial": float(r[2] or 0), "total_pago": float(r[3] or 0),
        "divida_atual": float(r[4] or 0), "valor_retirado": float(r[5] or 0),
        "pago_fora": float(r[6] or 0), "n_empenhos": r[7],
    }

_SEL = ("cnpj, razao_social, divida_inicial, total_pago, divida_atual, "
        "valor_retirado, pago_fora, n_empenhos")


@router.get("")
async def por_municipio(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Divida do Acordo FES do(s) fundo(s) municipal(is) de saude deste municipio."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "acordofes")
    rows = (await db.execute(text(
        f"SELECT {_SEL} FROM acordofes_credor WHERE municipio_id = :m "
        "ORDER BY divida_atual DESC"), {"m": municipio_id})).fetchall()
    credores = [_row(r) for r in rows]
    return {
        "credores": credores,
        "total_divida_atual": sum(c["divida_atual"] for c in credores),
        "total_pago": sum(c["total_pago"] for c in credores),
        "total_divida_inicial": sum(c["divida_inicial"] for c in credores),
    }


@router.get("/buscar")
async def buscar(
    q: str = Query(..., min_length=2, description="CNPJ ou parte da razao social"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Busca livre em TODOS os credores do Acordo FES (hospitais, consorcios, etc.)."""
    ensure_tela(current, "acordofes")
    digits = re.sub(r"\D", "", q)
    where = "razao_social ILIKE :q"
    params: dict = {"q": f"%{q.strip()}%"}
    if len(digits) >= 4:
        where = "(razao_social ILIKE :q OR cnpj LIKE :d)"
        params["d"] = f"%{digits}%"
    rows = (await db.execute(text(
        f"SELECT {_SEL} FROM acordofes_credor WHERE {where} "
        "ORDER BY divida_atual DESC LIMIT 100"), params)).fetchall()
    return {"items": [_row(r) for r in rows], "total": len(rows)}


@router.post("/refresh")
async def refresh(_: User = Depends(get_current_user)):
    """Dispara a ingestao do Acordo FES (espelho Excel do Painel)."""
    from ingestion.acordofes_ingest import ingest
    import anyio
    n = await anyio.to_thread.run_sync(ingest)
    return {"ok": True, "credores": n}
