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
from fastapi import APIRouter, Depends, Query, HTTPException, Response
from typing import Optional
import base64
import httpx
import logging
from services.auth import get_current_user, ensure_tela
from models.user import User
from services import authz
from services.registro_rotas import exige

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


@router.get("/buscar", dependencies=[exige("dou.ver")])
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
    current: User = Depends(get_current_user),
):
    """Busca em tempo real no Jornal Minas Gerais."""
    # A tela `dou` existe no cadastro (services/telas_catalog.py) e no menu do
    # frontend, mas NUNCA era conferida no servidor: conceder ou negar "Diario
    # Oficial" a alguem nao mudava nada: o menu sumia e o endpoint continuava
    # respondendo. Permissao que so esconde o botao nao e permissao.
    #
    # SO A TELA, sem municipio, e nao e omissao: o Jornal Minas Gerais e o
    # diario do ESTADO e a busca e por texto livre num acervo publico — nao ha
    # `municipio_id` no pedido nem recorte por municipio na resposta. O que se
    # protege aqui e a porta: a plataforma faz a chamada, mantem o token e paga
    # a saida.
    authz.exigir_tela(current, "dou")
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


def _extrair_pdf(raw: bytes) -> bytes:
    """O 'arquivo' do JMG vem como PKCS#7 assinado (base64). O PDF esta
    encapsulado; extraimos de %PDF ate o ultimo %%EOF (arquivo unico)."""
    i = raw.find(b"%PDF")
    j = raw.rfind(b"%%EOF")
    if i < 0 or j <= i:
        raise HTTPException(502, "Nao foi possivel extrair o PDF da publicacao")
    return raw[i:j + 5]


# `dou.ver` e nao `dou.exportar`, apesar do `?download=true`: esta rota nao GERA
# arquivo com dado nosso — ela entrega a edicao do Jornal Minas Gerais, que e
# publica, e e o proprio botao "visualizar" da tela. Quem exporta o RESULTADO da
# busca (dado nosso, em PDF montado aqui) e `/api/export-pdf/dou`, e la a chave e
# `dou.exportar`. Exigir `exportar` para abrir a publicacao tiraria o leitor da
# tela de quem so tem "Ver".
@router.get("/publicacao/{id_jornal}", dependencies=[exige("dou.ver")])
def publicacao(id_jornal: int, download: bool = False,
               current: User = Depends(get_current_user)):
    """Serve a PUBLICACAO (PDF) do Jornal MG pela propria plataforma.
    Busca a edicao (Jornal/ObterEdicaoPorId), extrai o PDF do PKCS#7 e devolve
    inline (visualizar) ou como anexo (baixar)."""
    # Mesmo gate do `/buscar`, e aqui pesa mais: este endpoint BAIXA a edicao
    # inteira (PDF de dezenas de MB) usando o token da plataforma. Sem checagem,
    # qualquer sessao autenticada virava um proxy de download do Jornal MG.
    #
    # Endpoint SINCRONO (`def`, porque o httpx aqui e sincrono). `ensure_tela`
    # tambem e sincrona, entao nada muda para ela; e o registro do modo aviso
    # sabe rodar a partir da thread do pool (services/authz.py::_enviar guarda o
    # event loop no contexto justamente para este caso).
    authz.exigir_tela(current, "dou")

    def _fetch(tok: str):
        return httpx.get(
            f"{JMG_BASE}/api/v1/Jornal/ObterEdicaoPorId/{id_jornal}",
            headers={"Authorization": f"Bearer {tok}", "Accept": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=60, verify=False,
        )

    tok = _get_token()
    try:
        r = _fetch(tok)
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            _TOKEN_CACHE["token"] = None
            r = _fetch(_get_token())
            r.raise_for_status()
        else:
            raise HTTPException(e.response.status_code, f"JMG: {e.response.text[:200]}")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Falha ao obter publicacao no Jornal MG: {e}")

    dados = (r.json() or {}).get("dados") or {}
    ap = dados.get("arquivoCadernoPrincipal") or {}
    b64 = ap.get("arquivo")
    if not b64:
        raise HTTPException(404, "Publicacao sem arquivo disponivel")
    pdf = _extrair_pdf(base64.b64decode(b64))
    dispo = "attachment" if download else "inline"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{dispo}; filename="dou-mg-{id_jornal}.pdf"'},
    )
