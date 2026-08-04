"""Endpoint para Emendas Parlamentares Estaduais (SIGCON-MG / Pesquisar Emendas Por Convenente)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional
from database import get_db
from services.auth import get_current_user, ensure_municipio_access, ensure_tela
from services.registro_rotas import exige
from models.user import User

router = APIRouter(prefix="/api/emendas-estaduais", tags=["emendas-estaduais"])


@router.get("", dependencies=[exige("emendas.ver")])
async def list_emendas_estaduais(
    municipio_id: Optional[int] = None,
    # Plurais ao lado dos singulares (aditivo): quem ja manda `ano=` ou `tipo=`
    # continua funcionando. Mesmo padrao de routers/convenios.py.
    ano: Optional[int] = None,
    anos: Optional[list[int]] = Query(None, description="Multi-select de ano"),
    responsavel: Optional[str] = None,
    tipo: Optional[str] = None,
    tipos: Optional[list[str]] = Query(None, description="Multi-select de tipo de indicacao"),
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "emendas")
    where_parts = ["1=1"]
    params: dict = {}
    if municipio_id:
        where_parts.append("municipio_id = :mun")
        params["mun"] = municipio_id
    _anos = anos or ([ano] if ano else [])
    if _anos:
        where_parts.append("ano = ANY(:anos)")
        params["anos"] = _anos
    if responsavel:
        where_parts.append("nome_responsavel ILIKE :resp")
        params["resp"] = f"%{responsavel}%"
    _tipos = tipos or ([tipo] if tipo else [])
    if _tipos:
        # UNIAO: marcar "Convenio" e "Aplicacao Direta" traz os dois. Continua
        # ILIKE por item porque o rotulo gravado varia em acento e caixa.
        cond = " OR ".join(f"tipo_indicacao ILIKE :tipo{i}" for i in range(len(_tipos)))
        where_parts.append(f"({cond})")
        for i, t in enumerate(_tipos):
            params[f"tipo{i}"] = f"%{t}%"
    if status:
        where_parts.append("status_indicacao ILIKE :status")
        params["status"] = f"%{status}%"

    where_sql = " AND ".join(where_parts)

    # Total
    r = await db.execute(text(f"SELECT count(*) FROM emendas_estaduais WHERE {where_sql}"), params)
    total = r.scalar() or 0

    # Items - ordenar por ano DESC, valor DESC
    offset = (page - 1) * per_page
    params["limit"] = per_page
    params["offset"] = offset
    r = await db.execute(text(f"""
        SELECT id, municipio_id, nr_indicacao, nome_responsavel, tipo_indicacao,
               uo_codigo, uo_sigla, cnpj_beneficiario, beneficiario,
               grupo_despesa, tipo_atendimento, valor_indicacao, status_indicacao, ano
        FROM emendas_estaduais
        WHERE {where_sql}
        ORDER BY ano DESC NULLS LAST, valor_indicacao DESC NULLS LAST
        LIMIT :limit OFFSET :offset
    """), params)
    items = [dict(row._mapping) for row in r.all()]
    # Convert valores Decimal -> float
    for it in items:
        if it.get("valor_indicacao") is not None:
            it["valor_indicacao"] = float(it["valor_indicacao"])

    pages = (total + per_page - 1) // per_page if total > 0 else 1
    return {"items": items, "total": total, "page": page, "per_page": per_page, "pages": pages}


@router.get("/anos", dependencies=[exige("emendas.ver")])
async def list_anos(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Anos distintos com emendas."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "emendas")
    params: dict = {}
    where = "ano IS NOT NULL"
    if municipio_id:
        where += " AND municipio_id = :mun"
        params["mun"] = municipio_id
    r = await db.execute(text(f"SELECT DISTINCT ano FROM emendas_estaduais WHERE {where} ORDER BY ano DESC"), params)
    return [row[0] for row in r.all()]


@router.get("/responsaveis", dependencies=[exige("emendas.ver")])
async def list_responsaveis(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Responsaveis distintos."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "emendas")
    params: dict = {}
    where = "nome_responsavel IS NOT NULL AND nome_responsavel != ''"
    if municipio_id:
        where += " AND municipio_id = :mun"
        params["mun"] = municipio_id
    r = await db.execute(text(f"SELECT DISTINCT nome_responsavel FROM emendas_estaduais WHERE {where} ORDER BY nome_responsavel"), params)
    return [row[0] for row in r.all()]


@router.get("/stats", dependencies=[exige("emendas.ver")])
async def stats(
    municipio_id: Optional[int] = None,
    # O plural TEM que existir aqui tambem. Sem ele, a tela cai no contorno de
    # "so manda o ano se for exatamente um" — e com o mandato marcado a tabela
    # filtra enquanto os 4 cards do topo somam a base inteira, se contradizendo
    # na mesma tela. Card que discorda da lista embaixo dele destroi a confianca
    # no numero mais rapido do que numero nenhum.
    ano: Optional[int] = None,
    anos: Optional[list[int]] = Query(None, description="Multi-select de ano"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "emendas")
    where = "1=1"
    params: dict = {}
    if municipio_id:
        where += " AND municipio_id = :mun"
        params["mun"] = municipio_id
    _anos = anos or ([ano] if ano else [])
    if _anos:
        where += " AND ano = ANY(:anos)"
        params["anos"] = _anos
    r = await db.execute(text(f"""
        SELECT
            count(*) AS total,
            COALESCE(SUM(valor_indicacao), 0) AS valor_total,
            count(DISTINCT nome_responsavel) AS responsaveis,
            count(*) FILTER (WHERE status_indicacao ILIKE '%aprovad%') AS aprovadas
        FROM emendas_estaduais WHERE {where}
    """), params)
    row = r.first()
    return {
        "total": row[0],
        "valor_total": float(row[1]) if row[1] else 0,
        "responsaveis": row[2],
        "aprovadas": row[3],
    }
