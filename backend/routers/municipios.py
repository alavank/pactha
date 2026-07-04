from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from datetime import date, datetime, timedelta
from database import get_db
from models import Municipio, ConvenioEstadual
from models.user import User
from schemas.municipio import MunicipioResponse, MunicipioSummary
from services.auth import get_current_user, ensure_municipio_access

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
    current: User = Depends(get_current_user),
):
    q = select(Municipio).where(Municipio.active == True)
    # Escopo: nao-admin so ve os municipios atribuidos a ele
    allowed = getattr(current, "allowed_municipio_ids", None)
    if allowed is not None:
        if not allowed:
            return []
        q = q.where(Municipio.id.in_(allowed))
    result = await db.execute(q.order_by(Municipio.nome))
    return [MunicipioResponse.model_validate(m) for m in result.scalars().all()]


@router.get("/{municipio_id}/summary", response_model=MunicipioSummary)
async def municipio_summary(
    municipio_id: int,
    ano: int | None = Query(None, description="Filtra os KPIs por ano (None=todos)"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    result = await db.execute(select(Municipio).where(Municipio.id == municipio_id))
    mun = result.scalar_one_or_none()
    if not mun:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Municipio nao encontrado")

    # Filtro de ano — SIGCON usa a coluna `ano`; TransfereGov deriva do sufixo do
    # numero_proposta ("xxx/AAAA"). None = todos os anos.
    def _ano_est(q):
        return q.where(ConvenioEstadual.ano == ano) if ano else q
    ano_txt = str(ano) if ano else None
    vol_ano_sql = " AND split_part(numero_proposta, '/', 2) = :ano_txt" if ano else ""

    est_count = await db.execute(_ano_est(
        select(func.count()).select_from(ConvenioEstadual).where(ConvenioEstadual.municipio_id == municipio_id)
    ))
    est_valor = await db.execute(_ano_est(
        select(func.coalesce(func.sum(ConvenioEstadual.valor_total), 0))
        .where(ConvenioEstadual.municipio_id == municipio_id)
    ))

    hoje = date.today()
    limite120 = hoje + timedelta(days=120)
    limite60 = hoje + timedelta(days=60)
    # Vencidos ha +90 dias -> prestacao de contas obrigatoria
    venc90 = hoje - timedelta(days=90)
    alertas120 = await db.execute(_ano_est(
        select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id == municipio_id)
        .where(ConvenioEstadual.dt_vigencia_atual <= limite120)
        .where(ConvenioEstadual.dt_vigencia_atual >= hoje)
    ))
    alertas60 = await db.execute(_ano_est(
        select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id == municipio_id)
        .where(ConvenioEstadual.dt_vigencia_atual <= limite60)
        .where(ConvenioEstadual.dt_vigencia_atual >= hoje)
    ))
    prest_contas = await db.execute(_ano_est(
        select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id == municipio_id)
        .where(ConvenioEstadual.dt_vigencia_atual < venc90)
    ))

    # TransfereGov Voluntarias (dt_fim_vigencia eh string dd/mm/yyyy -> parse em Python)
    vol_params = {"m": municipio_id}
    if ano:
        vol_params["ano_txt"] = ano_txt
    vol = await db.execute(text(
        "SELECT dt_fim_vigencia, COALESCE(valor_global, valor_repasse, 0) "
        "FROM transferegov_propostas WHERE municipio_id = :m" + vol_ano_sql
    ), vol_params)
    vol_rows = vol.fetchall()
    total_vol = len(vol_rows)
    vol_120 = vol_60 = vol_prest = 0
    vol_valor = 0.0
    for (dtf, val) in vol_rows:
        try:
            vol_valor += float(val or 0)
        except (TypeError, ValueError):
            pass
        d = _parse_dt(dtf)
        if not d:
            continue
        if hoje <= d <= limite120:
            vol_120 += 1
            if d <= limite60:
                vol_60 += 1
        elif d < venc90:
            vol_prest += 1

    prest_est = prest_contas.scalar()
    return MunicipioSummary(
        municipio=MunicipioResponse.model_validate(mun),
        total_convenios_estadual=est_count.scalar(),
        valor_total_estadual=float(est_valor.scalar()),
        valor_total_federal=vol_valor,
        total_voluntarias=total_vol,
        alertas_vigencia=alertas120.scalar() + vol_120,
        alertas_vigencia_60d=alertas60.scalar() + vol_60,
        alertas_prestacao_contas=prest_est + vol_prest,
        alertas_prestacao_contas_estadual=prest_est,
        alertas_prestacao_contas_federal=vol_prest,
    )
