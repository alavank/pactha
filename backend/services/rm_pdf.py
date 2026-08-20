"""Gerador de PDF do RM seguindo o padrao Freitas.

Estrutura visual (replica do PDF de exemplo):
  - Margem padrao, rodape fixo em todas as paginas (endereco Freitas)
  - Cabecalho: titulo + cidade/data
  - Por PARTE: titulo grande centralizado/destacado
  - Por SECAO: subtitulo (caps)
  - Por GRUPO: bullet '●' + nome do orgao (negrito)
  - Por ITEM: identificador (negrito) + bullets '➢' com cada campo
"""
from __future__ import annotations
import io
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from config import get_settings
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, KeepTogether,
)

# Altura do logo no cabecalho. A largura e o dobro apenas como CAIXA maxima — o
# `preserveAspectRatio` encaixa a imagem dentro dela sem deformar.
_LOGO_ALT = 1.8 * cm


def _fmt_dt(d: Any) -> str:
    if not d:
        return ""
    try:
        if isinstance(d, str):
            d = datetime.fromisoformat(d[:10]).date()
        if isinstance(d, date):
            return d.strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        pass
    return str(d)


def _fmt_money(v: Any) -> str:
    if v is None or v == "":
        return ""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = f"{v:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def _meses_pt(n: int) -> str:
    return [
        "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
    ][n - 1]


def _data_extenso(d: Any) -> str:
    if isinstance(d, str):
        try:
            d = datetime.fromisoformat(d[:10]).date()
        except ValueError:
            return d
    if isinstance(d, date):
        return f"{d.day:02d} de {_meses_pt(d.month)} de {d.year}"
    return str(d)


def _styles():
    """⚠️ ENTRELINHA 1,5 EM TODO O DOCUMENTO — `leading = 1,5 × fontSize`.

    É a medida da referência: no .docx do padrão Freitas os parágrafos do corpo
    trazem `w:spacing w:line="360"` com `lineRule` automático, e 360/240 = 1,5
    linhas. Vale para o título, para o corpo e para os títulos de parte/seção
    (medido parágrafo a parágrafo no XML). O documento fica mais longo do que
    estava — é o efeito esperado, não regressão."""
    base = getSampleStyleSheet()
    s = {}
    s["titulo_principal"] = ParagraphStyle(
        "TituloPrincipal", parent=base["Title"], fontName="Helvetica-Bold",
        fontSize=13, alignment=TA_CENTER, spaceAfter=4, leading=19.5,
    )
    # LOCAL E DATA À DIREITA — é assim na referência ("Brasília/DF, 29 de Julho de
    # 2026", `align=right` logo abaixo do título centralizado). Estava centralizada.
    s["data_local"] = ParagraphStyle(
        "DataLocal", parent=base["Normal"], fontName="Helvetica",
        fontSize=11, alignment=TA_RIGHT, spaceAfter=14, leading=16.5,
    )
    s["parte_titulo"] = ParagraphStyle(
        "ParteTitulo", parent=base["Heading1"], fontName="Helvetica-Bold",
        fontSize=12, alignment=TA_CENTER, spaceBefore=14, spaceAfter=10,
        leading=18.0, textColor=colors.HexColor("#1e40af"),
    )
    s["secao_titulo"] = ParagraphStyle(
        "SecaoTitulo", parent=base["Heading2"], fontName="Helvetica-Bold",
        fontSize=11, alignment=TA_CENTER, spaceBefore=10, spaceAfter=8,
        leading=16.5, textColor=colors.HexColor("#111827"),
    )
    s["grupo_titulo"] = ParagraphStyle(
        "GrupoTitulo", parent=base["Normal"], fontName="Helvetica-Bold",
        fontSize=10.5, spaceBefore=10, spaceAfter=4, leftIndent=4, leading=15.75,)
    s["item_id"] = ParagraphStyle(
        "ItemId", parent=base["Normal"], fontName="Helvetica-Bold",
        fontSize=10, spaceBefore=4, spaceAfter=2, leftIndent=14, leading=15.0,)
    s["item_campo"] = ParagraphStyle(
        "ItemCampo", parent=base["Normal"], fontName="Helvetica",
        fontSize=9.5, leftIndent=28, bulletIndent=18, spaceAfter=1,
        leading=14.25, alignment=TA_JUSTIFY,
    )
    s["rodape"] = ParagraphStyle(
        "Rodape", parent=base["Normal"], fontName="Helvetica",
        fontSize=8, alignment=TA_CENTER, textColor=colors.HexColor("#475569"),
    )
    # DESTAQUE da Cláusula Suspensiva / Liminar Judicial (caixa âmbar)
    s["clausula"] = ParagraphStyle(
        "Clausula", parent=base["Normal"], fontName="Helvetica",
        fontSize=9.5, leftIndent=28, rightIndent=10, spaceBefore=3, spaceAfter=3,
        leading=14.25, backColor=colors.HexColor("#FEF3C7"),
        borderColor=colors.HexColor("#D97706"), borderWidth=1, borderPadding=5,
        textColor=colors.HexColor("#7c2d12"),
    )
    # INFORMATIVO (caixa cinza): licitacoes em dia, evento do historico, ultima
    # alteracao. ⚠️ Estas NAO sao alerta — usavam o mesmo ambar da clausula
    # suspensiva, e um convenio saudavel com 5 licitacoes "Concluído" virava um
    # bloco de alerta de 6 linhas. O ambar fica reservado ao que pede acao
    # (clausula/liminar e licitacao ZERO em contratacao Normal).
    s["informativo"] = ParagraphStyle(
        "Informativo", parent=base["Normal"], fontName="Helvetica",
        fontSize=9.5, leftIndent=28, rightIndent=10, spaceBefore=3, spaceAfter=3,
        leading=14.25, backColor=colors.HexColor("#F1F5F9"),
        borderColor=colors.HexColor("#CBD5E1"), borderWidth=1, borderPadding=5,
        textColor=colors.HexColor("#334155"),
    )
    return s


