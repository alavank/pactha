"""
Pagamentos da SES-MG aos Fundos Municipais de Saúde por RESOLUÇÃO SES — o fundo a
fundo ESTADUAL da saúde de Minas. Painel público, sem login:

    https://pagamentoderesolucoes.saude.mg.gov.br/pagamentos-orcamentarios
    https://pagamentoderesolucoes.saude.mg.gov.br/restos-a-pagar

Formulário Laravel: GET da página (cookie de sessão + `_token` CSRF) e POST com o
ANO DO PAGAMENTO e o NOME do município. Volta uma tabela HTML com cada ordem de
pagamento: projeto/atividade, fonte, UPG, empenho, nº do documento (OB), data,
valor, banco/agência/conta, CNPJ do credor e nº da Resolução. ~0,5-1,2 s por POST.

O QUE ESTA FONTE ACRESCENTA (medido em Monte Sião, 2026): o dinheiro ORDINÁRIO que
o Estado paga todo mês ao Fundo Municipal — incentivo da APS (R$ 290.992,79), CBAF
(R$ 68.399,53), Promoção da Saúde (R$ 36.508,41), farmácia DCEAF + Rede Farmácia de
Minas (R$ 36.050,35). Até aqui a plataforma via de saúde estadual em MG só a DÍVIDA
(Acordo FES) e a emenda INDICADA (emendas_mg).

AS ARMADILHAS, medidas em 24/09/2026:

1. ⚠️ **NOME QUE O FORMULÁRIO NÃO CONHECE DÁ TABELA VAZIA, COM 200.** "NAO EXISTE"
   volta a mesma página de resultado, com a tabela e zero linhas — igual a um
   município que não recebeu nada. Por isso o nome é conferido na LISTA DE OPÇÕES
   do próprio formulário antes do POST; fora dela, o município sai `partial` com o
   nome, e nada é apagado.

2. **O NOME DO FORMULÁRIO é o do IBGE em CAIXA ALTA SEM ACENTO** (846 dos 853), com
   cinco grafias próprias, medidas contra a lista do IBGE e guardadas POR IBGE em
   `APELIDOS_FORMULARIO` (BRASOPOLIS, DONA EUSEBIA, PASSA-VINTE...). O casamento com
   a lista é por letras (`_chave_letras`: "PINGO D AGUA" = "PINGO-D'AGUA"), e só
   vale se a chave for única na lista.

3. ⚠️ **A BUSCA É POR NOME, MAS A VERDADE É O CNPJ.** O filtro traz todo credor
   SEDIADO no município: em Divinópolis, dois consórcios intermunicipais junto do
   Fundo Municipal. Só é do município o CNPJ conferido (`ConfereCredor`), nesta
   ordem: raiz do CNPJ da prefeitura (`municipios.cnpj`); fundo que o FNS lista
   PELO IBGE (`fns_saldo_conta`); cadastro da Receita (BrasilAPI, reserva
   minhareceita) com o IBGE do município e natureza jurídica MUNICIPAL (1244
   Município, 1333 Fundo Público...). Consórcio (1210) não é. Credor não conferido
   fica gravado com `do_municipio = false`, FORA das contas. Credor que não se
   conseguiu conferir (as duas APIs fora) deixa a fatia inteira sem gravar.

4. **EMENDA × ORDINÁRIO É PELA UPG, E PELO CÓDIGO.** O dropdown do formulário chama
   a UPG 666 de "EMENDAS PARLAMENTARES SES - INVESTIMENTO" e a 675 de "... -
   CUSTEIO"; a TABELA de resultado escreve as mesmas como "ATENDIMENTO A DEMANDAS
   DOS MUNICÍPIOS E ENTIDADES". O nome muda de uma página para a outra; o código,
   não. Conferido em Monte Sião: as 5 OBs da Res. 11058/2026 (UPG 666) são as 5
   indicações "RESOLUÇÃO SES" da SEGOV, mesmo valor e mesma conta. 650 = emenda
   FEDERAL que passa pelo fundo estadual; 948 = "REPASSE DE RECOMPOSIÇÃO DO ACORDO
   FES". O resto é ordinário. Emenda fica À PARTE: ela já soma em Emendas
   parlamentares › Estaduais (MG), pela indicação.

5. **RESTOS A PAGAR SÃO OUTRA PÁGINA, com outro layout** (ano do empenho, valor
   não processado + processado, CNPJ PONTUADO, nº do documento VAZIO) — e o título
   da página de resultado diz "Pagamentos Orçamentários" nas DUAS (cópia no
   template deles). O layout é conferido pelo CABEÇALHO, coluna por nome. Resto de
   empenho que está na dívida do Acordo FES (Res. 6949/2019 de Monte Sião, paga em
   8 parcelas em 2026) é marcado na TELA pela chave (CNPJ, ano, nº do empenho) de
   `acordofes_empenho` — nunca somado à dívida.

6. **A PÁGINA MISTURA CODIFICAÇÕES.** O `<meta>` do template tem aspas do
   Windows-1252 (byte 0x94); o dado é UTF-8. Decodificar como UTF-8 com
   `errors="replace"` — decodificar estrito explode no byte 59.

7. **CSRF.** Token errado ou vencido = HTTP 419. Um GET renova, e o POST é repetido
   uma vez. O mesmo token serve às duas páginas (é da sessão).

8. **"Última atualização" da página inicial** (diária, 07:00 de Brasília) vai para
   `ses_mg_cobertura.fonte_atualizada_em` e para a tela. Parada há mais de
   `IDADE_MAX_DIAS` = `partial`.

9. CNPJ que perdeu o zero à esquerda (12 dígitos, "639952000150") é completado.
   CPF de credor não é guardado inteiro.

IDEMPOTÊNCIA: cada (município, tipo, ano) é TROCADO inteiro, e só com a resposta
lida inteira (cabeçalho medido, nº de <tr> = linhas lidas, todo credor conferido).
Fatia que tinha linhas e voltou vazia não apaga (`partial`) — OB paga não some.

CUSTO: 2 POSTs por município por noite (orçamentário e restos do ano corrente; até
março também o ano anterior) + 2 de histórico por noite para o ano mais recente
ainda não lido, até 2019. Pausa de `PAUSA_S` entre POSTs.

    python -u ingestion/ses_mg_resolucoes.py                     # coleta de verdade
    python -u ingestion/ses_mg_resolucoes.py --dry               # lê tudo, não grava
    python -u ingestion/ses_mg_resolucoes.py --sonda "MONTE SIAO" 2026   # sem banco
"""
from __future__ import annotations

