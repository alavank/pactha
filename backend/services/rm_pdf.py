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
from datetime import date, datetime
from typing import Any
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, KeepTogether,
)


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
    base = getSampleStyleSheet()
    s = {}
    s["titulo_principal"] = ParagraphStyle(
        "TituloPrincipal", parent=base["Title"], fontName="Helvetica-Bold",
        fontSize=13, alignment=TA_CENTER, spaceAfter=4, leading=15,
    )
    s["data_local"] = ParagraphStyle(
        "DataLocal", parent=base["Normal"], fontName="Helvetica",
        fontSize=11, alignment=TA_CENTER, spaceAfter=14, leading=13,
    )
    s["parte_titulo"] = ParagraphStyle(
        "ParteTitulo", parent=base["Heading1"], fontName="Helvetica-Bold",
        fontSize=12, alignment=TA_CENTER, spaceBefore=14, spaceAfter=10,
        textColor=colors.HexColor("#1e40af"),
    )
    s["secao_titulo"] = ParagraphStyle(
        "SecaoTitulo", parent=base["Heading2"], fontName="Helvetica-Bold",
        fontSize=11, alignment=TA_CENTER, spaceBefore=10, spaceAfter=8,
        textColor=colors.HexColor("#111827"),
    )
    s["grupo_titulo"] = ParagraphStyle(
        "GrupoTitulo", parent=base["Normal"], fontName="Helvetica-Bold",
        fontSize=10.5, spaceBefore=10, spaceAfter=4, leftIndent=4,
    )
    s["item_id"] = ParagraphStyle(
        "ItemId", parent=base["Normal"], fontName="Helvetica-Bold",
        fontSize=10, spaceBefore=4, spaceAfter=2, leftIndent=14,
    )
    s["item_campo"] = ParagraphStyle(
        "ItemCampo", parent=base["Normal"], fontName="Helvetica",
        fontSize=9.5, leftIndent=28, bulletIndent=18, spaceAfter=1,
        leading=12, alignment=TA_JUSTIFY,
    )
    s["rodape"] = ParagraphStyle(
        "Rodape", parent=base["Normal"], fontName="Helvetica",
        fontSize=8, alignment=TA_CENTER, textColor=colors.HexColor("#475569"),
    )
    # DESTAQUE da Cláusula Suspensiva / Liminar Judicial (caixa âmbar)
    s["clausula"] = ParagraphStyle(
        "Clausula", parent=base["Normal"], fontName="Helvetica",
        fontSize=9.5, leftIndent=28, rightIndent=10, spaceBefore=3, spaceAfter=3,
        leading=13, backColor=colors.HexColor("#FEF3C7"),
        borderColor=colors.HexColor("#D97706"), borderWidth=1, borderPadding=5,
        textColor=colors.HexColor("#7c2d12"),
    )
    return s


def _on_page(canvas, doc, rodape_txt: str):
    canvas.saveState()
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
    if item.get("clausula_motivo"):
        partes.append(f"<b>Motivo:</b> {_escape(item['clausula_motivo'])}")
    if item.get("clausula_dt"):
        partes.append(f"<b>Data prevista para resolução:</b> {_escape(_fmt_dt(item['clausula_dt']))}")
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
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=1.8 * cm, bottomMargin=1.6 * cm,
        title=f"RM - {municipio_nome}",
    )
    s = _styles()
    story = []
    titulo = meta.get("titulo") or f"RELATÓRIO DE MONITORAMENTO – {municipio_nome.upper()}"
    story.append(Paragraph(_escape(titulo), s["titulo_principal"]))
    cidade = meta.get("cidade_emissao", "Brasília/DF")
    data_ext = _data_extenso(meta.get("data_referencia"))
    story.append(Paragraph(f"{_escape(cidade)}, {_escape(data_ext)}", s["data_local"]))

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
