"""Export PDF: Convenios SIGCON-MG, Emendas Estaduais, Diario Oficial MG."""
import re
import html
from io import BytesIO
from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from database import get_db
from models import ConvenioEstadual, Municipio
from models.user import User
from services.auth import get_current_user, ensure_municipio_access, ensure_tela

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether

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


# ---------------------------------------------------------------------------
# Parlamentares — relatorio por parlamentar (respeita a busca da tela)
# ---------------------------------------------------------------------------
_CELL = ParagraphStyle("cell", fontSize=7, leading=8.5)


def _pc(txt, limit: int = 400):
    """Celula que quebra linha (Paragraph). '-' quando vazio."""
    s = "" if txt is None else str(txt)
    s = s.replace("\n", " ").strip()
    return Paragraph((s[:limit] or "-"), _CELL)


def _sec_table(headers: list, rows: list, col_widths_mm: list) -> Table:
    t = Table([headers] + rows, repeatRows=1, hAlign="LEFT",
              colWidths=[w * mm for w in col_widths_mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


@router.get("/parlamentares")
async def export_parlamentares_pdf(
    municipio_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None),
    ano: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """PDF da tela Parlamentares — uma secao por parlamentar (respeita a busca
    `q`, o ano e o filtro de municipio), com TODOS os lancamentos: SIGCON-MG
    (estadual), TransfereGov/SICONV (federal) e Emendas estaduais."""
    ensure_tela(current, "parlamentares")
    ensure_municipio_access(current, municipio_id)

    from routers.parlamentares import listar as _listar, detalhe as _detalhe
    lista = await _listar(municipio_id=municipio_id, q=q, ano=ano, db=db, current=current)
    items = lista.get("items", [])

    styles = getSampleStyleSheet()
    name_style = ParagraphStyle("pname", parent=styles["Heading2"], fontSize=11,
                                textColor=colors.HexColor("#1e40af"),
                                spaceBefore=10, spaceAfter=1)
    meta_style = ParagraphStyle("pmeta", parent=styles["Normal"], fontSize=8,
                                textColor=colors.HexColor("#475569"), spaceAfter=3)
    sub_style = ParagraphStyle("psub", parent=styles["Normal"], fontSize=8.5,
                               fontName="Helvetica-Bold",
                               textColor=colors.HexColor("#0f766e"),
                               spaceBefore=4, spaceAfter=2)
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=15,
                                 textColor=colors.HexColor("#1e40af"), spaceAfter=2)
    subt_style = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=9,
                                textColor=colors.HexColor("#475569"), spaceAfter=10)

    filtros = []
    if q:
        filtros.append(f"busca: \"{q}\"")
    filtros.append(f"ano: {ano}" if ano else "todos os anos")
    filtros.append(f"municipio: {municipio_id}" if municipio_id else "todos os municipios")
    story = [
        Paragraph("Relatorio de Parlamentares", title_style),
        Paragraph(f"{len(items)} parlamentar(es) · {' · '.join(filtros)}", subt_style),
    ]

    for p in items:
        try:
            det = await _detalhe(nome_normalizado=p["nome_display"],
                                 municipio_id=municipio_id, ano=ano, db=db, current=current)
        except HTTPException:
            det = {"sigcon": [], "voluntarias": [], "emendas": [], "plano_acao": [], "pac": [], "fns": []}

        pf = p.get("por_fonte", {})
        muns = ", ".join(p.get("municipios", []))
        cab = [
            Paragraph(p["nome_display"], name_style),
            Paragraph(
                f"{p['total_lancamentos']} lancamento(s) · Total {_br(p['valor_total'])} · "
                f"SIGCON: {pf.get('sigcon', 0)} · TransfereGov: {pf.get('voluntaria', 0)} · "
                f"Emendas: {pf.get('emenda', 0)} · Transf. Especial: {pf.get('plano_acao', 0)} · "
                f"PAC: {pf.get('pac', 0)} · FNS: {pf.get('fns', 0)}"
                + (f" · Municipios: {muns}" if muns else ""),
                meta_style),
        ]
        story.append(KeepTogether(cab))

        sig = det.get("sigcon", [])
        if sig:
            rows = [[
                _pc(s.get("municipio_nome"), 30), _pc(s.get("numero"), 20),
                _pc(s.get("orgao"), 60), _pc(s.get("situacao"), 40),
                _pc(_br(s.get("valor_total"))),
                _pc(s.get("dt_vigencia_atual") or s.get("dt_vigencia_final")),
                _pc(s.get("objeto"), 500),
            ] for s in sig]
            story.append(Paragraph(f"SIGCON-MG (Estadual) — {len(sig)} convenio(s)", sub_style))
            story.append(_sec_table(
                ["Municipio", "Nº SIGCON", "Orgao", "Situacao", "Valor Total", "Vigencia", "Objeto"],
                rows, [24, 22, 34, 30, 26, 22, 119]))

        vol = det.get("voluntarias", [])
        if vol:
            rows = [[
                _pc(v.get("municipio_nome"), 30), _pc(v.get("numero_proposta"), 20),
                _pc(v.get("codigo_instrumento"), 20), _pc(v.get("orgao"), 40),
                _pc(v.get("situacao"), 40), _pc(v.get("situacao_contratacao"), 30),
                _pc(_br(v.get("valor_global"))),
                _pc(_br(v.get("dt_fim_vigencia")) if v.get("dt_fim_vigencia") else "-"),
                _pc(v.get("objeto"), 500),
            ] for v in vol]
            story.append(Paragraph(f"TransfereGov / SICONV (Federal) — {len(vol)} proposta(s)", sub_style))
            story.append(_sec_table(
                ["Municipio", "Nº Proposta", "Instrumento", "Orgao", "Situacao", "Sit.Contr.", "Valor Global", "Fim Vig.", "Objeto"],
                rows, [22, 22, 22, 26, 26, 22, 26, 20, 91]))

        em = det.get("emendas", [])
        if em:
            rows = [[
                _pc(e.get("municipio_nome"), 30), _pc(e.get("nr_indicacao"), 20),
                _pc(e.get("ano")), _pc(e.get("uo_sigla"), 14),
                _pc(e.get("beneficiario"), 120), _pc(e.get("tipo_atendimento"), 60),
                _pc(_br(e.get("valor_indicacao"))), _pc(e.get("status_indicacao"), 40),
            ] for e in em]
            story.append(Paragraph(f"Emendas Estaduais — {len(em)} indicacao(oes)", sub_style))
            story.append(_sec_table(
                ["Municipio", "Indicacao", "Ano", "UO", "Beneficiario", "Tipo", "Valor", "Status"],
                rows, [24, 24, 12, 16, 70, 45, 26, 60]))

        pa = det.get("plano_acao", [])
        if pa:
            rows = [[
                _pc(x.get("municipio_nome"), 30), _pc(x.get("codigo"), 20),
                _pc(x.get("emenda"), 16), _pc(x.get("situacao"), 16),
                _pc(_br(x.get("valor_custeio"))), _pc(_br(x.get("valor_investimento"))),
                _pc(_br(x.get("valor_total"))), _pc(x.get("objeto"), 500),
            ] for x in pa]
            story.append(Paragraph(f"Transferencia Especial / Plano de Acao (RP9) — {len(pa)} plano(s)", sub_style))
            story.append(_sec_table(
                ["Municipio", "Plano", "Emenda", "Situacao", "Custeio", "Investim.", "Valor Total", "Objeto/Politica"],
                rows, [24, 26, 26, 22, 26, 26, 26, 101]))

        pac = det.get("pac", [])
        if pac:
            rows = [[
                _pc(x.get("municipio_nome"), 30), _pc(x.get("numero_proposta"), 20),
                _pc(x.get("programa"), 120), _pc(x.get("situacao"), 40),
                _pc(_br(x.get("valor_total"))), _pc(x.get("emenda_parlamentar"), 40),
            ] for x in pac]
            story.append(Paragraph(f"Selecao PAC / Novo PAC — {len(pac)} proposta(s)", sub_style))
            story.append(_sec_table(
                ["Municipio", "Nº Proposta", "Programa", "Situacao", "Valor Total", "Emenda"],
                rows, [26, 24, 90, 40, 28, 45]))

        fns = det.get("fns", [])
        if fns:
            rows = [[
                _pc(x.get("municipio_nome"), 30), _pc(x.get("numero"), 20),
                _pc(x.get("orgao"), 40), _pc(x.get("situacao"), 40),
                _pc(_br(x.get("valor_total"))), _pc(x.get("ano")),
                _pc(x.get("objeto"), 500),
            ] for x in fns]
            story.append(Paragraph(f"FNS — Fundo Nacional de Saude (Federal) — {len(fns)} proposta(s)", sub_style))
            story.append(_sec_table(
                ["Municipio", "Nº Proposta", "Orgao", "Situacao", "Valor Total", "Ano", "Objeto"],
                rows, [24, 24, 34, 34, 26, 14, 97]))

        if not (sig or vol or em or pa or pac or fns):
            story.append(Paragraph("Sem lancamentos detalhados.", meta_style))
        story.append(Spacer(1, 6))

    if not items:
        story.append(Paragraph("Nenhum parlamentar para o filtro atual.", meta_style))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} | PACTHA - Plataforma de Acompanhamento",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=7,
                       textColor=colors.HexColor("#64748b"), alignment=2)))

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=10*mm, rightMargin=10*mm,
                            topMargin=10*mm, bottomMargin=10*mm)
    doc.build(story)
    buf.seek(0)
    fn = "parlamentares"
    if q:
        fn += "_" + "".join(ch for ch in q if ch.isalnum())[:20]
    if ano:
        fn += f"_{ano}"
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={fn}.pdf"})


