"""
SIOPS (saúde), SIOPE (educação) e os instrumentos de planejamento do SUS
(Plano, PAS, RDQA, RAG) — o detalhe que falta aos itens 3.2.3, 3.2.4, 5.1 e 5.2
do CAUC. Tudo público, sem login e sem token.

O CAUC só diz "!" ou uma data de validade. Ele não diz QUAL bimestre falta, nem o
percentual aplicado, nem se o município JÁ entregou e o Tesouro ainda não
atualizou. Este coletor diz as três coisas, e é o que mata o alarme falso de
Nova Palma/RS: 4º bimestre do SIOPS homologado em 23/09/2026, CAUC 3.2.4 ainda
"válido até 30/09" — e o PACTHA avisando "vence em 6 dias".

As quatro fontes (todas responderam 200 da VPS em 24/09/2026):

    SIOPS, API:    https://siops-consulta-publica-api.saude.gov.br/v1/
                   indicador/municipal/{ibge6}/{ano}/{periodo}
                   -> 14 indicadores; o "3.2" é o % da receita própria em ASPS
                      (mínimo 15%), com numerador e denominador. ~0,15 s.
    SIOPS, legado: http://siops.datasus.gov.br/consmuntransm.php  (POST cmbAno,
                   cmbUF, cmbPeriodo, cmbOrdenacao=Codigo)
                   -> a lista dos municípios HOMOLOGADOS da UF naquele período,
                      com a DATA da homologação. 0,1-1,2 MB, 1-4 s. Uma chamada
                      por UF e período.
    SIOPE, OData:  https://www.fnde.gov.br/olinda-ide/servico/DADOS_ABERTOS_SIOPE/
                   versao/v1/odata/{Dados_Gerais_Siope|Indicadores_Siope}
                   (Ano_Consulta, Num_Peri, Sig_UF) -> por UF: DAT_DECL e NUM_RECI
                      de quem declarou; o indicador 1.1 (% em MDE, mínimo 25%) e o
                      1.2 (FUNDEB na remuneração, mínimo 70%). ~1-3 s por chamada.
    DigiSUS DGMP:  https://digisusgmp.saude.gov.br/v1.5/transparencia/extracao/
                   download?co_esfera=1&fase={2|9}&uf=XX&instrumento=&formato=2
                   -> HTML disfarçado de .xls, uma linha por município, com a
                      situação de Plano, PAS, 1º/2º/3º RDQA e RAG por ano.
                      Fase 2 = 2022-2025, fase 9 = 2026-2029. 1-20 s por UF (MG
                      e PR são os lentos).

AS ARMADILHAS, medidas em 24/09/2026:

1. ⚠️⚠️ **A API DO SIOPS RESPONDE `msg03` PARA TUDO QUE NÃO ACHA.** O bimestre
   não homologado volta HTTP 404 com `{"error":"msg03","message":"Dados não
   homologado(s)."}` — e o MESMO 404 com a MESMA frase volta para IBGE de 7
   dígitos (3143401), IBGE inexistente (999999), ano 2030 e período 99. Ler
   `msg03` como "não entregue" sem prova transformaria qualquer erro nosso de
   chave num município inadimplente. Por isso quem diz "não entregue" é a LISTA
   LEGADA de homologados (armadilha 2): a API só é perguntada por quem a lista
   diz que homologou (para buscar o %), e um `msg03` sem lista que o confirme é
   "não sei" — sem linha gravada, rodada `partial`.

2. **A lista legada só traz quem HOMOLOGOU**, com a data (RS 2026 4º bimestre:
   213 de 497). O rodapé diz "Quantidade de Municípios que Transmitiram: 213" —
   e o parser confere as linhas contra esse número: diferente = layout mudou,
   a lista é recusada (nunca "ninguém entregou"). Lista VAZIA (período recém
   encerrado, ou página quebrada) também não prova ausência de ninguém.

3. **Os códigos de período do SIOPS não são 1..6**: 12, 14, 1, 18, 20, 2 = 1º a
   6º bimestre (o 3º e o 6º têm os códigos do 1º e 2º semestre). Conferido no
   formulário e na receita acumulada de Monte Sião 2025, que cresce nessa ordem.
   O SIOPE usa 1..6 mesmo.

4. **O SIOPE (Olinda) exige `%20` no `$filter`.** O `params=` do httpx troca o
   espaço por `+`, e o Olinda responde 400 "The types 'Edm.Boolean' and
   'Edm.Int32' are not compatible". A URL é montada à mão com `quote()`.

5. **SIOPE: filtro por COD_MUNI impossível devolve 200 com `value: []`** — igual
   a "não declarou". Por isso a consulta é da UF INTEIRA (uma chamada traz os ~470
   declarantes do RS, 93 KB) e o município ausente só vira "não entregue" quando
   a UF veio com gente dentro. UF vazia = "não sei".

6. **`Dados_Gerais_Siope_Dados_Responsaveis` traz nome, e-mail e telefone do
   responsável.** Não é lido. `Dados_Gerais_Siope` vai com `$select` só dos
   campos de entrega.

7. **O percentual do bimestre é ACUMULADO e PARCIAL** (o mínimo se apura no ano,
   no 6º bimestre). O coletor grava o que a fonte publica; a cor é da regra em
   `services/saude_educacao.py`, a mesma da tela e do alerta.

8. **DGMP: as colunas saem do CABEÇALHO**, nunca de posição fixa: o arquivo tem
   12 colunas de identificação e depois grupos (Plano 1 coluna, os outros 4) com
   o ano na segunda linha do `thead`. Sem a coluna "CÓD. IBGE MUNICÍPIO" ou sem
   nenhum grupo conhecido, o arquivo é recusado. O rodapé traz o total de linhas
   e é conferido. Ano futuro ("Não Iniciado" em 2027-2029) é gravado, mas a tela
   não mostra: é calendário, não pendência.

9. **Monte Sião/MG (IBGE 3143401)** é o caso que prova o valor do DGMP: RAG
   2022-2025 aprovados e os RDQAs de 2023 a 2025 "Em Elaboração" — nunca
   concluídos. Juranda/PR (4112959) não declarou o 3º bimestre de 2026 ao SIOPE:
   é o "!" do CAUC 3.2.3.

A chave é o IBGE (6 dígitos nas quatro fontes = os 6 primeiros do nosso de 7) e a
UF sai do próprio IBGE — nunca do nome.

Rodável por Scheduled Task (1x/noite, todo worker) ou à mão:
    python -u ingestion/siops_siope.py            # coleta de verdade
    python -u ingestion/siops_siope.py --dry      # consulta e mostra, sem gravar
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime
from urllib.parse import quote

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.saude_educacao import (  # noqa: E402
    MINIMO, PERIODO_SIOPS, bimestres_encerrados, prazo_bimestre, rotulo_bimestre,
)

log = logging.getLogger("siops_siope")

SOURCE = "siops_siope"
API_SIOPS = "https://siops-consulta-publica-api.saude.gov.br/v1"
LEGADO_SIOPS = "http://siops.datasus.gov.br/consmuntransm.php"
SIOPE = "https://www.fnde.gov.br/olinda-ide/servico/DADOS_ABERTOS_SIOPE/versao/v1/odata"
DGMP = "https://digisusgmp.saude.gov.br/v1.5/transparencia/extracao/download"
# Fase do DigiSUS: 2 = quadriênio 2022-2025 (o 3º RDQA e o RAG de 2025 vencem em
# 2026), 9 = 2026-2029. Quando abrir o quadriênio seguinte, ele entra aqui.
FASES_DGMP = (2, 9)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131 Safari/537.36"}
TIMEOUT = 120
PAUSA_S = float(os.getenv("SIOPS_SIOPE_PAUSA_S") or "0.1")
# Orçamento interno: conferido ENTRE blocos (UF × período). O kill da task é
# maior (ver scripts/criar_task_siops_siope.sh).
BUDGET_S = int(os.getenv("SIOPS_SIOPE_BUDGET_S") or "1200")
FORCE = os.getenv("SIOPS_SIOPE_FORCE") == "1"

# Código IBGE da UF -> sigla (o SIOPE pede a sigla; a UF sai do IBGE).
UF_SIGLA = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}


class FonteIndisponivel(Exception):
    """A fonte respondeu algo que não prova nada (layout, vazio, erro)."""


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _pedir(client: httpx.Client, metodo: str, url: str, tentativas: int = 3, **kw) -> httpx.Response:
    """Com nova tentativa para rede e 5xx. 4xx volta para quem chamou decidir —
    o 404 `msg03` do SIOPS é resposta, não falha."""
    ultimo = None
    for i in range(tentativas):
        try:
            r = client.request(metodo, url, headers=UA, timeout=TIMEOUT, **kw)
            if r.status_code < 500:
                return r
            ultimo = FonteIndisponivel(f"HTTP {r.status_code}")
        except httpx.HTTPError as e:
            ultimo = e
        time.sleep(1.5 * (i + 1))
    raise ultimo  # type: ignore[misc]


def _num_br(v) -> float | None:
    """'22,22 %' -> 22.22 (SIOPS) e '10.27' -> 10.27 (SIOPE)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("%", "").strip()
    if not s or s in ("-", "null"):
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# SIOPS
# ---------------------------------------------------------------------------
def siops_indicadores(client: httpx.Client, ibge6: str, ano: int, bimestre: int):
    """('ok', lista) | ('msg03', None). Outra coisa levanta.

    ⚠️ `msg03` NÃO é "não entregue" (armadilha 1) — quem decide é o chamador,
    com a lista legada na mão."""
    r = _pedir(client, "GET",
               f"{API_SIOPS}/indicador/municipal/{ibge6}/{ano}/{PERIODO_SIOPS[bimestre]}")
    try:
        d = r.json()
    except ValueError:
        raise FonteIndisponivel(f"HTTP {r.status_code} sem JSON")
    if r.status_code == 404 and isinstance(d, list) and d and \
            isinstance(d[0], dict) and d[0].get("error") == "msg03":
        return "msg03", None
    if r.status_code != 200 or not isinstance(d, list) or not d:
        raise FonteIndisponivel(f"HTTP {r.status_code}: {str(d)[:120]}")
    return "ok", d


