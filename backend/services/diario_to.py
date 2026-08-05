"""Diário Oficial do Estado do TOCANTINS — plataforma própria, não SIGPub.

⚠️ POR QUE NÃO ENTRA EM `diario_sigpub.py`. O ES e GO rodam a mesma plataforma
(IOES/SIGPub, busca Elasticsearch com resultado POR PÁGINA e trecho destacado).
O Tocantins é outra coisa: um formulário HTML que devolve uma TABELA DE EDIÇÕES.
Forçar os dois no mesmo módulo faria o registro de provedores mentir sobre o que
cada um entrega.

⚠️ A DIFERENÇA QUE A TELA PRECISA SABER: aqui o resultado é POR EDIÇÃO, não por
página. A busca diz "estas edições contêm o termo" — não diz em que página nem
mostra o trecho. Preencher `texto_resultado` com um trecho inventado seria pior
que a limitação; o campo carrega a ficha factual da edição (número, data,
páginas, tamanho) e `pagina` fica nulo.

MECÂNICA (medida em 05/08/2026):
- Busca: GET https://diariooficial.to.gov.br/busca
  ?por=texto&texto=<termo>&data-inicial=YYYY-MM-DD&data-final=YYYY-MM-DD
  ⚠️ As datas são `<input type="date">` — ISO. Com dd/mm/aaaa a página volta o
  formulário em vez do resultado, sem erro nenhum.
- Resultado: HTML com <table>; cada <tr> traz Edição, Publicado em, Páginas,
  Tamanho, Downloads e o link https://doe.to.gov.br/diario/{id}/download
- PDF: esse mesmo link. Id inexistente devolve 404 de verdade (ao contrário da
  plataforma do ES/GO, que responde 200 com a home).

⚠️ TETO SILENCIOSO: a busca devolve no máximo 100 edições e NÃO tem paginação.
Um período de 19 meses bateu exatamente 100. Quem consome precisa avisar que a
lista pode estar cortada — número truncado sem aviso é o defeito que esta base
de código já pagou caro.
"""
import logging
import re
import unicodedata
from datetime import date
from typing import Optional

import httpx

logger = logging.getLogger("diario-to")

BASE = "https://diariooficial.to.gov.br"
BASE_PDF = "https://doe.to.gov.br"
TETO = 100  # a busca não pagina; acima disto a lista vem cortada
CADERNO = "DOE-TO"

_TAG = re.compile(r"<[^>]+>")
_LINHA = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELULA = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TABELA = re.compile(r"<table.*?</table>", re.S)
_ID = re.compile(r"/diario/(\d+)/download")


def _sem_acento(s: str) -> str:
    """⚠️ O TERMO VAI SEM ACENTO PARA A FONTE, e isto NÃO é preciosismo.

    Medido em 05/08/2026, num período com 68 edições ao todo:
        "Araguaina"  ->  33 edições   (filtro real)
        "Araguaína"  ->  65 edições   (quase tudo)
        "Paraiso"    ->  41           "Paraíso" -> 66
        "Pirenopolis" -> 0            (cidade de GO: correto)
    Ou seja: com acento a busca praticamente PARA DE FILTRAR e devolve o acervo
    inteiro. Quem digitasse "Araguaína" — a grafia CERTA — receberia 65 edições
    e concluiria que a cidade aparece em todas. Resultado falso apresentado como
    fato é pior que resultado nenhum.

    Tirar o acento devolve o comportamento correto (a fonte indexa sem acento),
    e não perde nada: "Araguaina" acha o que "Araguaína" deveria achar."""
    return "".join(c for c in unicodedata.normalize("NFKD", s or "")
                   if not unicodedata.combining(c))


def _texto(html_frag: str) -> str:
    import html as _h
    return " ".join(_h.unescape(_TAG.sub(" ", html_frag)).split())


