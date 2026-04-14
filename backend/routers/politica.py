from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from database import get_db
from models import Emenda, Parlamentar, Municipio, DadosEleitorais, ConvenioFederal, ConvenioEstadual
from schemas.politica import EmendaPorDeputado, BenchmarkMunicipio, TopDeputado
from services.auth import get_current_user

router = APIRouter(prefix="/api/politica", tags=["politica"])


@router.get("/emendas-por-deputado", response_model=list[EmendaPorDeputado])
async def emendas_por_deputado(
    municipio_id: Optional[int] = None,
    ano: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    q = (
        select(
            Parlamentar.id,
            Parlamentar.nome,
            Parlamentar.partido,
            Parlamentar.esfera,
            func.coalesce(func.sum(Emenda.valor), 0).label("total_valor"),
            func.count(Emenda.id).label("total_emendas"),
        )
        .join(Emenda, Emenda.parlamentar_id == Parlamentar.id)
        .group_by(Parlamentar.id, Parlamentar.nome, Parlamentar.partido, Parlamentar.esfera)
    )
    if municipio_id:
        q = q.where(Emenda.municipio_id == municipio_id)
    if ano:
        q = q.where(Emenda.ano == ano)
    q = q.order_by(func.sum(Emenda.valor).desc())

    result = await db.execute(q)
    return [
        EmendaPorDeputado(
            parlamentar_id=row[0],
            parlamentar_nome=row[1],
            partido=row[2],
            esfera=row[3],
            total_valor=float(row[4]),
            total_emendas=row[5],
        )
        for row in result.all()
    ]


@router.get("/benchmark-municipios", response_model=list[BenchmarkMunicipio])
async def benchmark_municipios(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    results = []
    municipios = await db.execute(select(Municipio).where(Municipio.active == True))
    for mun in municipios.scalars().all():
        # Emendas total
        emendas_q = await db.execute(
            select(func.coalesce(func.sum(Emenda.valor), 0))
            .where(Emenda.municipio_id == mun.id)
        )
        total_emendas = float(emendas_q.scalar())

        # Convenios count and value
        fed_q = await db.execute(
            select(func.count(), func.coalesce(func.sum(ConvenioFederal.valor_global), 0))
            .where(ConvenioFederal.municipio_id == mun.id)
        )
        fed_row = fed_q.one()
        est_q = await db.execute(
            select(func.count(), func.coalesce(func.sum(ConvenioEstadual.valor_total), 0))
            .where(ConvenioEstadual.municipio_id == mun.id)
        )
        est_row = est_q.one()

        results.append(BenchmarkMunicipio(
            municipio_id=mun.id,
            municipio_nome=mun.nome,
            total_emendas=total_emendas,
            total_convenios=fed_row[0] + est_row[0],
            total_valor_convenios=float(fed_row[1]) + float(est_row[1]),
        ))

    results.sort(key=lambda x: x.total_valor_convenios, reverse=True)
    return results


@router.get("/cruzamento-eleitoral")
async def cruzamento_eleitoral(
    municipio_id: int,
    ano_eleicao: int = 2022,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Cross-reference electoral data with parliamentary amendments."""
    q = (
        select(
            DadosEleitorais,
            Parlamentar.nome,
            Parlamentar.partido,
            Parlamentar.esfera,
        )
        .join(Parlamentar, Parlamentar.id == DadosEleitorais.parlamentar_id)
        .where(DadosEleitorais.municipio_id == municipio_id)
        .where(DadosEleitorais.ano_eleicao == ano_eleicao)
        .order_by(DadosEleitorais.votos.desc())
    )
    result = await db.execute(q)
    items = []
    for de, nome, partido, esfera in result.all():
        emenda_q = await db.execute(
            select(
                func.coalesce(func.sum(Emenda.valor), 0),
                func.count(Emenda.id),
            )
            .where(Emenda.parlamentar_id == de.parlamentar_id)
            .where(Emenda.municipio_id == municipio_id)
        )
        total_valor, total_count = emenda_q.one()
        items.append({
            "parlamentar_id": de.parlamentar_id,
            "parlamentar_nome": nome,
            "partido": partido,
            "esfera": esfera,
            "cargo": de.cargo,
            "votos": de.votos,
            "eleito": de.eleito,
            "total_emendas_valor": float(total_valor),
            "total_emendas_count": total_count,
            "valor_por_voto": float(total_valor) / de.votos if de.votos > 0 else 0,
        })
    return items


@router.get("/emendas-por-funcao")
async def emendas_por_funcao(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Group emendas by area/funcao."""
    q = (
        select(
            Emenda.funcao,
            func.coalesce(func.sum(Emenda.valor), 0).label("total"),
            func.count(Emenda.id).label("count"),
        )
        .group_by(Emenda.funcao)
    )
    if municipio_id:
        q = q.where(Emenda.municipio_id == municipio_id)
    q = q.order_by(func.sum(Emenda.valor).desc())

    result = await db.execute(q)
    return [
        {"funcao": row[0] or "Nao classificada", "total_valor": float(row[1]), "count": row[2]}
        for row in result.all()
    ]


@router.get("/top-deputados", response_model=list[TopDeputado])
async def top_deputados(
    municipio_id: int,
    ano_eleicao: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    q = (
        select(
            DadosEleitorais,
            Parlamentar.nome,
            Parlamentar.partido,
        )
        .join(Parlamentar, Parlamentar.id == DadosEleitorais.parlamentar_id)
        .where(DadosEleitorais.municipio_id == municipio_id)
    )
    if ano_eleicao:
        q = q.where(DadosEleitorais.ano_eleicao == ano_eleicao)
    q = q.order_by(DadosEleitorais.votos.desc()).limit(10)

    result = await db.execute(q)
    deputados = []
    for de, nome, partido in result.all():
        # Get total emendas for this deputy in this municipality
        emenda_q = await db.execute(
            select(func.coalesce(func.sum(Emenda.valor), 0))
            .where(Emenda.parlamentar_id == de.parlamentar_id)
            .where(Emenda.municipio_id == municipio_id)
        )
        total_emendas = float(emenda_q.scalar())

        deputados.append(TopDeputado(
            parlamentar_id=de.parlamentar_id,
            parlamentar_nome=nome,
            partido=partido,
            votos=de.votos,
            cargo=de.cargo,
            eleito=de.eleito,
            total_emendas_valor=total_emendas,
        ))
    return deputados