def parse_siops_indicadores(lista: list[dict]) -> dict:
    """{pct, numerador, denominador, indicadores} a partir da resposta da API.
    O "3.2" é o do CAUC 5.2 (% da receita própria em ASPS)."""
    ind = {}
    for x in lista:
        n = str(x.get("numero_indicador") or "").strip()
        if not n:
            continue
        ind[n] = {
            "descricao": " ".join(str(x.get("ds_indicador") or "").split()),
            "valor": _num_br(x.get("indicador_calculado")),
            "numerador": x.get("numerador"),
            "denominador": x.get("denominador"),
        }
    asps = ind.get("3.2") or {}
    return {
        "pct": asps.get("valor"),
        "numerador": asps.get("numerador"),
        "denominador": asps.get("denominador"),
        "indicadores": ind,
    }


_RE_LINHA_LEGADO = re.compile(
    r'<th class="tdc caixa"\s*>\s*(\d{6})\s*</th>\s*'
    r'<th class="caixa"\s*>.*?</th>\s*'
    r'<td[^>]*>(.*?)</td>', re.S)
_RE_TOTAL_LEGADO = re.compile(r"que Transmitiram\s*</td>\s*<td[^>]*>\s*(\d+)", re.S)
_RE_DATA = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


def parse_lista_homologados(html: str) -> dict[str, date | None]:
    """{ibge6: data_homologacao} da página legada (armadilha 2).

    Levanta FonteIndisponivel se o cabeçalho sumiu ou se o número de linhas não
    bate com o rodapé "que Transmitiram"."""
    if "Data da Homologa" not in html:
        raise FonteIndisponivel("página sem a coluna 'Data da Homologação' (layout mudou?)")
    out: dict[str, date | None] = {}
    for ibge6, cel in _RE_LINHA_LEGADO.findall(html):
        m = _RE_DATA.search(cel)
        d = None
        if m:
            try:
                d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                d = None
        out[ibge6] = d
    t = _RE_TOTAL_LEGADO.search(html)
    if not t:
        raise FonteIndisponivel("página sem o total 'que Transmitiram' (layout mudou?)")
    if int(t.group(1)) != len(out):
        raise FonteIndisponivel(
            f"lista com {len(out)} linha(s) e rodapé dizendo {t.group(1)} — layout mudou?")
    return out


