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
    Cross-reference TSE eleicoes with emendas (federal+estadual).
    Retorna TODOS com status: completo, sem_emendas, sem_tse, coletivo.
    """
    # TSE entries (com votos > 0)
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
        tse_entries.append({
            "id": pid, "nome": nome, "partido": partido, "esfera": esfera,
            "votos": votos, "cargo": cargo, "eleito": eleito,
            "norm": norm_name(nome),
        })

    # Get ALL emendas with parlamentar info
    em_q = (
        select(
            Parlamentar.id,
            Parlamentar.nome,
            Parlamentar.partido,
            Parlamentar.esfera,
            func.coalesce(func.sum(Emenda.valor), 0),
            func.count(Emenda.id),
        )
        .select_from(
            Emenda.__table__.join(Parlamentar.__table__, Emenda.parlamentar_id == Parlamentar.id)
        )
        .where(Emenda.municipio_id == municipio_id)
        .group_by(Parlamentar.id, Parlamentar.nome, Parlamentar.partido, Parlamentar.esfera)
    )
    if ano:
        em_q = em_q.where(Emenda.ano == ano)
    emendas_q = await db.execute(em_q)

    emendas_entries = []
    for pid, pnome, ppart, pesfera, e_valor, e_count in emendas_q.all():
        if not pnome:
            continue
        upper = pnome.upper().strip()
        is_coletivo = any(
            kw in upper
            for kw in ["RELATOR", "COM.", "COMISS", "BANCADA", "SUBCOM", "GABINETE", "BLOCO"]
        )
        emendas_entries.append({
            "id": pid, "nome": pnome, "partido": ppart, "esfera": pesfera,
            "valor": float(e_valor), "count": int(e_count),
            "norm": norm_name(pnome),
            "is_coletivo": is_coletivo,
        })

    result_map = {}
    matched_emenda_ids = set()

    for t in tse_entries:
        total_valor = 0.0
        total_count = 0
        matched_partido = t["partido"]
        for em in emendas_entries:
            if em["id"] in matched_emenda_ids or em["is_coletivo"]:
                continue
            exact = em["norm"] == t["norm"]
            fuzzy = False
            if not exact:
                tse_words = set(t["norm"].split())
                em_words = set(em["norm"].split())
                if len(tse_words) >= 2 and len(em_words) >= 2:
                    common = tse_words & em_words
                    if len(common) >= 2:
                        fuzzy = True
            if exact or fuzzy:
                total_valor += em["valor"]
                total_count += em["count"]
                matched_emenda_ids.add(em["id"])
                if not matched_partido and em["partido"]:
                    matched_partido = em["partido"]

        status = "completo" if total_valor > 0 else "sem_emendas"
        result_map[t["id"]] = {
            "parlamentar_id": t["id"],
            "parlamentar_nome": t["nome"],
            "partido": matched_partido,
            "esfera": t["esfera"],
            "cargo": t["cargo"],
            "votos": t["votos"],
            "eleito": t["eleito"],
            "total_emendas_valor": total_valor,
            "total_emendas_count": total_count,
            "valor_por_voto": total_valor / t["votos"] if t["votos"] > 0 else 0,
            "status": status,
        }

    # Unmatched emendas (sem TSE ou coletivos)
    for em in emendas_entries:
        if em["id"] in matched_emenda_ids or em["id"] in result_map:
            continue
        status = "coletivo" if em["is_coletivo"] else "sem_tse"
        result_map[em["id"]] = {
            "parlamentar_id": em["id"],
            "parlamentar_nome": em["nome"],
            "partido": em["partido"],
            "esfera": em["esfera"],
            "cargo": "Coletivo/Comissao" if em["is_coletivo"] else "Deputado",
            "votos": 0,
            "eleito": False,
            "total_emendas_valor": em["valor"],
            "total_emendas_count": em["count"],
            "valor_por_voto": 0,
            "status": status,
        }

    items = list(result_map.values())
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


@router.get("/relatorio-eleitoral")
async def relatorio_eleitoral(
    municipio_id: int,
    ano_eleicao: int = 2022,
    ano_emenda_inicio: int = 2023,
    ano_emenda_fim: int = 2026,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Atende a aba 6 da Planilha_Mapeamento_Processos: Top N mais votados +
    valor total de emendas no periodo.

    Retorno separado por esfera (federal/estadual). Para cada deputado:
    nome, partido, votos no municipio, qtd e valor de emendas no periodo,
    R$/voto (eficiencia da indicacao).
    """
    # 1. TSE: top N mais votados deste municipio + esfera
    out = {"municipio_id": municipio_id, "ano_eleicao": ano_eleicao,
           "periodo_emenda": f"{ano_emenda_inicio}-{ano_emenda_fim}",
           "federal": [], "estadual": []}

    for esfera in ("federal", "estadual"):
        tse = (await db.execute(
            select(
                Parlamentar.id, Parlamentar.nome, Parlamentar.partido,
                DadosEleitorais.votos, DadosEleitorais.cargo, DadosEleitorais.eleito,
            )
            .join(Parlamentar, Parlamentar.id == DadosEleitorais.parlamentar_id)
            .where(DadosEleitorais.municipio_id == municipio_id)
            .where(DadosEleitorais.ano_eleicao == ano_eleicao)
            .where(DadosEleitorais.votos > 0)
            .where(Parlamentar.esfera == esfera)
            .order_by(DadosEleitorais.votos.desc())
            .limit(limit)
        )).all()

        for pid, nome, part, votos, cargo, eleito in tse:
            # Buscar emendas do mesmo parlamentar OU de homonimo (match por nome)
            em_q = (await db.execute(
                select(
                    func.coalesce(func.sum(Emenda.valor), 0),
                    func.count(Emenda.id),
                )
                .select_from(
                    Emenda.__table__.join(Parlamentar.__table__, Emenda.parlamentar_id == Parlamentar.id)
                )
                .where(Emenda.municipio_id == municipio_id)
                .where(Emenda.ano.between(ano_emenda_inicio, ano_emenda_fim))
                .where(func.upper(Parlamentar.nome) == nome.upper())
            )).first()
            valor = float(em_q[0] or 0)
            qtd = int(em_q[1] or 0)
            out[esfera].append({
                "parlamentar_id": pid, "nome": nome, "partido": part,
                "cargo": cargo, "eleito": bool(eleito), "votos": votos,
                "qtd_emendas": qtd, "valor_emendas": valor,
                "reais_por_voto": (valor / votos) if votos else 0,
            })
    return out