import html as _html
import logging
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

log = logging.getLogger("ses_mg_resolucoes")

BASE = "https://pagamentoderesolucoes.saude.mg.gov.br"
ROTAS = {"orcamentario": "pagamentos-orcamentarios", "restos": "restos-a-pagar"}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131 Safari/537.36"}
UF = "MG"
SOURCE = "ses_mg_resolucoes"
ANO_INICIAL = 2019                   # o menor "Ano do Pagamento" das duas páginas
PAUSA_S = float(os.getenv("SES_MG_PAUSA_S") or "1.0")
BUDGET_S = int(os.getenv("SES_MG_BUDGET_S") or "1200")
ANOS_HISTORICO_POR_NOITE = int(os.getenv("SES_MG_ANOS_HISTORICO") or "1")
IDADE_MAX_DIAS = 3
MAX_CONSULTAS_RECEITA = 200          # por rodada; o cache guarda para sempre

# Armadilha 2: as cinco grafias do formulário que não são o nome do IBGE sem acento.
APELIDOS_FORMULARIO = {
    "3105509": "BARAO DE MONTE ALTO",    # IBGE: Barão do Monte Alto
    "3108909": "BRASOPOLIS",             # IBGE: Brazópolis
    "3122900": "DONA EUSEBIA",           # IBGE: Dona Euzébia
    "3147808": "PASSA-VINTE",            # IBGE: Passa Vinte
    "3165206": "SAO THOME DAS LETRAS",   # IBGE: São Tomé das Letras
}

# Armadilha 4 — pelo CÓDIGO da UPG; o texto é só reserva.
UPG_EMENDA = {"666", "675"}          # "EMENDAS PARLAMENTARES SES" (investimento, custeio)
UPG_EMENDA_FEDERAL = {"650"}         # "PAGAMENTOS RELATIVOS À EMENDAS PARLAMENTARES FEDERAIS"
UPG_ACORDO_FES = {"948"}             # "REPASSE DE RECOMPOSIÇÃO DO ACORDO FES"

# Natureza jurídica (tabela CONCLA) que é o PRÓPRIO município. Consórcio (1210) e
# associação privada (3999) ficam de fora — atendem vários municípios.
NATUREZAS_MUNICIPAIS = {
    1031,   # Órgão Público do Poder Executivo Municipal
    1120,   # Autarquia Municipal
    1155,   # Fundação Pública de Direito Público Municipal
    1180,   # Órgão Público Autônomo Municipal
    1244,   # Município
    1287,   # Fundação Pública de Direito Privado Municipal
    1309,   # Fundo Público da Administração Indireta Municipal
    1333,   # Fundo Público da Administração Direta Municipal (o Fundo de Saúde)
}
RECEITA_URLS = ("https://brasilapi.com.br/api/cnpj/v1/{}", "https://minhareceita.org/{}")