def siops_homologados(client: httpx.Client, uf_cod: str, ano: int, bimestre: int) -> dict:
    r = _pedir(client, "POST", LEGADO_SIOPS, data={
        "cmbAno": ano, "cmbUF": uf_cod, "cmbPeriodo": PERIODO_SIOPS[bimestre],
        "cmbOrdenacao": "Codigo", "Submit": "Consulta"})
    if r.status_code != 200:
        raise FonteIndisponivel(f"HTTP {r.status_code}")
    return parse_lista_homologados(r.content.decode("latin-1"))


# ---------------------------------------------------------------------------
# SIOPE
# ---------------------------------------------------------------------------
def _siope_url(recurso: str, uf: str, ano: int, bimestre: int,
               filtro: str | None = None, select: str | None = None) -> str:
    # Armadilha 4: montada à mão, com %20 no $filter.
    u = (f"{SIOPE}/{recurso}(Ano_Consulta=@Ano_Consulta,Num_Peri=@Num_Peri,Sig_UF=@Sig_UF)"
         f"?@Ano_Consulta={ano}&@Num_Peri={bimestre}&@Sig_UF='{uf}'&$format=json")
    if filtro:
        u += "&$filter=" + quote(filtro)
    if select:
        u += "&$select=" + select
    return u


def _siope_valores(client: httpx.Client, url: str) -> list[dict]:
    r = _pedir(client, "GET", url)
    if r.status_code != 200:
        raise FonteIndisponivel(f"HTTP {r.status_code}: {r.text[:120]}")
    try:
        d = r.json()
    except ValueError:
        raise FonteIndisponivel("resposta sem JSON")
    if not isinstance(d, dict) or not isinstance(d.get("value"), list):
        raise FonteIndisponivel("resposta sem 'value' (layout mudou?)")
    return d["value"]


