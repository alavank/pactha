"""Repasses estaduais — a EXECUÇÃO do recurso, quando o estado não publica o
instrumento.

⚠️ POR QUE ESTA TELA EXISTE ao lado de "Convênios Estaduais". Minas (SIGCON) e
o Espírito Santo (GConv) publicam o INSTRUMENTO: número, vigência, situação,
valor pactuado. Goiás publica o PAGAMENTO: quem recebeu, quando, quanto, por
qual unidade orçamentária. São perguntas diferentes, e forçar o dado de GO na
tela de convênio deixaria metade das colunas vazia — o gestor que conhece Minas
concluiria que o sistema perdeu dado.

⭐ GATE PRÓPRIO desde 05/09/2026: `repasses.ver` + tela `repasses`.

⚠️ Até aqui esta tela era gateada por `convenios.ver` e pela tela `convenios`,
com o argumento de que é "a mesma família de informação". O argumento não
sobreviveu ao pedido do dono de granularidade Módulo › Tela › Ação: liberar
Convênios Estaduais concedia junto, em silêncio, mais nove telas do grupo — e o
administrador não tinha como conceder uma sem a outra. Cada tela do grupo agora
carrega a própria chave.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.registro_rotas import exige

router = APIRouter(prefix="/api/repasses", tags=["repasses"])
logger = logging.getLogger("repasses")


@router.get("", dependencies=[exige("repasses.ver")])
async def listar(
    municipio_id: Optional[int] = None,
    anos: Optional[list[int]] = Query(None),
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Lista os repasses do município, do mais recente para o mais antigo."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "repasses")
    if not municipio_id:
        return {"items": [], "total": 0, "page": page, "pages": 1,
                "total_valor": 0, "fonte": None}

    onde = ["r.municipio_id = :m"]
    p: dict = {"m": municipio_id}
    if anos:
        onde.append("r.ano = ANY(:anos)")
        p["anos"] = list(anos)
    if search and search.strip():
        # Busca no que o gestor lembra: credor, órgão, descrição, processo,
        # e o nome do deputado (é a pergunta "o que veio do fulano?").
        onde.append("(r.credor ILIKE :q OR r.orgao ILIKE :q OR r.descricao ILIKE :q"
                    " OR r.processo ILIKE :q OR r.processo_alt ILIKE :q"
                    " OR r.emenda_autor ILIKE :q OR r.emenda_numero ILIKE :q)")
        p["q"] = f"%{search.strip()}%"
    w = " AND ".join(onde)

    tot = (await db.execute(text(
        f"SELECT count(*), coalesce(sum(r.valor), 0) FROM repasses_estaduais r WHERE {w}"
    ), p)).first()
    total, soma = int(tot[0] or 0), float(tot[1] or 0)

    p2 = dict(p, lim=per_page, off=(page - 1) * per_page)
    rows = (await db.execute(text(f"""
        SELECT r.id, r.data_repasse, r.valor, r.credor, r.orgao, r.formalidade,
               r.elemento, r.sub_elemento, r.processo, r.processo_alt,
               r.fonte_recursos, r.descricao, r.emenda_numero, r.emenda_autor,
               r.ano, r.fonte
        FROM repasses_estaduais r WHERE {w}
        ORDER BY r.data_repasse DESC NULLS LAST, r.id DESC
        LIMIT :lim OFFSET :off
    """), p2)).fetchall()

    itens = [{
        "id": x[0],
        "data_repasse": x[1].isoformat() if x[1] else None,
        "valor": float(x[2]) if x[2] is not None else None,
        "credor": x[3], "orgao": x[4], "formalidade": x[5],
        "elemento": x[6], "sub_elemento": x[7],
        "processo": x[8], "processo_alt": x[9], "fonte_recursos": x[10],
        "descricao": x[11], "emenda_numero": x[12], "emenda_autor": x[13],
        "ano": x[14], "fonte": x[15],
    } for x in rows]
    return {
        "items": itens, "total": total, "page": page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "total_valor": soma,
        "fonte": (rows[0][15] if rows else None),
    }


@router.get("/anos", dependencies=[exige("repasses.ver")])
async def anos(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Anos com repasse, para o filtro da tela."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "repasses")
    if not municipio_id:
        return []
    rows = (await db.execute(text(
        "SELECT DISTINCT ano FROM repasses_estaduais WHERE municipio_id = :m "
        "AND ano IS NOT NULL ORDER BY ano DESC"
    ), {"m": municipio_id})).fetchall()
    return [int(r[0]) for r in rows]
