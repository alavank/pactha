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
from services.control_auth import require_control_scope, ControlPrincipal
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