# Armadilha 6: SÓ os campos de entrega — nada de responsável.
_SIOPE_SELECT = "TIPO,NUM_ANO,NUM_PERI,COD_MUNI,NUM_RECI,DAT_DECL,IDN_DECL_RETI"


def parse_siope_declaracoes(valores: list[dict]) -> dict[str, dict]:
    """{cod6: {data, recibo, retificadora}}; com mais de uma, a mais recente."""
    out: dict[str, dict] = {}
    for x in valores:
        if str(x.get("TIPO") or "Municipal").strip().lower() != "municipal":
            continue
        cod = str(x.get("COD_MUNI") or "").strip()
        if len(cod) != 6:
            continue
        d = None
        try:
            d = date.fromisoformat(str(x.get("DAT_DECL"))[:10]) if x.get("DAT_DECL") else None
        except ValueError:
            d = None
        atual = out.get(cod)
        if atual and atual["data"] and d and d <= atual["data"]:
            continue
        out[cod] = {"data": d,
                    "recibo": str(x.get("NUM_RECI")) if x.get("NUM_RECI") is not None else None,
                    "retificadora": (x.get("IDN_DECL_RETI") or "").strip().upper() == "S"}
    return out


def parse_siope_indicadores(valores: list[dict]) -> dict[str, dict]:
    """{cod6: {"1.1": {nome, valor}, "1.2": {...}}}."""
    out: dict[str, dict] = {}
    for x in valores:
        cod = str(x.get("COD_MUNI") or "").strip()
        exib = str(x.get("COD_EXIB") or "").strip()
        if len(cod) != 6 or not exib:
            continue
        out.setdefault(cod, {})[exib] = {
            "descricao": " ".join(str(x.get("NOM_INDI") or "").split()),
            "valor": _num_br(x.get("VAL_INDI")),
        }
    return out


def siope_declaracoes(client: httpx.Client, uf: str, ano: int, bimestre: int) -> dict:
    return parse_siope_declaracoes(_siope_valores(
        client, _siope_url("Dados_Gerais_Siope", uf, ano, bimestre, select=_SIOPE_SELECT)))


def siope_indicadores(client: httpx.Client, uf: str, ano: int, bimestre: int) -> dict:
    return parse_siope_indicadores(_siope_valores(
        client, _siope_url("Indicadores_Siope", uf, ano, bimestre,
                           filtro="COD_EXIB eq '1.1' or COD_EXIB eq '1.2'")))


# ---------------------------------------------------------------------------
# DigiSUS DGMP
# ---------------------------------------------------------------------------
def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn")


def _texto(celula: str) -> str:
    t = re.sub(r"<[^>]+>", " ", celula)
    t = t.replace("&nbsp;", " ")
    return " ".join(t.split())


def _instrumento_do_grupo(nome: str) -> str | None:
    n = _sem_acento(nome).lower()
    m = re.search(r"([123])\s*[oº°]?\s*rdqa", n)
    if m:
        return f"RDQA{m.group(1)}"
    if "plano de saude" in n:
        return "PLANO"
    if "programacao anual" in n:
        return "PAS"
    if re.search(r"\brag\b", n) or "relatorio anual de gestao" in n:
        return "RAG"
    return None


_RE_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_RE_TH = re.compile(r"<th([^>]*)>(.*?)</th>", re.S)
_RE_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_RE_COLSPAN = re.compile(r'colspan="?(\d+)')
_RE_ROWSPAN = re.compile(r'rowspan="?(\d+)')


