"""
Endpoints REST das 6 fontes novas:
- /api/dou           : busca DOU
- /api/sancoes/ceis  : checagem CNPJ no CEIS
- /api/oportunidades : programas federais abertos
- /api/deputados     : perfil + despesas + proposicoes + emendas
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional

from database import get_db
from services.auth import get_current_user


router = APIRouter(tags=["fontes-extras"])


# ============ DOU ============
@router.get("/api/dou")
async def listar_dou(
    keyword: Optional[str] = None,
    municipio: Optional[str] = None,
    dt_inicio: Optional[str] = None,
    dt_fim: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    q = "SELECT id, dt_publicacao, secao, orgao, titulo, LEFT(texto, 400) as preview, url_pdf, municipio_match FROM dou_publicacoes WHERE 1=1"
    params = {}
    if keyword:
        q += " AND (titulo ILIKE :kw OR texto ILIKE :kw)"
        params["kw"] = f"%{keyword}%"
    if municipio:
        q += " AND municipio_match ILIKE :m"
        params["m"] = f"%{municipio}%"
    if dt_inicio:
        q += " AND dt_publicacao >= :di"
        params["di"] = dt_inicio
    if dt_fim:
        q += " AND dt_publicacao <= :df"
        params["df"] = dt_fim
    q += " ORDER BY dt_publicacao DESC, id DESC LIMIT :l"
    params["l"] = limit
    r = (await db.execute(text(q), params)).all()
    return {"total": len(r), "items": [dict(zip(
        ["id","dt","secao","orgao","titulo","preview","url_pdf","municipio_match"], row)) for row in r]}


# ============ CEIS (Sanções) ============
@router.get("/api/sancoes/ceis")
async def listar_sancoes(
    cpf_cnpj: Optional[str] = None,
    razao_social: Optional[str] = None,
    ativa: bool = True,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Busca CEIS. Por padrao retorna so sancoes ATIVAS (dt_fim_sancao >= hoje OU NULL)."""
    q = "SELECT id, cpf_cnpj, razao_social, tipo_sancao, dt_inicio_sancao, dt_fim_sancao, orgao_sancionador FROM sancoes_ceis WHERE 1=1"
    params = {}
    if cpf_cnpj:
        cnpj_clean = cpf_cnpj.replace(".","").replace("/","").replace("-","").strip()
        q += " AND cpf_cnpj = :c"
        params["c"] = cnpj_clean
    if razao_social:
        q += " AND upper(razao_social) LIKE :r"
        params["r"] = f"%{razao_social.upper()}%"
    if ativa:
        q += " AND (dt_fim_sancao IS NULL OR dt_fim_sancao >= CURRENT_DATE)"
    q += " ORDER BY dt_inicio_sancao DESC LIMIT :l"
    params["l"] = limit
    r = (await db.execute(text(q), params)).all()
    return {"total": len(r), "items": [dict(zip(
        ["id","cpf_cnpj","razao_social","tipo_sancao","dt_inicio","dt_fim","orgao"], row)) for row in r]}