_ASSETS = Path(__file__).resolve().parent.parent / "assets"


def _logo_path() -> str | None:
    """Caminho do logo do cabecalho, ou None.

    Aceita o MESMO valor que o frontend ja usa em NEXT_PUBLIC_CLIENT_LOGO — por
    isso fica so com o NOME do arquivo: "/freitas-logo.jpeg" e "freitas-logo.jpeg"
    dao no mesmo, e o dono pode copiar a env de um app para o outro sem editar.
    Caminho absoluto tambem vale (monta um volume e aponta).

    Arquivo ausente devolve None e o cabecalho sai sem logo — nunca levanta
    excecao: um logo faltando nao pode impedir a emissao do relatorio."""
    try:
        nome = (get_settings().RM_LOGO or "").strip()
    except Exception:
        return None
    if not nome:
        return None
    # ⚠️ A ORDEM IMPORTA. O valor tipico e "/freitas-logo.jpeg", copiado do
    # NEXT_PUBLIC_CLIENT_LOGO — que em Linux e um caminho ABSOLUTO e nao existe na
    # raiz do container. Por isso: tenta o caminho literal (serve para quem monta
    # um volume) e, NAO existindo, cai para o nome do arquivo em backend/assets/.
    # Sem esse fallback, justamente o valor que o dono ia copiar nao acharia nada.
    p = Path(nome)
    if p.is_absolute() and p.is_file():
        return str(p)
    alt = _ASSETS / p.name
    return str(alt) if alt.is_file() else None


def _on_page(canvas, doc, rodape_txt: str):
    canvas.saveState()
    # CABECALHO: logo a ESQUERDA, em TODAS as paginas — a regra da referencia
    # (o .docx nao marca `titlePg`, entao o cabecalho padrao vale desde a 1a
    # pagina). Fica na faixa reservada pela margem superior de 4,5 cm, a 1,6 cm do
    # topo, alinhado a margem esquerda. `preserveAspectRatio` para nao deformar
    # logos de proporcoes diferentes (o da Freitas e quase quadrado, 512x487; os
    # brasoes de Monte Siao e Santa Maria nao sao).
    _logo = _logo_path()
    if _logo:
        try:
            canvas.drawImage(_logo, 2 * cm, A4[1] - 1.6 * cm - _LOGO_ALT,
                             width=_LOGO_ALT * 2, height=_LOGO_ALT,
                             preserveAspectRatio=True, anchor="sw", mask="auto")
        except Exception:
            pass          # logo ilegivel nunca derruba a emissao
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#475569"))
    canvas.drawCentredString(A4[0] / 2, 0.8 * cm, rodape_txt)
    canvas.drawRightString(A4[0] - 1.5 * cm, 0.8 * cm, str(doc.page))
    canvas.restoreState()


