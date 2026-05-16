"""Proxy autenticado pra busca em tempo real no Jornal Minas Gerais.

API descoberta via inspect:
- POST /api/v1/Autenticacao/Autenticar  -> JWT publico (sem credenciais)
- GET  /api/v1/Pesquisa/PesquisarJornaisPaginados
       ?TextoPesquisa=...
       &DataPublicacaoInicial=YYYY-MM-DD
       &DataPublicacaoFinal=YYYY-MM-DD
       &DiarioExecutivo=true|false
       &DiarioMunicipios=true|false
       &DiarioTerceiros=true|false
       &EdicaoExtra=true|false
       &PaginaAtual=1
       &TamanhoPagina=20
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional
import httpx
import logging
from services.auth import get_current_user

router = APIRouter(prefix="/api/dou-mg", tags=["dou-mg"])
logger = logging.getLogger("dou-mg")

JMG_BASE = "https://www.jornalminasgerais.mg.gov.br"
# Cache do JWT em memoria (~1h TTL)
_TOKEN_CACHE: dict = {"token": None, "exp_at": 0}


def _get_token() -> str:
    """Autentica como usuario publico e cacheia o JWT."""
    import time
    now = time.time()
    if _TOKEN_CACHE["token"] and _TOKEN_CACHE["exp_at"] > now:
        return _TOKEN_CACHE["token"]
    try:
        with httpx.Client(timeout=15, verify=False) as cli:
            r = cli.post(
                f"{JMG_BASE}/api/v1/Autenticacao/Autenticar",
                json={},
                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
            )
            r.raise_for_status()
            data = r.json()
            tok = data.get("dados") or data.get("token") or data.get("access_token")
            if not tok:
                raise ValueError(f"JMG sem token na resposta: {data}")
            _TOKEN_CACHE["token"] = tok
            _TOKEN_CACHE["exp_at"] = now + 3600  # 1h
            return tok
    except Exception as e:
        logger.error(f"auth JMG falhou: {e}")
        raise HTTPException(502, f"Falha ao autenticar no Jornal MG: {e}")


@router.get("/buscar")
async def buscar(
    texto: str = Query(..., description="Palavra ou frase pra buscar"),
    data_inicial: str = Query(..., description="YYYY-MM-DD"),
    data_final: Optional[str] = Query(None, description="YYYY-MM-DD (default = hoje)"),
    diario_executivo: bool = True,
    diario_municipios: bool = False,
    diario_terceiros: bool = False,
    edicao_extra: bool = False,
    pagina: int = Query(1, ge=1),
    tamanho: int = Query(20, ge=1, le=100),
    _=Depends(get_current_user),
):
    """Busca em tempo real no Jornal Minas Gerais."""
    if not data_final:
        from datetime import date
        data_final = date.today().isoformat()
    tok = _get_token()
    params = {
        "TextoPesquisa": texto,
        "DataPublicacaoInicial": data_inicial,
        "DataPublicacaoFinal": data_final,
        "DiarioExecutivo": "true" if diario_executivo else "false",
        "DiarioMunicipios": "true" if diario_municipios else "false",
        "DiarioTerceiros": "true" if diario_terceiros else "false",
        "EdicaoExtra": "true" if edicao_extra else "false",
        "PaginaAtual": pagina,
        "TamanhoPagina": tamanho,
    }
    try:
        with httpx.Client(timeout=30, verify=False) as cli:
            r = cli.get(
                f"{JMG_BASE}/api/v1/Pesquisa/PesquisarJornaisPaginados",
                params=params,
                headers={
                    "Authorization": f"Bearer {tok}",
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0",
                },
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        # 401? Token expirou - limpa cache e refaz
        if e.response.status_code == 401:
            _TOKEN_CACHE["token"] = None
            tok = _get_token()
            r = httpx.get(
                f"{JMG_BASE}/api/v1/Pesquisa/PesquisarJornaisPaginados",
                params=params,
                headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"},
                timeout=30,
                verify=False,
            )
            r.raise_for_status()
            data = r.json()
        else:
            raise HTTPException(e.response.status_code, f"JMG: {e.response.text[:200]}")

    items = data.get("dados", []) or []
    # Normaliza pra estrutura amigavel
    normalized = []
    for it in items:
        normalized.append({
            "id_jornal": it.get("idJornal"),
            "data_publicacao": it.get("dataPublicacao"),
            "tipo_caderno": it.get("tipoCaderno"),
            "texto_resultado": it.get("textoResultado"),
            "pagina": it.get("pagina"),
            "url_visualizar": f"{JMG_BASE}/jornal/visualizar/{it.get('idJornal')}",
            "url_baixar": f"{JMG_BASE}/jornal/baixar/{it.get('idJornal')}",
        })
    return {
        "items": normalized,
        "pagina_atual": data.get("paginaAtual", pagina),
        "total_paginas": data.get("totalDePaginas", 1),
        "total_registros": data.get("totalDeRegistros", len(normalized)),
        "params": params,
    }
