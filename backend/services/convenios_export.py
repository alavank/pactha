"""Excel e Word dos Convênios Estaduais.

O PDF continua em `routers/export_pdf.py` (usa o `_build_pdf` compartilhado com
os outros relatórios); aqui ficam os dois formatos novos, pedidos pelo dono em
03/09/2026 junto com o conserto do filtro.

⚠️ OS TRÊS FORMATOS IMPRIMEM O MESMO RECORTE E AS MESMAS COLUNAS. A tentação é
deixar o Excel "mais completo" porque cabe — e aí o gestor que exporta nos dois
encontra números diferentes e não sabe em qual acreditar. Uma coluna nova entra
nos três ou em nenhum.

⚠️ O RECORTE VAI ESCRITO NO DOCUMENTO. Um papel que diz "Convênios Estaduais —
Monte Sião/MG" sem dizer que são apenas os em vigor é indistinguível de um que
lista a base inteira, e foi exatamente essa ambiguidade que gerou a queixa. O
texto vem das condições APLICADAS (`convenios_filtro.condicoes`), não da
querystring: valor desconhecido é descartado em silêncio pelo filtro, e
descrever o pedido em vez do aplicado faria o documento mentir por escrito.

Módulo sem acesso a banco: recebe linhas prontas e devolve bytes.
"""
from __future__ import annotations

import io
from datetime import date, datetime
from typing import Optional

_AZUL = "1F4E79"

# (chave, rótulo, largura no Excel). A MESMA ordem dos três formatos.
COLUNAS: list[tuple[str, str, int]] = [
    ("fonte", "Fonte", 12),
    ("proposta", "Proposta", 16),
    ("plano", "Plano", 14),
    ("instrumento", "Instrumento", 16),
    ("orgao", "Órgão concedente", 30),
    ("objeto", "Objeto", 60),
    ("situacao", "Situação", 18),
    ("repasse", "Repasse (R$)", 16),
    ("assinatura", "Assinatura", 13),
    ("vigencia", "Fim da vigência", 15),
]


def _dt(v) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def linha_de(c) -> dict:
    """Um `ConvenioEstadual` vira a linha que os três formatos imprimem.

    ⚠️ `objetivo` PRIMEIRO, e isso não é preferência de estilo. No dialeto do ES
    a coluna `objeto` guarda o CÓDIGO do processo ("2026-M632Z") e a descrição
    real vive em `objetivo`; em MG é o contrário — `objeto` é a descrição e
    `objetivo` é NULO em 869 de 869 linhas. O `or` resolve os dois sem ramificar
    por fonte, e é a mesma regra que o PDF já usava.
    """
    raw = c.raw_data if isinstance(c.raw_data, dict) else {}
    nr_proposta = raw.get("nr_proposta") or (
        c.nr_plano_trabalho if c.nr_plano_trabalho and "/" in c.nr_plano_trabalho else "")
    nr_instr = raw.get("nr_instrumento") or raw.get("numOriginal") or (
        c.nr_sigcon if c.nr_sigcon and "/" in c.nr_sigcon else "")
    plano = (c.nr_plano_trabalho or "") if (c.nr_plano_trabalho and "/" not in c.nr_plano_trabalho) else ""
    return {
        "fonte": c.fonte or "",
        "proposta": nr_proposta or "",
        "plano": plano,
        "instrumento": nr_instr or "",
        "orgao": c.orgao_concedente or "",
        "objeto": (c.objetivo or c.objeto) or "",
        "situacao": c.situacao or "",
        # Número de verdade no Excel (dá para somar); o PDF/Word formatam.
        "repasse": c.valor_concedente if c.valor_concedente is not None else c.valor_total,
        "assinatura": _dt(c.dt_vigencia_inicial),
        "vigencia": _dt(c.dt_vigencia_atual or c.dt_vigencia_final),
    }


def _brl(v) -> str:
    if v is None:
        return "-"
    try:
        return f"{float(v):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    except (TypeError, ValueError):
        return "-"


def _dbr(v) -> str:
    d = _dt(v)
    return d.strftime("%d/%m/%Y") if d else "-"


