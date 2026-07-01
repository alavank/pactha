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
from models.user import User
from services.auth import get_current_user, ensure_municipio_access

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
        f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} | Total: {len(rows)} registros | PACTHA - Plataforma de Acompanhamento",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=7,
                       textColor=colors.HexColor("#64748b"), alignment=2)))
    doc.build(story)
    buf.seek(0)
    return buf


@router.get("/convenios")
async def export_convenios_pdf(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
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


@router.get("/voluntarias")
async def export_voluntarias_pdf(
    municipio_id: int = Query(...),
    categoria: Optional[str] = Query(None),
    situacao: Optional[str] = Query(None),
    orgao: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    parlamentar: Optional[str] = Query(None),
    situacao_contratacao: Optional[str] = Query(None),
    vigencia: Optional[str] = Query(None),
    vig_fim_de: Optional[str] = Query(None),
    vig_fim_ate: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """PDF dos instrumentos FEDERAIS (TransfereGov) com os MESMOS filtros da tela —
    relatorio personalizado da selecao (parlamentar, vigencia, situacao, etc.)."""
    ensure_municipio_access(current, municipio_id)
    mun = (await db.execute(select(Municipio).where(Municipio.id == municipio_id))).scalar_one_or_none()
    if not mun:
        raise HTTPException(404, "Municipio nao encontrado")
    # Reusa a mesma logica de filtro do endpoint da tela
    from routers.transferegov import voluntarias as _voluntarias
    res = await _voluntarias(
        municipio_id=municipio_id, situacao=situacao, orgao=orgao, search=search,
        parlamentar=parlamentar, situacao_contratacao=situacao_contratacao,
        vigencia=vigencia, vig_fim_de=vig_fim_de, vig_fim_ate=vig_fim_ate,
        categoria=categoria, db=db, _=None,
    )
    items = res.get("items", [])
    rows = []
    for it in items:
        rows.append([
            (it.get("codigo_instrumento") or it.get("numero_proposta") or "-")[:14],
            (it.get("orgao") or "")[:16],
            Paragraph((it.get("objeto") or "")[:110], ParagraphStyle("o", fontSize=7)),
            (it.get("parlamentar") or "-")[:18],
            (it.get("situacao") or "")[:16],
            (it.get("situacao_contratacao") or "-")[:14],
            it.get("dt_inicio_vigencia") or "-",
            it.get("dt_fim_vigencia") or "-",
            str(it["dias_restantes"]) if it.get("dias_restantes") is not None else "-",
        ])
    # Subtitulo com os filtros ativos (deixa claro o recorte do relatorio)
    _f = []
    if parlamentar: _f.append(f"parlamentar: {parlamentar}")
    if orgao: _f.append(f"orgao: {orgao}")
    if situacao_contratacao: _f.append(f"sit.contratacao: {situacao_contratacao}")
    _VIG = {"vence30": "vence 30d", "vence60": "vence 60d", "vence90": "vence 90d",
            "vence120": "vence 120d", "prestacao": "prestacao de contas"}
    if vigencia: _f.append(_VIG.get(vigencia, vigencia))
    if vig_fim_de: _f.append(f"fim vig. de {vig_fim_de}")
    if vig_fim_ate: _f.append(f"fim vig. ate {vig_fim_ate}")
    if search: _f.append(f"busca: {search}")
    filtros = " | ".join(_f) if _f else "sem filtros (todos)"
    pdf = _build_pdf(
        f"Instrumentos Federais (TransfereGov) - {mun.nome}/{mun.uf}",
        f"Categoria: {categoria or 'geral'} · Filtros: {filtros} · {len(rows)} instrumento(s)",
        ["Instrumento", "Orgao", "Objeto", "Parlamentar", "Situacao", "Sit.Contr.", "Inicio Vig.", "Fim Vig.", "Dias"],
        rows,
    )
    return StreamingResponse(pdf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=federais_{mun.nome.replace(' ','_')}.pdf"})


def _parse_emenda(cod: str):
    """codigoEmendaFormatado "202341760002-Vilson da Fetaemg" -> (codigo, parlamentar)."""
    if not cod:
        return ("", "")
    if "-" in cod:
        c, n = cod.split("-", 1)
        return (c.strip(), n.strip())
    return (cod.strip(), "")


@router.get("/plano-acao")
async def export_plano_acao_pdf(
    municipio_id: int = Query(...),
    situacao: Optional[str] = Query(None),
    programa: Optional[str] = Query(None),
    parlamentar: Optional[str] = Query(None),
    emenda: Optional[str] = Query(None),
    objeto: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """PDF dos Planos de Acao (Transferencia Especial / Pix Parlamentar) com os
    MESMOS filtros da tela Especiais."""
    ensure_municipio_access(current, municipio_id)
    mun = (await db.execute(select(Municipio).where(Municipio.id == municipio_id))).scalar_one_or_none()
    if not mun:
        raise HTTPException(404, "Municipio nao encontrado")
    from routers.transferegov import buscar as _buscar
    res = await _buscar(
        municipio_id=municipio_id,
        situacao=(situacao if situacao and situacao != "TODAS" else None),
        programa=programa, parlamentar=parlamentar, emenda=emenda, objeto=objeto,
        refresh=False, db=db, _=None,
    )
    items = res.get("items", [])
    rows = []
    for it in items:
        cod, parl = _parse_emenda(it.get("emenda_codigo") or "")
        benef = f"{it.get('beneficiario_cnpj') or ''} - {it.get('beneficiario_nome') or ''}".strip(" -")
        rows.append([
            (it.get("codigo") or "")[:16],
            cod[:14] or "-",
            Paragraph((parl or "-")[:50], ParagraphStyle("p", fontSize=7)),
            Paragraph(benef[:70], ParagraphStyle("b", fontSize=7)),
            _br(it.get("valor_total")),
            (it.get("situacao_plano_acao") or "")[:14],
            (it.get("situacao_plano_trabalho") or "-")[:22],
        ])
    _f = []
    if situacao and situacao != "TODAS": _f.append(f"situacao: {situacao}")
    if programa: _f.append(f"programa: {programa}")
    if parlamentar: _f.append(f"parlamentar/emenda: {parlamentar}")
    if emenda: _f.append(f"emenda: {emenda}")
    if objeto: _f.append(f"objeto: {objeto}")
    filtros = " | ".join(_f) if _f else "sem filtros (todos)"
    pdf = _build_pdf(
        f"Planos de Acao - Transferencia Especial - {mun.nome}/{mun.uf}",
        f"Filtros: {filtros} · {len(rows)} plano(s)",
        ["Codigo", "Emenda", "Parlamentar", "Beneficiario", "Valor", "Sit. P. Acao", "Sit. P. Trabalho"],
        rows,
    )
    return StreamingResponse(pdf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=plano_acao_{mun.nome.replace(' ','_')}.pdf"})


@router.get("/emendas")
async def export_emendas_pdf(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
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
    current: User = Depends(get_current_user),
):
    """DOU eh real-time. Frontend envia os titulos/edicoes ja filtrados via query."""
    ensure_municipio_access(current, municipio_id)
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
