"""
DOU federal — o que saiu no Diário Oficial da União sobre cada município.

É o gatilho da captação: a portaria que autoriza o repasse, habilita o serviço,
publica o resultado da seleção ou reconhece a emergência sai no DOU ANTES de
aparecer em qualquer sistema (TransfereGov, FNS, SIOP). Em Nova Palma, 14/09/2026:
a Portaria MIDR 3.006 altera a transferência da Defesa Civil ao município — e a
Portaria GM/MS 12.122 lista o PSE de 2026 por código IBGE, numa tabela com os
5.570 municípios.

Fonte: a busca pública da Imprensa Nacional, sem login, e a página de cada ato.

    https://www.in.gov.br/consulta/-/buscar/dou?q="..."&s=todos&exactDate=personalizado
    https://www.in.gov.br/web/dou/-/{urlTitle}

O INLABS (edição inteira em XML) exige cadastro e ficou para depois: a busca
pública respondeu 200 do IP da VPS em 22/09/2026 (10 buscas seguidas, sem limite).

AS ARMADILHAS, todas medidas contra a fonte em 22/09/2026:

1. ⚠️ **NOME NÃO É CHAVE** ([[chave de município é IBGE ou CNPJ]]). "Nova Palma"
   devolve a naturalização de uma pessoa com esse sobrenome; "Santa Maria" dá
   1.246 resultados em 80 dias (o Herval, o DF, hospitais, pessoas). A BUSCA só
   junta candidatos; o ato entra quando traz uma evidência forte
   (`evidencia_no_texto`, da mais forte para a mais fraca — `EVIDENCIAS`):
     - `orgao`: foi a PRÓPRIA prefeitura quem publicou (armadilha 8);
     - `ibge`: o código de 7 dígitos, ou o de 6 colado ao nome (tabela do MS:
       "RS 431310 NOVA PALMA 100,00%");
     - `cnpj`: o CNPJ da prefeitura (extrato de convênio no DO3);
     - `municipio`: o nome colado à UF com "Município de"/"Prefeitura de" antes
       ("ao Município de Nova Palma/RS"), ou "Prefeitura Municipal de X" SEM UF
       quando X existe uma vez só no Brasil (lista do IBGE: Santa Maria é RS e
       RN, Bom Jesus são cinco);
     - `cidade`: o nome colado à UF sem mais nada (armadilha 9).
   "SANTA MARIA DO HERVAL/RS" não casa, porque depois do nome vem " DO HERVAL";
   e um município do mesmo estado cujo nome TERMINA no do alvo ("Nova Palma" para
   um alvo "Palma") é barrado pela lista nacional do IBGE (`travas`).

2. ⚠️ **O TRECHO DA BUSCA NÃO SERVE PARA DECIDIR.** A busca devolve ~400
   caracteres de cada ato; o município numa tabela de 5.570 linhas não está ali.
   A leitura diária (`/leiturajornal`) também é só índice: 458 atos no DO1 de
   21/09 com o mesmo trecho curto. Por isso cada candidato NOVO tem a página do
   ato lida inteira (`div.texto-dou`) — e só uma vez: o que já foi avaliado fica
   em `dou_atos` e não é relido na noite seguinte.

3. ⚠️ **A BUSCA PAGINA POR CURSOR, NÃO POR NÚMERO.** A página 2 pede `newPage=2`
   junto com `score`, `id` (classPK) e `displayDate` (displayDateSortable) do
   ÚLTIMO item da página 1. `delta` aceita no máximo 75 — pedir 100 ou 500 volta
   ao padrão de 20, sem aviso. Sem o cursor, a "página 2" repete a 1.

4. ⚠️ **O USER-AGENT DO HTTPX É DERRUBADO** — a conexão cai sem resposta
   (`RemoteProtocolError`). Qualquer UA "Mozilla/5.0 (...)" responde 200.

5. ⚠️ **RESPOSTA SEM O BLOCO DE RESULTADOS É FALHA, NÃO ZERO.** A página vem com
   HTTP 200 mesmo quando o portlet não monta. Sem o `<script ..._params>` a busca
   do município é dada como não feita: a `dou_cobertura` dele não anda e a rodada
   é `partial`. Busca vazia de verdade vem com o bloco e `jsonArray: []`.

6. **A BUSCA IGNORA ACENTO** ("Monte Siao" = "Monte Sião" = 41) e respeita a frase
   entre aspas ("Nova Palma" 20 × Nova Palma 24.527). Valor impossível
   (`"9999999"`) devolve 0 — o filtro filtra.

7. **ATO NÃO MUDA DEPOIS DE PUBLICADO** (a retificação é outro ato). Nada aqui é
   apagado; a rodada só acrescenta.

8. ⚠️ **O QUE A PREFEITURA PUBLICA NEM SEMPRE DIZ A UF.** O aviso de licitação
   da prefeitura no DO3 assina "Santa Maria, 17 de setembro de 2026". O que diz
   quem é o órgão: `hierarchyStr` = "Prefeituras/Estado do Rio Grande do
   Sul/Prefeitura Municipal de Santa Maria" (12 atos em 60 dias). Casado até o
   FIM da hierarquia: "...Santa Maria do Salto" (MG, 26 atos) é outro município.

9. ⚠️ **A CIDADE NÃO É A PREFEITURA.** Em 14 dias, 28 atos citam "Santa
   Maria/RS" com certeza — e ~20 deles como ENDEREÇO: UFSM, Colégio Militar,
   Base Aérea, vara federal, empresa sediada lá. A citação é gravada com
   `evidencia = 'cidade'`, e a tela e o Radar a deixam de fora por padrão. Em
   Nova Palma, cidade pequena, quase tudo é `municipio`.

10. ⚠️ **NOME QUE É SOBRENOME ESTOURA A BUSCA** (medido 24/09/2026). A frase entre
   aspas não impede o radical: "Araújos" (MG) casa com todo "Araújo" do DOU — 46
   páginas em 30 dias, a rodada falhava nele TODA noite e a cobertura dele nunca
   andava. A primeira página já diz o total: acima de MAX_PAGINAS a busca desiste
   ali (`JanelaLarga`) e o nome é trocado pelas frases que só a prefeitura usa
   (`frases`): "Município de Araújos", "Prefeitura Municipal de Araújos" e
   "Araújos/MG" — 1 página cada. A busca ignora a pontuação: "Araújos - MG" e
   "Araújos (MG)" devolvem os mesmos 4 atos que "Araújos/MG".

11. ⚠️ **O ORÇAMENTO VALE DENTRO DO MUNICÍPIO.** Conferido só entre municípios,
   um que começou aos 7 min e tinha dezenas de atos novos passou do `timeout` da
   task: a Freitas foi morta em 24/09/2026 sem gravar a rodada. Agora o prazo é
   visto a cada ato; o que já foi lido fica gravado, a cobertura do município não
   anda e a rodada sai `partial` — a próxima continua de onde parou, porque ato
   avaliado não é relido.

A janela de cada município sai de `dou_cobertura.conferido_ate`: revê os últimos
DOU_DIAS_REVISAO dias (edição extra publicada depois da rodada), e município que
nunca foi conferido começa DOU_DIAS_INICIAL dias atrás. Uma noite perdida se
recupera sozinha na seguinte (até DOU_DIAS_MAX).

Rodável por Scheduled Task em todo worker (federal, vale para toda UF), ou à mão:
    python -u ingestion/dou_federal.py                              # coleta de verdade
    python -u ingestion/dou_federal.py --dry --ibge 4313102 --nome "Nova Palma" --uf RS
Envs: DOU_DIAS_INICIAL (30) · DOU_DIAS_REVISAO (2) · DOU_DIAS_MAX (60) ·
DOU_BUDGET_S (2400: orçamento da rodada; o resto fica para a próxima, na ordem de
quem está há mais tempo sem conferir) · DOU_REAVALIAR=1 relê atos já avaliados.
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import logging
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("dou_federal")

BUSCA = "https://www.in.gov.br/consulta/-/buscar/dou"
ATO = "https://www.in.gov.br/web/dou/-/"
IBGE_MUNICIPIOS = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
# Armadilha 4: o UA padrão do httpx é derrubado.
UA = {"User-Agent": "Mozilla/5.0 (compatible; PACTHA/1.0; dados abertos DOU)"}
FONTE = "dou_federal"
TIMEOUT = 60
DELTA = 75            # armadilha 3: o máximo que a busca aceita
MAX_PAGINAS = 30      # 2.250 candidatos por termo: acima disso a janela está errada
PAUSA_S = float(os.getenv("DOU_PAUSA_S") or "0.3")
DIAS_INICIAL = int(os.getenv("DOU_DIAS_INICIAL") or "30")
DIAS_REVISAO = int(os.getenv("DOU_DIAS_REVISAO") or "2")
DIAS_MAX = int(os.getenv("DOU_DIAS_MAX") or "60")
ORCAMENTO_S = int(os.getenv("DOU_BUDGET_S") or "2400")
REAVALIAR = (os.getenv("DOU_REAVALIAR") or "").strip() == "1"
TRECHO_ANTES, TRECHO_DEPOIS = 220, 380

ESTADOS = {
    "AC": "ACRE", "AL": "ALAGOAS", "AP": "AMAPA", "AM": "AMAZONAS", "BA": "BAHIA",
    "CE": "CEARA", "DF": "DISTRITO FEDERAL", "ES": "ESPIRITO SANTO", "GO": "GOIAS",
    "MA": "MARANHAO", "MT": "MATO GROSSO", "MS": "MATO GROSSO DO SUL",
    "MG": "MINAS GERAIS", "PA": "PARA", "PB": "PARAIBA", "PR": "PARANA",
    "PE": "PERNAMBUCO", "PI": "PIAUI", "RJ": "RIO DE JANEIRO",
    "RN": "RIO GRANDE DO NORTE", "RS": "RIO GRANDE DO SUL", "RO": "RONDONIA",
    "RR": "RORAIMA", "SC": "SANTA CATARINA", "SP": "SAO PAULO", "SE": "SERGIPE",
    "TO": "TOCANTINS",
}


class BuscaFalhou(Exception):
    """A busca não devolveu o bloco de resultados (armadilha 5)."""


class JanelaLarga(BuscaFalhou):
    """O termo casa com mais de MAX_PAGINAS páginas na janela (armadilha 10)."""


# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------
_TRADUZ = str.maketrans({"–": "-", "—": "-", "‐": "-", "‑": "-", "−": "-",
                         "’": "'", "‘": "'", "´": "'", "`": "'",
                         " ": " "})


def normaliza(s: str | None) -> str:
    """Maiúsculas sem acento, CARACTERE A CARACTERE: o texto normalizado tem o
    mesmo comprimento do original, e a posição de um casamento nele é a mesma no
    original — é o que deixa recortar o trecho com a grafia de verdade."""
    saida = []
    for c in (s or "").translate(_TRADUZ):
        base = "".join(x for x in unicodedata.normalize("NFKD", c)
                       if not unicodedata.combining(x))
        saida.append((base[:1] or c).upper()[:1] or c)
    return "".join(saida)


def _nome_regex(nome_norm: str) -> str:
    partes = [re.escape(p) for p in re.split(r"\s+", nome_norm.strip()) if p]
    return r"\s+".join(partes)


def ibge6(ibge7: str) -> str:
    return re.sub(r"\D", "", ibge7 or "")[:6]


def padroes(m: dict, trava: dict | None = None) -> dict:
    """Regex de evidência do município `m` (nome, uf, ibge, cnpj).

    `trava` sai de `travas()` (lista nacional do IBGE): `antes` são os prefixos
    de municípios do mesmo estado cujo nome termina no do alvo; `depois`, as
    continuações de municípios de qualquer estado cujo nome começa nele; `unico`
    diz se o nome existe uma vez só no Brasil. Sem a lista, só as regras que não
    dependem dela."""
    trava = trava or {}
    nome = normaliza(m["nome"]).strip()
    uf = (m.get("uf") or "").upper()
    estado = ESTADOS.get(uf, "")
    # Nome que TERMINA no nome do alvo, no mesmo estado ("NOVA PALMA" x "PALMA").
    antes = "".join(f"(?<!{re.escape(p)} )" for p in trava.get("antes") or [])
    nome_re = f"{antes}(?<![A-Z0-9]){_nome_regex(nome)}(?![A-Z0-9])"
    uf_re = []
    if uf:
        uf_re.append(rf"{uf}(?![A-Z])")
    if estado:
        est = _nome_regex(estado)
        uf_re.append(rf"(?:NO\s+)?ESTADO\s+D[OAE]\s+{est}(?![A-Z])")
        uf_re.append(rf"{est}(?![A-Z])")
    p = {"nome": re.compile(nome_re)}
    if uf_re:
        p["nome_uf"] = re.compile(
            nome_re + r"\s*(?:[-/(,]\s*|\s+)(?:" + "|".join(uf_re) + ")")
    # "PREFEITURA MUNICIPAL DE NOVA PALMA", sem UF (despacho da ANM de 07/2026).
    # SÓ para nome que existe uma vez no Brasil: Santa Maria é RS e RN, Bom Jesus
    # são cinco. E barra a continuação ("MUNICIPIO DE PALMA SOLA" não é Palma).
    if trava.get("unico"):
        depois = "".join(rf"(?!\s+{_nome_regex(s)}(?![A-Z0-9]))"
                         for s in trava.get("depois") or [])
        p["nome_unico"] = re.compile(
            r"(?<![A-Z])(?:PREFEITURA\s+MUNICIPAL|PREFEITURA|MUNICIPIO|CAMARA\s+MUNICIPAL)"
            rf"\s+D[EO]\s+{_nome_regex(nome)}(?![A-Z0-9]){depois}")
    i7 = re.sub(r"\D", "", m.get("ibge") or "")
    if len(i7) == 7:
        p["ibge7"] = re.compile(rf"(?<!\d){i7}(?!\d)")
        i6 = i7[:6]
        p["ibge6"] = re.compile(
            rf"(?<!\d){i6}(?!\d).{{0,60}}?{nome_re}|{nome_re}.{{0,60}}?(?<!\d){i6}(?!\d)",
            re.S)
    cnpj = re.sub(r"\D", "", m.get("cnpj") or "")
    if len(cnpj) == 14:
        c = cnpj
        p["cnpj"] = re.compile(
            rf"(?<!\d){c[0:2]}\.?{c[2:5]}\.?{c[5:8]}\s*/?\s*{c[8:12]}\s*-?\s*{c[12:14]}(?!\d)")
    # Quem PUBLICOU: "Prefeituras/Estado do Rio Grande do Sul/Prefeitura
    # Municipal de Santa Maria" (armadilha 8). Nome até o FIM da hierarquia:
    # "...de Santa Maria do Salto" é outro município.
    if estado:
        p["orgao"] = re.compile(
            rf"^PREFEITURAS\s*/\s*ESTADO\s+D[OAE]\s+{_nome_regex(estado)}\s*/\s*"
            rf"(?:PREFEITURA\s+MUNICIPAL|PREFEITURA|MUNICIPIO|CAMARA\s+MUNICIPAL)"
            rf"\s+D[EOA]\s+{_nome_regex(nome)}\s*$")
    return p


# O que vem logo antes do nome e diz que o texto fala do ENTE, e não do lugar.
_PREFIXO_ENTE = re.compile(
    r"(?:MUNICIPIO|PREFEITURA(?:\s+MUNICIPAL)?|CAMARA\s+MUNICIPAL|FUNDO\s+MUNICIPAL\b.{0,40})"
    r"\s+D[EOA]\s*$")
# ...a não ser que o "Município de" seja ENDEREÇO: "empresa DROGA MINAS SUL LTDA,
# localizada no Município de Monte Sião - MG" (Farmácia Popular, 08/09/2026).
_PREFIXO_LUGAR = re.compile(
    r"(?:LOCALIZAD|SEDIAD|RESIDENT|DOMICILIAD|ESTABELECID|SITUAD)\w*\s+(?:NO|EM|NA)\s+"
    r"(?:\w+\s+){0,2}$")

# Força da ligação, da maior para a menor. `cidade` é o nome colado à UF SEM
# "Município de" antes: endereço de empresa, campus, vara federal (armadilha 9).
EVIDENCIAS = ("orgao", "ibge", "cnpj", "municipio", "cidade")


def evidencia_no_texto(texto_norm: str, p: dict,
                       orgao_norm: str | None = None) -> tuple[str, int] | None:
    """(evidência, posição) da ligação mais forte do município com o ato, ou None.

    Ordem de `EVIDENCIAS`. O nome sozinho NUNCA basta (armadilha 1)."""
    rx = p.get("orgao")
    if rx is not None and orgao_norm and rx.search(orgao_norm.strip()):
        return "orgao", 0
    for chave, tipo in (("ibge7", "ibge"), ("ibge6", "ibge"), ("cnpj", "cnpj")):
        rx = p.get(chave)
        achado = rx.search(texto_norm) if rx is not None else None
        if achado:
            return tipo, achado.start()
    rx = p.get("nome_uf")
    primeiro = None
    for achado in (rx.finditer(texto_norm) if rx is not None else ()):
        antes = texto_norm[max(0, achado.start() - 60):achado.start()]
        m = _PREFIXO_ENTE.search(antes)
        if m and not _PREFIXO_LUGAR.search(antes[:m.start()]):
            return "municipio", achado.start()
        if primeiro is None:
            primeiro = achado.start()
    rx = p.get("nome_unico")
    for achado in (rx.finditer(texto_norm) if rx is not None else ()):
        if not _PREFIXO_LUGAR.search(texto_norm[max(0, achado.start() - 40):achado.start()]):
            return "municipio", achado.start()
    if primeiro is not None:
        return "cidade", primeiro
    return None


def trecho(texto: str, pos: int) -> str:
    ini = max(0, pos - TRECHO_ANTES)
    fim = min(len(texto), pos + TRECHO_DEPOIS)
    if ini > 0:
        esp = texto.find(" ", ini)
        ini = esp + 1 if 0 <= esp < pos else ini
    if fim < len(texto):
        esp = texto.rfind(" ", pos, fim)
        fim = esp if esp > pos else fim
    t = re.sub(r"\s+", " ", texto[ini:fim]).strip()
    return ("… " if ini > 0 else "") + t + (" …" if fim < len(texto) else "")


# ---------------------------------------------------------------------------
# Classificação: o que o ato pede do município
# ---------------------------------------------------------------------------
# Ordem importa: o primeiro que casa decide. As quatro primeiras são as de
# CAPTAÇÃO (viram alerta no Radar); as outras só organizam a lista.
CATEGORIAS_CAPTACAO = ("emergencia", "selecao", "habilitacao", "repasse")
_REGRAS = (
    ("emergencia", r"SITUACAO DE EMERGENCIA|ESTADO DE CALAMIDADE|CALAMIDADE PUBLICA"),
    ("selecao", r"RESULTADO\b.{0,80}(SELECAO|CHAMAMENTO|CHAMADA PUBLICA)"
                r"|PROPOSTAS? SELECIONADA|SELECIONA(DAS?|DOS?)?\s+(AS|OS)?\s*PROPOSTA"
                r"|HOMOLOGA\b.{0,60}RESULTADO"),
    ("habilitacao", r"\bHABILITA|CREDENCIA"),
    # Prazo de ação JÁ autorizada: a Portaria MIDR 2.753 prorroga a Defesa Civil de
    # Nova Palma até 27/02/2027. Vem antes de `repasse` porque o texto cita a
    # portaria que "autorizou a transferência de recursos".
    ("prazo", r"PRORROG\w*\b.{0,40}PRAZO|(RENOV|ALTER)\w*\b.{0,20}PRAZO DE EXECUCAO"
              r"|PRAZO DE (EXECUCAO|VIGENCIA)"),
    # Instrumento assinado: extrato, aditivo. "Extrato de Contrato de REPASSE" é
    # isto, e não repasse novo — por isso vem antes.
    ("convenio", r"CONVENIO|TERMO DE COMPROMISSO|CONTRATO DE REPASSE|TERMO DE FOMENTO"
                 r"|TERMO DE COLABORACAO|TERMO ADITIVO|PLANO DE TRABALHO"),
    ("repasse", r"TRANSFERENCIA DE RECURSOS|REPASSE|FUNDO A FUNDO|INCREMENTO TEMPORARIO"
                r"|AUTORIZA\b.{0,80}TRANSFER|DESTINA\b.{0,40}RECURSO|ESTABELECE\b.{0,40}RECURSO"
                r"|RECURSOS? FINANCEIROS?|EMPENHO|APOIO FINANCEIRO|INCENTIVO FINANCEIRO"
                r"|COMPLEMENTAC(AO|OES) DA UNIAO|CRONOGRAMAS? DE DESEMBOLSO"),
    ("licitacao", r"LICITACAO|PREGAO|CONCORRENCIA|TOMADA DE PRECOS|DISPENSA|INEXIGIBILIDADE"
                  r"|ATA DE REGISTRO|HOMOLOGACAO|ADJUDICACAO"),
)
_REGRAS_RX = tuple((c, re.compile(r)) for c, r in _REGRAS)


def categoria(titulo: str | None, ementa: str | None, tipo_ato: str | None,
              inicio_texto: str | None = None) -> str:
    """`emergencia` | `selecao` | `habilitacao` | `prazo` | `convenio` |
    `repasse` | `licitacao` | `outros`, pelo título, tipo e ementa do ato.

    O corpo do texto só entra quando não há ementa (extrato no DO3 não tem, e
    portaria de prorrogação também não): o começo e o que vem depois do
    "resolve:", que é o dispositivo. Uma portaria de nomeação cita "recursos" no
    preâmbulo e não é repasse — por isso nunca o texto inteiro."""
    t = normaliza(" | ".join(x for x in (tipo_ato, titulo, ementa) if x))
    if not ementa and inicio_texto:
        tn = normaliza(inicio_texto)
        t += " | " + tn[:600]
        r = tn.find("RESOLVE")
        if r >= 0:
            t += " | " + tn[r:r + 400]
    for cat, rx in _REGRAS_RX:
        if rx.search(t):
            return cat
    return "outros"


# ---------------------------------------------------------------------------
# Fonte
# ---------------------------------------------------------------------------
_RX_PARAMS = re.compile(
    r'<script[^>]*id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params"[^>]*>'
    r"(.*?)</script>", re.S)
_RX_TOTAL_PAG = re.compile(r"totalPages\s*:\s*(\d+)")


def _dmy(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def ler_resultados(pagina_html: str) -> tuple[list[dict], int]:
    """(itens, total de páginas). `BuscaFalhou` se o bloco não veio."""
    m = _RX_PARAMS.search(pagina_html)
    if not m:
        raise BuscaFalhou("página sem o bloco de resultados")
    try:
        itens = json.loads(m.group(1)).get("jsonArray") or []
    except ValueError as e:
        raise BuscaFalhou(f"bloco de resultados ilegível: {e}") from e
    tp = _RX_TOTAL_PAG.search(pagina_html)
    return itens, int(tp.group(1)) if tp else 1


def buscar(client: httpx.Client, termo: str, ini: date, fim: date) -> list[dict]:
    """Todos os resultados de `"termo"` entre `ini` e `fim` (as duas pontas
    inclusive), seguindo o cursor (armadilha 3)."""
    base = {"q": f'"{termo}"', "s": "todos", "exactDate": "personalizado",
            "sortType": "0", "delta": DELTA,
            "publishFrom": _dmy(ini), "publishTo": _dmy(fim)}
    todos: list[dict] = []
    params = dict(base)
    for pagina in range(1, MAX_PAGINAS + 1):
        r = client.get(BUSCA, params=params, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        itens, total = ler_resultados(r.text)
        if total > MAX_PAGINAS:
            # A 1ª página já diz o total: não gastar 30 pedidos para desistir.
            raise JanelaLarga(f'"{termo}": {total} páginas — janela larga demais')
        todos.extend(itens)
        if pagina >= total or not itens:
            return todos
        u = itens[-1]
        params = dict(base, currentPage=pagina, newPage=pagina + 1,
                      score=u.get("score", 0), id=u.get("classPK", ""),
                      displayDate=u.get("displayDateSortable", ""))
        time.sleep(PAUSA_S)
    raise JanelaLarga(f'"{termo}": mais de {MAX_PAGINAS} páginas — janela larga demais')


def ler_ato(pagina_html: str) -> dict:
    """Identificação, ementa e texto integral da página de um ato."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(pagina_html, "html.parser")
    corpo = soup.select_one("div.texto-dou")
    if corpo is None:
        raise ValueError("página do ato sem div.texto-dou")

    def _um(sel: str) -> str | None:
        el = corpo.select_one(sel)
        return re.sub(r"\s+", " ", el.get_text(" ")).strip() if el else None

    for tr in corpo.find_all("tr"):
        tr.append(" \n")
    texto = html_lib.unescape(corpo.get_text(" "))
    texto = re.sub(r"[ \t\r\f\v]+", " ", texto)
    return {"identifica": _um("p.identifica"), "ementa": _um("p.ementa"),
            "texto": texto}