def _iso_para_br(iso: str) -> Optional[str]:
    """A tabela traz dd/mm/aaaa; devolvemos ISO para o contrato da tela."""
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", (iso or "").strip())
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def buscar(texto: str, data_inicial: str, data_final: Optional[str],
           pagina: int = 1) -> dict:
    """Mesmo contrato de saída do dou_mg/dou_es — a tela consome os três igual.

    `pagina` é aceito e ignorado: a fonte não pagina (ver TETO). Aceitar e
    ignorar é melhor que recusar — a tela é uma só e manda o parâmetro."""
    if not data_final:
        data_final = date.today().isoformat()
    params = {
        "por": "texto", "texto": _sem_acento(texto),
        "data-inicial": data_inicial, "data-final": data_final,
    }
    try:
        with httpx.Client(timeout=45, follow_redirects=True) as cli:
            r = cli.get(f"{BASE}/busca", params=params,
                        headers={"User-Agent": "Mozilla/5.0",
                                 "Accept-Encoding": "gzip, deflate"})
            r.raise_for_status()
            html = r.text
    except Exception as e:
        logger.warning("busca TO falhou (%s: %s) — termo=%r periodo=%s..%s",
                       type(e).__name__, str(e)[:160], texto,
                       data_inicial, data_final)
        raise

    tab = _TABELA.search(html)
    if not tab:
        # Sem tabela = zero resultados. A página devolve o formulário e a
        # palavra "Nenhum"; não é erro.
        return {"items": [], "pagina_atual": 1, "total_paginas": 1,
                "total_registros": 0,
                "params": {"texto": texto, "texto_enviado": _sem_acento(texto),
                           "data_inicial": data_inicial,
                           "data_final": data_final, "uf": "TO"}}

    itens = []
    for linha in _LINHA.finditer(tab.group(0)):
        bruto = linha.group(1)
        mid = _ID.search(bruto)
        if not mid:
            continue  # cabeçalho
        cels = [_texto(c) for c in _CELULA.findall(bruto)]
        # [Edição, Publicado em, Páginas, Tamanho, Downloads, botão]
        edicao = cels[0] if len(cels) > 0 else ""
        publicado = cels[1] if len(cels) > 1 else ""
        paginas = cels[2] if len(cels) > 2 else ""
        tamanho = cels[3] if len(cels) > 3 else ""
        did = int(mid.group(1))
        # ⚠️ FICHA DA EDIÇÃO, e não um trecho: a fonte não devolve o excerto.
        # Inventar um seria pior que a limitação.
        ficha = " · ".join(x for x in (edicao, paginas, tamanho) if x)
        itens.append({
            "id_jornal": did,
            "data_publicacao": _iso_para_br(publicado),
            "tipo_caderno": CADERNO,
            "texto_resultado": ficha or f"Edição {did}",
            # NULO de propósito: a busca é por edição, não por página.
            "pagina": None,
            "url_visualizar": f"{BASE_PDF}/diario/{did}/download",
            "url_baixar": f"{BASE_PDF}/diario/{did}/download",
        })

    return {
        "items": itens,
        "pagina_atual": 1,
        "total_paginas": 1,
        "total_registros": len(itens),
        # ⚠️ O AVISO DE CORTE. Sem ele, "100 edições" seria lido como o total.
        "truncado": len(itens) >= TETO,
        "params": {"texto": texto, "texto_enviado": _sem_acento(texto),
                   "data_inicial": data_inicial,
                   "data_final": data_final, "uf": "TO"},
    }


def baixar_pdf(diario_id: int) -> bytes:
    """PDF da edição. Id inexistente devolve 404 aqui (a plataforma do ES/GO
    devolve 200 com HTML — por isso lá é preciso conferir o content-type)."""
    url = f"{BASE_PDF}/diario/{diario_id}/download"
    try:
        with httpx.Client(timeout=90, follow_redirects=True) as cli:
            r = cli.get(url, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
    except httpx.HTTPStatusError as e:
        # ⚠️ 404 da fonte = edição não existe, e o router tem de responder 404 —
        # não 502. Sem esta linha, "id errado" viraria "portal indisponível", e
        # quem lesse o log iria caçar uma falha de rede que não houve.
        if e.response.status_code == 404:
            logger.info("PDF TO: id=%s nao existe na fonte (404)", diario_id)
            raise ValueError("nao-existe")
        logger.warning("PDF TO falhou (HTTP %s) — url=%s",
                       e.response.status_code, url)
        raise
    except Exception as e:
        logger.warning("PDF TO falhou (%s: %s) — url=%s",
                       type(e).__name__, str(e)[:160], url)
        raise
    ct = r.headers.get("content-type") or ""
    if "application/pdf" not in ct:
        logger.info("PDF TO: id=%s nao devolveu PDF (content-type=%s)",
                    diario_id, ct[:60])
        raise ValueError("nao-e-pdf")
    return r.content