def _campos_do_item(item: dict) -> list[tuple[str, str]]:
    """Retorna lista [(label, valor), ...] de campos nao vazios do item."""
    out = []
    def add(label, val):
        if val not in (None, "", 0) or (label == "Valor de contrapartida" and val == 0):
            out.append((label, val))

    if item.get("objeto"):
        out.append(("Objeto", item["objeto"]))
    # PROGRAMA logo abaixo do Objeto (pedido do dono): o objeto diz O QUE é, o
    # programa diz DE ONDE vem o dinheiro (ex.: "PRONE"). Hoje só as voluntárias
    # preenchem esta chave; nas demais fontes ela nem existe no item e a linha não
    # é impressa — por isso não usa o helper `add`, que trata 0 como vazio.
    if item.get("programa"):
        out.append(("Programa", item["programa"]))
    if item.get("parlamentar"):
        out.append(("Parlamentar responsável pela indicação", item["parlamentar"]))
    add("Valor global", _fmt_money(item.get("valor_global")))
    add("Valor de repasse", _fmt_money(item.get("valor_repasse")))
    if item.get("valor_contrapartida") is not None:
        out.append(("Valor de contrapartida", _fmt_money(item.get("valor_contrapartida"))))
    if item.get("dt_fim_vigencia"):
        out.append(("Final da Vigência", _fmt_dt(item["dt_fim_vigencia"])))
    if item.get("banco"):
        out.append(("Banco", item["banco"]))
    if item.get("agencia"):
        out.append(("Agência", item["agencia"]))
    if item.get("conta"):
        out.append(("Conta", item["conta"]))
    if item.get("saldo_bancario") is not None:
        saldo_txt = _fmt_money(item["saldo_bancario"])
        if item.get("dt_saldo"):
            saldo_txt += f" atualizado em {_fmt_dt(item['dt_saldo'])}"
        out.append(("Saldo Bancário", saldo_txt))
    # Situação atual (status do ciclo, ex.: "Em execução")
    if item.get("situacao_atual"):
        out.append(("Situação atual", item["situacao_atual"]))
    # Empenhado (TransfereGov: Sim/Não)
    if item.get("empenhado"):
        out.append(("Empenhado", item["empenhado"]))
    # Situação de Contratação "Normal" aparece como linha simples; Cláusula
    # Suspensiva / Liminar Judicial vão para a CAIXA DE DESTAQUE (_clausula_destaque),
    # então NÃO entram aqui.
    sc = (item.get("situacao_contratacao") or "")
    if sc and not _tem_clausula(item):
        out.append(("Situação de Contratação", sc))
    return out


def _tem_clausula(item: dict) -> bool:
    """True quando o item tem Cláusula Suspensiva / Liminar Judicial (merece destaque)."""
    sc = (item.get("situacao_contratacao") or "").lower()
    return ("clausula" in sc or "cláusula" in sc or "suspensiv" in sc or "liminar" in sc
            or bool(item.get("clausula_motivo")) or bool(item.get("clausula_dt")))


def _clausula_destaque(item: dict) -> str | None:
    """Texto (markup) da caixa de destaque da cláusula, ou None se não houver."""
    if not _tem_clausula(item):
        return None
    sc = item.get("situacao_contratacao") or "Cláusula Suspensiva"
    partes = [f"⚠ <b>Situação de Contratação:</b> {_escape(sc)}"]
    # Situacao do CONTRATO no TransfereGov (ex.: "Cláusula Suspensiva"), que vinha
    # so no JSONB do portal e nao era exibida.
    if item.get("situacao_contrato"):
        partes.append(f"<b>Situação atual do contrato:</b> {_escape(item['situacao_contrato'])}")
    if item.get("clausula_motivo"):
        partes.append(f"<b>Motivo:</b> {_escape(item['clausula_motivo'])}")
    # O motivo diz QUAL documento trava (ex.: "Termo de Referência"); esta linha
    # diz em que PÉ ele está no portal (ex.: "Em Análise"). Sem ela o relatório
    # apontava a pendência sem saber se o município já havia entregado o documento.
    if item.get("projeto_basico"):
        partes.append("<b>Projeto Básico/Termo de Referência:</b> "
                      + _escape(item["projeto_basico"]))
    if item.get("clausula_dt"):
        partes.append(f"<b>Data prevista para resolução:</b> {_escape(_fmt_dt(item['clausula_dt']))}")
    return "<br/>".join(partes)