# Cabeçalho medido (armadilha 5). Coluna lida por NOME; faltando uma, recusa.
COLUNAS = {
    "orcamentario": {
        "municipio": "Município", "cod_atividade": "Cód. Projeto/Atividade",
        "atividade": "Projeto/Atividade", "cod_fonte": "Cód. Fonte", "cod_upg": "Cód. UPG",
        "upg": "UPG", "num_empenho": "Nº de Empenho", "num_ob": "Nº de Documento de Pagamento",
        "data": "Data de Pagamento", "valor": "Valor Pago Financeiro",
        "banco": "Cód. Banco Creditado", "agencia": "Cód. Agência Creditada",
        "conta": "Conta Corrente Creditada", "situacao": "Situação da Ordem de Pagamento",
        "cnpj": "CNPJ/CPF do Credor", "razao": "Razão Social", "resolucao": "N° da Resolução",
        "acoes": "Ações",
    },
}
COLUNAS["restos"] = {
    **{k: v for k, v in COLUNAS["orcamentario"].items() if k != "valor"},
    "ano_empenho": "Ano Empenho",
    "valor_nao_processado": "Valor Pago Não Processado",
    "valor_processado": "Valor Pago Processado",
}


class LayoutMudou(ValueError):
    """A página não é a tabela medida — nada desta fatia pode ser gravado."""


# ── texto ────────────────────────────────────────────────────────────────────

def _sem_acento(s) -> str:
    t = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _norm(s) -> str:
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", _sem_acento(s).upper()).split())


def _chave_letras(s) -> str:
    return re.sub(r"[^A-Z]", "", _sem_acento(_html.unescape(str(s or ""))).upper())


def _celula(fragmento: str) -> str:
    return " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", fragmento)).split())


def decodifica(conteudo: bytes) -> str:
    """Armadilha 6: meta em Windows-1252, dado em UTF-8."""
    return conteudo.decode("utf-8", errors="replace")


def _valor(s: str) -> Decimal:
    t = re.sub(r"[^\d,.\-]", "", s or "")
    if not t:
        raise LayoutMudou(f"valor vazio ou ilegível: {s!r}")
    try:
        return Decimal(t.replace(".", "").replace(",", "."))
    except InvalidOperation as e:
        raise LayoutMudou(f"valor ilegível: {s!r}") from e


