"""Enrich por-instrumento via HTTP puro (httpx) — sem Chromium.

O enrich do transferegov gastava ~15-30s POR instrumento dirigindo o browser
(historico /private/ ~12s, obras/medicao ~10-30s, ops_obs+processo ~7s). As
telas sao Struts/JSF/REST: TUDO que o browser busca sai por HTTP simples com os
mesmos cookies — provado ao vivo (~3-4s/instrumento, ~10x). Este modulo replica
cada extractor com o MESMO contrato de retorno do browser:
    dict com dados | {} vazio-mas-consultado | None sem acesso/sessao/erro
Ligado por TG_HTTP_ENRICH=1 em transferegov_voluntarias (default off = browser).

Mapa (sondado ao vivo, ver memoria freitas-paridade-piloto):
- contexto Struts: GET ConsultarProposta/ResultadoDaConsultaDePropostaDetalharProposta.do
  ?idProposta=ID — os endpoints guest (ListarRepasses/ListarLicitacoes) NAO levam
  o id na URL: leem o convenio do contexto server-side da sessao. Por isso o
  cliente e STATEFUL e os metodos sao sequenciais por instrumento (1 sessao,
  nunca compartilhar entre workers concorrentes).
- historico (mandatarias /private/, exige sessao gov.br): GET index.jsf?idProposta
  -> regex javax.faces.ViewState -> POST partial-ajax (tabChange p/ tabQuadroResumo)
  -> XML com CDATA; parse por ASSINATURA DE CABECALHO (igual ao browser).
- obras (medicao, REST): GET idp//token/key?app=MED (302 -> UUID no Location) ->
  GET idp//token/jwt -> Bearer JWT -> medicao-backend JSON (mesmos payloads que o
  listener do browser capturava).
"""
from __future__ import annotations
import re
import json
import logging

import httpx
from lxml import html as lxml_html
from lxml import etree

try:  # silencia o aviso de verify=False (a cadeia do portal nao valida na imagem)
    import urllib3
    urllib3.disable_warnings()
except Exception:
    pass

logger = logging.getLogger("transferegov_http")

_DISCRIC = "https://discricionarias.transferegov.sistema.gov.br"
_MAND = "https://mandatarias.transferegov.sistema.gov.br"
# URL DIRETA da listagem de licitacoes (Execucao Convenente > Processo de Execucao).
# A antiga (ForwardAction.do?...destino=ListarLicitacoes) passou a exigir re-SAML do
# modulo `execucao` e devolvia so o form SAML (falso 0). Esta serve a pagina
# server-rendered com a tabela — validado 16/08/2026 no instrumento 996050.
_LIC_URL = (_DISCRIC + "/voluntarias/execucao/ListarLicitacoes/"
            "ListarLicitacoes.do?destino=ListarLicitacoes")
# URL DIRETA da aba Projeto Basico/Termo de Referencia (Execucao Convenente).
# ⚠️ O `idProposta=null` NAO e engano nem placeholder por preencher: e o que o
# proprio portal poe na barra. A tela le o convenio do CONTEXTO server-side
# (o que o _seta_contexto estabelece), nao da query string — por isso pedir esta
# URL "no seco" devolve "Proposta nao encontrada" e cai no Principal.do.
_PB_URL = (_DISCRIC + "/voluntarias/execucao/ListarDocumentosProjetoBasico/"
           "ListarDocumentosProjetoBasico.do?idProposta=null")
# URL DIRETA da aba Execucao Concedente > NEs (Listagem de Notas de Empenho).
# ⚠️ Mora sob /prestacao/ e e .jsf (JSF), nao Struts como as duas de cima — mas
# NAO escapa da parede: medido em guest, devolve os MESMOS 3469 bytes de "HTTP
# Post Binding" que o _LIC_URL e o _PB_URL. O "Acesso Livre" que aparece na tela
# do portal e a sessao do usuario ja tendo passado pelo SAML, nao a pagina ser
# publica. Depende da mesma re-captura de sessao.
_NE_URL = (_DISCRIC + "/voluntarias/prestacao/_proposta/empenho/"
           "listarEmpenhosNovoSiafi.jsf?destino=ManterEmpenhoNovoSiafi")
