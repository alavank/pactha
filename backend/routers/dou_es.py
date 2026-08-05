"""Proxy de busca no Diario Oficial dos Municipios do Espirito Santo (DOM/ES).

Espelha o contrato de saida do dou_mg (mesma tela consome os dois), mas a fonte
e outra: a plataforma IOES (ioes.dio.es.gov.br), busca Elasticsearch publica,
sem login nem token. O DOM/ES e a edicao consolidada da AMUNES onde as
prefeituras capixabas publicam — Conceicao da Barra, Anchieta, Guarapari saem
nele (os atos municipais NAO saem no diario ESTADUAL).

API descoberta por inspecao (05/08/2026):
- Busca (GET): /dom/busca/busca/buscar/query/{pagina0}[/di:YYYY-MM-DD][/df:YYYY-MM-DD]/?1=1&q={termo}
  -> JSON Elasticsearch: hits.total, hits.hits[]._source {data, pagina, paginas,
     pdf_id, diario_id}, highlight.conteudo[] (trechos com <strong>).
  10 hits por pagina, pagina 0-based.
- PDF (GET): /portal/edicoes/download/{diario_id} -> application/pdf direto.
- Visualizar: /portal/visualizacoes/pdf/{diario_id}.

⚠️ NAO ha caderno aqui (o DOM e um so). A tela esconde os 3 cadernos do JMG
quando o ambiente e do ES; o tipo_caderno vem fixo "DOM/ES" so para preencher a
coluna.
"""
import logging
import re
from datetime import date
from typing import Optional
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from models.user import User
from services import authz
from services.auth import get_current_user
from services.registro_rotas import exige

router = APIRouter(prefix="/api/dou-es", tags=["dou-es"])
logger = logging.getLogger("dou-es")

IOES = "https://ioes.dio.es.gov.br"
POR_PAGINA = 10  # fixo da plataforma IOES
_TAG = re.compile(r"</?strong>", re.I)


def _texto(hit: dict) -> str:
    """Junta os trechos destacados em texto limpo (sem o <strong> do highlight).
    Sem highlight, cai no conteudo da pagina, truncado."""
    hl = (hit.get("highlight") or {}).get("conteudo") or []
    if hl:
        return _TAG.sub("", " … ".join(hl)).strip()[:600]
    conteudo = (hit.get("_source") or {}).get("conteudo") or ""
    return conteudo.strip()[:600]


@router.get("/buscar", dependencies=[exige("dou.ver")])
async def buscar(
    texto: str = Query(..., description="Palavra ou frase pra buscar"),
    data_inicial: str = Query(..., description="YYYY-MM-DD"),
    data_final: Optional[str] = Query(None, description="YYYY-MM-DD (default = hoje)"),
    pagina: int = Query(1, ge=1),
    current: User = Depends(get_current_user),
):
    """Busca em tempo real no DOM/ES. Mesma porta protegida do dou_mg: a tela
    'dou' e conferida no servidor, e a plataforma paga a saida (busca publica,
    sem municipio_id no pedido)."""
    authz.exigir_tela(current, "dou")
    if not data_final:
        data_final = date.today().isoformat()
    pagina0 = pagina - 1  # a IOES e 0-based
    # aspas na frase = busca exata (comportamento do proprio buscador da IOES).
    url = (f"{IOES}/dom/busca/busca/buscar/query/{pagina0}"
           f"/di:{quote(data_inicial)}/df:{quote(data_final)}/"
           f"?1=1&q={quote(texto)}")
    try:
        with httpx.Client(timeout=30) as cli:
            r = cli.get(url, headers={"Accept": "application/json",
                                      "User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"IOES: {e.response.text[:200]}")
    except Exception as e:
        raise HTTPException(502, f"IOES indisponivel: {type(e).__name__}")

    hits = (data.get("hits") or {}).get("hits") or []
    total = (data.get("hits") or {}).get("total") or 0
    if isinstance(total, dict):  # ES 7+ devolve {"value": N}
        total = total.get("value", 0)
    normalized = []
    for h in hits:
        src = h.get("_source") or {}
        did = src.get("diario_id")
        normalized.append({
            "id_jornal": did,
            "data_publicacao": src.get("data"),
            "tipo_caderno": "DOM/ES",
            "texto_resultado": _texto(h),
            "pagina": src.get("pagina"),
            "url_visualizar": f"{IOES}/portal/visualizacoes/pdf/{did}" if did else None,
            "url_baixar": f"{IOES}/portal/edicoes/download/{did}" if did else None,
        })
    total_paginas = max(1, (int(total) + POR_PAGINA - 1) // POR_PAGINA)
    return {
        "items": normalized,
        "pagina_atual": pagina,
        "total_paginas": total_paginas,
        "total_registros": int(total),
        "params": {"texto": texto, "data_inicial": data_inicial, "data_final": data_final},
    }


@router.get("/publicacao/{diario_id}", dependencies=[exige("dou.ver")])
def publicacao(diario_id: int, download: bool = False,
               current: User = Depends(get_current_user)):
    """Baixa o PDF da edicao do DOM/ES. Direto — sem o PKCS#7 do JMG."""
    authz.exigir_tela(current, "dou")
    try:
        with httpx.Client(timeout=60, follow_redirects=True) as cli:
            r = cli.get(f"{IOES}/portal/edicoes/download/{diario_id}",
                        headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
    except Exception as e:
        raise HTTPException(502, f"IOES: nao consegui o PDF ({type(e).__name__})")
    if "application/pdf" not in (r.headers.get("content-type") or ""):
        # A IOES responde a homepage (200 HTML) quando o id nao existe — nao e PDF.
        raise HTTPException(404, "Edicao nao encontrada no DOM/ES")
    disp = "attachment" if download else "inline"
    return Response(content=r.content, media_type="application/pdf",
                    headers={"Content-Disposition": f'{disp}; filename="dom-es-{diario_id}.pdf"'})
