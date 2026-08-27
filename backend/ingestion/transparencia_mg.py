"""Portal da Transparencia de MG — confirma se o Estado PAGOU o convenio.

O QUE ISTO RESOLVE. O pedido do dono: "no portal fazemos as pesquisas por CNPJ do
Municipio para confirmar se o pagamento foi realizado". Hoje isso e feito a mao,
convenio a convenio.

O CAMINHO, provado em teste real (26/08/2026) e so com HTTP — sem browser, sem
login, sem credencial:

    CNPJ -> GET listagem com id_favorecido=0  -> resolve o id interno do portal
         -> GET listagem com o id            -> ids de empenho + token de sessao
         -> GET detalhamento=1               -> HISTORICO (traz o nº do convenio)
         -> GET detalhamento=3               -> pagamento (data, OB, situacao, valor)

⚠️ NAO E SPA. A URL parece Angular, mas o portal e JOOMLA (`com_transparenciamg`)
e a listagem vem renderizada no HTML. O detalhe e que e AJAX.

⚠️ SEM O COOKIE, O DETALHE DEVOLVE 0 BYTES — nao erro, nao 403: vazio. O cookie e
o token saem da propria listagem, entao o fluxo se resolve sozinho.

⚠️ OS DADOS ABERTOS NAO SERVEM. `dm_empenho_desp_AAAA.csv.gz` (dados.mg.gov.br)
tem 9 colunas e NAO traz o historico. Sem historico nao ha vinculo com o
convenio, e o vinculo e o ponto inteiro deste coletor. Medido, nao suposto.

⚠️ SO MINAS. E o portal do ESTADO de MG: serve municipio de MG e mais ninguem. O
coletor filtra por `uf='MG'` e, em tenant sem municipio de MG, nao faz uma
requisicao sequer — e diz isso no log, para "nao coletou" nunca se confundir com
"nao ha o que coletar".
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import date, datetime

logger = logging.getLogger("transparencia_mg")

_BASE = "https://www.transparencia.mg.gov.br"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# ⚠️ USER-AGENT DE NAVEGADOR NAO E ENFEITE: medido, o portal devolve 403 para o
# UA do curl/httpx em alguns caminhos (o download dos dados abertos, por exemplo).

# As abas do modal, na numeracao do proprio portal.
_ABA_EMPENHO = 1
_ABA_PAGAMENTO = 3

# ORCAMENTO. O host tem 2 vCPU e um LOCK UNICO entre todos os coletores — a regra
# da casa e nunca aumentar concorrencia de scraping. Os defaults sao propositalmente
# conservadores: e melhor cobrir menos por rodada, todo dia, do que estourar a
# janela e ser morto no meio, deixando estado pela metade.
_BUDGET_S = float(os.getenv("TRANSPMG_BUDGET_S", "600") or 600)
_MAX_MUNICIPIOS = int(os.getenv("TRANSPMG_LOTE_MUNICIPIOS", "8") or 8)
_MAX_DETALHES = int(os.getenv("TRANSPMG_MAX_DETALHES", "150") or 150)
_PAUSA_S = float(os.getenv("TRANSPMG_PAUSA_S", "0.4") or 0.4)

# ⚠️ MODO MEDICAO. `TRANSPMG_SO_LISTAGEM=1` varre as listagens, loga quantos
# empenhos cada municipio tem e NAO BUSCA DETALHE NEM GRAVA NADA. Existe porque
# tres numeros que mudam o desenho por ordens de grandeza (quantos empenhos por
# municipio, se a fase `pago` aceita janela por data de pagamento, e a taxa de
# acerto do vinculo) so producao responde — e chutar qualquer um deles custa mais
# do que medir.
_SO_LISTAGEM = (os.getenv("TRANSPMG_SO_LISTAGEM", "0") or "0").strip() == "1"


# ---------------------------------------------------------------------------
# FUNCOES PURAS — sao elas que decidem o vinculo, e as unicas testaveis sem banco
# (nao ha Postgres de teste em lugar nenhum deste repo).
# ---------------------------------------------------------------------------

# ⚠️ A REGEX DO CONVENIO, e por que ela e assim.
#
# O historico medido em producao:
#   "APROPRIACAO EMPENHO - INVESTIMENTOS AQUISICAO DE VEICULOS ... MUNICIPIO DE
#    PEQUI 1261002849/2025 9492993"
#
# O numero do convenio e `1261002849/2025`. Logo DEPOIS vem `9492993`, solto — e
# e por causa dele que a regex exige a BARRA e o ano de 4 digitos: um `\d{6,}`
# solto pegaria os dois e o segundo viraria um "convenio" que nao existe.
#
# 6 a 12 digitos cobre o que o SIGCON usa (nr_proposta/nr_plano_trabalho tem
# formatos diferentes por orgao) sem descer a numero de 3 digitos, que em texto
# livre e quase sempre outra coisa.
_RE_CONVENIO = re.compile(r"\b(\d{6,12})\s*/\s*((?:19|20)\d{2})\b")
# O numero solto que costuma seguir o do convenio. GUARDADO, nao usado para
# juntar — ver o comentario da coluna `numero_solto` na migration.
_RE_SOLTO = re.compile(r"/(?:19|20)\d{2}\s+(\d{6,9})\b")


def extrair_referencias(historico: str | None) -> tuple[str | None, str | None]:
    """(numero_do_convenio, numero_solto) a partir do texto livre do historico.

    Devolve (None, None) quando nao ha nada no formato — que e diferente de
    "historico vazio" e diferente de "nao li o historico". Quem distingue os tres
    e o `vinculo_status`, ver `classificar`."""
    s = " ".join((historico or "").split())
    if not s:
        return None, None
    m = _RE_CONVENIO.search(s)
    if not m:
        return None, None
    ref = f"{m.group(1)}/{m.group(2)}"
    ms = _RE_SOLTO.search(s)
    return ref, (ms.group(1) if ms else None)


def _so_digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def normalizar_ref(v) -> str:
    """Forma comparavel de um numero de convenio: so digitos, sem zeros a
    esquerda no corpo.

    ⚠️ O PORTAL E O SIGCON ESCREVEM DIFERENTE. O historico traz
    `1261002849/2025`; o SIGCON guarda o mesmo numero ora com barra, ora sem, e
    as vezes com zero a esquerda. Comparar as strings cruas erraria por
    pontuacao, e errar aqui vincula PAGAMENTO AO CONVENIO ERRADO — pior do que
    nao vincular."""
    d = _so_digitos(v)
    return d.lstrip("0") or d


def casar_convenio(ref: str | None, candidatos: list[dict]) -> tuple[int | None, str, str]:
    """Acha o convenio do municipio cujo numero bate com `ref`.

    `candidatos`: [{id, nr_proposta, nr_plano_trabalho, nr_siafi, nr_sigcon}, ...]
    Devolve (convenio_id, status, metodo).

    ⚠️ A ORDEM DAS COLUNAS E DELIBERADA e vai do mais especifico ao mais generico.
    `nr_sigcon` fica por ULTIMO porque ele e DERIVADO (nr_siafi > nr_plano >
    nr_proposta, ver sigcon_scraper) — casar por ele primeiro esconderia por qual
    campo o vinculo aconteceu de verdade, e e essa informacao que vai dizer,
    depois, qual chave vale a pena manter.

    ⚠️ AMBIGUIDADE NAO ESCOLHE. Dois convenios com o mesmo numero devolvem
    'ambiguo' e convenio_id None. Escolher "o primeiro" seria inventar um vinculo
    com 50% de chance de estar errado, e ninguem saberia."""
    if not ref:
        return None, "sem_numero", ""
    alvo = normalizar_ref(ref)
    if not alvo:
        return None, "sem_numero", ""
    for campo in ("nr_proposta", "nr_plano_trabalho", "nr_siafi", "nr_sigcon"):
        achados = [c for c in candidatos if normalizar_ref(c.get(campo)) == alvo]
        if len(achados) == 1:
            return achados[0].get("id"), "casado", campo
        if len(achados) > 1:
            return None, "ambiguo", campo
    return None, "nao_casou", ""


def classificar(detalhe_ok: bool, tem_rotulo: bool, historico: str | None,
                ref: str | None, convenio_id: int | None, status_casamento: str) -> str:
    """O `vinculo_status` final. Sete valores, nenhum deles colapsado num NULL.

    ⚠️ Sem esta distincao, uma mudanca de ROTULO no portal se disfarca de
    "empenho sem historico" para sempre — a cobertura cai e nada acusa. E o mesmo
    defeito que ja custou um ciclo inteiro nas Notas de Empenho."""
    if not detalhe_ok:
        return "detalhe_falhou"
    if not tem_rotulo:
        return "layout_mudou"
    if not (historico or "").strip():
        return "sem_historico"
    return status_casamento if not convenio_id else "casado"


def montar_pagamentos(linhas: list[dict]) -> dict:
    """O bloco `pagamentos`, no MESMO formato de `ops_obs` das voluntarias.

    ⚠️ O formato e copiado de proposito: `rm_builder._desembolso_ops_obs` e
    `rm_pdf._desembolso_destaque` ja sabem ler isso. Um formato proprio exigiria
    um segundo parser no builder — e seria a segunda copia da mesma regra, que
    neste repo e o jeito conhecido de as duas divergirem."""
    obs = []
    total = 0.0
    for l in linhas:
        v = l.get("valor")
        if v is not None:
            total += float(v)
        obs.append({
            "data_emissao_ob": l.get("data"),
            "valor": v,
            "numero_ob": l.get("numero"),
            "situacao": l.get("situacao"),
        })
    return {
        "valor_desembolsado": round(total, 2),
        "data_ultimo_desembolso": (obs[-1].get("data_emissao_ob") if obs else None),
        "obs": obs,
    }


# ---------------------------------------------------------------------------
# LEITURA DO HTML — o portal e Joomla, entao tudo chega renderizado.
# ---------------------------------------------------------------------------
_RE_ID_EMPENHO = re.compile(r'data-idEmpenho="(\d+)"')
# ⚠️ O TOKEN CSRF aparece em DUAS formas no mesmo HTML: como `&<md5>=1` (dentro
# do `data-session` que o JS concatena na URL) e como `name="<md5>" value="1"`
# (o campo escondido do formulario). Aceitar so uma delas e apostar em qual
# bloco do template vai sobreviver a proxima atualizacao do portal.
_RE_TOKEN = re.compile(
    r'(?:name="([0-9a-f]{32})"\s+value="1"|([0-9a-f]{32})=1)')


def ler_id_favorecido(html: str, cnpj: str) -> str | None:
    """O id interno do favorecido, a partir da pagina de LISTAGEM DE FAVORECIDOS
    (a mesma URL, com id_favorecido=0).

    ⚠️ E ESTE PASSO QUE DESTRAVA TUDO, e ele nao era obvio. O portal NAO tem
    autocomplete (digitar no campo nao dispara requisicao nenhuma) e o POST do
    formulario com o CNPJ cru resolve para id=0 e devolve zero empenho. O id
    estava no link da propria pagina de favorecidos."""
    # ⚠️ TODAS as ocorrencias, e a PRIMEIRA NAO-ZERO — nao a primeira. A pagina
    # cita a si mesma (`.../0/0/<cnpj>/4`, o link do breadcrumb "Favorecidos"),
    # entao `search` acha o zero e o coletor concluiria que nao resolveu. Custou
    # um teste contra o HTML de verdade para aparecer.
    achados = re.findall(
        r"despesa-favorecidos/\d{4}/[\d-]+/[\d-]+/(\d+)/0/" + re.escape(_so_digitos(cnpj)),
        html or "")
    return next((a for a in achados if a != "0"), None)


def ler_ids_empenho(html: str) -> list[str]:
    return list(dict.fromkeys(_RE_ID_EMPENHO.findall(html or "")))


def ler_token(html: str) -> str | None:
    m = _RE_TOKEN.search(html or "")
    return (m.group(1) or m.group(2)) if m else None


def _texto(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html or "").split())


_ROTULO_HIST = "Histórico do Empenho"


def ler_detalhe_empenho(html: str) -> dict:
    """Campos da aba Empenho. `tem_rotulo` diz se a pagina AINDA tem o rotulo do
    historico — e o que separa "layout mudou" de "historico vazio"."""
    t = _texto(html)
    tem_rotulo = ("Histórico do Empenho" in t) or ("Historico do Empenho" in t)
    hist = ""
    m = re.search(r"Hist[oó]rico do Empenho:\s*(.*?)(?:\s+Refor[cç]o|\s+Anula[cç][ãa]o|$)", t)
    if m:
        hist = m.group(1).strip()
    # ⚠️ O VALOR VAI ATE O PROXIMO ROTULO CONHECIDO, e nao ate "dois espacos" ou
    # "a proxima palavra com dois-pontos". O texto achatado do portal e uma linha
    # so — "Número do Empenho: 881 Ano de Exercício: 2026 Data de Registro..." —
    # e qualquer heuristica de espacamento devolve None ou o campo inteiro.
    _ROTULOS = ("Número do Empenho", "Ano de Exercício", "Data de Registro do Empenho",
                "Tipo de Empenho", "CNPJ/ CPF e Descrição do Favorecido",
                "Valor Inicial da despesa empenhada", "Valor Atual do Empenho",
                "Descrição Histórico do Empenho", "Reforço", "Anulação")

    def _campo(rot):
        prox = "|".join(re.escape(r) for r in _ROTULOS if r != rot)
        mm = re.search(re.escape(rot) + r":\s*(.*?)\s*(?:" + prox + r"|$)", t)
        v = (mm.group(1).strip() if mm else "")
        return v or None
    return {
        "tem_rotulo": tem_rotulo,
        "historico": hist,
        "nr_empenho": _campo("Número do Empenho"),
        "ano_exercicio": _campo("Ano de Exercício"),
        "tipo_empenho": _campo("Tipo de Empenho"),
    }


_RE_DINHEIRO = re.compile(r"R\$\s*([\d.]+,\d{2})")
_RE_LINHA_PGTO = re.compile(
    r"(\d{2}/\d{2}/\d{4})\s+(\S+)\s+(.+?)\s+(\d{14})\s*-\s*.+?R\$\s*([\d.]+,\d{2})")


def _num_br(v) -> float | None:
    if not v:
        return None
    try:
        return float(str(v).replace(".", "").replace(",", "."))
    except ValueError:
        return None


def ler_pagamentos(html: str) -> list[dict]:
    """Linhas da aba Pagamento.

    Medido: "25/03/2026 1939 Acatada pelo banco 18313874000164 - PM PEQUI
    R$ 938.793,55". A `situacao` importa tanto quanto o valor — "Acatada pelo
    banco" e o que confirma que o dinheiro saiu; ha estados intermediarios que
    NAO sao pagamento."""
    out = []
    for m in _RE_LINHA_PGTO.finditer(_texto(html)):
        out.append({
            "data": m.group(1),
            "numero": m.group(2),
            "situacao": m.group(3).strip(),
            "valor": _num_br(m.group(5)),
        })
    return out