@router.get("/top-deputados", response_model=list[TopDeputado])
async def top_deputados(
    municipio_id: int,
    ano_eleicao: Optional[int] = None,
    ano: Optional[int] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Retorna deputados cruzando TSE com SICONV/SIGCON.
    Inclui tanto os com votos quanto os com emendas, com status:
    - completo: tem votos > 0 E emendas > 0 (match TSE+SICONV)
    - sem_emendas: tem votos mas nao enviou emendas para este municipio
    - sem_tse: enviou emendas mas nao tem match no TSE (nome diferente ou fora do pilot)
    - coletivo: nao e pessoa fisica (COM./BANCADA/RELATOR)
    """
    # Get all TSE votes (all votos > 0)
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
        tse_entries.append({
            "id": pid, "nome": nome, "partido": partido,
            "votos": votos, "cargo": cargo, "eleito": eleito,
            "norm": norm_name(nome),
        })

    # Get all emendas grouped by normalized name (filter by ano if provided)
    em_q = (
        select(
            Parlamentar.id,
            Parlamentar.nome,
            Parlamentar.partido,
            func.coalesce(func.sum(Emenda.valor), 0),
        )
        .select_from(
            Emenda.__table__.join(Parlamentar.__table__, Emenda.parlamentar_id == Parlamentar.id)
        )
        .where(Emenda.municipio_id == municipio_id)
        .group_by(Parlamentar.id, Parlamentar.nome, Parlamentar.partido)
    )
    if ano:
        em_q = em_q.where(Emenda.ano == ano)
    emendas_q = await db.execute(em_q)
    # Build emendas list with full parlamentar info
    emendas_entries = []
    for pid, pnome, ppart, e_valor in emendas_q.all():
        if not pnome:
            continue
        upper = pnome.upper().strip()
        is_coletivo = any(
            kw in upper
            for kw in ["RELATOR", "COM.", "COMISS", "BANCADA", "SUBCOM", "GABINETE", "BLOCO"]
        )
        emendas_entries.append({
            "id": pid, "nome": pnome, "partido": ppart,
            "valor": float(e_valor),
            "norm": norm_name(pnome),
            "is_coletivo": is_coletivo,
        })

    # Cross-reference TSE with emendas
    result_map = {}
    matched_emenda_ids = set()

    for t in tse_entries:
        total_emendas = 0.0
        matched_partido = t["partido"]
        for em in emendas_entries:
            if em["id"] in matched_emenda_ids or em["is_coletivo"]:
                continue
            exact = em["norm"] == t["norm"]
            fuzzy = False
            if not exact:
                tse_words = set(t["norm"].split())
                em_words = set(em["norm"].split())
                if len(tse_words) >= 2 and len(em_words) >= 2:
                    common = tse_words & em_words
                    if len(common) >= 2:
                        fuzzy = True
            if exact or fuzzy:
                total_emendas += em["valor"]
                matched_emenda_ids.add(em["id"])
                if not matched_partido and em["partido"]:
                    matched_partido = em["partido"]

        status = "completo" if total_emendas > 0 else "sem_emendas"
        result_map[t["id"]] = {
            "parlamentar_id": t["id"],
            "parlamentar_nome": t["nome"],
            "partido": matched_partido,
            "votos": t["votos"],
            "cargo": t["cargo"],
            "eleito": t["eleito"],
            "total_emendas_valor": total_emendas,
            "status": status,
        }

    # Add unmatched emenda entries (have emendas but no TSE match)
    for em in emendas_entries:
        if em["id"] in matched_emenda_ids or em["id"] in result_map:
            continue
        status = "coletivo" if em["is_coletivo"] else "sem_tse"
        result_map[em["id"]] = {
            "parlamentar_id": em["id"],
            "parlamentar_nome": em["nome"],
            "partido": em["partido"],
            "votos": 0,
            "cargo": "Coletivo/Comissao" if em["is_coletivo"] else "Deputado",
            "eleito": False,
            "total_emendas_valor": em["valor"],
            "status": status,
        }

    items = list(result_map.values())
    items.sort(key=lambda x: (x["total_emendas_valor"], x["votos"]), reverse=True)
    return [TopDeputado(**it) for it in items[:limit]]