# ---------------------------------------------------------------------------
# IA PACTHA — exporta uma resposta da IA (markdown) em PDF
# ---------------------------------------------------------------------------
def _md_inline(t: str) -> str:
    """Markdown inline -> markup do reportlab Paragraph (<b>, <i>, code)."""
    t = html.escape(t or "", quote=False)
    t = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"__([^_]+)__", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\*\w])\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", t)
    return t


def _md_to_flowables(md: str, styles) -> list:
    """Converte markdown (headings, listas, tabelas, negrito) em flowables."""
    body = ParagraphStyle("mdbody", parent=styles["Normal"], fontSize=10, leading=14, spaceAfter=4)
    h1 = ParagraphStyle("mdh1", parent=styles["Heading1"], fontSize=14, textColor=colors.HexColor("#1e40af"), spaceBefore=8, spaceAfter=4)
    h2 = ParagraphStyle("mdh2", parent=styles["Heading2"], fontSize=12, textColor=colors.HexColor("#1e40af"), spaceBefore=6, spaceAfter=3)
    h3 = ParagraphStyle("mdh3", parent=styles["Heading3"], fontSize=11, textColor=colors.HexColor("#334155"), spaceBefore=4, spaceAfter=2)
    cell = ParagraphStyle("mdcell", parent=styles["Normal"], fontSize=8, leading=10)

    out = []
    lines = (md or "").replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        # Tabela markdown (linha com | e proxima com ---)
        if "|" in s and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:\-|]+\|?\s*$", lines[i + 1]) and "-" in lines[i + 1]:
            def _cells(row):
                row = row.strip().strip("|")
                return [c.strip() for c in row.split("|")]
            header = _cells(s)
            data = [[Paragraph(_md_inline(c), cell) for c in header]]
            i += 2
            while i < len(lines) and "|" in lines[i]:
                data.append([Paragraph(_md_inline(c), cell) for c in _cells(lines[i])])
                i += 1
            t = Table(data, repeatRows=1, hAlign="LEFT")
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            out.append(t)
            out.append(Spacer(1, 6))
            continue
        if not s:
            out.append(Spacer(1, 4))
        elif s.startswith("### "):
            out.append(Paragraph(_md_inline(s[4:]), h3))
        elif s.startswith("## "):
            out.append(Paragraph(_md_inline(s[3:]), h2))
        elif s.startswith("# "):
            out.append(Paragraph(_md_inline(s[2:]), h1))
        elif re.match(r"^([-*+])\s+", s):
            out.append(Paragraph("• " + _md_inline(re.sub(r"^([-*+])\s+", "", s)), body, bulletText=None))
        elif re.match(r"^\d+\.\s+", s):
            out.append(Paragraph(_md_inline(s), body))
        elif re.match(r"^[-=]{3,}$", s):
            out.append(Spacer(1, 4))
        else:
            out.append(Paragraph(_md_inline(s), body))
        i += 1
    return out


