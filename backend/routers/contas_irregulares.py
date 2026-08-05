"""Contas julgadas irregulares pelo tribunal de contas do estado.

⚠️ ISTO É INDÍCIO, NÃO DOCUMENTO — e o endpoint devolve os campos que forçam a
tela a dizer isso. `total` sem `entidades` não conta a história: 99 linhas em
Goiânia são 37 da prefeitura e 62 de autarquias, e as duas coisas pesam
diferente para quem vai assinar convênio.

Ausência aqui NÃO é regularidade: significa "sem conta irregular listada".
Quem consome não pode pintar verde com isto — ver o cabeçalho da migration.
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

router = APIRouter(prefix="/api/contas-irregulares", tags=["contas-irregulares"])
logger = logging.getLogger("contas-irregulares")


@router.get("", dependencies=[exige("cauc.ver")])
async def listar(
    municipio_id: Optional[int] = None,
    limite: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Resumo + lista. Gateado pela tela de Regularidade (`cauc`), que é onde
    o dado aparece."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "cauc")
    vazio = {"tem_dados": False, "total": 0, "prefeitura": 0, "autarquias": 0,
             "de_prefeito": 0, "fonte": None, "itens": []}
    if not municipio_id:
        return vazio

    resumo = (await db.execute(text("""
        SELECT count(*),
               count(*) FILTER (WHERE entidade IS NULL),
               count(*) FILTER (WHERE tipo_lista ILIKE '%Prefeito%'),
               max(fonte)
        FROM contas_irregulares WHERE municipio_id = :m
    """), {"m": municipio_id})).first()
    total = int(resumo[0] or 0)
    if not total:
        return vazio

    rows = (await db.execute(text("""
        SELECT entidade, responsavel, assunto, competencia, processo,
               dt_julgamento, tipo_lista, url
        FROM contas_irregulares WHERE municipio_id = :m
        ORDER BY (tipo_lista ILIKE '%Prefeito%') DESC,
                 dt_julgamento DESC NULLS LAST
        LIMIT :lim
    """), {"m": municipio_id, "lim": limite})).fetchall()

    return {
        "tem_dados": True,
        "total": total,
        "prefeitura": int(resumo[1] or 0),
        "autarquias": total - int(resumo[1] or 0),
        "de_prefeito": int(resumo[2] or 0),
        "fonte": resumo[3],
        "itens": [{
            "entidade": r[0], "responsavel": r[1], "assunto": r[2],
            "competencia": r[3], "processo": r[4],
            "dt_julgamento": r[5].isoformat() if r[5] else None,
            "tipo_lista": r[6], "url": r[7],
        } for r in rows],
    }