def _data(s: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except ValueError as e:
        raise LayoutMudou(f"data ilegível: {s!r}") from e


def doc_credor(s: str) -> str | None:
    """14 dígitos (CNPJ, completando o zero perdido) ou CPF MASCARADO."""
    d = re.sub(r"\D", "", s or "")
    if 12 <= len(d) <= 13:
        d = d.zfill(14)
    if len(d) == 14:
        return d
    if len(d) == 11:
        return f"***{d[3:9]}**"
    return None


def resolucao_norm(s) -> str | None:
    """"011058/2026" -> "11058/2026" — a forma da SES; a SEGOV põe zeros à esquerda."""
    m = re.fullmatch(r"\s*0*(\d+)\s*/\s*(\d{4})\s*", str(s or ""))
    return f"{m.group(1)}/{m.group(2)}" if m else None


def conta_sem_dv(conta) -> str | None:
    """A SES cola o dígito na conta ("261017", "26105X"); a SEGOV grava a conta
    ("26101") e o dígito à parte. Tira o último caractere e os zeros à esquerda."""
    c = re.sub(r"[^0-9Xx]", "", str(conta or ""))
    if len(c) < 2:
        return None
    return c[:-1].lstrip("0") or None


def categoria(cod_upg: str | None, upg: str | None) -> str:
    cod = (cod_upg or "").strip()
    n = _norm(upg)
    if cod in UPG_ACORDO_FES or "ACORDO FES" in n:
        return "acordo_fes"
    if cod in UPG_EMENDA_FEDERAL or ("EMENDA" in n and "FEDERA" in n):
        return "emenda_federal"
    if cod in UPG_EMENDA or "EMENDA" in n or "ATENDIMENTO A DEMANDAS DOS MUNICIPIOS" in n:
        return "emenda"
    return "ordinario"


# ── formulário ───────────────────────────────────────────────────────────────

def token_csrf(pagina: str) -> str | None:
    m = re.search(r'name="_token"\s+value="([^"]+)"', pagina)
    return m.group(1) if m else None


def opcoes_municipio(pagina: str) -> list[str]:
    i = pagina.find('id="dsc_municipio"')
    if i < 0:
        return []
    sel = pagina[i:pagina.find("</select>", i)]
    return [_html.unescape(o).strip() for o in re.findall(r"<option>([^<]+)</option>", sel)]


def nome_no_formulario(nome: str, ibge: str, opcoes: list[str]) -> str | None:
    """O nome exatamente como o formulário tem na lista — ou None (armadilha 1)."""
    apelido = APELIDOS_FORMULARIO.get((ibge or "").strip())
    if apelido and apelido in opcoes:
        return apelido
    alvo = _chave_letras(apelido or nome)
    achados = [o for o in opcoes if _chave_letras(o) == alvo]
    return achados[0] if len(achados) == 1 else None


def atualizado_em(pagina_inicial: str) -> datetime | None:
    m = re.search(r"tima atualiza[^:]*:\s*(\d{2}/\d{2}/\d{4})\s*\S*\s*(\d{2}:\d{2}(?::\d{2})?)",
                  pagina_inicial)
    if not m:
        return None
    hora = m.group(2) if len(m.group(2)) == 8 else m.group(2) + ":00"
    try:
        return datetime.strptime(f"{m.group(1)} {hora}", "%d/%m/%Y %H:%M:%S")
    except ValueError:
        return None


def ler_tabela(pagina: str, tipo: str) -> list[dict]:
    """Linhas da tabela de resultado. LayoutMudou se não for a tabela medida ou se
    alguma linha não fechar — nesse caso NADA desta resposta vale."""
    i = pagina.find('id="table"')
    if i < 0:
        raise LayoutMudou("a resposta não tem a tabela de resultado")
    ini, fim = pagina.find("<thead", i), pagina.find("</thead>", i)
    if ini < 0 or fim < 0:
        raise LayoutMudou("tabela sem cabeçalho")
    # "Projeto/<br>Atividade": o <br> do cabeçalho some, não vira espaço.
    cab = [_celula(re.sub(r"<br\s*/?>", "", h))
           for h in re.findall(r"<th[^>]*>(.*?)</th>", pagina[ini:fim], re.S)]
    esperado = COLUNAS[tipo]
    falta = [v for v in esperado.values() if v not in cab]
    if falta:
        raise LayoutMudou(f"cabeçalho de {tipo} fora do medido — faltam {falta[:4]}")
    pos = {k: cab.index(v) for k, v in esperado.items()}
    b0, b1 = pagina.find("<tbody", fim), pagina.find("</tbody>", fim)
    if b0 < 0 or b1 < 0:
        raise LayoutMudou("tabela sem corpo")
    corpo = pagina[b0:b1]
    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", corpo, re.S)
    if len(trs) != len(re.findall(r"<tr[\s>]", corpo)):
        raise LayoutMudou("linha da tabela sem fechamento — resposta cortada?")
    linhas = []
    for tr in trs:
        tds_brutas = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds_brutas) != len(cab):
            raise LayoutMudou(f"linha com {len(tds_brutas)} células, cabeçalho tem {len(cab)}")
        tds = [_celula(t) for t in tds_brutas]
        g = lambda k: tds[pos[k]]  # noqa: E731
        m = re.search(r"/visualizar/(\d+)", tds_brutas[pos["acoes"]])
        if not m:
            raise LayoutMudou("linha sem o link Visualizar (o id da fonte)")
        doc = doc_credor(g("cnpj"))
        if not doc:
            raise LayoutMudou(f"credor sem CNPJ legível: {g('cnpj')!r}")
        ln = {
            "id_fonte": int(m.group(1)), "municipio_fonte": g("municipio"),
            "cod_atividade": g("cod_atividade")[:10] or None, "atividade": g("atividade") or None,
            "cod_fonte": g("cod_fonte")[:10] or None, "cod_upg": g("cod_upg")[:10] or None,
            "upg": g("upg") or None, "num_empenho": g("num_empenho")[:20] or None,
            "num_ob": g("num_ob")[:20] or None, "data_pagamento": _data(g("data")),
            "banco": g("banco")[:10] or None, "agencia": g("agencia")[:10] or None,
            "conta": g("conta")[:20] or None, "situacao": g("situacao")[:100] or None,
            "cnpj_credor": doc, "razao_credor": g("razao") or None,
            "resolucao": g("resolucao")[:20] or None,
        }
        if tipo == "restos":
            vnp, vp = _valor(g("valor_nao_processado")), _valor(g("valor_processado"))
            ln.update(valor=vnp + vp, valor_nao_processado=vnp, valor_processado=vp)
            try:
                ln["ano_empenho"] = int(g("ano_empenho"))
            except ValueError as e:
                raise LayoutMudou(f"ano do empenho ilegível: {g('ano_empenho')!r}") from e
        else:
            ln.update(valor=_valor(g("valor")), valor_nao_processado=None,
                      valor_processado=None, ano_empenho=None)
        ln["categoria"] = categoria(ln["cod_upg"], ln["upg"])
        linhas.append(ln)
    return linhas