def parse_dgmp(html: str) -> dict[str, list[dict]]:
    """{ibge6: [{instrumento, ano, periodo, situacao}]} do arquivo do DGMP
    (armadilha 8). Levanta FonteIndisponivel se o layout não for reconhecido."""
    i, j = html.find("<thead"), html.find("</thead>")
    k = html.find("</tbody>")
    if i < 0 or j < 0 or k < 0:
        raise FonteIndisponivel("arquivo sem thead/tbody (layout mudou?)")
    linhas_cab = _RE_TR.findall(html[i:j])
    if len(linhas_cab) < 2:
        raise FonteIndisponivel("cabeçalho com menos de duas linhas")
    fixas: list[str] = []
    grupos: list[tuple[str, int]] = []
    for attrs, conteudo in _RE_TH.findall(linhas_cab[0]):
        nome = _texto(conteudo)
        if _RE_ROWSPAN.search(attrs):
            fixas.append(nome)
        else:
            m = _RE_COLSPAN.search(attrs)
            grupos.append((nome, int(m.group(1)) if m else 1))
    subs = [_texto(c) for _a, c in _RE_TH.findall(linhas_cab[1])]
    try:
        col_ibge = [_sem_acento(f).upper() for f in fixas].index("COD. IBGE MUNICIPIO")
    except ValueError:
        raise FonteIndisponivel("sem a coluna 'CÓD. IBGE MUNICÍPIO' (layout mudou?)")
    colunas: list[tuple[str | None, str]] = []   # (instrumento, subcabeçalho)
    for nome, n in grupos:
        instr = _instrumento_do_grupo(nome)
        for _ in range(n):
            colunas.append((instr, subs[len(colunas)] if len(colunas) < len(subs) else ""))
    if not any(c[0] for c in colunas):
        raise FonteIndisponivel(f"nenhum instrumento conhecido nos grupos {[g for g, _ in grupos]}")

    corpo = html[j:k]
    out: dict[str, list[dict]] = {}
    n_linhas = 0
    for tr in _RE_TR.findall(corpo):
        cels = [_texto(c) for c in _RE_TD.findall(tr)]
        if len(cels) < len(fixas) + len(colunas):
            continue
        n_linhas += 1
        ibge6 = re.sub(r"\D", "", cels[col_ibge])
        if len(ibge6) != 6:
            continue
        itens = []
        for (instr, sub), valor in zip(colunas, cels[len(fixas):]):
            if not instr or not valor:
                continue
            anos = re.findall(r"20\d{2}", sub)
            if not anos:
                continue
            itens.append({
                "instrumento": instr,
                "ano": int(anos[0]),
                # Só o Plano é quadrienal: "2026 - 2029" -> periodo "2026-2029".
                "periodo": "-".join(anos) if len(anos) > 1 else None,
                "situacao": valor,
            })
        out[ibge6] = itens
    # O rodapé "Total N" confere a leitura inteira.
    rod = re.search(r"Total</th>\s*<th[^>]*>\s*(\d+)", html[k:])
    if rod and int(rod.group(1)) != n_linhas:
        raise FonteIndisponivel(f"{n_linhas} linha(s) lida(s) e rodapé dizendo {rod.group(1)}")
    if not n_linhas:
        raise FonteIndisponivel("arquivo sem nenhuma linha de município")
    return out


def dgmp_extracao(client: httpx.Client, uf: str, fase: int) -> dict[str, list[dict]]:
    r = _pedir(client, "GET", DGMP, params={
        "co_esfera": 1, "fase": fase, "uf": uf, "instrumento": "", "formato": 2})
    if r.status_code != 200:
        raise FonteIndisponivel(f"HTTP {r.status_code}")
    return parse_dgmp(r.content.decode("utf-8-sig", errors="replace"))


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
def _alvos(cur) -> list[dict]:
    """Todo município ATIVO com IBGE de 7 dígitos. A UF sai do IBGE."""
    cur.execute("""
        SELECT id, nome, ibge_code FROM municipios
         WHERE active AND length(coalesce(ibge_code, '')) = 7
         ORDER BY ibge_code
    """)
    out = []
    for mid, nome, ibge in cur.fetchall():
        uf = UF_SIGLA.get(ibge[:2])
        if uf:
            out.append({"id": mid, "nome": nome, "ibge": ibge, "ibge6": ibge[:6],
                        "uf_cod": ibge[:2], "uf": uf})
    return out


