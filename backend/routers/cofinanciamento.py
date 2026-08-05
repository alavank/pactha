"""Cofinanciamento estadual da saúde — o que o Estado repassa ao fundo municipal.

⚠️ O VALOR DESTA TELA ESTÁ NA DIFERENÇA, não no total. Na Atenção Primária, o
que importa é `valor_teto - valor`: é dinheiro que o município deixa de receber
por indicador de desempenho (ISF), e que ele PODE reverter. Na Vigilância, o que
importa é a parcela com `liberado = false`: dinheiro parado.

Por isso o endpoint devolve os dois agregados prontos — se cada tela tivesse de
calcular, uma delas calcularia diferente.
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

router = APIRouter(prefix="/api/cofinanciamento", tags=["cofinanciamento"])
logger = logging.getLogger("cofinanciamento")


@router.get("", dependencies=[exige("convenios.ver")])
async def listar(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "convenios")
    vazio = {"tem_dados": False, "fonte": None,
             "primaria": {"itens": [], "perdido_total": 0, "teto_total": 0},
             "vigilancia": {"itens": [], "travado_total": 0, "travadas": 0,
                            "liberado_total": 0}}
    if not municipio_id:
        return vazio

    ap = (await db.execute(text("""
        SELECT competencia, valor_teto, valor, perc_receber, indicador, fechado, ano
        FROM cofinanciamento_saude
        WHERE municipio_id = :m AND tipo = 'atencao_primaria'
        ORDER BY ano DESC NULLS LAST, competencia DESC
    """), {"m": municipio_id})).fetchall()

    vg = (await db.execute(text("""
        SELECT competencia, programa, valor, liberado, data_ref, ano
        FROM cofinanciamento_saude
        WHERE municipio_id = :m AND tipo = 'vigilancia'
        ORDER BY liberado NULLS FIRST, data_ref DESC NULLS LAST
    """), {"m": municipio_id})).fetchall()

    if not ap and not vg:
        return vazio

    fonte = (await db.execute(text(
        "SELECT max(fonte) FROM cofinanciamento_saude WHERE municipio_id = :m"
    ), {"m": municipio_id})).scalar()

    itens_ap = [{
        "competencia": r[0],
        "valor_teto": float(r[1]) if r[1] is not None else None,
        "valor": float(r[2]) if r[2] is not None else None,
        "perdido": (float(r[1]) - float(r[2]))
                   if (r[1] is not None and r[2] is not None) else None,
        "perc_receber": float(r[3]) if r[3] is not None else None,
        "indicador": float(r[4]) if r[4] is not None else None,
        "fechado": r[5], "ano": r[6],
    } for r in ap]

    itens_vg = [{
        "competencia": r[0], "programa": r[1],
        "valor": float(r[2]) if r[2] is not None else None,
        "liberado": r[3],
        "data_ref": r[4].isoformat() if r[4] else None,
        "ano": r[5],
    } for r in vg]

    travadas = [i for i in itens_vg if i["liberado"] is False]
    return {
        "tem_dados": True,
        "fonte": fonte,
        "primaria": {
            "itens": itens_ap,
            "perdido_total": sum(i["perdido"] or 0 for i in itens_ap),
            "teto_total": sum(i["valor_teto"] or 0 for i in itens_ap),
        },
        "vigilancia": {
            "itens": itens_vg,
            "travadas": len(travadas),
            "travado_total": sum(i["valor"] or 0 for i in travadas),
            "liberado_total": sum(i["valor"] or 0 for i in itens_vg
                                  if i["liberado"] is True),
        },
    }