class Formulario:
    """Sessão no painel: cookie + token, renovados quando a fonte responde 419."""

    def __init__(self, client: httpx.Client):
        self.client = client
        self.token: str | None = None
        self.opcoes: list[str] = []

    def abrir(self) -> None:
        r = self.client.get(f"{BASE}/{ROTAS['orcamentario']}", headers=UA, timeout=60)
        r.raise_for_status()
        pagina = decodifica(r.content)
        self.token = token_csrf(pagina)
        self.opcoes = opcoes_municipio(pagina)
        if not self.token or len(self.opcoes) < 800:
            raise LayoutMudou(f"formulário fora do medido (token={bool(self.token)}, "
                              f"{len(self.opcoes)} municípios na lista)")

    def consultar(self, tipo: str, nome: str, ano: int) -> list[dict]:
        if not self.token:
            self.abrir()
        for tentativa in (1, 2):
            dados = {"_token": self.token, "data_pgto": str(ano), "dsc_municipio": nome,
                     "ref_contrato_saida": "", "cod_atv": "", "cod_upg": "",
                     "id_credor": "", "credor": "", "conta": ""}
            if tipo == "restos":
                dados["ano_empenho"] = ""
            r = self.client.post(f"{BASE}/{ROTAS[tipo]}", data=dados, headers=UA, timeout=90)
            if r.status_code == 419 and tentativa == 1:       # armadilha 7
                self.abrir()
                continue
            r.raise_for_status()
            return ler_tabela(decodifica(r.content), tipo)
        raise RuntimeError("CSRF recusado duas vezes (419)")


# ── conferência do credor (armadilha 3) ──────────────────────────────────────

def cadastro_da_receita(client: httpx.Client, cnpj: str) -> dict | None:
    for url in RECEITA_URLS:
        try:
            r = client.get(url.format(cnpj), headers=UA, timeout=30)
            if r.status_code != 200:
                continue
            d = r.json()
            if re.sub(r"\D", "", str(d.get("cnpj") or "")).zfill(14) != cnpj:
                continue
            nat = d.get("codigo_natureza_juridica")
            return {
                "cnpj": cnpj, "razao_social": d.get("razao_social"),
                "ibge": str(d.get("codigo_municipio_ibge") or "")[:7] or None,
                "uf": (d.get("uf") or None), "natureza_codigo": int(nat) if nat else None,
                "natureza": d.get("natureza_juridica"),
                "situacao": d.get("descricao_situacao_cadastral"),
                "fonte": url.split("/")[2],
            }
        except (httpx.HTTPError, ValueError) as e:
            log.info("  cadastro %s em %s: %s", cnpj, url.split("/")[2], type(e).__name__)
    return None


class ConfereCredor:
    """O credor é o próprio município? True, False ou None (não deu para saber)."""

    def __init__(self, fns: dict[int, set], cadastro: dict[str, dict],
                 consultar=None, max_consultas: int = MAX_CONSULTAS_RECEITA):
        self.fns, self.cadastro = fns, cadastro
        self.consultar, self.restam = consultar, max_consultas
        self.novos: list[dict] = []

    def __call__(self, cnpj: str, alvo: dict) -> tuple[bool | None, str | None]:
        if not cnpj.isdigit():                                  # CPF mascarado
            return False, None
        pref = alvo.get("cnpj")
        if pref and cnpj[:8] == pref[:8]:
            return True, "prefeitura"
        if cnpj in self.fns.get(alvo["id"], set()):
            return True, "fns"
        cad = self.cadastro.get(cnpj)
        if cad is None and self.consultar and self.restam > 0:
            self.restam -= 1
            cad = self.consultar(cnpj)
            if cad:
                self.cadastro[cnpj] = cad
                self.novos.append(cad)
            if PAUSA_S:
                time.sleep(PAUSA_S)
        if cad is None:
            return None, None
        if cad.get("ibge") == alvo["ibge"] and cad.get("natureza_codigo") in NATUREZAS_MUNICIPAIS:
            return True, "receita"
        return False, None


# ── rodada ───────────────────────────────────────────────────────────────────

def anos_da_rodada(hoje: date, lidos: set, historico: int = ANOS_HISTORICO_POR_NOITE) -> list[int]:
    """Ano corrente (e o anterior até março, que ainda recebe lançamento) + o ano
    mais recente de histórico que ainda não foi lido inteiro nas duas páginas."""
    anos = [hoje.year] + ([hoje.year - 1] if hoje.month <= 3 else [])
    faltam = [a for a in range(hoje.year - 1, ANO_INICIAL - 1, -1)
              if a not in anos and not {("orcamentario", a), ("restos", a)} <= lidos]
    return anos + faltam[:max(0, historico)]