# Nome legivel da fonte a partir do nome tecnico da ferramenta, para a secao de
# procedencia. O que nao estiver aqui nao aparece — melhor omitir do que
# imprimir "query_xyz" num documento institucional.
_FONTE_DA_TOOL = {
    "municipio_summary": "Resumo consolidado do município (base PACTHA)",
    "query_convenios_sigcon": "SIGCON-MG — convênios estaduais",
    "query_situacoes_sigcon": "SIGCON-MG — situações dos convênios",
    "query_voluntarias": "TransfereGov / SICONV — propostas federais",
    "search_by_parlamentar": "Busca por parlamentar (todas as fontes)",
    "query_simec_liberacoes": "SIMEC PAR — liberações do MEC",
    "query_simec_dimensoes": "SIMEC PAR — diagnóstico por dimensão",
    "query_emendas_estaduais": "SIGCON-MG — emendas estaduais",
    "query_fns": "FNS — Fundo Nacional de Saúde",
    "query_plano_acao": "Transferências Especiais (RP9) — Ministério da Fazenda",
    "list_municipios": None,  # ruido: nao entra no relatorio
}


@router.post("/ai-relatorio")
async def export_ai_relatorio(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Relatorio em PDF de UM resultado da IA.

    Diferente do /ai antigo (que imprimia "Solicitacao: <pergunta>" seguida da
    resposta e parecia transcricao de conversa): aqui sai um documento —
    cabecalho institucional com municipio e data de emissao, o conteudo como
    corpo, e uma secao de PROCEDENCIA com as fontes que a IA realmente
    consultou. Body: {assunto, conteudo, municipio_id?, tools?: [nomes]}."""
    conteudo = (payload.get("conteudo") or "").strip()
    if not conteudo:
        raise HTTPException(400, "conteudo vazio")
    assunto = (payload.get("assunto") or "Relatório").strip().replace("\n", " ")[:160]

    municipio_txt = ""
    mid = payload.get("municipio_id")
    if mid:
        ensure_municipio_access(current, mid)
        row = (await db.execute(
            text("SELECT nome, uf FROM municipios WHERE id = :i"), {"i": int(mid)})).first()
        if row:
            municipio_txt = f"{row[0]}/{row[1]}"

    fontes: list[str] = []
    for t in (payload.get("tools") or []):
        nome = _FONTE_DA_TOOL.get(str(t))
        if nome and nome not in fontes:
            fontes.append(nome)

    styles = getSampleStyleSheet()
    st_rotulo = ParagraphStyle("Rotulo", parent=styles["Normal"], fontSize=7.5,
                               textColor=colors.HexColor("#64748b"), spaceAfter=1,
                               alignment=1)
    st_titulo = ParagraphStyle("TituloRel", parent=styles["Heading1"], fontSize=16,
                               textColor=colors.HexColor("#0f172a"), spaceAfter=2,
                               alignment=1, leading=19)
    st_sub = ParagraphStyle("SubRel", parent=styles["Normal"], fontSize=9,
                            textColor=colors.HexColor("#475569"), alignment=1,
                            spaceAfter=10)
    st_sec = ParagraphStyle("SecRel", parent=styles["Heading3"], fontSize=10,
                            textColor=colors.HexColor("#1e40af"), spaceBefore=10,
                            spaceAfter=3)
    st_fonte = ParagraphStyle("FonteRel", parent=styles["Normal"], fontSize=8.5,
                              textColor=colors.HexColor("#334155"), leftIndent=8,
                              spaceAfter=1)
    st_rodape = ParagraphStyle("RodapeRel", parent=styles["Normal"], fontSize=7,
                               textColor=colors.HexColor("#94a3b8"), alignment=1)

    emitido = datetime.now().strftime("%d/%m/%Y as %H:%M")
    linha_sub = " · ".join(x for x in [
        municipio_txt, f"Emitido em {emitido}",
        html.escape(getattr(current, "name", "") or ""),
    ] if x)
    story = [
        Paragraph("RELATÓRIO GERADO PELA PLATAFORMA PACTHA", st_rotulo),
        Paragraph(html.escape(assunto), st_titulo),
        Paragraph(linha_sub, st_sub),
        Table([[""]], colWidths=[180 * mm], rowHeights=[0.6],
              style=TableStyle([("BACKGROUND", (0, 0), (-1, -1),
                                 colors.HexColor("#1e40af"))])),
        Spacer(1, 8),
    ]
    story.extend(_md_to_flowables(conteudo, styles))

    if fontes:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Procedência dos dados", st_sec))
        for f in fontes:
            story.append(Paragraph("• " + html.escape(f), st_fonte))

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "Documento gerado automaticamente a partir dos dados da plataforma PACTHA na data de "
        "emissão. Os valores refletem a última coleta de cada fonte oficial.", st_rodape))

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=14 * mm, bottomMargin=12 * mm,
                            title=assunto, author="PACTHA")
    doc.build(story)
    buf.seek(0)
    nome_arq = re.sub(r"[^A-Za-z0-9]+", "-", assunto).strip("-").lower()[:60] or "relatorio"
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=relatorio-{nome_arq}.pdf"})


@router.post("/ai")
async def export_ai_pdf(
    payload: dict = Body(...),
    current: User = Depends(get_current_user),
):
    """Exporta uma resposta da IA PACTHA (markdown) em PDF. Body: {titulo?, pergunta?, conteudo}."""
    conteudo = (payload.get("conteudo") or "").strip()
    if not conteudo:
        raise HTTPException(400, "conteudo vazio")
    titulo = (payload.get("titulo") or "Relatorio - IA PACTHA").strip()[:120]
    pergunta = (payload.get("pergunta") or "").strip()

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=15,
                                 textColor=colors.HexColor("#1e40af"), spaceAfter=2)
    q_style = ParagraphStyle("Q", parent=styles["Normal"], fontSize=9,
                             textColor=colors.HexColor("#475569"), spaceAfter=2,
                             leftIndent=6, borderPadding=4)
    story = [Paragraph(html.escape(titulo), title_style)]
    if pergunta:
        story.append(Paragraph("<b>Solicitação:</b> " + _md_inline(pergunta), q_style))
    story.append(Spacer(1, 6))
    story.extend(_md_to_flowables(conteudo, styles))
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        f"Gerado pela IA PACTHA em {datetime.now().strftime('%d/%m/%Y %H:%M')} · "
        "confira os dados na plataforma antes de usar.",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=7,
                       textColor=colors.HexColor("#94a3b8"), alignment=1)))

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm,
                            topMargin=15*mm, bottomMargin=12*mm)
    doc.build(story)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=ia-pactha.pdf"})
