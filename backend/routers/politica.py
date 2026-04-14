import unicodedata
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from database import get_db
from models import Emenda, Parlamentar, Municipio, DadosEleitorais, ConvenioFederal, ConvenioEstadual
from schemas.politica import EmendaPorDeputado, BenchmarkMunicipio, TopDeputado
from services.auth import get_current_user


def norm_name(s):
    if not s:
        return ""
    s = str(s).strip().upper()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

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
    ano: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Cross-reference TSE eleicoes with SICONV emendas.
    Returns ONLY parlamentares with: partido + votos>0 + emendas>0.
    ano: filtra as emendas por ano (opcional)
    """
    # TSE entries with partido and votos > 0
    tse_q = await db.execute(
        select(
            Parlamentar.id, Parlamentar.nome, Parlamentar.partido, Parlamentar.esfera,
            DadosEleitorais.votos, DadosEleitorais.cargo, DadosEleitorais.eleito,
        )
        .join(Parlamentar, Parlamentar.id == DadosEleitorais.parlamentar_id)
        .where(DadosEleitorais.municipio_id == municipio_id)
        .where(DadosEleitorais.ano_eleicao == ano_eleicao)
        .where(DadosEleitorais.votos > 0)
    )
    tse_entries = []
    for pid, nome, partido, esfera, votos, cargo, eleito in tse_q.all():
        if not partido:
            continue
        tse_entries.append({
            "id": pid, "nome": nome, "partido": partido, "esfera": esfera,
            "votos": votos, "cargo": cargo, "eleito": eleito,
            "norm": norm_name(nome),
        })

    # Emendas grouped by normalized name (excluding collective entries, filter by ano)
    em_q = (
        select(
            Parlamentar.nome,
            func.coalesce(func.sum(Emenda.valor), 0),
            func.count(Emenda.id),
        )
        .select_from(
            Emenda.__table__.join(Parlamentar.__table__, Emenda.parlamentar_id == Parlamentar.id)
        )
        .where(Emenda.municipio_id == municipio_id)
        .group_by(Parlamentar.nome)
    )
    if ano:
        em_q = em_q.where(Emenda.ano == ano)
    emendas_q = await db.execute(em_q)
    emendas_by_norm = {}
    for e_nome, e_valor, e_count in emendas_q.all():
        if not e_nome:
            continue
        upper = e_nome.upper().strip()
        # Skip collective/non-individual entries
        if any(
            kw in upper
            for kw in ["RELATOR", "COM.", "COMISS", "BANCADA", "SUBCOM", "GABINETE"]
        ):
            continue
        key = norm_name(e_nome)
        if key in emendas_by_norm:
            emendas_by_norm[key] = (
                emendas_by_norm[key][0] + float(e_valor),
                emendas_by_norm[key][1] + int(e_count),
            )
        else:
            emendas_by_norm[key] = (float(e_valor), int(e_count))

    items = []
    seen_ids = set()
    for t in tse_entries:
        if t["id"] in seen_ids:
            continue
        total_valor = 0.0
        total_count = 0
        if t["norm"] in emendas_by_norm:
            total_valor, total_count = emendas_by_norm[t["norm"]]
        else:
            tse_words = set(t["norm"].split())
            if len(tse_words) >= 2:
                for em_norm, (em_v, em_c) in emendas_by_norm.items():
                    em_words = set(em_norm.split())
                    if len(em_words) >= 2:
                        common = tse_words & em_words
                        if len(common) >= 2:
                            total_valor += em_v
                            total_count += em_c

        # Only include if emendas > 0
        if total_valor > 0:
            items.append({
                "parlamentar_id": t["id"],
                "parlamentar_nome": t["nome"],
                "partido": t["partido"],
                "esfera": t["esfera"],
                "cargo": t["cargo"],
                "votos": t["votos"],
                "eleito": t["eleito"],
                "total_emendas_valor": float(total_valor),
                "total_emendas_count": total_count,
                "valor_por_voto": float(total_valor) / t["votos"] if t["votos"] > 0 else 0,
            })
            seen_ids.add(t["id"])

    # Sort by emendas desc
    items.sort(key=lambda x: (x["total_emendas_valor"], x["votos"]), reverse=True)
    return items


@router.get("/emendas-por-funcao")
async def emendas_por_funcao(
    municipio_id: Optional[int] = None,
    ano: Optional[int] = None,
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
    if ano:
        q = q.where(Emenda.ano == ano)
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
    ano: Optional[int] = None,
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Retorna deputados com votos>0 E emendas>0 E partido preenchido,
    cruzando TSE com SICONV via match fuzzy por nome.
    ano: filtra as emendas por ano (opcional)
    """
    # Get all TSE votes grouped by normalized name
    tse_q = await db.execute(
        select(
            Parlamentar.id, Parlamentar.nome, Parlamentar.partido,
            DadosEleitorais.votos, DadosEleitorais.cargo, DadosEleitorais.eleito,
        )
        .join(Parlamentar, Parlamentar.id == DadosEleitorais.parlamentar_id)
        .where(DadosEleitorais.municipio_id == municipio_id)
        .where(DadosEleitorais.votos > 0)
    )
    tse_entries = []
    for pid, nome, partido, votos, cargo, eleito in tse_q.all():
        if not partido:
            continue
        tse_entries.append({
            "id": pid, "nome": nome, "partido": partido,
            "votos": votos, "cargo": cargo, "eleito": eleito,
            "norm": norm_name(nome),
        })

    # Get all emendas grouped by normalized name (filter by ano if provided)
    em_q = (
        select(
            Parlamentar.nome,
            func.coalesce(func.sum(Emenda.valor), 0),
        )
        .select_from(
            Emenda.__table__.join(Parlamentar.__table__, Emenda.parlamentar_id == Parlamentar.id)
        )
        .where(Emenda.municipio_id == municipio_id)
        .group_by(Parlamentar.nome)
    )
    if ano:
        em_q = em_q.where(Emenda.ano == ano)
    emendas_q = await db.execute(em_q)
    emendas_by_norm = {}
    for e_nome, e_valor in emendas_q.all():
        if not e_nome:
            continue
        # Skip collective entries (RELATOR GERAL, COM., BANCADA, etc.)
        upper = e_nome.upper().strip()
        if any(
            kw in upper
            for kw in ["RELATOR", "COM.", "COMISS", "BANCADA", "SUBCOM", "GABINETE"]
        ):
            continue
        key = norm_name(e_nome)
        emendas_by_norm[key] = emendas_by_norm.get(key, 0) + float(e_valor)

    # Cross-reference: for each TSE entry, find matching emenda
    deputados = []
    seen_ids = set()
    for t in tse_entries:
        if t["id"] in seen_ids:
            continue
        total_emendas = emendas_by_norm.get(t["norm"], 0)
        if total_emendas == 0:
            # Try fuzzy word match
            tse_words = set(t["norm"].split())
            if tse_words and len(tse_words) >= 2:
                for em_norm, em_v in emendas_by_norm.items():
                    em_words = set(em_norm.split())
                    if len(em_words) >= 2:
                        common = tse_words & em_words
                        if len(common) >= 2:  # at least 2 words in common
                            total_emendas += em_v

        # Only include if has emendas > 0
        if total_emendas > 0:
            deputados.append(TopDeputado(
                parlamentar_id=t["id"],
                parlamentar_nome=t["nome"],
                partido=t["partido"],
                votos=t["votos"],
                cargo=t["cargo"],
                eleito=t["eleito"],
                total_emendas_valor=total_emendas,
            ))
            seen_ids.add(t["id"])

    # Sort by emendas desc, then votos desc
    deputados.sort(key=lambda d: (d.total_emendas_valor or 0, d.votos or 0), reverse=True)
    return deputados[:limit]