def status_da_rodada(fatias_ok: int, falhas: list[str], notas: list[str]
                     ) -> tuple[str, str | None]:
    msgs = falhas + notas
    if falhas and not fatias_ok:
        return "error", " | ".join(msgs)[:400]
    if msgs:
        return "partial", " | ".join(msgs)[:400]
    return "success", None


def confere_fatia(linhas: list[dict], alvo: dict, confere) -> list[str]:
    """Marca `do_municipio`/`conferido_por` em cada linha; devolve os CNPJs que
    não se conseguiu conferir (se houver, a fatia não pode ser gravada)."""
    sem_resposta = []
    for ln in linhas:
        ok, por = confere(ln["cnpj_credor"], alvo)
        if ok is None:
            sem_resposta.append(ln["cnpj_credor"])
        ln["do_municipio"], ln["conferido_por"] = bool(ok), por
    return sorted(set(sem_resposta))


_SQL_INS = """
INSERT INTO ses_mg_pagamentos (
    municipio_id, tipo, id_fonte, ano_pagamento, ano_empenho, categoria, cod_atividade,
    atividade, cod_fonte, cod_upg, upg, num_empenho, num_ob, data_pagamento, valor,
    valor_nao_processado, valor_processado, banco, agencia, conta, situacao,
    cnpj_credor, razao_credor, do_municipio, conferido_por, resolucao, atualizado_em)
VALUES (
    %(mid)s, %(tipo)s, %(id_fonte)s, %(ano)s, %(ano_empenho)s, %(categoria)s,
    %(cod_atividade)s, %(atividade)s, %(cod_fonte)s, %(cod_upg)s, %(upg)s,
    %(num_empenho)s, %(num_ob)s, %(data_pagamento)s, %(valor)s, %(valor_nao_processado)s,
    %(valor_processado)s, %(banco)s, %(agencia)s, %(conta)s, %(situacao)s,
    %(cnpj_credor)s, %(razao_credor)s, %(do_municipio)s, %(conferido_por)s,
    %(resolucao)s, NOW())
ON CONFLICT (tipo, id_fonte) DO UPDATE SET
    municipio_id = EXCLUDED.municipio_id, ano_pagamento = EXCLUDED.ano_pagamento,
    ano_empenho = EXCLUDED.ano_empenho, categoria = EXCLUDED.categoria,
    cod_atividade = EXCLUDED.cod_atividade, atividade = EXCLUDED.atividade,
    cod_fonte = EXCLUDED.cod_fonte, cod_upg = EXCLUDED.cod_upg, upg = EXCLUDED.upg,
    num_empenho = EXCLUDED.num_empenho, num_ob = EXCLUDED.num_ob,
    data_pagamento = EXCLUDED.data_pagamento, valor = EXCLUDED.valor,
    valor_nao_processado = EXCLUDED.valor_nao_processado,
    valor_processado = EXCLUDED.valor_processado, banco = EXCLUDED.banco,
    agencia = EXCLUDED.agencia, conta = EXCLUDED.conta, situacao = EXCLUDED.situacao,
    cnpj_credor = EXCLUDED.cnpj_credor, razao_credor = EXCLUDED.razao_credor,
    do_municipio = EXCLUDED.do_municipio, conferido_por = EXCLUDED.conferido_por,
    resolucao = EXCLUDED.resolucao, atualizado_em = NOW()
"""

_SQL_COBERTURA = """
INSERT INTO ses_mg_cobertura (municipio_id, tipo, ano, nome_consultado, n_linhas, total,
                              fonte_atualizada_em, coletado_em)
VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
ON CONFLICT (municipio_id, tipo, ano) DO UPDATE SET
    nome_consultado = EXCLUDED.nome_consultado, n_linhas = EXCLUDED.n_linhas,
    total = EXCLUDED.total, fonte_atualizada_em = EXCLUDED.fonte_atualizada_em,
    coletado_em = NOW()
"""

_SQL_CADASTRO = """
INSERT INTO ses_mg_credores (cnpj, razao_social, ibge, uf, natureza_codigo, natureza,
                             situacao, fonte, consultado_em)
VALUES (%(cnpj)s, %(razao_social)s, %(ibge)s, %(uf)s, %(natureza_codigo)s, %(natureza)s,
        %(situacao)s, %(fonte)s, NOW())
ON CONFLICT (cnpj) DO UPDATE SET
    razao_social = EXCLUDED.razao_social, ibge = EXCLUDED.ibge, uf = EXCLUDED.uf,
    natureza_codigo = EXCLUDED.natureza_codigo, natureza = EXCLUDED.natureza,
    situacao = EXCLUDED.situacao, fonte = EXCLUDED.fonte, consultado_em = NOW()
"""


