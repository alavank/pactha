"""Mudancas de status detectadas nas atualizacoes diarias (trigger log_status_change).

Alimenta o aviso no dashboard: "o que mudou de status desde a ultima vez".
Fonte: tabela status_changes (preenchida por trigger AFTER UPDATE em
transferegov_propostas e convenios_estadual).
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from services.auth import get_current_user, ensure_municipio_access
from services import authz
from services.registro_rotas import declarado
from models.user import User

router = APIRouter(prefix="/api/status-changes", tags=["status-changes"])

# ⚠️ A tabela `status_changes` e alimentada por trigger em DUAS tabelas —
# `convenios_estadual` e `transferegov_propostas` — e o endpoint devolve as duas
# misturadas. A exigencia honesta e "uma das duas": `exige()` cobraria as duas
# juntas e tiraria o aviso do dashboard de quem so acompanha uma das fontes.
# Mesmo desenho de `routers/municipios.py::municipio_summary`.
_FONTES_PERMISSOES = ("convenios.ver", "transferegov.ver")


def _clean(s):
    if not isinstance(s, str):
        return s
    return s.replace("�", "").replace("  ", " ").strip()


async def listar_core(
    db: AsyncSession,
    municipio_ids: list[int],
    days: int = 30,
    limit: int = 100,
) -> dict:
    """Nucleo SET-AWARE das mudancas de status, SEM gate de auth. Varre um
    CONJUNTO de municipios (`= ANY(:mids)`); para [X] === por-municipio. Reusado
    pelo endpoint /api/status-changes e pelo Painel de Indicadores (BI)."""
    if not municipio_ids:
        return {"items": [], "total": 0}
    rows = (await db.execute(text("""
        SELECT id, fonte, tabela, ref, orgao, objeto,
               status_anterior, status_novo, changed_at
        FROM status_changes
        WHERE municipio_id = ANY(:mids)
          AND changed_at >= NOW() - make_interval(days => :days)
          AND length(trim(coalesce(objeto, ''))) > 3
          AND coalesce(ref, '') !~* 'n[aã]o h'
        ORDER BY changed_at DESC
        LIMIT :lim
    """), {"mids": list(municipio_ids), "days": days, "lim": limit})).fetchall()
    items = [{
        "id": r[0],
        "fonte": r[1],
        "ref": r[3],
        "orgao": _clean(r[4]),
        "objeto": _clean(r[5]),
        "status_anterior": _clean(r[6]),
        "status_novo": _clean(r[7]),
        "changed_at": r[8].isoformat() if r[8] else None,
    } for r in rows]
    return {"items": items, "total": len(items)}


@router.get("", dependencies=[declarado(*_FONTES_PERMISSOES)])
async def listar(
    municipio_id: int = Query(...),
    days: int = Query(30, description="janela em dias"),
    limit: int = Query(100),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Lista as mudancas de status recentes de um municipio (mais novas primeiro)."""
    ensure_municipio_access(current, municipio_id)
    if not any(authz.pode(current, chave) for chave in _FONTES_PERMISSOES):
        authz.negar(current, tipo="permissao",
                    exigido=" ou ".join(_FONTES_PERMISSOES),
                    possui=authz.permissoes_de(current),
                    mensagem="Voce nao tem permissao para esta acao")
    return await listar_core(db, [municipio_id], days, limit)
