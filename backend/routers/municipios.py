from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from datetime import date, datetime, timedelta
from database import get_db
from models import Municipio, ConvenioEstadual
from schemas.municipio import MunicipioResponse, MunicipioSummary
from services.auth import get_current_user

router = APIRouter(prefix="/api/municipios", tags=["municipios"])


def _parse_dt(s) -> date | None:
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s).strip()[:10], fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


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

    hoje = date.today()
    limite120 = hoje + timedelta(days=120)
    limite60 = hoje + timedelta(days=60)
    # Vencidos ha +90 dias -> prestacao de contas obrigatoria
    venc90 = hoje - timedelta(days=90)
    alertas120 = await db.execute(
        select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id == municipio_id)
        .where(ConvenioEstadual.dt_vigencia_atual <= limite120)
        .where(ConvenioEstadual.dt_vigencia_atual >= hoje)
    )
    alertas60 = await db.execute(
        select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id == municipio_id)
        .where(ConvenioEstadual.dt_vigencia_atual <= limite60)
        .where(ConvenioEstadual.dt_vigencia_atual >= hoje)
    )
    prest_contas = await db.execute(
        select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id == municipio_id)
        .where(ConvenioEstadual.dt_vigencia_atual < venc90)
    )

    # TransfereGov Voluntarias (dt_fim_vigencia eh string dd/mm/yyyy -> parse em Python)
    vol = await db.execute(text(
        "SELECT dt_fim_vigencia FROM transferegov_propostas WHERE municipio_id = :m"
    ), {"m": municipio_id})
    vol_rows = vol.fetchall()
    total_vol = len(vol_rows)
    vol_120 = vol_60 = vol_prest = 0
    for (dtf,) in vol_rows:
        d = _parse_dt(dtf)
        if not d:
            continue
        if hoje <= d <= limite120:
            vol_120 += 1
            if d <= limite60:
                vol_60 += 1
        elif d < venc90:
            vol_prest += 1

    return MunicipioSummary(
        municipio=MunicipioResponse.model_validate(mun),
        total_convenios_estadual=est_count.scalar(),
        valor_total_estadual=float(est_valor.scalar()),
        total_voluntarias=total_vol,
        alertas_vigencia=alertas120.scalar() + vol_120,
        alertas_vigencia_60d=alertas60.scalar() + vol_60,
        alertas_prestacao_contas=prest_contas.scalar() + vol_prest,
    )
