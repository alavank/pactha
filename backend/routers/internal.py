"""
Endpoints INTERNOS - acessados apenas por scrapers/workers via Service Token.
NUNCA expor publicamente, NUNCA usar JWT de usuario aqui.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models.cofre import CofreSenha
from models.service_token import ServiceToken
from services.service_auth import get_service_token, require_scope
from services import crypto
from services.audit import log_event

router = APIRouter(prefix="/api/internal", tags=["internal"])


@router.get("/secrets/{automation_key}")
async def get_secret_for_automation(
    automation_key: str,
    municipio_id: int | None = None,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    token: ServiceToken = Depends(get_service_token),
):
    """Retorna credenciais cadastradas no Cofre marcadas com automation_key.

    Scraper precisa de scope `secret:read:<automation_key>` ou `secret:read:*`.
    Cada chamada e auditada com IP, IP do scraper, automation_key, municipio.
    """
    require_scope(token, f"secret:read:{automation_key}")

    q = select(CofreSenha).where(CofreSenha.automation_key == automation_key)
    if municipio_id:
        q = q.where(CofreSenha.municipio_id == municipio_id)
    result = await db.execute(q)
    items = result.scalars().all()

    out = []
    for it in items:
        out.append({
            "id": it.id,
            "municipio_id": it.municipio_id,
            "sistema": it.sistema,
            "url": it.url,
            "usuario": it.usuario,
            "senha": crypto.decrypt(it.senha_encrypted) if it.senha_encrypted else "",
        })

    # Auditoria
    await log_event(
        db, action="secret.read",
        request=request,
        target_type="automation",
        target_id=automation_key,
        details={
            "service_token": token.name,
            "token_prefix": token.token_prefix,
            "municipio_id": municipio_id,
            "n_secrets": len(out),
        },
    )
    return {"secrets": out}
