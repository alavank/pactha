"""Diário Oficial do Estado do Tocantins (DOE-TO).

⚠️ A MECÂNICA MORA EM `services/diario_to.py`. Este arquivo é a porta HTTP com
o gate de permissão — igual ao dou_es/dou_go, e de propósito.

⚠️ Diferente do ES e de GO: a busca do TO devolve EDIÇÕES, não páginas com
trecho. `pagina` vem nula e `texto_resultado` traz a ficha da edição. A resposta
pode trazer `truncado: true` — a fonte corta em 100 sem paginar.
"""
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from models.user import User
from services import authz
from services.auth import get_current_user
from services.diario_to import baixar_pdf, buscar as _buscar
from services.registro_rotas import exige

router = APIRouter(prefix="/api/dou-to", tags=["dou-to"])
logger = logging.getLogger("dou-to")


@router.get("/buscar", dependencies=[exige("dou.ver")])
async def buscar(
    texto: str = Query(..., description="Palavra ou frase pra buscar"),
    data_inicial: str = Query(..., description="YYYY-MM-DD"),
    data_final: Optional[str] = Query(None, description="YYYY-MM-DD (default = hoje)"),
    pagina: int = Query(1, ge=1),
    current: User = Depends(get_current_user),
):
    """Busca em tempo real no DOE-TO."""
    authz.exigir_tela(current, "dou")
    try:
        return _buscar(texto, data_inicial, data_final, pagina)
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"DOE-TO: {e.response.text[:200]}")
    except Exception as e:
        raise HTTPException(502, f"DOE-TO indisponivel: {type(e).__name__}")


@router.get("/publicacao/{diario_id}", dependencies=[exige("dou.ver")])
def publicacao(diario_id: int, download: bool = False,
               current: User = Depends(get_current_user)):
    """Baixa o PDF da edição do DOE-TO."""
    authz.exigir_tela(current, "dou")
    try:
        conteudo = baixar_pdf(diario_id)
    except ValueError:
        raise HTTPException(404, "Edicao nao encontrada no DOE-TO")
    except Exception as e:
        raise HTTPException(502, f"DOE-TO: nao consegui o PDF ({type(e).__name__})")
    disp = "attachment" if download else "inline"
    return Response(content=conteudo, media_type="application/pdf",
                    headers={"Content-Disposition": f'{disp}; filename="doe-to-{diario_id}.pdf"'})