def grava_fatia(cur, mid: int, tipo: str, ano: int, linhas: list[dict], nome: str,
                fonte_em: datetime | None, antes: int | None) -> str | None:
    """Troca a fatia (município, tipo, ano) inteira. Devolve o motivo de recusa, ou
    None se gravou. Fatia que tinha linhas e voltou vazia não apaga (OB paga não
    some — é a fonte recarregando)."""
    if not linhas and antes:
        return f"{nome} {tipo} {ano}: a fonte devolveu 0 onde havia {antes} — não apaguei"
    import psycopg2.extras
    cur.execute("DELETE FROM ses_mg_pagamentos WHERE municipio_id = %s AND tipo = %s "
                "AND ano_pagamento = %s", (mid, tipo, ano))
    regs = [{**ln, "mid": mid, "tipo": tipo, "ano": ano,
             "ano_empenho": ln.get("ano_empenho") or (ano if tipo == "orcamentario" else None)}
            for ln in linhas]
    if regs:
        psycopg2.extras.execute_batch(cur, _SQL_INS, regs, page_size=200)
    total = sum((ln["valor"] for ln in linhas if ln.get("do_municipio")), Decimal("0"))
    cur.execute(_SQL_COBERTURA, (mid, tipo, ano, nome, len(linhas), total, fonte_em))
    return None


def _salva_cadastro(cur, conn, confere: ConfereCredor) -> None:
    """O cadastro consultado na Receita fica guardado já — uma rodada morta pelo
    `timeout` não paga a consulta de novo na próxima."""
    if not confere.novos:
        return
    import psycopg2.extras
    psycopg2.extras.execute_batch(cur, _SQL_CADASTRO, confere.novos)
    conn.commit()
    confere.novos = []


def _alvos(cur) -> list[dict]:
    cur.execute("""
        SELECT id, nome, ibge_code, regexp_replace(coalesce(cnpj, ''), '\\D', '', 'g')
          FROM municipios WHERE active AND upper(coalesce(uf, '')) = %s ORDER BY id
    """, (UF,))
    return [{"id": r[0], "nome": r[1], "ibge": (r[2] or "").strip(),
             "cnpj": r[3] if len(r[3] or "") == 14 else None} for r in cur.fetchall()]


def _consulta_opcional(cur, conn, sql: str, params=()) -> list:
    """Leitura de tabela de OUTRA fonte (pode não existir num banco atrasado)."""
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    except Exception as e:
        conn.rollback()
        log.info("  (sem %s: %s)", sql.split("FROM")[1].split()[0], type(e).__name__)
        return []