def _desembolso_destaque(item: dict) -> str | None:
    """Caixa do DESEMBOLSO (OPs/OBs): o valor desembolsado e CADA lancamento
    (data · valor · nº da OB). Quando nada saiu e a licitacao ja foi aceita, o
    proprio `situacao_atual` ja diz PENDENTE DE DESEMBOLSO — aqui detalhamos.
    None quando o instrumento nao tem OPs/OBs coletadas."""
    vd = item.get("valor_desembolsado")
    va = item.get("valor_a_desembolsar")
    lanc = item.get("desembolsos") or []
    if vd is None and va is None and not lanc:
        return None
    partes = []
    cab = []
    if vd is not None:
        cab.append("<b>Desembolsado:</b> " + _escape(_fmt_money_br(vd)))
    if va:
        cab.append("<b>A desembolsar:</b> " + _escape(_fmt_money_br(va)))
    if cab:
        partes.append(" · ".join(cab))
    for l in lanc[:12]:
        if not isinstance(l, dict):
            continue
        linha = "• " + _escape(l.get("data") or "—")
        if l.get("valor") is not None:
            linha += " · " + _escape(_fmt_money_br(l.get("valor")))
        if l.get("numero_ob"):
            linha += " · OB " + _escape(str(l["numero_ob"]))
        if l.get("situacao"):
            linha += " · " + _escape(str(l["situacao"]))
        partes.append(linha)
    if len(lanc) > 12:
        partes.append(f"<i>(+{len(lanc) - 12} lançamento(s))</i>")
    return "<br/>".join(partes) if partes else None


def _fmt_money_br(v) -> str:
    try:
        return "R$ " + f"{float(v):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    except (TypeError, ValueError):
        return ""


def _evento_destaque(item: dict) -> str | None:
    """Caixa do EVENTO ATUAL (Histórico de Comunicações do TransfereGov): onde o
    instrumento está de fato na análise, com a SITUAÇÃO e as CONSIDERAÇÕES do
    concedente. None quando não há histórico capturado."""
    ev = (item.get("evento_atual") or "").strip()
    sit = (item.get("evento_situacao") or "").strip()
    cons = (item.get("evento_consideracoes") or "").strip()
    if not (ev or sit or cons):
        return None
    dt = (item.get("evento_data") or "").strip()
    cab = "<b>Evento atual:</b> " + _escape(ev or "-")
    if dt:
        cab += f" ({_escape(dt)})"
    partes = [cab]
    if sit:
        partes.append(f"<b>Situação:</b> {_escape(sit)}")
    if cons:
        partes.append(f"<b>Considerações:</b> {_escape(cons)}")
    return "<br/>".join(partes)


def _alteracao_destaque(item: dict) -> str | None:
    """Caixa da ULTIMA ALTERACAO do convenio ESTADUAL (SIGCON): onde o instrumento
    esta de fato (ex.: "ANALISE - CHECKLIST DE TERMO ADITIVO"), com tipo, titulo e
    data. E o equivalente estadual do _evento_destaque dos federais. None quando o
    scraper ainda nao capturou a alteracao daquele convenio."""
    sit = (item.get("alteracao_situacao") or "").strip()
    tipo = (item.get("alteracao_tipo") or "").strip()
    data = (item.get("alteracao_data") or "").strip()
    nr = (item.get("alteracao_nr_controle") or "").strip()
    tit0 = (item.get("alteracao_titulo") or "").strip()
    # Captura PARCIAL tambem vale: sem a situacao, o tipo/data/titulo ja informam.
    if not (sit or tipo or data or nr or tit0):
        return None
    partes = ["<b>Última alteração:</b> " + _escape(sit or tipo or "(sem situação informada)")]
    cab = " · ".join(x for x in (
        # nao repete o tipo quando ele ja virou o cabecalho (captura sem situacao)
        _escape(tipo) if (tipo and sit) else "",
        ("nº " + _escape(nr)) if nr else "",
        _escape(data) if data else "",
    ) if x)
    if cab:
        partes.append(cab)
    if tit0:
        partes.append("<b>Título:</b> " + _escape(tit0))
    return "<br/>".join(partes)


