"""Programas estaduais de fomento do RS — catálogo de captação.

⚠️ NÃO LÊ O BANCO, e isso é intencional: o conteúdo é curado em
`services/programas_rs.py`, com a data em que cada número foi lido na fonte. Não
há tabela porque não há coleta — e inventar uma tabela vazia só para "ficar
parecido com as outras telas" criaria a expectativa de atualização automática que
justamente não existe.

⚠️ GATE `convenios.ver` + tela `convenios`: é o funil de onde nasce o convênio
estadual. Mesma razão da Consulta Popular.

⚠️ E RESPONDE SÓ PARA MUNICÍPIO DO RS. Não por bairrismo: os programas são do
Estado do Rio Grande do Sul e não existem para uma prefeitura mineira — mostrá-los
lá seria oferecer uma porta que não abre.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.programas_rs import (
    AREAS, AVISO_NAO_AUTOMATICO, NORMAS, por_area,
)
from services.registro_rotas import exige

router = APIRouter(prefix="/api/programas-rs", tags=["programas-rs"])


@router.get("", dependencies=[exige("convenios.ver")])
async def programas(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Catálogo dos programas estaduais gaúchos de fomento."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "convenios")

    uf = (await db.execute(text(
        "SELECT upper(coalesce(uf, '')) FROM municipios WHERE id = :m"),
        {"m": municipio_id})).scalar()
    if uf != "RS":
        return {"tem_dados": False,
                "motivo": "Os programas deste catálogo são do Estado do Rio "
                          "Grande do Sul e não se aplicam a este município."}

    grupos = por_area()
    return {
        "tem_dados": True,
        "aviso": AVISO_NAO_AUTOMATICO,
        "areas": [
            {
                "chave": area,
                "titulo": AREAS.get(area, area),
                "programas": [
                    {"chave": p.chave, "nome": p.nome, "orgao": p.orgao,
                     "resumo": p.resumo, "exigencias": list(p.exigencias),
                     "como": p.como, "url": p.url, "numeros": p.numeros,
                     "observacao": p.observacao}
                    for p in grupos[area]
                ],
            }
            for area in AREAS if area in grupos
        ],
        "normas": [{"norma": n, "sobre": s} for n, s in NORMAS],
    }
