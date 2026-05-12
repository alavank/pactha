from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, case
from datetime import date, timedelta
from typing import Optional
from database import get_db
from models import ConvenioFederal, ConvenioEstadual, Emenda, Parlamentar
from schemas.convenio import ConvenioResponse, ConvenioListResponse, ConvenioStats, AlertaVigencia
from services.auth import get_current_user
import math

router = APIRouter(prefix="/api/convenios", tags=["convenios"])


def federal_to_response(c: ConvenioFederal) -> ConvenioResponse:
    dias = None
    if c.dt_fim_vigencia:
        dias = (c.dt_fim_vigencia - date.today()).days
    return ConvenioResponse(
        id=c.id,
        esfera="federal",
        nr_convenio=c.nr_convenio,
        municipio_id=c.municipio_id,
        orgao_concedente=c.orgao_concedente,
        objeto=c.objeto,
        situacao=c.situacao,
        valor_total=float(c.valor_global) if c.valor_global else None,
        valor_repasse=float(c.valor_repasse) if c.valor_repasse else None,
        valor_empenhado=float(c.valor_empenhado) if c.valor_empenhado else None,
        valor_desembolsado=float(c.valor_desembolsado) if c.valor_desembolsado else None,
        valor_contrapartida=float(c.valor_contrapartida) if c.valor_contrapartida else None,
        dt_inicio=c.dt_inicio,
        dt_fim_vigencia=c.dt_fim_vigencia,
        dias_restantes=dias,
        ano=c.ano,
        programa=c.programa,
        fonte=c.fonte,
        tipo_programa=c.tipo_programa,
        banco=c.banco,
        agencia=c.agencia,
        conta_corrente=c.conta_corrente,
        saldo_bancario=float(c.saldo_bancario) if c.saldo_bancario else None,
        dt_saldo=c.dt_saldo,
        nr_sei=c.nr_sei,
        dt_empenho=c.dt_empenho,
        dt_desembolso=c.dt_desembolso,
    )


def estadual_to_response(c: ConvenioEstadual) -> ConvenioResponse:
    dias = None
    if c.dt_vigencia_atual:
        dias = (c.dt_vigencia_atual - date.today()).days
    elif c.dt_vigencia_final:
        dias = (c.dt_vigencia_final - date.today()).days
    return ConvenioResponse(
        id=c.id,
        esfera="estadual",
        nr_sigcon=c.nr_sigcon,
        municipio_id=c.municipio_id,
        orgao_concedente=c.orgao_concedente,
        objeto=c.objeto,
        situacao=c.situacao,
        valor_total=float(c.valor_total) if c.valor_total else None,
        valor_repasse=float(c.valor_concedente) if c.valor_concedente else None,
        valor_empenhado=float(c.valor_emenda_parlamentar) if c.valor_emenda_parlamentar else None,
        valor_desembolsado=float(c.valor_repassado) if c.valor_repassado else None,
        valor_contrapartida=float(c.valor_contrapartida) if c.valor_contrapartida else None,
        dt_inicio=c.dt_vigencia_inicial,
        dt_fim_vigencia=c.dt_vigencia_atual or c.dt_vigencia_final,
        dias_restantes=dias,
        ano=c.ano,
        etapa_sigcon=c.etapa_sigcon,
        etapa_sigcon_nr=c.etapa_sigcon_nr,
        fonte=c.fonte,
        tipo_programa=c.tipo_programa,
        banco=c.banco,
        agencia=c.agencia,
        conta_corrente=c.conta_corrente,
        saldo_bancario=float(c.saldo_bancario) if c.saldo_bancario else None,
        dt_saldo=c.dt_saldo,
        nr_sei=c.nr_sei,
        dt_empenho=c.dt_empenho,
        dt_desembolso=c.dt_desembolso,
    )


