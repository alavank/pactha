"""Endpoint para Emendas Parlamentares Estaduais (SIGCON-MG / Pesquisar Emendas Por Convenente)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional
from database import get_db
from services.auth import get_current_user, ensure_municipio_access, ensure_tela
from services.coleta import frescor_coleta
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
    # CONVENIO RELACIONADO (#3): casa a emenda ao convenio pelo NUMERO DA INDICACAO.
    # A emenda ja tem nr_indicacao; o convenio passou a ter em raw_data->>'nr_indicacao'
    # (capturado por _scrape_indicacoes, #2). LATERAL LIMIT 1: o 1o convenio do mesmo
    # municipio com a mesma indicacao. Vazio enquanto o #2 nao populou aquele convenio.
    r = await db.execute(text(f"""
        {SQL_EMENDAS_COM_CONVENIO}
        WHERE {where_sql}
        ORDER BY ano DESC NULLS LAST, valor_indicacao DESC NULLS LAST
        LIMIT :limit OFFSET :offset
    """), params)
    items = [dict(row._mapping) for row in r.all()]
    # Convert valores Decimal -> float
    for it in items:
        for k in ("valor_indicacao", "valor_empenhado", "valor_liquidado", "valor_pago",
                  "valor_resto_saldo"):
            if it.get(k) is not None:
                it[k] = float(it[k])
        if it.get("execucao_em") is not None:
            it["execucao_em"] = it["execucao_em"].isoformat()

    # Frescor do DATASET de emendas (fonte='sigcon_emendas', carimbo proprio no
    # scraper: a falha de _scrape_emendas e engolida com warning e o carimbo
    # compartilhado diria "fresco" com o dado congelado). Fallback p/ 'sigcon'
    # enquanto as linhas novas nao existem (1a rodada pos-deploy preenche).
    coleta_em, coleta_falhas = (await frescor_coleta(db, municipio_id,
                                                     ("sigcon_emendas", "sigcon"))
                                if municipio_id else (None, 0))

    pages = (total + per_page - 1) // per_page if total > 0 else 1
    return {"items": items, "total": total, "page": page, "per_page": per_page, "pages": pages,
            "coleta_em": coleta_em, "coleta_falhas": coleta_falhas}


# A emenda com o convenio que ela gerou. Constante de modulo desde 17/09/2026: a
# tela de Emendas parlamentares le a MESMA junção (sem paginar), e uma copia
# "equivalente" e como as duas telas passariam a discordar do convenio ligado.
SQL_EMENDAS_COM_CONVENIO = """
        SELECT id, municipio_id, nr_indicacao, nome_responsavel, tipo_indicacao,
               uo_codigo, uo_sigla, cnpj_beneficiario, beneficiario,
               grupo_despesa, tipo_atendimento, valor_indicacao, status_indicacao, ano,
               -- Execução pelos dados abertos da SEGOV (emendas_mg.py, 24/09/2026).
               -- NULO = a planilha não trouxe esta indicação; ZERO = afirmou zero.
               valor_empenhado, valor_liquidado, valor_pago, valor_resto_saldo,
               execucao_em,
               c.conv_id, c.conv_nr, c.conv_objeto
        FROM emendas_estaduais
        LEFT JOIN LATERAL (
            SELECT ce.id AS conv_id,
                   COALESCE(ce.nr_proposta, ce.nr_sigcon, ce.nr_siafi) AS conv_nr,
                   ce.objeto AS conv_objeto
            FROM convenios_estadual ce
            WHERE ce.municipio_id = emendas_estaduais.municipio_id
              AND emendas_estaduais.nr_indicacao IS NOT NULL
              AND emendas_estaduais.nr_indicacao <> ''
              -- Casa pelo numero da indicacao capturado no convenio (_scrape_indicacoes,
              -- modal expandido). Escalar (1a indicacao) OU qualquer uma da lista
              -- `indicacoes` (convenio pode ter varias). Ver ingestion/sigcon_scraper.py.
              AND (
                ce.raw_data->>'nr_indicacao' = emendas_estaduais.nr_indicacao
                OR EXISTS (
                    SELECT 1 FROM jsonb_array_elements(
                        CASE WHEN jsonb_typeof(ce.raw_data->'indicacoes') = 'array'
                             THEN ce.raw_data->'indicacoes' ELSE '[]'::jsonb END) ind
                    WHERE ind->>'nr_indicacao' = emendas_estaduais.nr_indicacao)
              )
            LIMIT 1
        ) c ON true
"""


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
            count(*) FILTER (WHERE status_indicacao ILIKE '%aprovad%') AS aprovadas,
            -- ⚠️ O PAGO só soma o que a planilha informou, e a tela diz de QUANDO
            -- é a planilha: ela pode ficar meses sem ser regerada (a de 24/09/2026
            -- era de 12/05), e "pago" parado em maio não é "não foi pago".
            SUM(valor_pago) AS valor_pago,
            count(*) FILTER (WHERE valor_pago IS NOT NULL) AS com_execucao,
            max(execucao_em) AS execucao_em
        FROM emendas_estaduais WHERE {where}
    """), params)
    row = r.first()
    return {
        "total": row[0],
        "valor_total": float(row[1]) if row[1] else 0,
        "responsaveis": row[2],
        "aprovadas": row[3],
        "valor_pago": float(row[4]) if row[4] is not None else None,
        "com_execucao": row[5],
        "execucao_em": row[6].isoformat() if row[6] else None,
    }


@router.get("/outros", dependencies=[exige("emendas.ver")])
async def outros_beneficiarios(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Indicações estaduais a quem está no município e NÃO é o município (OSC,
    caixa escolar, órgão estadual, consórcio) — `emendas_estaduais_outros`,
    preenchida pelos dados abertos da SEGOV desde 24/09/2026.

    ⚠️ Rota PRÓPRIA, fora da listagem e dos totais: é a regra do dono ("nada é
    descartado, nada entra na conta como se fosse da prefeitura"). A tela mostra
    num bloco recolhido, embaixo, e nenhum outro leitor soma esta tabela."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "emendas")
    rows = (await db.execute(text("""
        SELECT nr_indicacao, ano, nome_responsavel, tipo_indicacao, tipo_beneficiario,
               beneficiario, cnpj_beneficiario, valor_indicacao, valor_pago,
               status_indicacao, execucao_em
          FROM emendas_estaduais_outros
         WHERE municipio_id = :m
         ORDER BY ano DESC NULLS LAST, valor_indicacao DESC NULLS LAST
    """), {"m": municipio_id})).fetchall()
    return [{
        "nr_indicacao": r[0], "ano": r[1], "autor": r[2], "tipo_indicacao": r[3],
        "tipo_beneficiario": r[4], "beneficiario": r[5], "cnpj": r[6],
        "valor_indicacao": float(r[7]) if r[7] is not None else None,
        "valor_pago": float(r[8]) if r[8] is not None else None,
        "status": r[9], "execucao_em": r[10].isoformat() if r[10] else None,
    } for r in rows]
