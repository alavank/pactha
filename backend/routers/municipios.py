from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import date, timedelta
from database import get_db
from models import Municipio, ConvenioEstadual
from schemas.municipio import MunicipioResponse, MunicipioSummary
from services.auth import get_current_user

router = APIRouter(prefix="/api/municipios", tags=["municipios"])


@router.get("", response_model=list[MunicipioResponse])
async def list_municipios(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(
        select(Municipio).where(Municipio.active == True).order_by(Municipio.nome)
    )
    return [MunicipioResponse.model_validate(m) for m in result.scalars().all()]


@router.get("/{municipio_id}/summary", response_model=MunicipioSummary)
async def municipio_summary(
    municipio_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(select(Municipio).where(Municipio.id == municipio_id))
    mun = result.scalar_one_or_none()
    if not mun:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Municipio nao encontrado")

    est_count = await db.execute(
        select(func.count()).select_from(ConvenioEstadual).where(ConvenioEstadual.municipio_id == municipio_id)
    )
    est_valor = await db.execute(
        select(func.coalesce(func.sum(ConvenioEstadual.valor_total), 0))
        .where(ConvenioEstadual.municipio_id == municipio_id)
    )

    limite = date.today() + timedelta(days=120)
    alertas = await db.execute(
        select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id == municipio_id)
        .where(ConvenioEstadual.dt_vigencia_atual <= limite)
        .where(ConvenioEstadual.dt_vigencia_atual >= date.today())
    )

    return MunicipioSummary(
        municipio=MunicipioResponse.model_validate(mun),
        total_convenios_estadual=est_count.scalar(),
        valor_total_estadual=float(est_valor.scalar()),
        alertas_vigencia=alertas.scalar(),
    )
