"""
Helper para registrar entradas no audit log.
"""
from typing import Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Request

from models.audit import AuditLog


async def log_event(
    db: AsyncSession,
    *,
    action: str,
    user=None,
    request: Optional[Request] = None,
    target_type: Optional[str] = None,
    target_id: Optional[Any] = None,
    details: Optional[dict] = None,
    commit: bool = True,
):
    """Registra evento de auditoria. Nao quebra a request se falhar."""
    try:
        ip = None
        ua = None
        if request:
            ip = request.client.host if request.client else None
            ua = request.headers.get("user-agent", "")[:500]

        entry = AuditLog(
            user_id=getattr(user, "id", None) if user else None,
            user_email=getattr(user, "email", None) if user else None,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            ip=ip,
            user_agent=ua,
            details=details,
        )
        db.add(entry)
        if commit:
            await db.commit()
    except Exception:
        # Auditoria nao pode quebrar fluxo - apenas loga
        import logging
        logging.getLogger("audit").exception("Falha registrando audit_log")