def baixar_ato(client: httpx.Client, url_titulo: str) -> dict:
    r = client.get(ATO + url_titulo, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return ler_ato(r.text)


def catalogo_ibge(client: httpx.Client) -> list[tuple[str, str]] | None:
    """(UF, nome normalizado) dos 5.570 municípios, numa chamada (0,4 s, 2,3 MB).
    Falha devolve None: as regras de IBGE, CNPJ e nome colado à UF continuam
    valendo; só a de "Município de X" sem UF fica desligada na rodada."""
    try:
        r = client.get(IBGE_MUNICIPIOS, params={"view": "nivelado"}, headers=UA,
                       timeout=60)
        r.raise_for_status()
        lista = [(x["UF-sigla"], normaliza(x["municipio-nome"]).strip())
                 for x in r.json()]
    except Exception as e:
        log.warning("lista de municípios do IBGE indisponível (%s) — sem a regra "
                    "de nome único nesta rodada", type(e).__name__)
        return None
    return lista if len(lista) > 5000 else None


def travas(catalogo: list[tuple[str, str]] | None, uf: str, nome: str) -> dict:
    """Ver `padroes`. `nome` já normalizado."""
    if not catalogo:
        return {}
    return {
        "antes": [n[: -len(nome)].strip() for u, n in catalogo
                  if u == uf and n != nome and n.endswith(" " + nome)],
        "depois": sorted({n[len(nome):].strip() for _, n in catalogo
                          if n != nome and n.startswith(nome + " ")}),
        "unico": sum(1 for _, n in catalogo if n == nome) == 1,
    }


def _data_br(s: str | None) -> date | None:
    try:
        return datetime.strptime((s or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def linha_ato(hit: dict, lido: dict) -> dict:
    tipo = (hit.get("artType") or "").strip() or None
    titulo = lido.get("identifica") or (hit.get("title") or "").strip() or None
    return {
        "url_titulo": hit["urlTitle"],
        "class_pk": str(hit.get("classPK") or "") or None,
        "secao": hit.get("pubName"),
        "edicao": hit.get("editionNumber"),
        "pagina": hit.get("numberPage"),
        "data_publicacao": _data_br(hit.get("pubDate")),
        "tipo_ato": tipo,
        "orgao": hit.get("hierarchyStr"),
        "titulo": titulo,
        "ementa": lido.get("ementa"),
        "categoria": categoria(titulo, lido.get("ementa"), tipo, lido.get("texto")),
    }


def avaliar(texto: str, alvos: list[dict], orgao: str | None = None) -> list[dict]:
    """Os alvos que o ato cita com evidência forte, com o trecho."""
    tn = normaliza(texto)
    on = normaliza(orgao) if orgao else None
    saida = []
    for a in alvos:
        ev = evidencia_no_texto(tn, a["padroes"], on)
        if ev:
            saida.append({"municipio_id": a["id"], "evidencia": ev[0],
                          "trecho": trecho(texto, ev[1])})
    return saida


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
def _alvos(cur) -> list[dict]:
    cur.execute("""
        SELECT m.id, m.nome, upper(coalesce(m.uf, '')), m.ibge_code, m.cnpj,
               c.conferido_ate
          FROM municipios m LEFT JOIN dou_cobertura c ON c.municipio_id = m.id
         WHERE m.active AND m.ibge_code IS NOT NULL
         ORDER BY c.conferido_ate NULLS FIRST, m.nome
    """)
    return [{"id": r[0], "nome": r[1], "uf": r[2], "ibge": r[3], "cnpj": r[4],
             "conferido_ate": r[5]} for r in cur.fetchall()]


def _ja_avaliados(cur, urls: list[str]) -> set[str]:
    if not urls:
        return set()
    cur.execute("SELECT url_titulo FROM dou_atos WHERE url_titulo = ANY(%s)", (urls,))
    return {r[0] for r in cur.fetchall()}


def _grava_ato(cur, linha: dict, citacoes: list[dict]) -> int:
    cur.execute("""
        INSERT INTO dou_atos (url_titulo, class_pk, secao, edicao, pagina,
            data_publicacao, tipo_ato, orgao, titulo, ementa, categoria, avaliado_em)
        VALUES (%(url_titulo)s, %(class_pk)s, %(secao)s, %(edicao)s, %(pagina)s,
            %(data_publicacao)s, %(tipo_ato)s, %(orgao)s, %(titulo)s, %(ementa)s,
            %(categoria)s, NOW())
        ON CONFLICT (url_titulo) DO UPDATE SET
            class_pk = EXCLUDED.class_pk, secao = EXCLUDED.secao,
            edicao = EXCLUDED.edicao, pagina = EXCLUDED.pagina,
            data_publicacao = EXCLUDED.data_publicacao, tipo_ato = EXCLUDED.tipo_ato,
            orgao = EXCLUDED.orgao, titulo = EXCLUDED.titulo, ementa = EXCLUDED.ementa,
            categoria = EXCLUDED.categoria, avaliado_em = NOW()
        RETURNING id
    """, linha)
    ato_id = cur.fetchone()[0]
    for c in citacoes:
        cur.execute("""
            INSERT INTO dou_atos_municipio (ato_id, municipio_id, evidencia, trecho)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (ato_id, municipio_id) DO UPDATE SET
                evidencia = EXCLUDED.evidencia, trecho = EXCLUDED.trecho
        """, (ato_id, c["municipio_id"], c["evidencia"], c["trecho"]))
    return ato_id


def _marca_cobertura(cur, mid: int, ate: date) -> None:
    cur.execute("""
        INSERT INTO dou_cobertura (municipio_id, conferido_ate, atualizado_em)
        VALUES (%s, %s, NOW())
        ON CONFLICT (municipio_id) DO UPDATE SET
            conferido_ate = EXCLUDED.conferido_ate, atualizado_em = NOW()
    """, (mid, ate))


def _log_ingest(cur, conn, status: str, n: int, nota: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES (%s, %s, %s, %s, NOW())",
            (FONTE, status, n, nota))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.warning("ingestion_log falhou: %s", str(e)[:120])


# ---------------------------------------------------------------------------
# Rodada
# ---------------------------------------------------------------------------
def hoje_br() -> date:
    return datetime.now(timezone(timedelta(hours=-3))).date()


def janela(conferido_ate: date | None, hoje: date) -> date:
    """Primeiro dia a buscar para um município."""
    if conferido_ate is None:
        return hoje - timedelta(days=DIAS_INICIAL)
    return max(conferido_ate - timedelta(days=DIAS_REVISAO),
               hoje - timedelta(days=DIAS_MAX))


def termos(a: dict) -> list[str]:
    """O que buscar: o nome e o IBGE (7 e 6 dígitos — a tabela do MS usa o de 6)."""
    t = [a["nome"].strip()]
    i7 = re.sub(r"\D", "", a.get("ibge") or "")
    if len(i7) == 7:
        t += [i7, i7[:6]]
    return t


def frases(a: dict) -> list[str]:
    """Troca do nome quando ele estoura a busca (armadilha 10): só o que a
    prefeitura escreve. "X/UF" também pega "X - UF" e "X (UF)" — a busca ignora
    a pontuação."""
    n = a["nome"].strip()
    return [f"Município de {n}", f"Prefeitura Municipal de {n}", f"{n}/{a['uf']}"]


def candidatos(client: httpx.Client, a: dict, ini: date, fim: date) -> dict[str, dict]:
    """urlTitle -> item da busca, somando os termos do município."""
    achados: dict[str, dict] = {}
    nome = a["nome"].strip()
    for termo in termos(a):
        try:
            hits = buscar(client, termo, ini, fim)
        except JanelaLarga as e:
            if termo != nome:
                raise
            log.info("  %s: %s; buscando pelas frases da prefeitura", nome, e)
            hits = []
            for f in frases(a):
                hits += buscar(client, f, ini, fim)
                time.sleep(PAUSA_S)
        for hit in hits:
            if hit.get("urlTitle"):
                achados.setdefault(hit["urlTitle"], hit)
        time.sleep(PAUSA_S)
    return achados


def ingest(dry: bool = False) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    inicio = time.monotonic()
    hoje = hoje_br()
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            alvos = _alvos(cur)
            if not alvos:
                log.info("nenhum município ativo com IBGE — nada a buscar")
                if not dry:
                    _log_ingest(cur, conn, "success", 0)
                return 0
            gravados, notas, parcial, pulados = 0, [], False, 0
            with httpx.Client(follow_redirects=True) as client:
                catalogo = catalogo_ibge(client)
                for a in alvos:
                    a["padroes"] = padroes(
                        a, travas(catalogo, a["uf"], normaliza(a["nome"]).strip()))
                for a in alvos:
                    if time.monotonic() - inicio > ORCAMENTO_S:
                        pulados += 1
                        continue
                    ini = janela(a["conferido_ate"], hoje)
                    try:
                        achados = candidatos(client, a, ini, hoje)
                    except Exception as e:
                        parcial = True
                        notas.append(f"{a['nome']}: busca {type(e).__name__}")
                        log.warning("  %s: busca falhou: %s", a["nome"], str(e)[:200])
                        continue
                    novo = a["conferido_ate"] is None
                    conhecidos = set() if (REAVALIAR or novo) else _ja_avaliados(
                        cur, list(achados))
                    falhas, citados, estourou = 0, 0, False
                    for url, hit in achados.items():
                        if url in conhecidos:
                            continue
                        if time.monotonic() - inicio > ORCAMENTO_S:
                            estourou = True   # armadilha 11
                            break
                        try:
                            lido = baixar_ato(client, url)
                        except Exception as e:
                            falhas += 1
                            log.warning("  %s: ato %s: %s", a["nome"], url,
                                        str(e)[:150])
                            continue
                        linha = linha_ato(hit, lido)
                        if linha["data_publicacao"] is None:
                            falhas += 1
                            continue
                        cit = avaliar(lido["texto"], alvos, hit.get("hierarchyStr"))
                        citados += sum(1 for c in cit if c["municipio_id"] == a["id"])
                        if dry:
                            log.info("  %s | %s | %s | %s", linha["data_publicacao"],
                                     linha["categoria"], linha["titulo"],
                                     [(c["municipio_id"], c["evidencia"]) for c in cit])
                        else:
                            _grava_ato(cur, linha, cit)
                            gravados += len(cit)
                            conhecidos.add(url)
                        time.sleep(PAUSA_S)
                    if falhas or estourou:
                        # Ato que não foi lido pode ser justamente o do município:
                        # a cobertura não anda e a próxima rodada revê a janela.
                        parcial = True
                        if falhas:
                            notas.append(f"{a['nome']}: {falhas} ato(s) sem leitura")
                        if estourou:
                            notas.append(f"{a['nome']}: orçamento acabou no meio dos "
                                         "atos, continua na próxima rodada")
                    elif not dry:
                        _marca_cobertura(cur, a["id"], hoje)
                    if not dry:
                        conn.commit()
                    log.info("  %s (%s): %d candidato(s) desde %s, %d novo(s) citando o "
                             "município", a["nome"], a["uf"], len(achados),
                             ini.strftime("%d/%m"), citados)
            if pulados:
                parcial = True
                notas.append(f"orçamento de {ORCAMENTO_S}s: {pulados} município(s) "
                             "ficam para a próxima rodada")
            if dry:
                return 0
            status = "partial" if parcial else "success"
            nota = " | ".join(notas)[:400] or None
            log.info("=== DOU federal: %d citação(ões) gravada(s), status=%s ===",
                     gravados, status)
            _log_ingest(cur, conn, status, gravados, nota)
            return gravados
        except Exception as e:
            conn.rollback()
            log.error("DOU federal falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


def ensaio_sem_banco(nome: str, uf: str, ibge: str, cnpj: str | None, dias: int) -> None:
    """`--dry --ibge`: busca, lê e avalia sem banco — para conferir a fonte à mão."""
    hoje = hoje_br()
    alvo = {"id": 0, "nome": nome, "uf": uf.upper(), "ibge": ibge, "cnpj": cnpj}
    with httpx.Client(follow_redirects=True) as client:
        trava = travas(catalogo_ibge(client), alvo["uf"], normaliza(nome).strip())
        alvo["padroes"] = padroes(alvo, trava)
        achados = candidatos(client, alvo, hoje - timedelta(days=dias), hoje)
        log.info("%d candidato(s) em %d dias (trava: %s)", len(achados), dias, trava)
        entram = 0
        for url, hit in achados.items():
            lido = baixar_ato(client, url)
            linha = linha_ato(hit, lido)
            cit = avaliar(lido["texto"], [alvo], hit.get("hierarchyStr"))
            entram += bool(cit)
            log.info("%s %s | %-11s | %s | %s", "ENTRA" if cit else "  -  ",
                     linha["data_publicacao"], linha["categoria"],
                     (linha["titulo"] or "")[:70],
                     cit[0]["evidencia"] if cit else "")
            if cit:
                log.info("        %s", cit[0]["trecho"][:300])
            time.sleep(PAUSA_S)
        log.info("=== %d de %d candidato(s) entram ===", entram, len(achados))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser()
    p.add_argument("--dry", action="store_true")
    p.add_argument("--ibge", help="com --dry: avalia só este município, sem banco")
    p.add_argument("--nome")
    p.add_argument("--uf")
    p.add_argument("--cnpj")
    p.add_argument("--dias", type=int, default=30)
    a = p.parse_args()
    if a.dry and a.ibge:
        ensaio_sem_banco(a.nome, a.uf, a.ibge, a.cnpj, a.dias)
    else:
        ingest(dry=a.dry)