_IDP = "https://idp.transferegov.sistema.gov.br"
_MED = "https://medicao.transferegov.sistema.gov.br"

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_RE_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_RE_VIEWSTATE = re.compile(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"')


def _txt(el) -> str:
    """text_content normalizado (aprox. innerText p/ as tabelas planas do portal)."""
    return re.sub(r"\s+", " ", el.text_content() or "").strip()


def _parse(resp: httpx.Response):
    """lxml a partir do TEXTO ja decodificado pelo httpx.

    Parsear os BYTES quebra os acentos nas telas do portal (o lxml adivinha
    errado e 'Numero da OB' deixa de casar -> as ordens bancarias sumiam).
    Ja o str puro falha nas paginas JSF que vem com declaracao XML — entao a
    declaracao e removida antes de parsear."""
    txt = resp.text
    if txt.lstrip().startswith("<?xml"):
        txt = re.sub(r"^\s*<\?xml[^>]*\?>", "", txt, count=1)
    return lxml_html.fromstring(txt)


_BLOCO = {"p", "div", "tr", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6",
          "table", "td", "th", "section", "article", "header", "footer",
          "form", "fieldset", "legend", "ul", "ol", "dl", "dt", "dd", "pre",
          "blockquote", "hr", "option", "textarea", "caption"}


def _inner_text(root) -> str:
    """Aproxima o innerText do browser (o _extrai_detalhe roda regex sobre ele).

    text_content() cru junta tudo sem quebra de linha e os regexes de rotulo do
    _extrai_detalhe (que dependem de quebra apos o label) deixam de casar. Aqui
    insere-se quebra nas fronteiras de bloco e colapsam-se espacos em branco,
    como o innerText do browser faz."""
    partes = []
    dentro_celula = [0]

    def walk(e):
        tag = e.tag if isinstance(e.tag, str) else ""
        if tag in ("script", "style", "noscript"):
            if e.tail:
                partes.append(e.tail)
            return
        # innerText de TABELA: celulas separadas por TAB, linhas por quebra. Isso
        # importa: os regexes de rotulo exigem ":" ou quebra logo apos o label —
        # com TAB, "Situacao no SIAFI" no meio da linha nao casa (e e assim que o
        # browser se comporta hoje). Emular com quebra em vez de TAB mudaria o
        # valor gravado nas colunas.
        celula = tag in ("td", "th")
        # DENTRO de uma celula o conteudo e tratado como inline: divs/spans
        # aninhados NAO geram quebra (senao o rotulo e o valor caem em linhas
        # diferentes e os regexes passam a capturar so o 1o campo, divergindo do
        # browser). Fora de celula, bloco = quebra.
        bloco = (not celula) and tag in _BLOCO and dentro_celula[0] == 0
        if celula:
            partes.append("\t")
            dentro_celula[0] += 1
        elif bloco:
            partes.append("\n")
        if e.text:
            partes.append(e.text)
        for c in e:
            walk(c)
        if celula:
            dentro_celula[0] -= 1
        if bloco:
            partes.append("\n")
        if e.tail:
            partes.append(e.tail)

    walk(root)
    txt = "".join(partes)
    txt = re.sub(r"[ \xa0]+", " ", txt)          # colapsa espacos, PRESERVA \t
    txt = re.sub(r"[ ]*\n[ ]*", "\n", txt)
    txt = re.sub(r"[ ]*\t[ ]*", "\t", txt)
    txt = re.sub(r"\n{2,}", "\n", txt)
    txt = re.sub(r"\t{2,}", "\t", txt)
    txt = re.sub(r"\t*\n\t*", "\n", txt)
    txt = re.sub(r"^\t+|\t+$", "", txt, flags=re.M)  # tab no fim/inicio de linha
    return txt.strip()


def _num_br(s):
    """'R$ 2.800.000,00' -> 2800000.0 ; None se nao numerico (copia do browser)."""
    if s is None:
        return None
    t = re.sub(r"[^\d,.-]", "", str(s)).replace(".", "").replace(",", ".")
    try:
        return float(t) if t not in ("", "-", ".") else None
    except ValueError:
        return None


def _sessao_caiu(resp: httpx.Response) -> bool:
    u = str(resp.url).lower()
    return "idp.transferegov" in u or "sso.acesso" in u


class TgHttpEnrich:
    """Cliente HTTP stateful p/ o enrich de UM municipio (sequencial).

    NAO compartilhar entre tarefas concorrentes: os endpoints guest leem o
    convenio do contexto server-side da sessao (dado do instrumento errado, em
    silencio, se intercalar)."""

    def __init__(self, govbr_cookies: list[dict] | None = None):
        # verify=False: a cadeia do mandatarias/idp nao valida na imagem (o
        # browser roda com ignore_https_errors=True). Sem isto, todo GET do
        # /private/ estoura SSL e o except devolvia None em silencio.
        self.cli = httpx.Client(timeout=35, follow_redirects=True, verify=False,
                                headers={"User-Agent": _UA})
        for c in govbr_cookies or []:
            try:
                self.cli.cookies.set(
                    c.get("name"), c.get("value"),
                    domain=(c.get("domain") or "").lstrip("."),
                    path=c.get("path") or "/")
            except Exception:
                pass
        self._ctx_idp: str | None = None   # idProposta do contexto Struts atual
        self._guest_entrou = False

    def close(self):
        try:
            self.cli.close()
        except Exception:
            pass

    # ---------- contexto Struts (detalhe) ----------

    def _seta_contexto(self, id_proposta: str) -> bool:
        """GET do detalhe da proposta: seta o convenio no contexto server-side.
        Cacheia por idProposta (ops_obs + processo do mesmo instrumento reusam)."""
        if self._ctx_idp == id_proposta:
            return True
        url = (f"{_DISCRIC}/voluntarias/ConsultarProposta/"
               f"ResultadoDaConsultaDePropostaDetalharProposta.do?idProposta={id_proposta}&")
        for tent in (1, 2):
            try:
                r = self.cli.get(url)
                if r.status_code == 200 and not _sessao_caiu(r):
                    self._ctx_idp = id_proposta
                    return True
            except Exception as e:
                logger.debug(f"contexto {id_proposta}: {str(e)[:60]}")
            # 1a falha: estabelece a sessao guest (Acesso Livre) e tenta de novo
            if tent == 1 and not self._guest_entrou:
                try:
                    self.cli.get(f"{_DISCRIC}/voluntarias/ForwardAction.do"
                                 f"?modulo=Principal&path=/MostraPrincipalConsultarProposta.do")
                except Exception:
                    pass
                self._guest_entrou = True
        return False

    # ---------- Detalhe da proposta (pares label:valor + campos do topo) ----------

    def detalhe(self, id_proposta: str) -> dict | None:
        """Mesma saida do _extrai_detalhe do browser (pares label:valor, campos
        do topo, valores monetarios, documentos, situacao macro).

        ALIMENTA COLUNAS CRITICAS no upsert (codigo_instrumento, modalidade,
        situacao_siafi, numero_processo, objeto, valores) — por isso a saida foi
        validada chave-a-chave contra o browser antes de ser ligada. O GET aqui
        tb SETA o contexto Struts, entao ops_obs/processo na sequencia reusam."""
        url = (f"{_DISCRIC}/voluntarias/ConsultarProposta/"
               f"ResultadoDaConsultaDePropostaDetalharProposta.do?idProposta={id_proposta}&")
        try:
            r = self.cli.get(url)
        except Exception:
            return None
        if r.status_code != 200 or _sessao_caiu(r):
            return None
        self._ctx_idp = id_proposta  # o GET ja setou o contexto do convenio
        doc = _parse(r)
        out: dict = {}

        def set_kv(k, v):
            if k and len(k) < 70 and v and k not in out:
                out[k] = v[:600]

        # pares label|valor: linhas com 2 OU 4 celulas (label|valor|label|valor)
        for tr in doc.findall(".//tr"):
            tds = tr.xpath("./td|./th")
            if len(tds) == 2:
                set_kv(_txt(tds[0]), _txt(tds[1]))
            elif len(tds) == 4:
                set_kv(_txt(tds[0]), _txt(tds[1]))
                set_kv(_txt(tds[2]), _txt(tds[3]))

        corpo = doc.find(".//body")
        txt = _inner_text(corpo if corpo is not None else doc)

        def grab(label):
            m = re.search(label + r"\s*[:\n]\s*([^\n]{1,120})", txt, re.I)
            return m.group(1).strip() if m else None

        for lbl in ("Modalidade", "Situação no SIAFI", "Código do Instrumento",
                    "Número da Proposta", "Número do Processo",
                    "Situação de Contratação Atual"):
            v = grab(lbl)
            if v and lbl not in out:
                out[lbl] = v

        def grab_money(label):
            m = re.search(label + r"[\s\S]{0,40}?(R\$\s*[\d.]+,\d{2})", txt, re.I)
            return m.group(1).strip() if m else None

        for chave, variantes in (
            ("Valor Global", ("Valor Global do Instrumento", "Valor Global")),
            ("Valor de Repasse", ("Valor de Repasse da União", "Valor de Repasse", "Valor do Repasse")),
            ("Valor de Contrapartida", ("Valor da Contrapartida", "Valor de Contrapartida", "Valor Contrapartida")),
        ):
            for lbl in variantes:
                v = grab_money(lbl)
                if v:
                    out[chave] = v
                    break

        # documentos digitalizados (linhas com 'baixar' + .pdf)
        docs = []
        for a in doc.findall(".//a"):
            if "baixar" in (_txt(a) or "").lower():
                tr = a.xpath("ancestor::tr[1]")
                if tr:
                    linha = _txt(tr[0])
                    if ".pdf" in linha.lower():
                        docs.append(linha[:160])
        if docs:
            out["_documentos"] = docs

        m = re.search(r"Situação\s*\n\s*([^\n]+)", txt)
        if m:
            out["_situacao_macro"] = m.group(1).strip()[:100]
        # NAO devolver "Situação no SIAFI". Medido em 10/08/2026 comparando esta
        # saida com a do browser na MESMA pagina: o browser devolve None neste
        # campo, e a coluna situacao_siafi hoje e preenchida pelo CSV de dados
        # abertos (siconv_convenio), com valor semanticamente melhor
        # ("Prestação de Contas Comprovada"). O portal aqui traz o numero da nota
        # ("Enviado para o SIAFI - 2021NS000360"). Como o upsert usa COALESCE (que
        # so protege contra NULL), devolver este campo SOBRESCREVERIA o valor bom
        # do CSV. Omitir mantem o comportamento atual e deixa o CSV mandar.
        out.pop("Situação no SIAFI", None)
        return out

    # ---------- OPs/OBs (Listagem de Repasses, guest) ----------

    def ops_obs(self, id_proposta: str) -> dict | None:
        if not self._seta_contexto(id_proposta):
            return None
        try:
            r = self.cli.get(f"{_DISCRIC}/voluntarias/ForwardAction.do?modulo=proposta"
                             f"&path=/SelecionarConvenio/SelecionarConvenio.do?destino=ListarRepasses")
        except Exception:
            return None
        if r.status_code != 200 or _sessao_caiu(r):
            return None
        body = r.text
        if not re.search(r"Listagem de Repasses", body, re.I):
            return None
        doc = _parse(r)
        out: dict = {}
        for t in doc.findall(".//table"):
            if re.search(r"Valor Total de Repasse", _txt(t), re.I):
                for tr in t.findall(".//tr"):
                    c = [_txt(td) for td in tr.findall("td")]
                    if len(c) >= 4 and "R$" in c[0]:
                        out = {
                            "valor_total_repasse": _num_br(c[0]),
                            "valor_desembolsado": _num_br(c[1]),
                            "valor_a_desembolsar": _num_br(c[2]),
                            "data_ultimo_desembolso": (c[3] or "").strip() or None,
                            "obs": [],
                        }
                        break
                if out:
                    break
        # GERCOMP (ordens bancarias): acha o alvo no onclick/href e navega por GET.
        # Falha aqui degrada p/ resumo-only — mesmo comportamento do browser (try/except pass).
        try:
            g_url = None
            # o link real e: href="javascript:document.location='/voluntarias/
            # ListarRepasses/ListaDeRepassesOBsConfluxoEfetuadas.do?idProposta=N';"
            m = (re.search(r"""(?:document\.location|location\.href|window\.location)\s*=\s*['"]([^'"]*(?:OBsConfluxo|[Gg]ercomp)[^'"]*)['"]""", body)
                 or re.search(r"""['"](/[^'"]*OBsConfluxo[^'"]*)['"]""", body))
            if m:
                g_url = m.group(1)
            else:
                for a in doc.findall(".//a"):
                    alvo = (a.get("href") or "") + " " + (a.get("onclick") or "") + " " + _txt(a)
                    if re.search(r"GERCOMP", alvo, re.I):
                        g_url = a.get("href") or None
                        if not g_url or g_url.lower().startswith("javascript"):
                            m2 = re.search(r"""['"]([^'"]+\.do[^'"]*)['"]""", a.get("onclick") or "")
                            g_url = m2.group(1) if m2 else None
                        break
                if not g_url:
                    for i in doc.findall(".//input"):
                        if re.search(r"GERCOMP", (i.get("value") or ""), re.I):
                            m2 = re.search(r"""['"]([^'"]+\.do[^'"]*)['"]""", i.get("onclick") or "")
                            g_url = m2.group(1) if m2 else None
                            break
            if g_url:
                if not g_url.startswith("http"):
                    g_url = _DISCRIC + (g_url if g_url.startswith("/") else "/voluntarias/" + g_url)
                rg = self.cli.get(g_url)
                if rg.status_code == 200 and not _sessao_caiu(rg):
                    gd = _parse(rg)
                    if not out:
                        out = {"obs": []}
                    for t in gd.findall(".//table"):
                        tt = _txt(t)
                        trs = t.findall(".//tr")
                        if (re.search(r"Valor Previsto", tt, re.I)
                                and re.search(r"Valor Desembolsado", tt, re.I)
                                and len(trs) <= 4):
                            resumo = {}
                            for tr in trs:
                                c = [_txt(td) for td in tr.findall("td")]
                                if len(c) == 2:
                                    resumo[c[0]] = c[1]
                            out.setdefault("valor_total_repasse", _num_br(resumo.get("Valor Previsto")))
                            if out.get("valor_desembolsado") is None:
                                out["valor_desembolsado"] = _num_br(resumo.get("Valor Desembolsado"))
                            if out.get("valor_a_desembolsar") is None:
                                out["valor_a_desembolsar"] = _num_br(resumo.get("Valor a Desembolsar"))
                        if re.search(r"N[uú]mero da OB", tt, re.I):
                            for tr in t.findall(".//tr"):
                                c = [_txt(td) for td in tr.findall("td")]
                                if len(c) >= 10 and re.search(r"OB\d", c[3] or "", re.I):
                                    out["obs"].append({
                                        "numero_interno": c[0], "numero_ns": c[1], "numero_op": c[2],
                                        "numero_ob": c[3], "ug_emitente": c[4], "gestao_emitente": c[5],
                                        "valor": _num_br(c[6]), "valor_acerto": _num_br(c[7]),
                                        "situacao": c[8], "data_emissao_ob": c[9],
                                    })
        except Exception:
            pass
        return out or {}

    # ---------- Processo de Execucao (Listagem de Licitacoes, guest) ----------

    @staticmethod
    def _le_listagem_licitacoes(resp) -> int | None:
        """N licitacoes da tela de Processo de Execucao, ou None se indeterminado.

        None e IMPORTANTE: significa "nao consegui ler", nao "nenhuma" — quem
        chama nao deve gravar 0 nesse caso (0 vira alerta de 'municipio parado')."""
        body = resp.text
        # 1) TABELA DE LICITACOES pela assinatura do cabecalho — sinal PRIMARIO.
        #    Rodava por ultimo; agora vem primeiro. O bug do "falso 0": a tela de
        #    Processo de Execucao tem subsecoes que trazem "Nenhum registro" (sem
        #    "foi encontrado"), e o check largo abaixo disparava ANTES de contar a
        #    tabela — um convenio com licitacao Concluida virava 0 (observado no
        #    instrumento 996050). Contando a tabela primeiro, o 0 falso some.
        doc = _parse(resp)
        for t in doc.findall(".//table"):
            trs = t.findall(".//tr")
            if not trs:
                continue
            heads = [_txt(x) for x in trs[0].xpath("./th|./td")]
            chave = "|".join(heads).lower()
            if "processo de execu" in chave and ("data da public" in chave or "situa" in chave):
                return len([tr for tr in trs[1:] if any(_txt(c) for c in tr.findall("td"))])
        # 2) marcador "(N item(s))" da paginacao
        m = re.search(r"\((\d+)\s*ite", body, re.I)
        if m:
            return int(m.group(1))
        # 3) vazio ESTRITO — a frase completa, nao o "Nenhum registro" largo que
        #    casa subsecoes. Alinhado com o fallback de :499.
        if re.search(r"Nenhum registro foi encontrado", body, re.I):
            return 0
        return None

    def processo_execucao(self, id_proposta: str) -> int | None:
        if not self._seta_contexto(id_proposta):
            return None
        try:
            r = self.cli.get(_LIC_URL)
        except Exception:
            return None
        if r.status_code != 200 or _sessao_caiu(r):
            return None
        body = r.text
        if not re.search(r"Listagem de Licita|Processo de Execu|Situa..o no Sistema", body, re.I):
            return None
        # A tela JA VEM POPULADA no GET — ler daqui primeiro.
        #
        # O codigo antigo submetia o "Consultar" antes de ler, acreditando que a
        # listagem so populava apos o filtro. E o oposto: o POST DESTROI o
        # resultado (devolve uma pagina curta, sem a tabela) e a proposta virava
        # 0 licitacoes em silencio. Reproduzido no instrumento 993503
        # (proposta 011147/2026): o GET traz a licitacao 102026, o POST a some,
        # e gravavamos 0 — o alerta "sem processo de execucao" ficava mentindo.
        lido = self._le_listagem_licitacoes(r)
        if lido is not None:
            return lido
        # Indeterminado no GET: ai sim tenta o submit do filtro (fallback).
        doc = _parse(r)
        posted = False
        for form in doc.findall(".//form"):
            botao = None
            for i in form.findall(".//input"):
                if (i.get("type") or "").lower() in ("submit", "button") and \
                        re.search(r"Consultar", i.get("value") or "", re.I):
                    botao = i
                    break
            if botao is None:
                continue
            # O Struts troca a action no clique: onclick=setaAcao('/X/Y', ...) ->
            # action = <contexto>/X/Y.do. Sem isso o POST vai p/ a action ESTATICA
            # do form (…IncluirLicitacao.do = acao de INCLUIR) e volta 401.
            acao_js = None
            m_acao = re.search(r"setaAcao\(\s*['\"]([^'\"]+)['\"]", botao.get("onclick") or "")
            if m_acao:
                acao_js = m_acao.group(1)
            data = {}
            for i in form.findall(".//input"):
                nome = i.get("name")
                if not nome:
                    continue
                tipo = (i.get("type") or "text").lower()
                if tipo in ("submit", "button"):
                    continue
                if tipo in ("checkbox", "radio") and not i.get("checked"):
                    continue
                data[nome] = i.get("value") or ""
            for s in form.findall(".//select"):
                nome = s.get("name")
                if not nome:
                    continue
                sel = s.find(".//option[@selected]")
                data[nome] = (sel.get("value") if sel is not None
                              else (s.find(".//option").get("value") if s.find(".//option") is not None else ""))
            if botao.get("name"):
                data[botao.get("name")] = botao.get("value") or ""
            action = form.get("action") or ""
            if acao_js:
                # contexto = 1o segmento da action estatica (ex.: /voluntarias)
                ctx = "/voluntarias"
                m_ctx = re.match(r"(/[^/]+)/", action)
                if m_ctx:
                    ctx = m_ctx.group(1)
                action = f"{_DISCRIC}{ctx}{acao_js}.do"
            elif not action.startswith("http"):
                action = _DISCRIC + (action if action.startswith("/") else "/voluntarias/" + action)
            try:
                r = self.cli.post(action, data=data)
                posted = True
            except Exception:
                return None
            break
        if not posted:
            return None  # nao achou o form -> indeterminado (nao assume 0)
        if r.status_code != 200 or _sessao_caiu(r):
            return None
        body = r.text
        if re.search(r"Nenhum registro foi encontrado", body, re.I):
            return 0
        m = re.search(r"\((\d+)\s*ite", body, re.I)
        if m:
            return int(m.group(1))
        doc = _parse(r)
        for t in doc.xpath(".//table[contains(@class,'dataTable') or contains(@class,'listagem') or @id='listagem']"):
            rows = t.findall(".//tbody//tr") or []
            if rows:
                return len(rows)
        return None  # indeterminado -> NAO assume 0 (evita falso flag)

    @staticmethod
    def _le_licitacoes_lista(resp) -> list | None:
        """Linhas da tabela de licitacoes como dicts, COM a situacao.
        {numero, modalidade, data_publicacao, situacao, sistema_origem, aceite}.
        None = indeterminado (nao gravar); [] = vazio de verdade.

        Mapeia por CABECALHO (nao por posicao fixa) — o portal reordena colunas.
        `situacao` e o que o dono pediu ('Concluído' etc.); `modalidade` e a coluna
        "Processo de Execução" (ex.: 'Licitação - Concorrência', 'Inexigibilidade')."""
        body = resp.text
        doc = _parse(resp)
        for t in doc.findall(".//table"):
            trs = t.findall(".//tr")
            if not trs:
                continue
            heads = [_txt(x).lower() for x in trs[0].xpath("./th|./td")]
            chave = "|".join(heads)
            if "situa" in chave and ("licita" in chave or "processo" in chave or "publica" in chave):
                def col(frag):
                    for i, h in enumerate(heads):
                        if frag in h:
                            return i
                    return None
                i_num, i_mod = col("mero"), col("processo de execu")
                i_dt, i_sit = col("publica"), col("situa")
                i_sis, i_ac = col("sistema de orig"), col("aceite")
                out = []
                for tr in trs[1:]:
                    cels = [_txt(c) for c in tr.findall("td")]
                    if not any(cels):
                        continue
                    def g(i):
                        return (cels[i].strip() if (i is not None and i < len(cels)) else "") or None
                    out.append({"numero": g(i_num), "modalidade": g(i_mod),
                                "data_publicacao": g(i_dt), "situacao": g(i_sit),
                                "sistema_origem": g(i_sis), "aceite": g(i_ac)})
                return out
        if re.search(r"Nenhum registro foi encontrado", body, re.I):
            return []
        return None

    def processo_execucao_lista(self, id_proposta: str) -> list | None:
        """Lista de licitacoes/processos de execucao do instrumento, COM situacao.
        None = indeterminado (nao gravar); [] = vazio. Le a URL DIRETA (server-
        rendered) — a antiga ForwardAction exige re-SAML do modulo execucao."""
        if not self._seta_contexto(id_proposta):
            return None
        try:
            r = self.cli.get(_LIC_URL)
        except Exception:
            return None
        if r.status_code != 200 or _sessao_caiu(r):
            return None
        if not re.search(r"Listagem de Licita|Processo de Execu|Situa..o no Sistema", r.text, re.I):
            return None
        return self._le_licitacoes_lista(r)

    # ---------- Projeto Basico / Termo de Referencia (guest) ----------

    @staticmethod
    def _le_projeto_basico(resp) -> dict | None:
        """Situacao do Projeto Basico/Termo de Referencia + os documentos anexados.
        {situacao, documentos:[{nome_arquivo, descricao, tipo, data_upload}]}.
        None = indeterminado (nao gravar).

        A situacao vem de um par <td class="label">Situação</td><td class="field">,
        e os anexos de uma tabela com cabecalho "Nome Arquivo | Descricao | Tipo |
        Data Upload" — mapeada por CABECALHO, nunca por posicao (o portal reordena
        e ainda pendura colunas de acao DETALHAR/BAIXAR no fim da linha)."""
        doc = _parse(resp)
        situacao = None
        for tr in doc.findall(".//tr"):
            cels = tr.xpath("./th|./td")
            if len(cels) < 2:
                continue
            if re.fullmatch(r"situa..o\s*:?", _txt(cels[0]).strip(), re.I):
                situacao = _txt(cels[1]).strip() or None
                break
        documentos: list[dict] = []
        for t in doc.findall(".//table"):
            trs = t.findall(".//tr")
            if not trs:
                continue
            heads = [_txt(x).lower() for x in trs[0].xpath("./th|./td")]
            if not any("nome arquivo" in h for h in heads):
                continue

            def col(frag):
                for i, h in enumerate(heads):
                    if frag in h:
                        return i
                return None

            i_nome, i_desc = col("nome arquivo"), col("descri")
            i_tipo, i_dt = col("tipo"), col("data upload")
            for tr in trs[1:]:
                cels = [_txt(c) for c in tr.findall("td")]
                if not any(cels):
                    continue

                def g(i):
                    return (cels[i].strip() if (i is not None and i < len(cels)) else "") or None

                nome = g(i_nome)
                if not nome:
                    continue
                documentos.append({"nome_arquivo": nome, "descricao": g(i_desc),
                                   "tipo": g(i_tipo), "data_upload": g(i_dt)})
            break
        # Nem situacao nem anexo = pagina que nao e a que queriamos. Devolver
        # {} aqui gravaria "consultado e vazio" por cima de um dado bom.
        if situacao is None and not documentos:
            return None
        return {"situacao": situacao, "documentos": documentos}

    def projeto_basico(self, id_proposta: str) -> dict | None:
        """Aba Execucao Convenente > Projeto Basico/Termo de Referencia.
        None = indeterminado (nao gravar).

        Pedido do dono (18/08/2026): com o convenio em Clausula Suspensiva e SEM
        licitacao, o RM tem de dizer em que pe esta o documento — ex.: Termo de
        Referencia -> "Em Análise".

        DUAS COISAS APRENDIDAS AO VIVO EM 18/08/2026 (convenio 981397, Araujos,
        proposta 2124094 — 200, ~47KB, Situacao "Em Análise", 1 anexo):

        1. NAO e preciso POST com `idConvenio` na action ...INCLUIR (uma sondagem
           anterior concluiu isso e travou ali). E GET puro na URL direta — o
           `idProposta=null` da URL e irrelevante, a tela le o convenio do
           CONTEXTO server-side. Por isso o _seta_contexto vem antes.
        2. ⚠️ MAS NAO RODA EM GUEST. Esta tela esta sob /voluntarias/execucao/*,
           o MESMO SP SAML `execucao` do ListarLicitacoes: sem a sessao que cobre
           esse SP, o portal devolve 200 com a pagina "HTTP Post Binding" de 3469
           bytes — medido, identico ao _LIC_URL. Ou seja, esta captura vive e
           morre junto com a da Licitacao: se o keepalive perder o SP `execucao`,
           as duas voltam a devolver None (nunca apagam — o COALESCE preserva)."""
        if not self._seta_contexto(id_proposta):
            return None
        try:
            r = self.cli.get(_PB_URL)
        except Exception:
            return None
        if r.status_code != 200 or _sessao_caiu(r):
            return None
        # ⚠️ O SP `execucao` frio devolve 200 (nao redireciona), entao _sessao_caiu
        # nao pega: quem denuncia e o corpo SAML. Sem este teste a parede viraria
        # so "sem dado", escondendo "a sessao precisa ser recapturada".
        if re.search(r"Post Binding|SAMLResponse", r.text, re.I):
            logger.debug("projeto_basico: SP `execucao` frio (SAML) — recapturar sessao")
            return None
        # ⚠️ DOIS 200 QUE NAO SAO O DADO. A tela de UPLOAD responde 200 com tamanho
        # parecido (~44KB) e sem "Situação" — foi o falso positivo que enganou a
        # sondagem anterior. E sem contexto o portal serve o Principal.do com
        # "Proposta nao encontrada". Recusar os dois explicitamente.
        if re.search(r"MantendoProjetoBasicoINSERIR|Descri..o do documento", r.text, re.I):
            return None
        if re.search(r"Proposta n..o encontrada|Um erro ocorreu", r.text, re.I):
            return None
        return self._le_projeto_basico(r)

    # ---------- NEs / Notas de Empenho (Execucao Concedente) ----------

    @staticmethod
    def _le_notas_empenho(resp) -> list | None:
        """Linhas da Listagem de Notas de Empenho.
        [{numero, minuta, valor, valor_siafi, situacao, dt_emissao, minuta_apenas}]
        None = indeterminado (nao gravar); [] = vazio de verdade.

        Mapeia por CABECALHO, nunca por posicao — mesma disciplina do
        _le_licitacoes_lista e do _le_projeto_basico, e a unica que sobrevive a
        reordenacao de coluna.

        ⚠️ `minuta_apenas` E A LINHA QUE NAO E DINHEIRO. A listagem mistura o
        empenho de verdade com a MINUTA: no caso medido, a minuta vem sem numero
        de empenho, com "Valor do Empenho" de R$ 1,00 e situacao "Minuta de
        Empenho". Somar isso como empenho poe R$ 1,00 no relatorio como se fosse
        recurso — por isso a linha e marcada aqui, na leitura, e nao deixada para
        quem consome adivinhar."""
        doc = _parse(resp)
        for t in doc.findall(".//table"):
            trs = t.findall(".//tr")
            if not trs:
                continue
            heads = [_txt(x).lower() for x in trs[0].xpath("./th|./td")]
            chave = "|".join(heads)
            if "empenho" not in chave or "situa" not in chave:
                continue

            def col(frag):
                for i, h in enumerate(heads):
                    if frag in h:
                        return i
                return None

            # "Valor do Empenho" e "Valor do Empenho no SIAFI" comecam igual — o
            # do SIAFI e identificado pelo sufixo, e o outro pega o PRIMEIRO
            # indice que nao seja ele.
            i_siafi = col("siafi")
            i_val = next((i for i, h in enumerate(heads)
                          if "valor" in h and i != i_siafi), None)
            i_num, i_min = col("mero do empenho"), col("minuta")
            i_sit, i_dt = col("situa"), col("emiss")
            out = []
            for tr in trs[1:]:
                cels = [_txt(c) for c in tr.findall("td")]
                if not any(cels):
                    continue

                def g(i):
                    return (cels[i].strip() if (i is not None and i < len(cels)) else "") or None

                numero, sit = g(i_num), g(i_sit)
                if not numero and not g(i_min):
                    continue
                out.append({
                    "numero": numero, "minuta": g(i_min),
                    "valor": _num_br(g(i_val)), "valor_siafi": _num_br(g(i_siafi)),
                    "situacao": sit, "dt_emissao": g(i_dt),
                    "minuta_apenas": (not numero) or ("minuta" in (sit or "").casefold()),
                })
            return out
        if re.search(r"Nenhum registro foi encontrado", resp.text, re.I):
            return []
        return None

    def notas_empenho(self, id_proposta: str) -> list | None:
        """NEs do instrumento (Execucao Concedente > NEs). None = nao gravar.

        ⚠️ MESMA PAREDE DA LICITACAO E DO PROJETO BASICO. A aba mora sob
        /voluntarias/prestacao/ e e JSF, o que parecia livrar do SP SAML — nao
        livra: medido em guest, devolve 3469 bytes de "HTTP Post Binding",
        identico aos outros dois. Sem a sessao do cofre cobrindo esse SP, esta
        captura devolve None (nunca apaga: o upsert e COALESCE)."""
        if not self._seta_contexto(id_proposta):
            return None
        try:
            r = self.cli.get(_NE_URL)
        except Exception:
            return None
        if r.status_code != 200 or _sessao_caiu(r):
            return None
        if re.search(r"Post Binding|SAMLResponse", r.text, re.I):
            logger.debug("notas_empenho: SP frio (SAML) — recapturar sessao")
            return None
        return self._le_notas_empenho(r)

    # ---------- Obras (medicao, REST com JWT) ----------

    def obras(self, id_proposta: str) -> dict | None:
        # token: key (302 -> UUID no Location) -> jwt (Bearer)
        try:
            rk = self.cli.get(f"{_IDP}/idp//token/key?app=MED&idProposta={id_proposta}",
                              follow_redirects=False)
            loc = rk.headers.get("location") or ""
            mu = _RE_UUID.search(loc) or _RE_UUID.search(rk.text or "")
            if not mu:
                return None
            rj = self.cli.get(f"{_IDP}/idp//token/jwt?token={mu.group(0)}&prop={id_proposta}")
            jwt = (rj.json() or {}).get("token") if rj.status_code == 200 else None
            if not jwt:
                return None
        except Exception:
            return None
        H = {"Authorization": f"Bearer {jwt}"}

        def _med(path):
            """JSON de QUALQUER status (o portal responde 412 + {"data":{"errors":...}}
            p/ instrumento sem medicao — e o browser tb recebe esse JSON e conclui
            'sem obras' = {}). Sem JSON (ex.: HTML de login) -> None = sem acesso."""
            try:
                r = self.cli.get(f"{_MED}/medicao-backend{path}", headers=H)
                if "json" not in (r.headers.get("content-type") or ""):
                    return None
                return r.json()
            except Exception:
                return None

        cl = _med(f"/propostas/{id_proposta}/contratoslotes")
        if not isinstance(cl, dict):
            return None
        data = cl.get("data") or {}
        par = _med(f"/proposta/{id_proposta}/situacaoParalisacao")
        par_desc = ((par or {}).get("data") or {}).get("descricao") if isinstance(par, dict) else None

        lotes = []
        for cont in (data.get("contratosLotes") or []):
            idc = cont.get("id")
            lote = {
                "tipo": cont.get("tipo"), "numero": cont.get("numero"),
                "id_contrato": idc, "apto_iniciar": cont.get("aptoIniciar"),
                "atrasado": cont.get("atrasado"), "paralisado": cont.get("paralisado"),
                "dias_sem_medicao": cont.get("qtdeDiasSemMedicao"),
                "submetas": [{
                    "numero": s.get("numero"), "descricao": s.get("descricao"),
                    "situacao": s.get("situacao"), "regime_execucao": s.get("regimeExecucao"),
                    "valor": s.get("valorSubmeta"), "valor_realizado": s.get("valorRealizadoAcumulado"),
                } for s in (cont.get("submetas") or [])],
                "contrato": None, "arts": [],
                # Abas da tela de Dados Gerais do contrato (medicao): Responsável
                # Técnico, Documentação Complementar e as medições. Listas vazias
                # e contagens None quando o contrato não é do tipo "C" (só ele tem
                # essas abas) — nunca ausentes, para o consumidor não precisar de
                # `.get(...) or []` em toda leitura.
                "responsaveis": [], "documentos": [],
                "medicoes_total": None, "medicoes_atestadas": None,
            }
            if cont.get("tipo") == "C" and idc:
                cd = _med(f"/contratos/{idc}")
                cdd = (cd or {}).get("data") if isinstance(cd, dict) else None
                if cdd:
                    emp = None
                    fid = cdd.get("fornecedorId")
                    if fid:
                        ed = _med(f"/empresas/{fid}")
                        emp = ((ed or {}).get("data") or {}).get("razaoSocial") if isinstance(ed, dict) else None
                    vc = cdd.get("valorContrato")
                    try:
                        vc = float(vc) if vc not in (None, "") else None
                    except (TypeError, ValueError):
                        vc = None
                    lote["contrato"] = {
                        "numero": cdd.get("numeroContrato"), "cnpj": cdd.get("cnpj"),
                        "empresa": emp or cdd.get("nomeConvenente"),
                        "objeto": cdd.get("nomeObjetoContratoFornecimento"),
                        "valor": vc,
                        "dt_assinatura": cdd.get("dtAssinatura"),
                        "dt_inicio_vigencia": cdd.get("dtInicioVigencia"),
                        "dt_fim_vigencia": cdd.get("dtFimVigencia"),
                    }
                ar = _med(f"/contratos/{idc}/arts/")
                ard = (ar or {}).get("data") if isinstance(ar, dict) else None
                for a in (ard or []):
                    lote["arts"].append({
                        "tipo": a.get("tipo"), "numero": a.get("numeroArt") or a.get("numero"),
                        "dt_emissao": a.get("dtEmissao"),
                        "responsavel_tecnico": a.get("nomeResponsavelTecnico") or a.get("responsavelTecnico"),
                        "submetas": a.get("submetas"),
                    })

                # ---- RESPONSAVEL TECNICO, DOCUMENTOS COMPLEMENTARES, MEDICOES ----
                # Os tres caminhos NAO foram adivinhados: saem do bundle publico da
                # SPA de medicao, que traz as chamadas em texto claro nos chunks
                # lazy do Angular (`listarResponsavelTecnico`,
                # `consultarDocumentosComplementares`, `listarMedicoes`).
                #
                # ⚠️ O DO RT FOGE DO PADRAO: e `/responsavel/listar/{idContrato}`, e
                # NAO `/contratos/{id}/responsavel...` como todos os vizinhos.
                # Adivinhar por analogia teria errado — e era o que eu ia fazer.
                #
                # Custo: 3 GETs por CONTRATO (nao por proposta), e contrato e bem
                # mais raro que proposta. Ainda assim sai do mesmo TG_BUDGET_S.
                rt = _med(f"/responsavel/listar/{idc}")
                for p in ((rt or {}).get("data") or []):
                    if not isinstance(p, dict):
                        continue
                    lote["responsaveis"].append({
                        "cpf": p.get("cpf") or p.get("nrCpf"),
                        "nome": p.get("nome") or p.get("noResponsavel"),
                        "atividade": p.get("atividade") or p.get("dsAtividade"),
                        "tipo": p.get("tipo") or p.get("dsTipo"),
                        "crea_cau": (p.get("creaCau") or p.get("crea") or p.get("cau")
                                     or p.get("nrCreaCau")),
                        "dt_inclusao": p.get("dtInclusao") or p.get("dataInclusao"),
                    })

                dc = _med(f"/contratos/{idc}/documentoscomplementares")
                for d0 in ((dc or {}).get("data") or []):
                    if not isinstance(d0, dict):
                        continue
                    lote["documentos"].append({
                        "nome": d0.get("nomeArquivo") or d0.get("nmArquivo") or d0.get("nome"),
                        "tipo": d0.get("tipo") or d0.get("dsTipo"),
                        "dt_inclusao": d0.get("dtInclusao") or d0.get("dataInclusao"),
                    })

                # MEDICOES: o que interessa ao relatorio e QUANTAS foram ATESTADAS
                # — e o "02 medicoes atestadas" do texto que o dono especificou.
                # "atestada" e um estado real da medicao: a propria API tem
                # PUT /medicoes/{id}/ateste (atestarMedicao). Casamos por
                # SUBSTRING "atest" porque o rotulo exato varia entre
                # "Atestada"/"Atestado"/"Medição Atestada" e nao foi possivel
                # confirmar sem sessao.
                md = _med(f"/contratos/{idc}/medicoes")
                meds = [m for m in ((md or {}).get("data") or []) if isinstance(m, dict)]
                lote["medicoes_total"] = len(meds) or None
                lote["medicoes_atestadas"] = sum(
                    1 for m in meds
                    if "atest" in str(m.get("situacao") or m.get("dsSituacao") or "").casefold()
                ) or None
            lotes.append(lote)

        if not lotes:
            return {}
        ti = data.get("tipoInstrumento") or {}
        return {
            "situacao_paralisacao": par_desc,
            "valor_total_submetas": data.get("valorTotalSubmetas"),
            "valor_total_realizado": data.get("valorTotalRealizado"),
            "objeto": ti.get("nomeObjetoContratoRepasse"),
            "lotes": lotes,
        }

    # ---------- Historico de Comunicacoes (mandatarias /private/, JSF) ----------

    def historico(self, id_proposta: str) -> dict | None:
        """Mesmo contrato do browser: dict c/ eventos | {} autenticado-sem-eventos
        | None caiu no login/erro (nao marca checado)."""
        url = f"{_MAND}/projeto-basico/private/index.jsf?idProposta={id_proposta}"
        try:
            r = self.cli.get(url)
        except Exception:
            return None
        if r.status_code != 200 or _sessao_caiu(r):
            return None
        mv = _RE_VIEWSTATE.search(r.text)
        if not mv:
            # 200 + sessao viva, mas sem JSF view: proposta sem projeto-basico
            # (o portal devolve "ERRO INTERNO" p/ instrumentos antigos). O browser
            # tb chega nessa tela e devolve {} — CHECADA, sem dados. Devolver None
            # aqui faria a proposta nunca sair do backlog.
            return {}
        body = {
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": "tabViewMandatarias",
            # "@none tabViewMandatarias" (nao so "@none") — capturado do POST real
            # do browser; com "@none" o JSF re-renderiza a view inteira e a aba
            # Quadro Resumo nao vem.
            "javax.faces.partial.execute": "@none tabViewMandatarias",
            "javax.faces.partial.render": "tabViewMandatarias",
            "javax.faces.behavior.event": "tabChange",
            "javax.faces.partial.event": "tabChange",
            "tabViewMandatarias_contentLoad": "true",
            "tabViewMandatarias_newTab": "tabViewMandatarias:tabQuadroResumo",
            "tabViewMandatarias_tabindex": "8",
            "javax.faces.ViewState": mv.group(1),
        }
        try:
            # POST vai na URL BASE (sem ?idProposta=) — o browser faz assim; com a
            # query o JSF reinicializa a view e devolve so o ViewRoot.
            rp = self.cli.post(f"{_MAND}/projeto-basico/private/index.jsf", data=body,
                               headers={"Faces-Request": "partial/ajax",
                                        "X-Requested-With": "XMLHttpRequest",
                                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                                        "Referer": url})
        except Exception:
            return None
        if rp.status_code != 200 or _sessao_caiu(rp):
            return None
        # partial-response XML -> CDATA dos <update> -> tabelas HTML
        tabelas = []
        try:
            root = etree.fromstring(rp.content)
            for up in root.iter("update"):
                frag = up.text or ""
                if "<table" not in frag:
                    continue
                d = lxml_html.fromstring(f"<div>{frag}</div>")
                tabelas.extend(d.findall(".//table"))
        except Exception:
            return None
        # Assinatura de cabecalho (identica ao browser: buscar por titulo nao
        # funciona; a tabela certa se identifica pelas colunas)
        parsed = []
        for t in tabelas:
            rows = t.findall(".//tr")
            heads = [_txt(c) for c in rows[0].xpath("./th|./td")] if rows else []
            parsed.append({"rows": rows, "heads": heads,
                           "chave": "|".join(heads).lower()})

        def acha(*res):
            for x in parsed:
                if len(x["rows"]) < 2:
                    continue
                if all(re.search(rgx, x["chave"]) for rgx in res):
                    return x
            return None

        def ler(x):
            if not x:
                return []
            out = []
            for r_ in x["rows"][1:]:
                cells = [_txt(td) for td in r_.findall("td")]
                if not cells or all(not c for c in cells):
                    continue
                o = {}
                for i, c in enumerate(cells):
                    o[x["heads"][i] if i < len(x["heads"]) and x["heads"][i] else f"col{i}"] = c
                out.append(o)
            return out

        hist = (acha(r"data.?/?\s?hora", r"evento", r"situa", r"considera")
                or acha(r"data.?/?\s?hora", r"evento", r"situa"))
        docs = acha(r"descri", r"tipo", r"data de envio")
        data = {"historico": ler(hist), "documentos": ler(docs)}
        if not (data["historico"] or data["documentos"]):
            return {}  # autenticado porem sem eventos -> checada (mesma semantica do browser)
        return data