def _proc_exec_lista(item: dict) -> list:
    """A lista de licitações/processos do item, tolerando JSONB vindo como str
    (dependendo do driver) ou já parseado. Sempre devolve uma lista (vazia se n/a)."""
    lst = item.get("processo_execucao_lista")
    if isinstance(lst, str):
        try:
            lst = json.loads(lst)
        except (ValueError, TypeError):
            lst = None
    return lst if isinstance(lst, list) else []


def _processo_execucao_destaque(item: dict) -> str | None:
    """Destaque p/ convênio com contratação Normal e o Processo de Execução
    (Licitações): 0 = sem processo/licitação iniciado (flag de monitoramento);
    N = registros. Quando há a LISTA capturada, imprime CADA licitação com
    situação/modalidade/nº/data — não só a contagem. None quando não se aplica
    (não-Normal ou não capturado)."""
    qtd = item.get("processo_execucao_qtd")
    sc = (item.get("situacao_contratacao") or "").lower()
    if qtd is None or "normal" not in sc:
        return None
    if qtd == 0:
        return ("⚠ <b>Licitação:</b> nenhum registro "
                "(contratação Normal, sem licitação iniciada)")
    partes = [f"<b>Licitação:</b> {qtd} registro(s)"]
    # Detalhe por licitação — mesmo formato da tela (situação em negrito, depois
    # modalidade · nº · data · sistema · aceite). Só aparece quando o scraper
    # trouxe a lista; senão fica só a contagem (degrada suave).
    for pe in _proc_exec_lista(item):
        if not isinstance(pe, dict):
            continue
        extra = []
        if pe.get("modalidade"):
            extra.append(_escape(str(pe["modalidade"])))
        if pe.get("numero"):
            extra.append("nº " + _escape(str(pe["numero"])))
        if pe.get("data_publicacao"):
            extra.append(_escape(str(pe["data_publicacao"])))
        if pe.get("sistema_origem"):
            extra.append(_escape(str(pe["sistema_origem"])))
        if pe.get("aceite"):
            extra.append(_escape(str(pe["aceite"])))
        linha = "• <b>" + _escape(str(pe.get("situacao") or "—")) + "</b>"
        if extra:
            linha += " · " + " · ".join(extra)
        partes.append(linha)
    return "<br/>".join(partes)


