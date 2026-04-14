from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import date, timedelta
from database import get_db
from models import Municipio, ConvenioFederal, ConvenioEstadual, EditalAcompanhamento
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

    # Federal counts
    fed_count = await db.execute(
        select(func.count()).select_from(ConvenioFederal).where(ConvenioFederal.municipio_id == municipio_id)
    )
    fed_valor = await db.execute(
        select(func.coalesce(func.sum(ConvenioFederal.valor_global), 0))
        .where(ConvenioFederal.municipio_id == municipio_id)
    )

    # Estadual counts
    est_count = await db.execute(
        select(func.count()).select_from(ConvenioEstadual).where(ConvenioEstadual.municipio_id == municipio_id)
    )
    est_valor = await db.execute(
        select(func.coalesce(func.sum(ConvenioEstadual.valor_total), 0))
        .where(ConvenioEstadual.municipio_id == municipio_id)
    )

    # Alertas vigencia (120 dias)
    limite = date.today() + timedelta(days=120)
    alertas_fed = await db.execute(
        select(func.count()).select_from(ConvenioFederal)
        .where(ConvenioFederal.municipio_id == municipio_id)
        .where(ConvenioFederal.dt_fim_vigencia <= limite)
        .where(ConvenioFederal.dt_fim_vigencia >= date.today())
    )
    alertas_est = await db.execute(
        select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id == municipio_id)
        .where(ConvenioEstadual.dt_vigencia_atual <= limite)
        .where(ConvenioEstadual.dt_vigencia_atual >= date.today())
    )

    # Editais acompanhados
    editais_count = await db.execute(
        select(func.count()).select_from(EditalAcompanhamento)
        .where(EditalAcompanhamento.municipio_id == municipio_id)
    )

    return MunicipioSummary(
        municipio=MunicipioResponse.model_validate(mun),
        total_convenios_federal=fed_count.scalar(),
        total_convenios_estadual=est_count.scalar(),
        valor_total_federal=float(fed_valor.scalar()),
        valor_total_estadual=float(est_valor.scalar()),
        alertas_vigencia=alertas_fed.scalar() + alertas_est.scalar(),
        editais_acompanhados=editais_count.scalar(),
    )
