"""Busca em diário oficial na plataforma IOES/SIGPub — a MESMA em vários estados.

⚠️ POR QUE ISTO EXISTE, e não um arquivo por estado. O DOM/ES
(ioes.dio.es.gov.br) e o DOE-GO (diariooficial.abc.go.gov.br) são a mesma
plataforma: mesma rota de busca Elasticsearch, mesmo `_source`
(data/pagina/paginas/pdf_id/diario_id), mesmo `/portal/edicoes/download/{id}`
devolvendo PDF e mesmo `/portal/visualizacoes/pdf/{id}` para leitura. Copiar o
router do ES para um `dou_go.py` seria a TERCEIRA cópia da mesma lógica — e a
próxima correção (ou o próximo estado) precisaria ser lembrada em N lugares.

O que muda de estado para estado cabe em `PROVEDORES`: a base, o prefixo do
caminho de busca e o rótulo do caderno. Estado novo = uma linha lá.

⚠️ O que NÃO é comum e por isso não mora aqui: o Jornal Minas Gerais
(`routers/dou_mg.py`) é outra plataforma — tem JWT, três cadernos e PDF dentro
de PKCS#7. Ele fica como está.
"""
import logging
import re
from datetime import date
from typing import Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger("diario-sigpub")

POR_PAGINA = 10  # fixo da plataforma
_TAG = re.compile(r"</?strong>", re.I)


class ProvedorDiario:
    """Um diário na plataforma IOES/SIGPub.

    `prefixo` é o que difere ES de GO: o capixaba serve o diário MUNICIPAL sob
    `/dom`, o goiano serve o estadual na raiz. Descoberto medindo, não supondo.
    """

    def __init__(self, uf: str, base: str, prefixo: str, caderno: str, nome: str):
        self.uf = uf
        self.base = base.rstrip("/")
        self.prefixo = prefixo  # "" ou "/dom"
        self.caderno = caderno  # rótulo curto na coluna da tela
        self.nome = nome        # nome por extenso, para o subtítulo

    def url_busca(self, texto: str, di: str, df: str, pagina0: int) -> str:
        return (f"{self.base}{self.prefixo}/busca/busca/buscar/query/{pagina0}"
                f"/di:{quote(di)}/df:{quote(df)}/?1=1&q={quote(texto)}")

    def url_pdf(self, diario_id) -> str:
        return f"{self.base}/portal/edicoes/download/{diario_id}"

    def url_visualizar(self, diario_id) -> str:
        return f"{self.base}/portal/visualizacoes/pdf/{diario_id}"


# ⚠️ UF NOVA ENTRA AQUI, e o router de /api/dou-{uf} sai de graça. Antes de
# acrescentar: confirme com requisição REAL que a plataforma é esta (a rota de
# busca responde JSON com `hits.hits[]._source.diario_id`).
PROVEDORES: dict[str, ProvedorDiario] = {
    "ES": ProvedorDiario(
        "ES", "https://ioes.dio.es.gov.br", "/dom", "DOM/ES",
        "Diário dos Municípios do Espírito Santo"),
    "GO": ProvedorDiario(
        "GO", "https://diariooficial.abc.go.gov.br", "", "DOE-GO",
        "Diário Oficial do Estado de Goiás"),
}


def texto_do_hit(hit: dict) -> str:
    """Trechos destacados em texto limpo (sem o <strong> do highlight).
    Sem highlight, cai no conteúdo da página, truncado."""
    hl = (hit.get("highlight") or {}).get("conteudo") or []
    if hl:
        return _TAG.sub("", " … ".join(hl)).strip()[:600]
    return ((hit.get("_source") or {}).get("conteudo") or "").strip()[:600]


def buscar(prov: ProvedorDiario, texto: str, data_inicial: str,
           data_final: Optional[str], pagina: int) -> dict:
    """Busca síncrona; devolve o MESMO contrato de saída do dou_mg (a tela
    consome os dois igual). Levanta httpx.HTTPStatusError/RequestError — quem
    traduz para HTTPException é o router."""
    if not data_final:
        data_final = date.today().isoformat()
    url = prov.url_busca(texto, data_inicial, data_final, pagina - 1)
    try:
        with httpx.Client(timeout=30) as cli:
            r = cli.get(url, headers={"Accept": "application/json",
                                      "User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        # ⚠️ O RASTRO FICA AQUI, e não no router. O router traduz para
        # HTTPException — e HTTPException NÃO passa pelo handler global de
        # main.py, então sem esta linha a falha só existiria, efêmera, na tela de
        # quem clicou: o log do container teria apenas "502" e ninguém saberia se
        # foi timeout, HTML no lugar de JSON, ou bloqueio de WAF. Este serviço é
        # quem conhece a URL — logar aqui cobre os dois estados de uma vez.
        logger.warning("busca %s falhou (%s: %s) — url=%s",
                       prov.uf, type(e).__name__, str(e)[:160], url)
        raise

    hits = (data.get("hits") or {}).get("hits") or []
    total = (data.get("hits") or {}).get("total") or 0
    # ES 7+ devolve {"value": N}; a instalação de GO devolve int puro. Os dois.
    if isinstance(total, dict):
        total = total.get("value", 0)
    total = int(total or 0)

    itens = []
    for h in hits:
        src = h.get("_source") or {}
        did = src.get("diario_id")
        itens.append({
            "id_jornal": did,
            "data_publicacao": src.get("data"),
            "tipo_caderno": prov.caderno,
            "texto_resultado": texto_do_hit(h),
            "pagina": src.get("pagina"),
            "url_visualizar": prov.url_visualizar(did) if did else None,
            "url_baixar": prov.url_pdf(did) if did else None,
        })
    return {
        "items": itens,
        "pagina_atual": pagina,
        "total_paginas": max(1, (total + POR_PAGINA - 1) // POR_PAGINA),
        "total_registros": total,
        "params": {"texto": texto, "data_inicial": data_inicial,
                   "data_final": data_final, "uf": prov.uf},
    }


def baixar_pdf(prov: ProvedorDiario, diario_id: int) -> bytes:
    """PDF da edição. ⚠️ A plataforma responde a HOMEPAGE (HTTP 200, HTML) para
    id inexistente — sem conferir o content-type, o usuário baixaria um "PDF"
    que é uma página web. Quem levanta o 404 honesto é o chamador."""
    url = prov.url_pdf(diario_id)
    try:
        with httpx.Client(timeout=60, follow_redirects=True) as cli:
            r = cli.get(url, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
    except Exception as e:
        logger.warning("PDF %s falhou (%s: %s) — url=%s",
                       prov.uf, type(e).__name__, str(e)[:160], url)
        raise
    ct = r.headers.get("content-type") or ""
    if "application/pdf" not in ct:
        # Não é erro de rede: a plataforma responde 200 + HTML (a home) para id
        # inexistente. Sem esta linha, "edição não encontrada" e "o portal mudou
        # de comportamento" ficariam indistinguíveis no servidor.
        logger.info("PDF %s: id=%s nao devolveu PDF (content-type=%s) — url=%s",
                    prov.uf, diario_id, ct[:60], url)
        raise ValueError("nao-e-pdf")
    return r.content
