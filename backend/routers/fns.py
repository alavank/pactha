"""Proxy autenticado pra busca em tempo real no consultafns.saude.gov.br.

API descoberta via inspect:
- GET /recursos/proposta/consultar?ano=YYYY&coEsfera=&coMunicipioIbge=XXXXXX&sgUf=MG&count=20&page=1
- GET /recursos/anos
- GET /recursos/ufs
- GET /recursos/municipios/uf/{uf}

Autenticacao via cookies de sessao captura via bookmarklet (cofre_senhas
sistema='Sessao FNS').
"""
import json
import logging
import os
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from services.auth import get_current_user
from services.crypto import decrypt

router = APIRouter(prefix="/api/fns", tags=["fns"])
logger = logging.getLogger("fns")

FNS_BASE = "https://consultafns.saude.gov.br"

# Codigos IBGE FNS dos municipios PACTA (6 digitos, sem digito verificador)
FNS_CODE_OVERRIDE = {
    "ARAUJOS": "310390",
    "NOVA SERRANA": "314520",
    "BOM DESPACHO": "310740",
    "SAO TIAGO": "316500",
    "TOLEDO": "316910",
    "PIRACEMA": "315060",
}


async def _get_cookies(db: AsyncSession) -> dict:
    """Le sessao FNS do cofre + descriptografa."""
    r = await db.execute(text("SELECT senha_hash FROM cofre_senhas WHERE sistema = 'Sessao FNS' LIMIT 1"))
    row = r.first()
    if not row:
        raise HTTPException(503, "Sessao FNS nao cadastrada no cofre. Capture via bookmarklet.")
    sessao = decrypt(row[0])
    try:
        data = json.loads(sessao)
        cookies = data.get("cookies", [])
        return {c["name"]: c["value"] for c in cookies if "name" in c}
    except Exception as e:
        raise HTTPException(500, f"Sessao FNS invalida: {e}")


@router.get("/buscar")
async def buscar(
    municipio: str = Query(..., description="Nome do municipio (ex: ARAUJOS) ou codigo IBGE 6 digitos"),
    ano: int = Query(...),
    uf: str = Query("MG"),
    nr_proposta: Optional[str] = Query(None),
    tipo_emenda: Optional[str] = Query(None, description="TODOS, INDIVIDUAL, BANCADA, COMISSAO, BANCADA OBRIGATORIA"),
    pagina: int = Query(1, ge=1),
    tamanho: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Busca propostas FAF no FNS em tempo real."""
    # Resolve codigo IBGE FNS
    cod = municipio
    if not cod.isdigit():
        cod = FNS_CODE_OVERRIDE.get(municipio.upper().strip())
        if not cod:
            # Fallback: chama API de municipios
            cookies = await _get_cookies(db)
            try:
                with httpx.Client(cookies=cookies, timeout=15, verify=False) as cli:
                    r = cli.get(f"{FNS_BASE}/recursos/municipios/uf/{uf}",
                                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
                    for m in r.json().get("resultado", []):
                        if m.get("noMunicipio", "").upper().strip() == municipio.upper().strip():
                            cod = m.get("coMunicipioIbge")
                            break
            except Exception:
                pass
        if not cod:
            raise HTTPException(404, f"Municipio '{municipio}' nao mapeado")

    cookies = await _get_cookies(db)
    params = {
        "ano": str(ano),
        "coEsfera": "",
        "coMunicipioIbge": cod,
        "count": str(tamanho),
        "page": str(pagina),
        "sgUf": uf,
    }
    if nr_proposta:
        params["nuProposta"] = nr_proposta
    if tipo_emenda and tipo_emenda.upper() != "TODOS":
        params["dsTipoRecurso"] = tipo_emenda

    try:
        with httpx.Client(cookies=cookies, timeout=30, verify=False) as cli:
            r = cli.get(
                f"{FNS_BASE}/recursos/proposta/consultar",
                params=params,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0",
                    "Referer": f"{FNS_BASE}/",
                },
            )
            if r.status_code == 401 or "login" in r.text[:200].lower():
                raise HTTPException(401, "Sessao FNS expirada. Re-capture via bookmarklet.")
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"FNS: {e.response.text[:200]}")
    except Exception as e:
        raise HTTPException(502, f"Falha FNS: {e}")

    resultado = data.get("resultado", {}) or {}
    items = resultado.get("itensPagina", []) or []
    normalized = []
    for it in items:
        normalized.append({
            "tipo_proposta": it.get("coTipoProposta"),
            "tipo_recurso": it.get("dsTipoRecurso"),
            "nu_processo": it.get("nuProcesso"),
            "valor_proposta": float(it.get("vlProposta") or 0),
            "valor_pago": float(it.get("vlPago") or 0),
            "valor_pagar": float(it.get("vlPagar") or 0),
            "constituido_processo": it.get("constituidoProcesso"),
            "parlamentares": it.get("parlamentares", []),
            "pagamentos_count": len(it.get("pagamentos", []) or []),
        })
    return {
        "items": normalized,
        "params": {"municipio": municipio, "cod_ibge": cod, "ano": ano, "uf": uf},
        "total": len(normalized),
        "totais": {
            "valor_proposta": sum(i["valor_proposta"] for i in normalized),
            "valor_pago": sum(i["valor_pago"] for i in normalized),
            "valor_pagar": sum(i["valor_pagar"] for i in normalized),
        },
    }


@router.get("/anos")
async def anos(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    """Anos disponiveis no FNS."""
    cookies = await _get_cookies(db)
    try:
        with httpx.Client(cookies=cookies, timeout=15, verify=False) as cli:
            r = cli.get(f"{FNS_BASE}/recursos/anos",
                        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            return [a.get("valor") for a in r.json().get("resultado", [])]
    except Exception as e:
        # Fallback: range
        from datetime import datetime
        return [str(y) for y in range(datetime.now().year, 2018, -1)]


@router.get("/municipios")
async def municipios_pacta(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    """Lista municipios PACTA com codigo IBGE FNS."""
    return [{"nome": n, "cod_ibge": c} for n, c in FNS_CODE_OVERRIDE.items()]
