"""Busca no Diário Oficial do Rio Grande do Sul (DOE-RS, operado pela PROCERGS).

⚠️ POR QUE NAO ENTRA EM `diario_sigpub.py`. O ES e o GO sao a mesma plataforma
(IOES/SIGPub): mesma rota de busca Elasticsearch, mesmo `_source`, mesmo
download. O RS e OUTRA COISA — uma SPA Angular sobre uma API REST propria
(Jakarta/RESTEasy). Meti-lo la exigiria um `if uf == 'RS'` dentro de cada
metodo do ProvedorDiario, que e exatamente o que aquele modulo evita.

Em compensacao, e mais simples que os dois: JSON limpo, publico, paginado, com
filtro por texto e periodo. Nada de Elasticsearch cru, nada de PKCS#7 (o Jornal
Minas Gerais, em `routers/dou_mg.py`, embrulha o PDF nisso).

O ENDEREÇO NAO ESTA NO HTML — ele vem de `environments/environment.json`, que a
SPA carrega em runtime:

    GET https://www.diariooficial.rs.gov.br/environments/environment.json
        -> {"restEndPoint": "https://doe-backend.pro.rs.gov.br/", ...}

Deixamos o valor fixo abaixo (e nao uma busca em duas etapas a cada consulta)
porque a indirecao so muda quando a PROCERGS reconfigura o ambiente — e, se
mudar, queremos falha alta e visivel, nao um coletor que segue outro endpoint
sozinho.

CONTRATO MEDIDO EM 16/08/2026:

    GET /public/materias/?page=1&tipoDiario=1&queryString=<texto>
        &dataIni=AAAA-MM-DD&dataFim=AAAA-MM-DD
        -> {"collection": [{id, data, texto, origem, nroPagina, tipoMateria}],
            "collectionSize": N, "pageSize": 10,
            "filtroTiposMateria": ..., "filtroEntidades": ..., "filtroAssuntos": ...}
    GET /public/materias/{id}                       leitura da materia
    GET /public/materias/download/{id}/{pdf|txt}    a materia em arquivo

⚠️ A PAGINACAO COMECA EM 1 (`page=1`), nao em 0 como a do SIGPub. Chamar com 0
devolve a primeira pagina do mesmo jeito, entao o erro passaria despercebido ate
alguem reparar que a pagina 2 repete a 1.

⚠️ A API VALIDA CAMPO A CAMPO e responde em portugues:
`[{"message": "Data fim da publicação é obrigatória"}]` com HTTP 400. Isso e
util para descobrir parametro, e e por isso que o router repassa a mensagem.
"""
import logging
import re
import ssl
import time
from datetime import date
from typing import Optional

import httpx

logger = logging.getLogger("diario-rs")

BASE = "https://doe-backend.pro.rs.gov.br"
POR_PAGINA = 10  # fixo da plataforma (`pageSize` na resposta)
# 1 = Diario Oficial do Estado (o caderno que interessa ao municipio). O 0 que
# aparece em `/public/diarios/lista` e outra publicacao da mesma casa; nao
# adivinhe qual — quando precisar dela, meça primeiro.
TIPO_DOE = 1
UA = {"Accept": "application/json",
      "User-Agent": "Mozilla/5.0 (PACTHA/1.0 consulta publica DOE-RS)"}


_MARCA = re.compile(r"</?mark>", re.I)


def _sem_marcacao(texto: str | None) -> str:
    """O trecho sem o realce HTML da propria API.

    ⚠️ A busca devolve o termo embrulhado em `<mark>`: "Rua <mark>Santa
    Maria</mark>, 1000". A tela renderiza texto puro, entao as tags apareceriam
    LITERAIS no meio do resultado. Mesmo tratamento que `diario_sigpub` faz com
    o `<strong>` do highlight de la — e a razao de ser a mesma: o realce e do
    HTML do portal, nao do conteudo publicado."""
    return _MARCA.sub("", (texto or "").strip())[:600]


