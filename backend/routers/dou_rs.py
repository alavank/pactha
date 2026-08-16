"""Diário Oficial do Rio Grande do Sul (DOE-RS) — porta HTTP.

A mecânica mora em `services/diario_rs.py`; aqui fica só o gate de permissão e a
tradução de erro, como em `dou_es.py`/`dou_go.py`.

⚠️ Por que este router existe em vez de mais uma linha em `diario_sigpub.py`: o
DOE-RS não é a plataforma IOES/SIGPub — é uma API REST própria da PROCERGS. O
que ele tem em comum com os outros é só o CONTRATO DE SAÍDA, que é o suficiente
para a tela `/dashboard/dou` desenhar os três sem saber a diferença.

⚠️ E o que ele NÃO tem: página pública por matéria com URL estável. O portal
abre a matéria por estado interno da SPA; o que existe é o download. Por isso
`url_visualizar` e `url_baixar` apontam para o mesmo lugar — mandar o gestor
para a home do diário seria pior que não mandar.
"""
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from models.user import User
from services import authz
from services.auth import get_current_user
from services.diario_rs import baixar_materia, buscar as _buscar
from services.registro_rotas import exige

router = APIRouter(prefix="/api/dou-rs", tags=["dou-rs"])
logger = logging.getLogger("dou-rs")


@router.get("/buscar", dependencies=[exige("dou.ver")])
async def buscar(
    texto: str = Query(..., description="Palavra ou frase pra buscar"),
    data_inicial: str = Query(..., description="YYYY-MM-DD"),
    data_final: str | None = Query(None, description="YYYY-MM-DD (default = hoje)"),
    pagina: int = Query(1, ge=1),
    current: User = Depends(get_current_user),
):
    """Busca em tempo real no DOE-RS. Mesma porta protegida dos outros diários:
    a tela 'dou' é conferida no servidor, e a plataforma paga a saída (busca
    pública, sem municipio_id no pedido)."""
    authz.exigir_tela(current, "dou")
    try:
        return _buscar(texto, data_inicial, data_final, pagina)
    except RuntimeError as e:
        # A API valida campo a campo e responde em português ("Data fim da
        # publicação é obrigatória"). Repassar a frase poupa uma rodada inteira
        # de adivinhação — é dela que se descobre o parâmetro que falta.
        raise HTTPException(400, str(e)[:200])
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"DOE-RS: {e.response.text[:200]}")
    except Exception as e:
        raise HTTPException(502, f"DOE-RS indisponivel: {type(e).__name__}")


@router.get("/publicacao/{materia_id}", dependencies=[exige("dou.ver")])
def publicacao(materia_id: int, download: bool = False,
               current: User = Depends(get_current_user)):
    """Baixa a matéria em PDF. Direto — sem o PKCS#7 do Jornal Minas Gerais."""
    authz.exigir_tela(current, "dou")
    try:
        conteudo = baixar_materia(materia_id, "pdf")
    except ValueError as e:
        # content-type errado = id inexistente na prática (a plataforma responde
        # HTML com 200). 404 honesto em vez de entregar uma página web com
        # extensão .pdf.
        logger.info("materia %s indisponivel: %s", materia_id, e)
        raise HTTPException(404, "Matéria não encontrada no DOE-RS")
    except Exception as e:
        raise HTTPException(502, f"DOE-RS: nao consegui o PDF ({type(e).__name__})")
    disp = "attachment" if download else "inline"
    return Response(
        content=conteudo,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disp}; filename="doe-rs-{materia_id}.pdf"'},
    )