@router.get("/api/sancoes/checar/{cnpj}")
async def checar_fornecedor(
    cnpj: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Checagem rapida: este CNPJ esta no CEIS hoje?"""
    cnpj_clean = cnpj.replace(".","").replace("/","").replace("-","").strip()
    r = (await db.execute(text("""
      SELECT cpf_cnpj, razao_social, tipo_sancao, dt_inicio_sancao, dt_fim_sancao, orgao_sancionador
      FROM sancoes_ceis
      WHERE cpf_cnpj = :c
        AND (dt_fim_sancao IS NULL OR dt_fim_sancao >= CURRENT_DATE)
      ORDER BY dt_inicio_sancao DESC
    """), {"c": cnpj_clean})).all()
    return {
        "cnpj": cnpj_clean,
        "tem_sancao_ativa": len(r) > 0,
        "sancoes": [dict(zip(["cnpj","razao","tipo","inicio","fim","orgao"], row)) for row in r],
    }


# ============ Oportunidades ============
@router.get("/api/oportunidades")
async def listar_oportunidades(
    orgao: Optional[str] = None,
    aberto_apenas: bool = True,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    q = "SELECT id_programa, nome_programa, orgao, objetivo, situacao, dt_inicio_inscricao, dt_fim_inscricao, valor_minimo, valor_maximo FROM programas_federais WHERE 1=1"
    params = {}
    if aberto_apenas:
        q += " AND (situacao ILIKE 'Disponi%' OR situacao ILIKE 'Aberto%')"
        q += " AND (dt_fim_inscricao IS NULL OR dt_fim_inscricao >= CURRENT_DATE)"
    if orgao:
        q += " AND upper(orgao) LIKE :o"
        params["o"] = f"%{orgao.upper()}%"
    q += " ORDER BY dt_fim_inscricao ASC NULLS LAST LIMIT :l"
    params["l"] = limit
    r = (await db.execute(text(q), params)).all()
    return {"total": len(r), "items": [dict(zip(
        ["id","nome","orgao","objetivo","situacao","inicio","fim","valor_min","valor_max"], row)) for row in r]}


# ============ Deputados ============
@router.get("/api/deputados/{parlamentar_id}/perfil")
async def perfil_deputado(
    parlamentar_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Perfil completo: nome+partido + total emendas + despesas CEAP + proposicoes."""
    p = (await db.execute(text("""
      SELECT id, nome, partido, uf, esfera, legislatura, external_id
      FROM parlamentares WHERE id = :p
    """), {"p": parlamentar_id})).first()
    if not p:
        raise HTTPException(404, "Parlamentar nao encontrado")
    out = {"parlamentar": dict(zip(["id","nome","partido","uf","esfera","legislatura","external_id"], p))}

    em = (await db.execute(text("""
      SELECT COUNT(*), COALESCE(SUM(valor),0)::float
      FROM emendas WHERE parlamentar_id = :p
    """), {"p": parlamentar_id})).first()
    out["emendas"] = {"qtd": em[0], "soma": em[1]}

    desp = (await db.execute(text("""
      SELECT ano, COUNT(*), COALESCE(SUM(valor_liquido),0)::float
      FROM camara_despesas WHERE parlamentar_id = :p
      GROUP BY ano ORDER BY ano DESC LIMIT 5
    """), {"p": parlamentar_id})).all()
    out["despesas_ceap_por_ano"] = [dict(zip(["ano","qtd","soma"], row)) for row in desp]

    prop = (await db.execute(text("""
      SELECT id, sigla_tipo, numero, ano, ementa, situacao
      FROM camara_proposicoes WHERE autor_id_camara = (
        SELECT CAST(NULLIF(external_id, '') AS INTEGER) FROM parlamentares WHERE id = :p
      ) ORDER BY ano DESC, numero DESC LIMIT 20
    """), {"p": parlamentar_id})).all()
    out["proposicoes_recentes"] = [dict(zip(["id","tipo","nr","ano","ementa","situacao"], row)) for row in prop]
    return out


@router.get("/api/deputados/{parlamentar_id}/despesas")
async def despesas_deputado(
    parlamentar_id: int,
    ano: Optional[int] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    q = """SELECT ano, mes, tipo_despesa, fornecedor, valor_liquido::float, dt_documento
           FROM camara_despesas WHERE parlamentar_id = :p"""
    params = {"p": parlamentar_id}
    if ano:
        q += " AND ano = :a"
        params["a"] = ano
    q += " ORDER BY dt_documento DESC NULLS LAST, ano DESC, mes DESC LIMIT :l"
    params["l"] = limit
    r = (await db.execute(text(q), params)).all()
    return {"items": [dict(zip(["ano","mes","tipo","fornecedor","valor","dt"], row)) for row in r]}