def _log_ingest(cur, conn, status: str, n: int, nota: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES (%s, %s, %s, %s, NOW())",
            (SOURCE, status, n, nota))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def ingest(dry: bool = False, hoje: date | None = None) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    hoje = hoje or date.today()
    t0 = time.monotonic()
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            alvos = _alvos(cur)
            if not alvos:
                log.info("nenhum município de MG — pagamentos da SES-MG não se aplicam")
                if not dry:
                    _log_ingest(cur, conn, "success", 0)
                return 0
            ids = [a["id"] for a in alvos]
            fns: dict[int, set] = {}
            for mid, cnpj in _consulta_opcional(
                    cur, conn, "SELECT DISTINCT municipio_id, cnpj FROM fns_saldo_conta "
                               "WHERE municipio_id = ANY(%s)", (ids,)):
                fns.setdefault(mid, set()).add(cnpj)
            cadastro = {r[0]: {"cnpj": r[0], "ibge": r[1], "natureza_codigo": r[2]}
                        for r in _consulta_opcional(
                            cur, conn, "SELECT cnpj, ibge, natureza_codigo FROM ses_mg_credores")}
            cobertura: dict[int, dict] = {}
            for mid, tipo, ano, n, quando in _consulta_opcional(
                    cur, conn, "SELECT municipio_id, tipo, ano, n_linhas, coletado_em "
                               "FROM ses_mg_cobertura WHERE municipio_id = ANY(%s)", (ids,)):
                cobertura.setdefault(mid, {})[(tipo, ano)] = (n, quando)
            # Rodízio: quem está há mais tempo sem conferir o ano corrente vai primeiro.
            alvos.sort(key=lambda a: min(
                (q.timestamp() for (tp, an), (_n, q) in cobertura.get(a["id"], {}).items()
                 if an == hoje.year and q), default=0))

            falhas: list[str] = []
            notas: list[str] = []
            fatias_ok = gravadas = 0
            with httpx.Client(follow_redirects=True) as client:
                fonte_em = None
                try:
                    r = client.get(BASE + "/", headers=UA, timeout=60)
                    fonte_em = atualizado_em(decodifica(r.content))
                except httpx.HTTPError as e:
                    notas.append(f"página inicial: {type(e).__name__}")
                if fonte_em is None:
                    notas.append("a página inicial não disse a data da última atualização")
                elif (hoje - fonte_em.date()).days > IDADE_MAX_DIAS:
                    notas.append(f"o painel não atualiza desde {fonte_em:%d/%m/%Y}")
                form = Formulario(client)
                form.abrir()
                confere = ConfereCredor(fns, cadastro, lambda c: cadastro_da_receita(client, c))
                for n_alvo, alvo in enumerate(alvos):
                    if time.monotonic() - t0 > BUDGET_S:
                        falhas.append(f"orçamento de {BUDGET_S}s: {len(alvos) - n_alvo} "
                                      "município(s) ficam para a próxima rodada")
                        break
                    nome = nome_no_formulario(alvo["nome"], alvo["ibge"], form.opcoes)
                    if not nome:
                        falhas.append(f"{alvo['nome']} (IBGE {alvo['ibge']}) não está na lista "
                                      "de municípios do formulário")
                        continue
                    lidos = {k for k in cobertura.get(alvo["id"], {})}
                    for ano in anos_da_rodada(hoje, lidos):
                        for tipo in ("orcamentario", "restos"):
                            rot = f"{nome} {tipo} {ano}"
                            try:
                                linhas = form.consultar(tipo, nome, ano)
                            except (httpx.HTTPError, LayoutMudou, RuntimeError) as e:
                                falhas.append(f"{rot}: {type(e).__name__}: {str(e)[:100]}")
                                log.warning("  %s: %s", rot, e)
                                time.sleep(PAUSA_S)
                                continue
                            time.sleep(PAUSA_S)
                            sem = confere_fatia(linhas, alvo, confere)
                            if sem:
                                falhas.append(f"{rot}: credor(es) {', '.join(sem[:3])} sem "
                                              "cadastro na Receita — fatia não gravada")
                                continue
                            dele = [x for x in linhas if x["do_municipio"]]
                            log.info("  %s: %d pagamento(s), %d ao município, R$ %s",
                                     rot, len(linhas), len(dele),
                                     sum((x["valor"] for x in dele), Decimal("0")))
                            if dry:
                                fatias_ok += 1
                                continue
                            antes = (cobertura.get(alvo["id"], {}).get((tipo, ano)) or (None,))[0]
                            recusa = grava_fatia(cur, alvo["id"], tipo, ano, linhas, nome,
                                                 fonte_em, antes)
                            if recusa:
                                conn.rollback()
                                falhas.append(recusa)
                                continue
                            conn.commit()
                            fatias_ok += 1
                            gravadas += len(linhas)
                            _salva_cadastro(cur, conn, confere)
            if dry:
                log.info("=== SES-MG (dry): %d fatia(s) lidas, falhas: %s ===", fatias_ok, falhas)
                return 0
            status, nota = status_da_rodada(fatias_ok, falhas, notas)
            log.info("=== SES-MG resoluções: %d fatia(s), %d pagamento(s), status=%s ===",
                     fatias_ok, gravadas, status)
            _log_ingest(cur, conn, status, gravadas, nota)
            return gravadas
        except Exception as e:
            conn.rollback()
            log.error("SES-MG resoluções falhou: %s: %s", type(e).__name__, str(e)[:200])
            if not dry:
                _log_ingest(cur, conn, "error", 0, f"{type(e).__name__}: {str(e)[:380]}")
            raise
        finally:
            cur.close()


def sonda(nome: str, ano: int) -> None:
    """Sem banco: consulta as duas páginas e imprime o que seria gravado."""
    with httpx.Client(follow_redirects=True) as client:
        form = Formulario(client)
        form.abrir()
        achado = nome_no_formulario(nome, "", form.opcoes)
        print(f"nome no formulário: {achado!r}")
        if not achado:
            return
        for tipo in ("orcamentario", "restos"):
            linhas = form.consultar(tipo, achado, ano)
            por_cat: dict = {}
            for ln in linhas:
                por_cat.setdefault(ln["categoria"], Decimal("0"))
                por_cat[ln["categoria"]] += ln["valor"]
                print(f"  {tipo:12} {ln['data_pagamento']} {ln['cod_upg']:>5} {ln['categoria']:14}"
                      f" {ln['valor']:>14} {ln['cnpj_credor']} {ln['resolucao']}")
            print(f"{tipo}: {len(linhas)} linha(s), total R$ "
                  f"{sum((x['valor'] for x in linhas), Decimal('0'))} {por_cat}")
            time.sleep(PAUSA_S)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if "--sonda" in sys.argv:
        i = sys.argv.index("--sonda")
        sonda(sys.argv[i + 1], int(sys.argv[i + 2]))
    else:
        ingest(dry="--dry" in sys.argv)