_SQL_BIM = """
INSERT INTO saude_educacao_bimestre AS t
    (municipio_id, sistema, ano, bimestre, entregue, data_entrega, recibo,
     pct_aplicado, pct_minimo, numerador, denominador, indicadores, atualizado_em)
VALUES (%(mid)s, %(sistema)s, %(ano)s, %(bimestre)s, %(entregue)s, %(data)s, %(recibo)s,
        %(pct)s, %(minimo)s, %(num)s, %(den)s, %(ind)s::jsonb, NOW())
ON CONFLICT (municipio_id, sistema, ano, bimestre) DO UPDATE SET
    entregue = EXCLUDED.entregue,
    -- Entregue: o que faltou nesta rodada (lista legada fora do ar, indicador
    -- que falhou) fica com o valor já provado. Não entregue: limpa.
    data_entrega = CASE WHEN EXCLUDED.entregue
                        THEN COALESCE(EXCLUDED.data_entrega, t.data_entrega) END,
    recibo = CASE WHEN EXCLUDED.entregue THEN COALESCE(EXCLUDED.recibo, t.recibo) END,
    pct_aplicado = CASE WHEN EXCLUDED.entregue
                        THEN COALESCE(EXCLUDED.pct_aplicado, t.pct_aplicado) END,
    pct_minimo = EXCLUDED.pct_minimo,
    numerador = CASE WHEN EXCLUDED.entregue THEN COALESCE(EXCLUDED.numerador, t.numerador) END,
    denominador = CASE WHEN EXCLUDED.entregue
                       THEN COALESCE(EXCLUDED.denominador, t.denominador) END,
    indicadores = CASE WHEN EXCLUDED.entregue
                       THEN COALESCE(EXCLUDED.indicadores, t.indicadores) END,
    atualizado_em = NOW()
"""

_SQL_INSTR = """
INSERT INTO sus_instrumentos_planejamento
    (municipio_id, instrumento, ano, periodo, situacao, fase, atualizado_em)
VALUES (%(mid)s, %(instrumento)s, %(ano)s, %(periodo)s, %(situacao)s, %(fase)s, NOW())
ON CONFLICT (municipio_id, instrumento, ano) DO UPDATE SET
    periodo = EXCLUDED.periodo, situacao = EXCLUDED.situacao,
    fase = EXCLUDED.fase, atualizado_em = NOW()
"""


def _gravados(cur, ids: list[int]) -> dict:
    """{(mid, sistema, ano, bim): (entregue, data, pct, recibo)} já no banco."""
    cur.execute("""SELECT municipio_id, sistema, ano, bimestre, entregue, data_entrega,
                          pct_aplicado, recibo
                     FROM saude_educacao_bimestre WHERE municipio_id = ANY(%s)""", (ids,))
    return {(r[0], r[1], r[2], r[3]): (r[4], r[5], r[6], r[7]) for r in cur.fetchall()}


def _completo(gravados: dict, sistema: str, ano: int, bim: int, muns: list[dict]) -> bool:
    """Ano FECHADO com todo município entregue e com percentual: não pergunta de
    novo (SIOPS_SIOPE_FORCE=1 pergunta). O ano corrente é sempre perguntado."""
    if FORCE or ano >= date.today().year:
        return False
    for m in muns:
        g = gravados.get((m["id"], sistema, ano, bim))
        if not g or not g[0] or g[2] is None:
            return False
    return True


def _log_ingest(cur, conn, status: str, n: int, erro: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES (%s, %s, %s, %s, NOW())",
            (SOURCE, status, n, erro))
        conn.commit()
    except Exception as e:  # a contabilidade nunca derruba a coleta
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def status_da_rodada(gravados: int, falhas: list[str]) -> tuple[str, str | None]:
    """success sem falha; partial com falha e algo gravado; error sem nada.
    O motivo lista as primeiras falhas — é o que o vigia e o resumo mostram."""
    if not falhas:
        return "success", None
    motivo = f"{len(falhas)} falha(s): " + " | ".join(falhas[:6])
    return ("partial" if gravados else "error"), motivo[:900]


# ---------------------------------------------------------------------------
class _Rodada:
    def __init__(self, cur, dry: bool):
        self.cur, self.dry = cur, dry
        self.gravados = 0
        self.falhas: list[str] = []
        self.inicio = time.monotonic()
        self.resumo: dict = {}

    def estourou(self) -> bool:
        return time.monotonic() - self.inicio > BUDGET_S

    def bim(self, m: dict, sistema: str, ano: int, b: int, entregue: bool,
            data=None, recibo=None, pct=None, num=None, den=None, ind=None) -> None:
        self.resumo.setdefault(m["nome"], []).append(
            (sistema, ano, b, entregue, data, pct))
        if self.dry:
            return
        self.cur.execute(_SQL_BIM, {
            "mid": m["id"], "sistema": sistema, "ano": ano, "bimestre": b,
            "entregue": entregue, "data": data, "recibo": recibo, "pct": pct,
            "minimo": MINIMO[sistema], "num": num, "den": den,
            "ind": json.dumps(ind, ensure_ascii=False) if ind else None,
        })
        self.gravados += 1


