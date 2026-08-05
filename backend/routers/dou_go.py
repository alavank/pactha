"""Diário Oficial do Estado de Goiás (DOE-GO) — plataforma IOES/SIGPub.

⚠️ A MECÂNICA MORA EM `services/diario_sigpub.py`. Este arquivo é a porta HTTP
com o gate de permissão — igual ao dou_es.py, e de propósito.

DIFERENÇA DE GOIÁS, medida e não suposta: os municípios goianos publicam os
atos no diário ESTADUAL (Pirenópolis: 36 publicações em 30 dias; Goiânia:
1.966). Os dois diários consorciados de GO (AGM e FGM) cobrem 1 dos nossos 6
municípios e ficam atrás de reCAPTCHA — não são fonte. Os diários municipais
próprios de Anápolis e Goiânia são redundantes com este.
"""
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from models.user import User
from services import authz
from services.auth import get_current_user
from services.diario_sigpub import PROVEDORES, baixar_pdf, buscar as _buscar
from services.registro_rotas import exige

router = APIRouter(prefix="/api/dou-go", tags=["dou-go"])
logger = logging.getLogger("dou-go")

PROV = PROVEDORES["GO"]


@router.get("/buscar", dependencies=[exige("dou.ver")])
async def buscar(
    texto: str = Query(..., description="Palavra ou frase pra buscar"),
    data_inicial: str = Query(..., description="YYYY-MM-DD"),
    data_final: Optional[str] = Query(None, description="YYYY-MM-DD (default = hoje)"),
    pagina: int = Query(1, ge=1),
    current: User = Depends(get_current_user),
):
    """Busca em tempo real no DOE-GO."""
    authz.exigir_tela(current, "dou")
    try:
        return _buscar(PROV, texto, data_inicial, data_final, pagina)
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"DOE-GO: {e.response.text[:200]}")
    except Exception as e:
        raise HTTPException(502, f"DOE-GO indisponivel: {type(e).__name__}")


@router.get("/publicacao/{diario_id}", dependencies=[exige("dou.ver")])
def publicacao(diario_id: int, download: bool = False,
               current: User = Depends(get_current_user)):
    """Baixa o PDF da edição do DOE-GO."""
    authz.exigir_tela(current, "dou")
    try:
        conteudo = baixar_pdf(PROV, diario_id)
    except ValueError:
        raise HTTPException(404, "Edicao nao encontrada no DOE-GO")
    except Exception as e:
        raise HTTPException(502, f"DOE-GO: nao consegui o PDF ({type(e).__name__})")
    disp = "attachment" if download else "inline"
    return Response(content=conteudo, media_type="application/pdf",
                    headers={"Content-Disposition": f'{disp}; filename="doe-go-{diario_id}.pdf"'})