def gerar_xlsx(linhas: list[dict], *, titulo: str, recorte: list[str],
               emitido_em: datetime, truncado_em: Optional[int] = None) -> bytes:
    """Uma aba de dados com autofiltro, e uma aba «Recorte» com o filtro aplicado."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Convênios"

    azul = PatternFill("solid", fgColor=_AZUL)
    cab = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
    normal = Font(name="Calibri", size=10)
    centro = Alignment(horizontal="center", vertical="center", wrap_text=True)
    esq = Alignment(horizontal="left", vertical="top", wrap_text=True)
    fino = Side(style="thin", color="BFBFBF")
    borda = Border(left=fino, right=fino, top=fino, bottom=fino)

    for i, (_, rotulo, largura) in enumerate(COLUNAS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = largura
        c = ws.cell(1, i, rotulo)
        c.fill = azul; c.font = cab; c.alignment = centro; c.border = borda
    ws.freeze_panes = "A2"
    # Autofiltro no cabeçalho: é o motivo de alguém pedir Excel em vez de PDF.
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUNAS))}1"

    for r, item in enumerate(linhas, start=2):
        for i, (chave, _, _) in enumerate(COLUNAS, start=1):
            v = item.get(chave)
            c = ws.cell(r, i, v if v is not None else "")
            c.font = normal
            c.border = borda
            c.alignment = centro if chave in ("fonte", "situacao", "assinatura", "vigencia") else esq
            if chave in ("assinatura", "vigencia") and v:
                c.number_format = "DD/MM/YYYY"
            if chave == "repasse" and v is not None:
                # ⚠️ Número, não texto. Excel existe para somar e ordenar; um
                # "R$ 1.234,56" em célula de texto quebra as duas coisas, e é o
                # motivo pelo qual alguém pediu Excel.
                c.number_format = 'R$ #,##0.00'

    # --- aba «Recorte» -----------------------------------------------------
    wr = wb.create_sheet("Recorte")
    wr.column_dimensions["A"].width = 22
    wr.column_dimensions["B"].width = 70
    def _par(l, rot, val):
        a = wr.cell(l, 1, rot); a.font = Font(name="Calibri", bold=True, size=10)
        b = wr.cell(l, 2, val); b.font = Font(name="Calibri", size=10)
        b.alignment = Alignment(wrap_text=True, vertical="top")
    _par(1, "Relatório", titulo)
    _par(2, "Emitido em", emitido_em.strftime("%d/%m/%Y %H:%M"))
    _par(3, "Registros", len(linhas))
    linha = 4
    if truncado_em is not None:
        _par(linha, "⚠️ Truncado", f"o filtro tem mais de {truncado_em} registros; "
                                   f"o arquivo traz os {len(linhas)} primeiros")
        linha += 1
    _par(linha, "Filtros aplicados",
         "\n".join(recorte) if recorte else "nenhum — a base inteira do município")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def gerar_docx(linhas: list[dict], *, titulo: str, subtitulo: str,
               recorte: list[str], emitido_em: datetime,
               truncado_em: Optional[int] = None) -> bytes:
    """Word em paisagem — retrato não comporta as dez colunas sem virar ilegível."""
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor, Cm

    doc = Document()
    sec = doc.sections[0]
    # ⚠️ Troca de orientação exige inverter largura e altura à mão: mudar só
    # `orientation` deixa o Word em retrato com a flag mentindo.
    larg, alt = sec.page_width, sec.page_height
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = max(larg, alt), min(larg, alt)
    for m in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, m, Cm(1.2))

    h = doc.add_paragraph()
    r = h.add_run(titulo)
    r.bold = True
    r.font.size = Pt(14)
    r.font.color.rgb = RGBColor(0x1F, 0x4E, 0x79)

    s = doc.add_paragraph()
    rs = s.add_run(subtitulo)
    rs.font.size = Pt(9)
    rs.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    # ⚠️ O RECORTE VAI NO CORPO, não em rodapé. É o que diferencia "os em vigor"
    # de "a base inteira", e foi a ausência disso que gerou a queixa.
    rec = doc.add_paragraph()
    rr = rec.add_run("Filtros aplicados: " + ("; ".join(recorte) if recorte
                                              else "nenhum — a base inteira do município"))
    rr.italic = True
    rr.font.size = Pt(8)
    rr.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

    if truncado_em is not None:
        t = doc.add_paragraph()
        tr = t.add_run(f"⚠️ O filtro tem mais de {truncado_em} registros. "
                       f"Este documento traz os {len(linhas)} primeiros.")
        tr.bold = True
        tr.font.size = Pt(8)
        tr.font.color.rgb = RGBColor(0xB0, 0x00, 0x00)

    e = doc.add_paragraph()
    er = e.add_run(f"Emitido em {emitido_em.strftime('%d/%m/%Y %H:%M')}")
    er.font.size = Pt(8)
    er.font.color.rgb = RGBColor(0x77, 0x77, 0x77)

    if not linhas:
        doc.add_paragraph()
        doc.add_paragraph(subtitulo)
    else:
        tab = doc.add_table(rows=1, cols=len(COLUNAS))
        tab.style = "Table Grid"
        for i, (_, rotulo, _) in enumerate(COLUNAS):
            cel = tab.rows[0].cells[i]
            cel.text = ""
            p = cel.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(rotulo)
            run.bold = True
            run.font.size = Pt(7)
        for item in linhas:
            cells = tab.add_row().cells
            for i, (chave, _, _) in enumerate(COLUNAS):
                v = item.get(chave)
                if chave == "repasse":
                    txt = _brl(v)
                elif chave in ("assinatura", "vigencia"):
                    txt = _dbr(v)
                else:
                    txt = str(v or "")
                    if chave == "objeto":
                        txt = txt[:180]
                cells[i].text = ""
                p = cells[i].paragraphs[0]
                run = p.add_run(txt)
                run.font.size = Pt(6.5)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