def _escape(s: str) -> str:
    """Escape p/ Paragraph: &, <, > viram entidades."""
    if not isinstance(s, str):
        s = str(s) if s is not None else ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def gerar_pdf(meta: dict, conteudo: dict, municipio_nome: str) -> bytes:
    """Gera bytes do PDF.

    Args:
        meta: {data_referencia, cidade_emissao, titulo (opt), rodape}
        conteudo: {partes: [{ordem, titulo, secoes: [{ordem, titulo, grupos:
                  [{ordem, orgao, itens: [...]}]}]}]}
        municipio_nome: para o titulo
    """
    buf = io.BytesIO()
    rodape_txt = meta.get("rodape", "")
    # MARGENS DA REFERÊNCIA (medidas no .docx do padrão Freitas, sectPr/pgMar):
    # superior 4,5 · inferior 3,0 · esquerda 2,0 · direita 1,5 cm. São ASSIMÉTRICAS
    # de propósito — a margem superior larga é o espaço reservado ao cabeçalho, e a
    # direita é menor que a esquerda (documento pensado para encadernação).
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=1.5 * cm,
        topMargin=4.5 * cm, bottomMargin=3 * cm,
        title=f"RM - {municipio_nome}",
    )
    s = _styles()
    story = []
    titulo = meta.get("titulo") or f"RELATÓRIO DE MONITORAMENTO – {municipio_nome.upper()}"
    story.append(Paragraph(_escape(titulo), s["titulo_principal"]))
    cidade = meta.get("cidade_emissao") or ""   # ver nota em rm_export.py
    if meta.get("escopo") in ("completo", "parcial"):
        # RM por SELECAO de anos (padrao Freitas): nao ha um exercicio unico. Linha
        # local + data por extenso, como a referencia ("Brasília/DF, 29 de Julho de 2026").
        _de = _data_extenso(meta.get("data_referencia"))
        linha = f"{cidade}, {_de}".strip(", ") if _de else cidade
    else:
        # RM ANUAL: a linha local/data mostra o EXERCÍCIO (ano de emissão).
        _dr = str(meta.get("data_referencia") or "")
        _ano = _dr[:4] if len(_dr) >= 4 and _dr[:4].isdigit() else ""
        linha = f"{cidade} — Relatório referente ao exercício de {_ano}" if _ano else cidade
    story.append(Paragraph(_escape(linha), s["data_local"]))

    for p_idx, parte in enumerate(conteudo.get("partes", [])):
        if p_idx > 0:
            story.append(PageBreak())
        story.append(Paragraph(_escape(parte.get("titulo", "")), s["parte_titulo"]))
        for secao in parte.get("secoes", []):
            story.append(Paragraph(_escape(secao.get("titulo", "")), s["secao_titulo"]))
            for grupo in secao.get("grupos", []):
                story.append(Paragraph(f"● {_escape(grupo.get('orgao', ''))}", s["grupo_titulo"]))
                for item in grupo.get("itens", []):
                    bloco = []
                    tipo = item.get("tipo", "")
                    numero = item.get("numero", "")
                    id_txt = f"{tipo}: {numero}".strip(": ").strip()
                    bloco.append(Paragraph(_escape(id_txt), s["item_id"]))
                    for label, val in _campos_do_item(item):
                        bloco.append(Paragraph(
                            f"➢ <b>{_escape(label)}:</b> {_escape(str(val))}",
                            s["item_campo"],
                        ))
                    # Caixa de DESTAQUE p/ Cláusula Suspensiva / Liminar Judicial
                    destaque = _clausula_destaque(item)
                    if destaque:
                        bloco.append(Spacer(1, 2))
                        bloco.append(Paragraph(destaque, s["clausula"]))
                    # Licitacao: AMBAR so quando e alerta (contratacao Normal com
                    # ZERO licitacao). Com licitacoes registradas e informativo.
                    destaque_pe = _processo_execucao_destaque(item)
                    if destaque_pe:
                        _alerta_pe = item.get("processo_execucao_qtd") == 0
                        bloco.append(Spacer(1, 2))
                        bloco.append(Paragraph(destaque_pe, s["clausula" if _alerta_pe else "informativo"]))
                    destaque_ev = _evento_destaque(item)
                    if destaque_ev:
                        bloco.append(Spacer(1, 2))
                        bloco.append(Paragraph(destaque_ev, s["informativo"]))
                    # Estadual (SIGCON): a ultima alteracao e o "evento atual" dele.
                    destaque_alt = _alteracao_destaque(item)
                    if destaque_alt:
                        bloco.append(Spacer(1, 2))
                        bloco.append(Paragraph(destaque_alt, s["informativo"]))
                    # Desembolso (OPs/OBs): valor + lançamentos.
                    destaque_des = _desembolso_destaque(item)
                    if destaque_des:
                        bloco.append(Spacer(1, 2))
                        bloco.append(Paragraph(destaque_des, s["informativo"]))
                    bloco.append(Spacer(1, 4))
                    story.append(KeepTogether(bloco))

    if not conteudo.get("partes"):
        story.append(Paragraph(
            "<i>Relatório sem conteúdo. Use o botão 'Auto-popular' para puxar os dados atuais do banco.</i>",
            s["item_campo"],
        ))

    doc.build(
        story,
        onFirstPage=lambda c, d: _on_page(c, d, rodape_txt),
        onLaterPages=lambda c, d: _on_page(c, d, rodape_txt),
    )
    return buf.getvalue()