def _coletar_siops(client, rod: _Rodada, por_uf: dict, gravados: dict, hoje: date) -> None:
    for ano, b in bimestres_encerrados(hoje):
        rot = rotulo_bimestre(ano, b)
        for uf_cod, muns in por_uf.items():
            uf = UF_SIGLA[uf_cod]
            if rod.estourou():
                rod.falhas.append(f"SIOPS: orçamento de {BUDGET_S}s estourou antes de {uf} {rot}")
                return
            if _completo(gravados, "SIOPS", ano, b, muns):
                continue
            lista = None
            try:
                lista = siops_homologados(client, uf_cod, ano, b) or None
            except Exception as e:
                rod.falhas.append(f"SIOPS {uf} {rot}: lista de homologados: "
                                  f"{type(e).__name__}: {str(e)[:80]}")
            if lista is None and hoje > prazo_bimestre(ano, b):
                log.warning("SIOPS %s %s: sem lista de homologados — só a API responde "
                            "por quem entregou; ausência vira 'não sei'", uf, rot)
            nao_sei = erros_api = 0
            for m in muns:
                if lista is not None and m["ibge6"] not in lista:
                    rod.bim(m, "SIOPS", ano, b, False)          # a lista PROVA
                    continue
                data = lista.get(m["ibge6"]) if lista else None
                g = gravados.get((m["id"], "SIOPS", ano, b))
                if lista is not None and g and g[0] and g[1] == data and g[2] is not None \
                        and not FORCE:
                    # Mesma homologação já lida: o dado não mudou.
                    rod.bim(m, "SIOPS", ano, b, True, data=data, pct=g[2])
                    continue
                try:
                    st, resp = siops_indicadores(client, m["ibge6"], ano, b)
                except Exception as e:
                    erros_api += 1
                    log.warning("  SIOPS API %s %s: %s: %s", m["nome"], rot,
                                type(e).__name__, str(e)[:100])
                    if lista is not None:
                        rod.bim(m, "SIOPS", ano, b, True, data=data)   # a lista prova
                    continue
                finally:
                    time.sleep(PAUSA_S)
                if st == "ok":
                    p = parse_siops_indicadores(resp)
                    rod.bim(m, "SIOPS", ano, b, True, data=data, pct=p["pct"],
                            num=p["numerador"], den=p["denominador"], ind=p["indicadores"])
                elif lista is not None:
                    # A lista diz homologado e a API diz msg03: vale a lista (é
                    # ela que tem a data), sem percentual.
                    log.warning("  SIOPS %s %s: homologado em %s na lista, msg03 na API",
                                m["nome"], rot, data)
                    rod.bim(m, "SIOPS", ano, b, True, data=data)
                else:
                    nao_sei += 1                    # armadilha 1: msg03 sem prova
            if erros_api:
                rod.falhas.append(f"SIOPS {uf} {rot}: API falhou para {erros_api} município(s)")
            if nao_sei and hoje > prazo_bimestre(ano, b):
                rod.falhas.append(f"SIOPS {uf} {rot}: {nao_sei} município(s) sem prova "
                                  f"de entrega nem de falta (lista legada indisponível)")


def _coletar_siope(client, rod: _Rodada, por_uf: dict, gravados: dict, hoje: date) -> None:
    for ano, b in bimestres_encerrados(hoje):
        rot = rotulo_bimestre(ano, b)
        for uf_cod, muns in por_uf.items():
            uf = UF_SIGLA[uf_cod]
            if rod.estourou():
                rod.falhas.append(f"SIOPE: orçamento de {BUDGET_S}s estourou antes de {uf} {rot}")
                return
            if _completo(gravados, "SIOPE", ano, b, muns):
                continue
            try:
                decl = siope_declaracoes(client, uf, ano, b)
            except Exception as e:
                rod.falhas.append(f"SIOPE {uf} {rot}: declarações: {type(e).__name__}: {str(e)[:80]}")
                continue
            if not decl:
                # Armadilha 5: UF vazia não prova a falta de ninguém.
                if hoje > prazo_bimestre(ano, b):
                    rod.falhas.append(f"SIOPE {uf} {rot}: UF sem nenhuma declaração com o "
                                      f"prazo vencido — fonte fora do ar?")
                continue
            try:
                ind = siope_indicadores(client, uf, ano, b)
            except Exception as e:
                ind = {}
                rod.falhas.append(f"SIOPE {uf} {rot}: indicadores: {type(e).__name__}: {str(e)[:80]}")
            for m in muns:
                d = decl.get(m["ibge6"])
                if not d:
                    rod.bim(m, "SIOPE", ano, b, False)
                    continue
                i = ind.get(m["ibge6"]) or {}
                mde = (i.get("1.1") or {}).get("valor")
                rod.bim(m, "SIOPE", ano, b, True, data=d["data"], recibo=d["recibo"],
                        pct=mde, ind=({**i, "_retificadora": d["retificadora"]} if i else None))


