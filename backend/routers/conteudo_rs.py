"""As telas gaúchas de conteúdo curado — FUNRIGS, emendas estaduais e TCE-RS.

Um router para os três porque compartilham exatamente a mesma natureza: assunto
que entra no PACTHA pela regra do roadmap do RS (`docs/MAPA_RS.md` §13), mas cuja
fonte não é coletável hoje. O que muda entre eles é o conteúdo, não a mecânica.

⚠️ CADA RESPOSTA CARREGA O SEU `aviso`, e a tela é obrigada a mostrá-lo. Não é
rodapé nem nota de rodapé: sem ele, conteúdo estático se passa por monitoramento.

⚠️ Só respondem para município do RS. São assuntos do Estado; mostrá-los a uma
prefeitura de outra UF seria oferecer porta que não abre.

⚠️ Gate `convenios.ver` + tela `convenios` — os três são o funil de onde nasce
(ou de onde se perde) a transferência estadual. Mesma razão da Consulta Popular e
do catálogo de programas.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.conteudo_rs import (
    AVISO_EMENDAS, AVISO_FUNRIGS, AVISO_TCE, EMENDAS, FUNRIGS, TCE,
)
from services.registro_rotas import exige

router = APIRouter(prefix="/api/rs", tags=["conteudo-rs"])

_FORA_DO_RS = ("Este conteúdo trata de programas e obrigações do Estado do Rio "
               "Grande do Sul e não se aplica a este município.")


async def _guarda(db: AsyncSession, current: User, municipio_id: int) -> bool:
    """Auth + escopo + UF. Devolve True quando o município é do RS."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "convenios")
    uf = (await db.execute(text(
        "SELECT upper(coalesce(uf, '')) FROM municipios WHERE id = :m"),
        {"m": municipio_id})).scalar()
    if uf is None:
        raise HTTPException(404, "Município não encontrado")
    return uf == "RS"


@router.get("/funrigs", dependencies=[exige("convenios.ver")])
async def funrigs(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Plano Rio Grande / FUNRIGS — exigências do fundo a fundo da reconstrução."""
    if not await _guarda(db, current, municipio_id):
        return {"tem_dados": False, "motivo": _FORA_DO_RS}
    # A data-limite da calamidade é o único campo VIVO desta tela: ela muda o
    # comportamento do alarme do Decreto 56.939 (prazo de 120 dias em vez do
    # dia 15). Mostrá-la aqui deixa visível se o município a tem cadastrada.
    row = (await db.execute(text(
        "SELECT calamidade_ate, fundo_reconstrucao, fundo_reconstrucao_obs "
        "FROM municipios WHERE id = :m"), {"m": municipio_id})).first()
    return {
        "tem_dados": True,
        "aviso": AVISO_FUNRIGS,
        **FUNRIGS,
        "municipio": {
            "calamidade_ate": row[0].isoformat() if row and row[0] else None,
            "fundo_reconstrucao": row[1] if row else None,
            "fundo_reconstrucao_obs": row[2] if row else None,
        },
    }


@router.get("/emendas", dependencies=[exige("convenios.ver")])
async def emendas(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Emendas parlamentares estaduais do RS — e por que elas NÃO são impositivas."""
    if not await _guarda(db, current, municipio_id):
        return {"tem_dados": False, "motivo": _FORA_DO_RS}
    return {"tem_dados": True, "aviso": AVISO_EMENDAS, **EMENDAS}


@router.get("/tce", dependencies=[exige("convenios.ver")])
async def tce(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """TCE-RS — as remessas obrigatórias que refletem na habilitação."""
    if not await _guarda(db, current, municipio_id):
        return {"tem_dados": False, "motivo": _FORA_DO_RS}
    codigo = (await db.execute(text(
        "SELECT tce_orgao_codigo FROM municipios WHERE id = :m"),
        {"m": municipio_id})).scalar()
    return {"tem_dados": True, "aviso": AVISO_TCE, **TCE,
            "municipio": {"tce_orgao_codigo": codigo}}
