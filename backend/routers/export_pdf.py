"""Export PDF: Convenios SIGCON-MG, Emendas Estaduais, Diario Oficial MG."""
from io import BytesIO
from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from database import get_db
from models import ConvenioEstadual, Municipio
from services.auth import get_current_user

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

router = APIRouter(prefix="/api/export-pdf", tags=["export-pdf"])


def _br(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, (int, float)):
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if isinstance(v, (date, datetime)):
        return v.strftime("%d/%m/%Y")
    return str(v)


def _build_pdf(title: str, subtitle: str, headers: list, rows: list, landscape_mode: bool = True) -> BytesIO:
    buf = BytesIO()
    page = landscape(A4) if landscape_mode else A4
    doc = SimpleDocTemplate(buf, pagesize=page,
                            leftMargin=10*mm, rightMargin=10*mm,
                            topMargin=10*mm, bottomMargin=10*mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Heading1"],
                                 fontSize=14, textColor=colors.HexColor("#1e40af"),
                                 spaceAfter=4)
    sub_style = ParagraphStyle("Sub", parent=styles["Normal"],
                               fontSize=9, textColor=colors.HexColor("#475569"),
                               spaceAfter=8)
    story = [Paragraph(title, title_style), Paragraph(subtitle, sub_style), Spacer(1, 4)]

    # Wrap header + rows
    data = [headers] + rows
    t = Table(data, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} | Total: {len(rows)} registros | PACTA - Plataforma de Acompanhamento",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=7,
                       textColor=colors.HexColor("#64748b"), alignment=2)))
    doc.build(story)
    buf.seek(0)
    return buf


@router.get("/convenios")
async def export_convenios_pdf(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    mun = (await db.execute(select(Municipio).where(Municipio.id == municipio_id))).scalar_one_or_none()
    if not mun:
        raise HTTPException(404, "Municipio nao encontrado")

    r = await db.execute(
        select(ConvenioEstadual).where(ConvenioEstadual.municipio_id == municipio_id)
        .order_by(ConvenioEstadual.dt_vigencia_atual.asc().nullslast())
    )
    convs = r.scalars().all()
    rows = []
    for c in convs:
        raw = c.raw_data if isinstance(c.raw_data, dict) else {}
        nr_proposta = raw.get("nr_proposta") or (c.nr_plano_trabalho if c.nr_plano_trabalho and "/" in c.nr_plano_trabalho else "")
        nr_instr = raw.get("nr_instrumento") or (c.nr_sigcon if c.nr_sigcon and "/" in c.nr_sigcon else "")
        rows.append([
            (c.fonte or "")[:8],
            nr_proposta[:14] or "-",
            (c.nr_plano_trabalho or "")[:10] if (c.nr_plano_trabalho and "/" not in c.nr_plano_trabalho) else "-",
            nr_instr[:14] or "-",
            (c.orgao_concedente or "")[:15],
            Paragraph((c.objeto or "")[:120], ParagraphStyle("o", fontSize=7)),
            (c.situacao or "")[:18],
            _br(c.valor_concedente or c.valor_total),
            _br(c.dt_vigencia_inicial),
            _br(c.dt_vigencia_atual or c.dt_vigencia_final),
        ])
    pdf = _build_pdf(
        f"Convenios SIGCON-MG - {mun.nome}/{mun.uf}",
        f"{len(convs)} convenios registrados",
        ["Fonte", "Proposta", "Plano", "Instrumento", "Orgao", "Objeto", "Situacao", "Repasse", "Assinatura", "Vigencia"],
        rows,
    )
    return StreamingResponse(pdf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=convenios_{mun.nome.replace(' ','_')}.pdf"})


@router.get("/emendas")
async def export_emendas_pdf(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    mun = (await db.execute(select(Municipio).where(Municipio.id == municipio_id))).scalar_one_or_none()
    if not mun:
        raise HTTPException(404, "Municipio nao encontrado")
    r = await db.execute(text("""
        SELECT nr_indicacao, nome_responsavel, tipo_indicacao,
               uo_sigla, valor_indicacao, status_indicacao, ano
        FROM emendas_estaduais WHERE municipio_id = :mun
        ORDER BY ano DESC NULLS LAST, valor_indicacao DESC NULLS LAST
    """), {"mun": municipio_id})
    items = r.fetchall()
    rows = [[
        (r[0] or "")[:14],
        Paragraph((r[1] or "")[:80], ParagraphStyle("n", fontSize=7)),
        (r[2] or "")[:18],
        (r[3] or "")[:12],
        _br(float(r[4]) if r[4] else 0),
        (r[5] or "")[:14],
        str(r[6] or "-"),
    ] for r in items]
    pdf = _build_pdf(
        f"Emendas Estaduais (SIGCON-MG) - {mun.nome}/{mun.uf}",
        f"{len(items)} indicacoes parlamentares estaduais",
        ["Nº Indicacao", "Responsavel", "Tipo", "UO", "Valor", "Status", "Ano"],
        rows,
    )
    return StreamingResponse(pdf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=emendas_{mun.nome.replace(' ','_')}.pdf"})


@router.get("/dou")
async def export_dou_pdf(
    municipio_id: int = Query(...),
    edicoes: list[str] = Query(...),
    titulos: list[str] = Query(default=[]),
    _=Depends(get_current_user),
):
    """DOU eh real-time. Frontend envia os titulos/edicoes ja filtrados via query."""
    rows = []
    for i, (titulo, edicao) in enumerate(zip(titulos, edicoes)):
        rows.append([
            str(i+1),
            Paragraph(titulo[:200], ParagraphStyle("t", fontSize=7)),
            edicao,
        ])
    pdf = _build_pdf(
        f"Diario Oficial MG - Municipio {municipio_id}",
        f"{len(rows)} publicacoes encontradas",
        ["#", "Titulo", "Edicao/Data"],
        rows,
        landscape_mode=False,
    )
    return StreamingResponse(pdf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=dou_{municipio_id}.pdf"})