def _coletar_dgmp(client, rod: _Rodada, por_uf: dict) -> None:
    for uf_cod, muns in por_uf.items():
        uf = UF_SIGLA[uf_cod]
        for fase in FASES_DGMP:
            if rod.estourou():
                rod.falhas.append(f"DGMP: orçamento de {BUDGET_S}s estourou antes de {uf} fase {fase}")
                return
            try:
                t0 = time.monotonic()
                por_ibge = dgmp_extracao(client, uf, fase)
                log.info("DGMP %s fase %d: %d município(s) em %.1fs", uf, fase,
                         len(por_ibge), time.monotonic() - t0)
            except Exception as e:
                rod.falhas.append(f"DGMP {uf} fase {fase}: {type(e).__name__}: {str(e)[:80]}")
                continue
            for m in muns:
                itens = por_ibge.get(m["ibge6"])
                if itens is None:
                    rod.falhas.append(f"DGMP {uf} fase {fase}: {m['nome']} fora do arquivo")
                    continue
                for it in itens:
                    rod.resumo.setdefault(m["nome"] + " (SUS)", []).append(
                        (it["instrumento"], it["ano"], it["situacao"]))
                    if rod.dry:
                        continue
                    rod.cur.execute(_SQL_INSTR, {"mid": m["id"], "fase": fase, **it})
                    rod.gravados += 1


def ingest(dry: bool = False) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    hoje = date.today()
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        rod = _Rodada(cur, dry)
        try:
            alvos = _alvos(cur)
            if not alvos:
                log.info("nenhum município ativo com IBGE — nada a coletar")
                if not dry:
                    _log_ingest(cur, conn, "success", 0)
                return 0
            por_uf: dict[str, list[dict]] = {}
            for a in alvos:
                por_uf.setdefault(a["uf_cod"], []).append(a)
            log.info("%d município(s) em %d UF(s): %s", len(alvos), len(por_uf),
                     ", ".join(f"{UF_SIGLA[u]}={len(m)}" for u, m in por_uf.items()))
            gravados = _gravados(cur, [a["id"] for a in alvos])

            with httpx.Client(follow_redirects=True) as client:
                for nome, fn in (("SIOPS", lambda: _coletar_siops(client, rod, por_uf, gravados, hoje)),
                                 ("SIOPE", lambda: _coletar_siope(client, rod, por_uf, gravados, hoje)),
                                 ("DGMP", lambda: _coletar_dgmp(client, rod, por_uf))):
                    t0 = time.monotonic()
                    try:
                        fn()
                    except Exception as e:
                        rod.falhas.append(f"{nome}: {type(e).__name__}: {str(e)[:120]}")
                        log.exception("%s falhou", nome)
                    if not dry:
                        conn.commit()           # cada fonte fica, mesmo se a próxima cair
                    log.info("%s: %.1fs", nome, time.monotonic() - t0)

            for nome, linhas in sorted(rod.resumo.items()):
                log.info("  %s: %s", nome, "; ".join(
                    " ".join("-" if v is None else str(v) for v in l) for l in linhas[-8:]))
            status, motivo = status_da_rodada(rod.gravados if not dry else 1, rod.falhas)
            for f in rod.falhas:
                log.warning("falha: %s", f)
            if dry:
                return 0
            log.info("=== SIOPS/SIOPE/DGMP: %d linha(s) gravada(s), status %s ===",
                     rod.gravados, status)
            _log_ingest(cur, conn, status, rod.gravados, motivo)
            return rod.gravados
        except Exception as e:
            conn.rollback()
            log.error("siops_siope falhou: %s: %s", type(e).__name__, str(e)[:200])
            if not dry:
                _log_ingest(cur, conn, "error", rod.gravados, f"{type(e).__name__}: {str(e)[:400]}")
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ingest(dry="--dry" in sys.argv)
