"""
Endpoints INTERNOS - acessados apenas por scrapers/workers via Service Token.
NUNCA expor publicamente, NUNCA usar JWT de usuario aqui.
"""
from datetime import datetime
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from pydantic import BaseModel

from database import get_db
from models.cofre import CofreSenha
from models.service_token import ServiceToken
from models.convenio import ConvenioFederal
from services.service_auth import get_service_token, require_scope
from services import crypto
from services.audit import log_event

router = APIRouter(prefix="/api/internal", tags=["internal"])


class UpsertItem(BaseModel):
    municipio_id: int
    nr_proposta: str | None = None
    objeto: str | None = None
    programa: str | None = None
    tipo_programa: str | None = None
    valor: float = 0
    situacao: str | None = None
    ano: int | None = None
    fonte: str
    orgao_concedente: str | None = None


class UpsertRequest(BaseModel):
    items: list[UpsertItem]


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


@router.post("/upsert/{automation_key}")
async def upsert_from_scraper(
    automation_key: str,
    payload: UpsertRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: ServiceToken = Depends(get_service_token),
):
    """Recebe items coletados pelo scraper e faz upsert em convenios_federal.

    Scope necessario: write:<automation_key> (ex: write:fns).
    """
    require_scope(token, f"write:{automation_key}")

    inserted = 0
    skipped = 0
    for it in payload.items:
        # Gerar nr_convenio uniforme
        nr = (it.nr_proposta or "").strip()
        if not nr:
            nr = f"{automation_key.upper()}-{it.municipio_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{inserted}"
        nr = nr[:50]
        try:
            await db.execute(text("""
                INSERT INTO convenios_federal (
                    nr_convenio, municipio_id, orgao_concedente, objeto,
                    situacao, valor_repasse, ano, programa, tipo_programa,
                    fonte, raw_data, updated_at
                ) VALUES (
                    :nr, :mun, :orgao, :obj, :sit, :val, :ano, :prog, :tipo,
                    :fonte, :raw, NOW()
                )
                ON CONFLICT (nr_convenio) DO UPDATE SET
                    valor_repasse = EXCLUDED.valor_repasse,
                    situacao = EXCLUDED.situacao,
                    raw_data = EXCLUDED.raw_data,
                    updated_at = NOW()
            """), {
                "nr": nr,
                "mun": it.municipio_id,
                "orgao": it.orgao_concedente or it.fonte,
                "obj": (it.objeto or it.programa or "")[:1000],
                "sit": (it.situacao or "")[:200],
                "val": float(it.valor or 0),
                "ano": it.ano,
                "prog": it.programa,
                "tipo": it.tipo_programa,
                "fonte": it.fonte,
                "raw": "{}",
            })
            inserted += 1
        except Exception as e:
            skipped += 1
            continue
    await db.commit()

    await log_event(
        db, action="scraper.upsert", request=request,
        target_type="automation", target_id=automation_key,
        details={
            "service_token": token.name,
            "n_items": len(payload.items),
            "inserted": inserted,
            "skipped": skipped,
        },
    )
    return {"inserted": inserted, "skipped": skipped, "total": len(payload.items)}
