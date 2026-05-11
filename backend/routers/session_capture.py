"""
Endpoint para o bookmarklet enviar cookie de sessao do portal governamental.

Fluxo:
1. Cliente loga manualmente no portal (FNS/SIMEC/etc)
2. Clica no bookmarklet PACTA na barra de favoritos
3. JavaScript captura document.cookie + URL atual
4. POST aqui com X-Service-Token (do bookmarklet) ou JWT (logado em PACTA)
5. Backend criptografa e salva no Cofre como observacao da credencial
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel

from database import get_db
from models import CofreSenha, User
from services.auth import get_current_user
from services import crypto
from services.audit import log_event

router = APIRouter(prefix="/api/session-capture", tags=["session"])


class CapturedSession(BaseModel):
    automation_key: str   # ex: "fns", "govbr", "simec"
    municipio_id: int
    cookie: str
    url_atual: Optional[str] = None
    user_agent: Optional[str] = None


@router.post("")
async def capture_session(
    payload: CapturedSession,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Salva cookie de sessao capturado pelo bookmarklet no Cofre."""
    if not payload.cookie or len(payload.cookie) < 10:
        raise HTTPException(status_code=400, detail="Cookie vazio ou invalido")

    # Limita tamanho
    cookie_clean = payload.cookie[:8000]

    # Encontra credencial existente para esse automation_key + municipio
    q = select(CofreSenha).where(
        CofreSenha.automation_key == payload.automation_key,
        CofreSenha.municipio_id == payload.municipio_id,
    )
    res = await db.execute(q)
    item = res.scalar_one_or_none()

    captured_at = datetime.now(timezone.utc).isoformat()
    obs = (
        f"[SESSION] capturado em {captured_at} | "
        f"url={payload.url_atual or '?'} | "
        f"ua={(payload.user_agent or '?')[:80]}"
    )

    if item:
        # Atualiza observacao + senha (com cookie cifrado)
        item.senha_encrypted = crypto.encrypt(cookie_clean)
        item.observacao = obs
        item.atualizado_por_id = user.id
        await db.commit()
        action = "session.update"
    else:
        # Cria nova
        item = CofreSenha(
            municipio_id=payload.municipio_id,
            sistema=f"Sessao {payload.automation_key.upper()}",
            url=payload.url_atual,
            usuario="(cookie)",
            senha_encrypted=crypto.encrypt(cookie_clean),
            observacao=obs,
            categoria="Sessao",
            automation_key=payload.automation_key,
            atualizado_por_id=user.id,
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)
        action = "session.create"

    await log_event(
        db, action=action, user=user, request=request,
        target_type="cofre_session", target_id=item.id,
        details={
            "automation_key": payload.automation_key,
            "municipio_id": payload.municipio_id,
            "cookie_size": len(cookie_clean),
        },
    )
    return {"status": "ok", "id": item.id, "automation_key": payload.automation_key}


@router.get("/status/{automation_key}")
async def session_status(
    automation_key: str,
    municipio_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Verifica se ha sessao ativa cadastrada para esse portal/municipio."""
    q = select(CofreSenha).where(
        CofreSenha.automation_key == automation_key,
        CofreSenha.municipio_id == municipio_id,
    )
    res = await db.execute(q)
    item = res.scalar_one_or_none()
    if not item:
        return {"has_session": False}
    return {
        "has_session": True,
        "id": item.id,
        "atualizado_em": item.updated_at.isoformat() if item.updated_at else None,
        "observacao": item.observacao,
    }