def _contexto_tls() -> ssl.SSLContext:
    """⭐ SEM ISTO A FONTE PARECE BLOQUEAR BOT — E NAO BLOQUEIA.

    O host (`tuprd00-00.procergs.com.br`) **derruba a conexao no handshake**
    quando o ClientHello vem no padrao moderno do Python: `Connection reset by
    peer`, sem resposta HTTP nenhuma. Medido em 16/08/2026, de dentro do worker:

        httpx padrao ............... ConnectError (reset)
        curl_cffi impersonate ...... SSLError (reset)
        curl do host ............... 200  <- a pista
        TLS 1.2 no maximo .......... 200
        ALPN vazio ................. 200
        SECLEVEL=1 ................. 200

    Ou seja: qualquer alteracao no ClientHello resolve, e o mesmo IP responde
    normalmente ao curl. Nao e anti-bot (senao o curl tambem cairia) nem bloqueio
    de rede — e um middlebox/balanceador antigo que engasga com TLS 1.3 + ALPN
    `h2`. Diagnostico importante porque o sintoma engana: `Connection reset` leva
    direto a "o Estado bloqueou a gente", e a resposta errada seria partir para
    curl_cffi/Playwright — que aqui tambem falham.

    Fixamos as DUAS diferencas (teto em TLS 1.2 e ALPN vazio) em vez de so uma:
    isoladamente cada uma funciona, mas nao sabemos qual delas o middlebox
    realmente rejeita, e adivinhar deixaria a coleta refem da proxima mudanca
    dele. Verificacao de certificado continua LIGADA — o que se abre mao aqui e
    de versao de protocolo, nunca de autenticidade do servidor."""
    ctx = ssl.create_default_context()
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_alpn_protocols([])
    return ctx


def _get_com_retry(url: str, params: dict, tentativas: int = 3):
    """GET com repeticao curta — o host RESETA DE VEZ EM QUANDO.

    ⚠️ NAO E O MESMO PROBLEMA DO `_contexto_tls`, e por isso sao duas defesas
    separadas. Aquele conserta um erro DETERMINISTICO (o ClientHello moderno
    nunca passa). Este cobre o que sobra: com o contexto certo, a mesma chamada
    ora responde 200, ora derruba a conexao — comportamento tipico de
    balanceador com um no ruim atras. Medido na sequencia: falha, e dois minutos
    depois 200 na primeira tentativa, sem nada ter mudado.

    Espera curta e proposital: quem espera do outro lado e uma PESSOA que clicou
    em "buscar", nao um cron. Tres tentativas com 0,6s e 1,2s custam no pior caso
    ~2s a mais; um backoff generoso aqui viraria tela travada."""
    ultimo = None
    for i in range(1, tentativas + 1):
        try:
            with httpx.Client(timeout=45, verify=_contexto_tls()) as cli:
                r = cli.get(url, params=params, headers=UA)
                # ⚠️ 4xx NAO passa por raise_for_status, e nao e teimosia: a API
                # devolve 400 COM O MOTIVO EM PORTUGUES no corpo ("Data fim da
                # publicação é obrigatória"). Levantar antes de ler jogaria fora
                # exatamente a informacao que resolve o problema, e o usuario
                # veria um 502 generico. Alem disso, erro de parametro e
                # DETERMINISTICO: repetir tres vezes so atrasa a resposta.
                if 400 <= r.status_code < 500:
                    try:
                        return r.json()
                    except Exception:
                        raise RuntimeError(
                            f"DOE-RS recusou a consulta (HTTP {r.status_code})")
                r.raise_for_status()
                return r.json()
        except RuntimeError:
            raise
        except Exception as e:
            ultimo = e
            if i < tentativas:
                logger.info("DOE-RS tentativa %d/%d falhou (%s) — repetindo",
                            i, tentativas, type(e).__name__)
                time.sleep(0.6 * i)
    # Mesma disciplina do diario_sigpub: o rastro fica AQUI, porque
    # HTTPException nao passa pelo handler global e o log do container mostraria
    # so "502" sem dizer se foi timeout, reset de TLS ou HTML no lugar de JSON.
    logger.warning("busca DOE-RS falhou em %d tentativas (%s: %s) — params=%s",
                   tentativas, type(ultimo).__name__, str(ultimo)[:160], params)
    raise ultimo