@router.get("/situacoes")
async def list_situacoes(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Distinct situacoes from both federal and estadual, optionally filtered by municipio."""
    situacoes = set()

    q1 = select(ConvenioFederal.situacao).distinct().where(ConvenioFederal.situacao.is_not(None))
    if municipio_id:
        q1 = q1.where(ConvenioFederal.municipio_id == municipio_id)
    r1 = await db.execute(q1)
    for row in r1.all():
        if row[0]:
            situacoes.add(row[0].strip())

    q2 = select(ConvenioEstadual.situacao).distinct().where(ConvenioEstadual.situacao.is_not(None))
    if municipio_id:
        q2 = q2.where(ConvenioEstadual.municipio_id == municipio_id)
    r2 = await db.execute(q2)
    for row in r2.all():
        if row[0]:
            situacoes.add(row[0].strip())

    return sorted(situacoes)


@router.get("/anos")
async def list_anos(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Distinct years with convenios."""
    anos = set()

    q1 = select(ConvenioFederal.ano).distinct().where(ConvenioFederal.ano.is_not(None))
    if municipio_id:
        q1 = q1.where(ConvenioFederal.municipio_id == municipio_id)
    r1 = await db.execute(q1)
    for row in r1.all():
        if row[0]:
            anos.add(int(row[0]))

    q2 = select(ConvenioEstadual.ano).distinct().where(ConvenioEstadual.ano.is_not(None))
    if municipio_id:
        q2 = q2.where(ConvenioEstadual.municipio_id == municipio_id)
    r2 = await db.execute(q2)
    for row in r2.all():
        if row[0]:
            anos.add(int(row[0]))

    return sorted(anos, reverse=True)


@router.get("", response_model=ConvenioListResponse)
async def list_convenios(
    municipio_id: Optional[int] = None,
    esfera: Optional[str] = None,
    ano: Optional[int] = None,
    situacao: Optional[str] = None,
    fonte: Optional[str] = None,
    parlamentar_id: Optional[int] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    items = []
    total = 0

    # Federal
    if esfera in (None, "federal"):
        q = select(ConvenioFederal)
        q_count = select(func.count()).select_from(ConvenioFederal)
        if municipio_id:
            q = q.where(ConvenioFederal.municipio_id == municipio_id)
            q_count = q_count.where(ConvenioFederal.municipio_id == municipio_id)
        if ano:
            q = q.where(ConvenioFederal.ano == ano)
            q_count = q_count.where(ConvenioFederal.ano == ano)
        if situacao:
            q = q.where(ConvenioFederal.situacao.ilike(f"%{situacao}%"))
            q_count = q_count.where(ConvenioFederal.situacao.ilike(f"%{situacao}%"))
        if fonte:
            q = q.where(ConvenioFederal.fonte == fonte)
            q_count = q_count.where(ConvenioFederal.fonte == fonte)
        if search:
            q = q.where(or_(
                ConvenioFederal.objeto.ilike(f"%{search}%"),
                ConvenioFederal.nr_convenio.ilike(f"%{search}%"),
            ))
            q_count = q_count.where(or_(
                ConvenioFederal.objeto.ilike(f"%{search}%"),
                ConvenioFederal.nr_convenio.ilike(f"%{search}%"),
            ))
        if parlamentar_id:
            q = q.join(Emenda, Emenda.convenio_federal_id == ConvenioFederal.id).where(
                Emenda.parlamentar_id == parlamentar_id
            )
            q_count = q_count.join(Emenda, Emenda.convenio_federal_id == ConvenioFederal.id).where(
                Emenda.parlamentar_id == parlamentar_id
            )

        count_result = await db.execute(q_count)
        total += count_result.scalar()

        q = q.order_by(ConvenioFederal.dt_fim_vigencia.asc().nullslast())
        if esfera == "federal":
            q = q.offset((page - 1) * per_page).limit(per_page)
        result = await db.execute(q)
        items.extend([federal_to_response(c) for c in result.scalars().all()])

    # Estadual
    if esfera in (None, "estadual"):
        q = select(ConvenioEstadual)
        q_count = select(func.count()).select_from(ConvenioEstadual)
        if municipio_id:
            q = q.where(ConvenioEstadual.municipio_id == municipio_id)
            q_count = q_count.where(ConvenioEstadual.municipio_id == municipio_id)
        if ano:
            q = q.where(ConvenioEstadual.ano == ano)
            q_count = q_count.where(ConvenioEstadual.ano == ano)
        if situacao:
            q = q.where(ConvenioEstadual.situacao.ilike(f"%{situacao}%"))
            q_count = q_count.where(ConvenioEstadual.situacao.ilike(f"%{situacao}%"))
        if fonte:
            q = q.where(ConvenioEstadual.fonte == fonte)
            q_count = q_count.where(ConvenioEstadual.fonte == fonte)
        if search:
            q = q.where(or_(
                ConvenioEstadual.objeto.ilike(f"%{search}%"),
                ConvenioEstadual.nr_sigcon.ilike(f"%{search}%"),
            ))
            q_count = q_count.where(or_(
                ConvenioEstadual.objeto.ilike(f"%{search}%"),
                ConvenioEstadual.nr_sigcon.ilike(f"%{search}%"),
            ))

        count_result = await db.execute(q_count)
        total += count_result.scalar()

        q = q.order_by(ConvenioEstadual.dt_vigencia_atual.asc().nullslast())
        if esfera == "estadual":
            q = q.offset((page - 1) * per_page).limit(per_page)
        result = await db.execute(q)
        items.extend([estadual_to_response(c) for c in result.scalars().all()])

    # Sort combined by dias_restantes
    items.sort(key=lambda x: x.dias_restantes if x.dias_restantes is not None else 99999)

    # Paginate combined
    if esfera is None:
        start = (page - 1) * per_page
        items = items[start:start + per_page]

    pages = math.ceil(total / per_page) if total > 0 else 1
    return ConvenioListResponse(items=items, total=total, page=page, per_page=per_page, pages=pages)


@router.get("/stats", response_model=ConvenioStats)
async def convenio_stats(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    stats = ConvenioStats()

    # Federal stats
    q = select(
        func.count().label("cnt"),
        func.coalesce(func.sum(ConvenioFederal.valor_global), 0).label("total"),
        func.coalesce(func.sum(ConvenioFederal.valor_empenhado), 0).label("empenhado"),
        func.coalesce(func.sum(ConvenioFederal.valor_desembolsado), 0).label("desembolsado"),
    )
    if municipio_id:
        q = q.where(ConvenioFederal.municipio_id == municipio_id)
    result = await db.execute(q)
    row = result.one()
    fed_count = row.cnt
    stats.total_convenios += fed_count
    stats.valor_total += float(row.total)
    stats.valor_empenhado += float(row.empenhado)
    stats.valor_desembolsado += float(row.desembolsado)
    stats.por_esfera["federal"] = fed_count

    # Estadual stats
    q = select(
        func.count().label("cnt"),
        func.coalesce(func.sum(ConvenioEstadual.valor_total), 0).label("total"),
    )
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    result = await db.execute(q)
    row = result.one()
    est_count = row.cnt
    stats.total_convenios += est_count
    stats.valor_total += float(row.total)
    stats.por_esfera["estadual"] = est_count

    # Por situacao federal
    q = select(ConvenioFederal.situacao, func.count()).group_by(ConvenioFederal.situacao)
    if municipio_id:
        q = q.where(ConvenioFederal.municipio_id == municipio_id)
    result = await db.execute(q)
    for sit, cnt in result.all():
        if sit:
            stats.por_situacao[sit] = stats.por_situacao.get(sit, 0) + cnt

    return stats


@router.get("/alertas", response_model=list[AlertaVigencia])
async def alertas_vigencia(
    municipio_id: Optional[int] = None,
    dias: int = Query(120, ge=1),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    limite = date.today() + timedelta(days=dias)
    alertas = []

    # Federal
    q = select(ConvenioFederal).where(
        ConvenioFederal.dt_fim_vigencia <= limite,
        ConvenioFederal.dt_fim_vigencia >= date.today(),
    )
    if municipio_id:
        q = q.where(ConvenioFederal.municipio_id == municipio_id)
    q = q.order_by(ConvenioFederal.dt_fim_vigencia.asc())
    result = await db.execute(q)
    for c in result.scalars().all():
        dias_rest = (c.dt_fim_vigencia - date.today()).days
        alertas.append(AlertaVigencia(
            id=c.id, esfera="federal", nr_convenio=c.nr_convenio,
            objeto=c.objeto, orgao_concedente=c.orgao_concedente,
            dt_fim_vigencia=c.dt_fim_vigencia, dias_restantes=dias_rest,
            valor_total=float(c.valor_global) if c.valor_global else None,
            situacao=c.situacao,
        ))

    # Estadual
    q = select(ConvenioEstadual).where(
        ConvenioEstadual.dt_vigencia_atual <= limite,
        ConvenioEstadual.dt_vigencia_atual >= date.today(),
    )
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    q = q.order_by(ConvenioEstadual.dt_vigencia_atual.asc())
    result = await db.execute(q)
    for c in result.scalars().all():
        dias_rest = (c.dt_vigencia_atual - date.today()).days
        alertas.append(AlertaVigencia(
            id=c.id, esfera="estadual", nr_sigcon=c.nr_sigcon,
            objeto=c.objeto, orgao_concedente=c.orgao_concedente,
            dt_fim_vigencia=c.dt_vigencia_atual, dias_restantes=dias_rest,
            valor_total=float(c.valor_total) if c.valor_total else None,
            situacao=c.situacao,
        ))

    alertas.sort(key=lambda x: x.dias_restantes)
    return alertas
