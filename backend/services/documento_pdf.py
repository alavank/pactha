"""Render PDF de um documento (módulo Geração de Documentos) a partir do
schema + dados. Genérico (itera o schema), igual ao render DOCX."""
from __future__ import annotations
import io

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer


def _fmt(campo: dict, valor) -> str:
    if valor is None or valor == "":
        return "—"
    if campo.get("tipo") == "currency":
        try:
            v = float(str(valor).replace("R$", "").replace(".", "").replace(",", ".").strip())
            return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except (ValueError, TypeError):
            return str(valor)
    return str(valor)


def _esc(s: str) -> str:
    s = "" if s is None else str(s)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def gerar_pdf(schema: dict, dados: dict, municipio_nome: str = "", municipio_uf: str = "") -> bytes:
    dados = dados or {}
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    ss = getSampleStyleSheet()
    st_title = ParagraphStyle("t", parent=ss["Heading1"], fontSize=16, alignment=TA_CENTER,
                              textColor=colors.HexColor("#0f172a"), spaceAfter=2)
    st_sub = ParagraphStyle("s", parent=ss["Normal"], fontSize=10, alignment=TA_CENTER,
                            textColor=colors.HexColor("#475569"), spaceAfter=10)
    st_sec = ParagraphStyle("sec", parent=ss["Heading2"], fontSize=12,
                            textColor=colors.HexColor("#1e40af"), spaceBefore=12, spaceAfter=4)
    st_item = ParagraphStyle("it", parent=ss["Normal"], fontSize=10.5, spaceBefore=6, spaceAfter=2,
                             textColor=colors.HexColor("#333333"))
    st_campo = ParagraphStyle("c", parent=ss["Normal"], fontSize=10, leading=14, spaceAfter=4)
    st_nota = ParagraphStyle("n", parent=ss["Normal"], fontSize=8.5, spaceBefore=6,
                             textColor=colors.HexColor("#475569"))
    st_assin = ParagraphStyle("a", parent=ss["Normal"], fontSize=10, alignment=TA_CENTER, spaceBefore=2)

    story = [Paragraph(_esc(schema.get("titulo", "Documento").upper()), st_title)]
    if municipio_nome:
        story.append(Paragraph(_esc(f"{municipio_nome}/{municipio_uf}".strip("/")), st_sub))
    story.append(Spacer(1, 4))

    def campo(label, valor):
        story.append(Paragraph(f"<b>{_esc(label)}:</b> {_esc(valor)}", st_campo))

    for secao in schema.get("secoes", []):
        story.append(Paragraph(_esc(secao["titulo"].upper()), st_sec))
        if secao.get("tipo") == "lista":
            itens = dados.get(secao.get("key")) or []
            if not itens:
                story.append(Paragraph("<i>Nenhum item cadastrado.</i>", st_campo))
            for idx, item in enumerate(itens, 1):
                story.append(Paragraph(f"<b>{_esc(secao.get('item_label', 'Item'))} {idx}</b>", st_item))
                for c in secao["campos"]:
                    campo(c["label"], _fmt(c, (item or {}).get(c["key"])))
        else:
            for c in secao["campos"]:
                campo(c["label"], _fmt(c, dados.get(c["key"])))

    if schema.get("rodape_assinatura"):
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"<i>{_esc(schema['rodape_assinatura'])}</i>", st_nota))
        story.append(Spacer(1, 18))
        for label in ("Responsável pelo convenente", "Responsável pela sustentabilidade do objeto"):
            story.append(Spacer(1, 16))
            story.append(Paragraph("_" * 50, st_assin))
            story.append(Paragraph(_esc(label), st_assin))

    doc.build(story)
    return buf.getvalue()