def buscar(texto: str, data_inicial: str, data_final: Optional[str],
           pagina: int) -> dict:
    """Devolve o MESMO contrato de saida do dou_mg e do dou_es — a tela
    `/dashboard/dou` consome os tres igual, e e isso que permite entrar com um
    estado novo sem tocar no frontend.

    Levanta httpx.HTTPStatusError/RequestError; quem traduz para HTTPException
    e o router."""
    if not data_final:
        data_final = date.today().isoformat()
    params = {
        "page": max(1, int(pagina or 1)),
        "tipoDiario": TIPO_DOE,
        "queryString": texto,
        "dataIni": data_inicial,
        "dataFim": data_final,
    }
    url = f"{BASE}/public/materias/"
    data = _get_com_retry(url, params)

    # A API devolve uma LISTA de erros quando falta parametro; devolve OBJETO no
    # caminho feliz. Sem esta guarda, `.get` estouraria com AttributeError e a
    # mensagem util (em portugues, dizendo qual campo falta) se perderia.
    if isinstance(data, list):
        msg = "; ".join(str((e or {}).get("message") or "") for e in data) or "erro sem mensagem"
        raise RuntimeError(f"DOE-RS recusou a consulta: {msg}")

    total = int(data.get("collectionSize") or 0)
    itens = []
    for m in data.get("collection") or []:
        mid = m.get("id")
        itens.append({
            "id_jornal": mid,
            "data_publicacao": m.get("data"),          # dd/mm/aaaa, como vem
            # O que o SIGPub chama de caderno, aqui e o TIPO DA MATERIA
            # (Portaria, Edital, Comunicado...) — e mais util na coluna do que
            # repetir "DOE-RS" em toda linha.
            "tipo_caderno": m.get("tipoMateria") or "DOE-RS",
            "texto_resultado": _sem_marcacao(m.get("texto")),
            "pagina": m.get("nroPagina"),
            # ⚠️ A materia NAO tem pagina publica propria com URL estavel: o
            # portal a abre por estado interno da SPA. O que existe e o
            # download. Mandar o usuario para a home seria pior que nao mandar.
            "url_visualizar": f"{BASE}/public/materias/download/{mid}/pdf" if mid else None,
            "url_baixar": f"{BASE}/public/materias/download/{mid}/pdf" if mid else None,
        })
    return {
        "items": itens,
        "pagina_atual": max(1, int(pagina or 1)),
        "total_paginas": max(1, (total + POR_PAGINA - 1) // POR_PAGINA),
        "total_registros": total,
        "params": {"texto": texto, "data_inicial": data_inicial,
                   "data_final": data_final, "uf": "RS"},
    }


def baixar_materia(materia_id: int, formato: str = "pdf") -> bytes:
    """A materia em PDF (ou txt). ⚠️ Confere o content-type: plataforma de
    governo costuma responder HTML com HTTP 200 para id inexistente, e o
    usuario baixaria um "PDF" que e uma pagina web. Quem levanta o 404 honesto
    e o chamador."""
    fmt = "txt" if str(formato).lower() == "txt" else "pdf"
    url = f"{BASE}/public/materias/download/{materia_id}/{fmt}"
    with httpx.Client(timeout=60, follow_redirects=True,
                      verify=_contexto_tls()) as cli:
        r = cli.get(url, headers={"User-Agent": UA["User-Agent"]})
        r.raise_for_status()
        tipo = (r.headers.get("content-type") or "").lower()
        if fmt == "pdf" and "pdf" not in tipo:
            raise ValueError(f"DOE-RS devolveu {tipo or 'sem content-type'} no lugar do PDF")
        return r.content
