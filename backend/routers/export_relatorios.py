"""
Exports do RM em Word (DOCX), PDF e Resumo de Pendencias (XLSX).
Padrao Freitas: 4 partes, agrupado por orgao.

- POST /api/export-relatorios/rm-word?municipio_id=X      -> docx
- POST /api/export-relatorios/rm-pdf?municipio_id=X       -> pdf
- POST /api/export-relatorios/pendencias-xlsx?municipio_id=X -> xlsx
"""
import io
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from collections import defaultdict

from database import get_db
from models import ConvenioFederal, ConvenioEstadual, Municipio, Emenda, Parlamentar
from services.auth import get_current_user
from services.status_resolver import resolve_status, fmt_date_br

router = APIRouter(prefix="/api/export-relatorios", tags=["export"])

MESES_PT = {
    1: "Janeiro", 2: "Fevereiro", 3: "Marco", 4: "Abril", 5: "Maio", 6: "Junho",
    7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


def fmt_money(v):
    if v is None:
        return "R$ 0,00"
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


# ----- Categorizacao em 4 partes (mesma logica de relatorio_monitoramento.py) -----
def categorize_part(c, esfera):
    sit = (getattr(c, "situacao", None) or "").lower()
    ano_atual = date.today().year
    dt_vig = (getattr(c, "dt_fim_vigencia", None) or
              getattr(c, "dt_vigencia_atual", None) or
              getattr(c, "dt_vigencia_final", None))
    has_des = bool(getattr(c, "dt_desembolso", None))
    val_des = float(getattr(c, "valor_desembolsado", 0) or 0)

    if any(kw in sit for kw in ["proposta", "plano de trabalho"]) and \
       any(kw in sit for kw in ["enviad", "analise", "voluntar", "elabora"]):
        return 4
    if any(kw in sit for kw in ["concluido", "encerr", "anulad", "cancelad",
                                 "rescindid", "aprovada", "ressalvas", "diligencia"]):
        return 3
    if dt_vig and (date.today() - dt_vig).days > 180:
        return 3
    if has_des and dt_vig and dt_vig < date.today():
        return 3
    if esfera == "federal":
        ano = getattr(c, "ano", None) or 0
        if ano >= ano_atual - 1:
            if any(kw in sit for kw in ["pendente", "empenh", "aguardando", "analise", "elabora"]) or sit == "":
                if not has_des and val_des == 0:
                    return 1
    if dt_vig and dt_vig >= date.today():
        return 2
    if not dt_vig:
        return 3
    return 2


# ----- Buscar dados -----
async def fetch_data(db: AsyncSession, municipio_id: int):
    mun = await db.get(Municipio, municipio_id)
    if not mun:
        raise HTTPException(404, "Municipio nao encontrado")

    federais = (await db.execute(
        select(ConvenioFederal).where(ConvenioFederal.municipio_id == municipio_id)
    )).scalars().all()
    estaduais = (await db.execute(
        select(ConvenioEstadual).where(ConvenioEstadual.municipio_id == municipio_id)
    )).scalars().all()

    # parlamentar por convenio
    parl = {"fed": {}, "est": {}}
    em = await db.execute(
        select(Emenda.convenio_federal_id, Emenda.convenio_estadual_id, Parlamentar.nome)
        .select_from(Emenda.__table__.join(Parlamentar.__table__, Emenda.parlamentar_id == Parlamentar.id))
        .where(Emenda.municipio_id == municipio_id)
    )
    for cf_id, ce_id, nome in em.all():
        if cf_id and cf_id not in parl["fed"]:
            parl["fed"][cf_id] = nome
        if ce_id and ce_id not in parl["est"]:
            parl["est"][ce_id] = nome

    return mun, list(federais), list(estaduais), parl


def group_by_orgao(items, esfera, parl_map):
    """Agrupa por orgao concedente (estilo Freitas) e enriquece com parlamentar."""
    grupos = defaultdict(list)
    for c in items:
        orgao = (getattr(c, "orgao_concedente", None) or "Outros").strip()
        # Normalizar nomes mais frequentes
        orgao_norm = orgao
        oup = orgao.upper()
        if "FNS" in oup or "FUNDO NACIONAL DE SAUDE" in oup:
            orgao_norm = "Ministerio da Saude - FNS"
        elif "FAZENDA" in oup or oup == "25000":
            orgao_norm = "Ministerio da Fazenda"
        elif "EDUC" in oup or "FNDE" in oup or oup == "26000":
            orgao_norm = "Ministerio da Educacao - FNDE"
        elif "AGRICULT" in oup or oup in ("22000", "53000"):
            orgao_norm = "Ministerio da Agricultura e Pecuaria"
        elif "ESPORTE" in oup:
            orgao_norm = "Ministerio do Esporte"
        elif "CIDADES" in oup or "MCID" in oup:
            orgao_norm = "Ministerio das Cidades"
        elif "TURISMO" in oup or "MTUR" in oup:
            orgao_norm = "Ministerio do Turismo"
        elif "INTEGR" in oup or "DESENV REGIONAL" in oup or "MIDR" in oup:
            orgao_norm = "Ministerio da Integracao e do Desenvolvimento Regional"
        elif "CIDADANIA" in oup:
            orgao_norm = "Ministerio da Cidadania"
        elif "DESENVOLVIMENTO" in oup and "SOCIAL" in oup:
            orgao_norm = "Ministerio do Desenvolvimento e Assistencia Social, Familia e Combate a Fome"
        elif "FUNASA" in oup:
            orgao_norm = "FUNASA"
        elif "CULTURA" in oup or "MINC" in oup:
            orgao_norm = "Ministerio da Cultura"
        elif "JUSTICA" in oup:
            orgao_norm = "Ministerio da Justica"
        elif "SAUDE" in oup or "MS" == oup:
            orgao_norm = "Ministerio da Saude"
        elif "SEGOV" in oup or "GOVERNO" in oup:
            orgao_norm = "SEGOV - Secretaria de Estado de Governo"
        elif "SES" in oup or "SAUDE" in oup:
            orgao_norm = "SES - Secretaria de Estado de Saude"
        elif "EDUCA" in oup:
            orgao_norm = "SEE - Secretaria de Estado de Educacao"
        elif "INFRA" in oup:
            orgao_norm = "SEINFRA - Secretaria de Estado de Infraestrutura"
        elif "DESENVOL" in oup:
            orgao_norm = "SEDESE - Secretaria de Desenvolvimento Social"

        parl_nome = parl_map[esfera].get(c.id) or "Verificar"
        grupos[orgao_norm].append((c, parl_nome))
    return dict(grupos)


# ===================== EXPORT WORD =====================
@router.get("/rm-word")
async def export_rm_word(
    municipio_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Gera RM em DOCX no padrao Freitas (4 partes, agrupado por orgao)."""
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor, Inches
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        raise HTTPException(500, "python-docx nao instalado. Adicione ao requirements.txt")

    mun, federais, estaduais, parl_map = await fetch_data(db, municipio_id)

    # Categorizar
    p1, p2_fed, p2_est, p3_fed, p3_est, p4 = [], [], [], [], [], []
    for c in federais:
        cat = categorize_part(c, "federal")
        if cat == 1: p1.append(c)
        elif cat == 2: p2_fed.append(c)
        elif cat == 3: p3_fed.append(c)
        elif cat == 4: p4.append(c)
    for c in estaduais:
        cat = categorize_part(c, "estadual")
        if cat == 2: p2_est.append(c)
        elif cat == 3: p3_est.append(c)

    doc = Document()
    today = date.today()
    data_label = f"Brasilia/DF, {today.day:02d} de {MESES_PT.get(today.month,'')} de {today.year}"

    def add_title(text):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(text)
        run.bold = True
        run.font.size = Pt(14)
        run.font.color.rgb = RGBColor(0x0B, 0x1F, 0x3B)

    def add_section(text):
        p = doc.add_paragraph()
        run = p.add_run(text)
        run.bold = True
        run.font.size = Pt(12)
        run.font.color.rgb = RGBColor(0x1F, 0x4E, 0x79)

    def add_orgao(text):
        p = doc.add_paragraph()
        run = p.add_run(f"● {text}")
        run.bold = True
        run.font.size = Pt(11)

    def add_convenio(c, parl, esfera):
        nr = (getattr(c, "nr_convenio", None) or getattr(c, "nr_sigcon", None) or "-")
        ano = getattr(c, "ano", None) or ""
        objeto = (getattr(c, "objeto", None) or getattr(c, "objetivo", None) or "-")
        vg = fmt_money(getattr(c, "valor_global", None) or getattr(c, "valor_total", None))
        vr = fmt_money(getattr(c, "valor_repasse", None) or getattr(c, "valor_concedente", None))
        vc = fmt_money(getattr(c, "valor_contrapartida", None))
        sit = resolve_status(c, esfera)

        p = doc.add_paragraph()
        p.add_run(f"Proposta: {nr}{f' - {ano}' if ano else ''}").bold = True

        for label, val in [
            ("Objeto", objeto),
            ("Parlamentar responsavel pela indicacao", parl),
            ("Valor global", vg),
            ("Valor de repasse", vr),
            ("Valor de contrapartida", vc),
        ]:
            li = doc.add_paragraph(style="List Bullet")
            r1 = li.add_run(f"{label}: ")
            r1.bold = True
            li.add_run(str(val))

        dt_vig = (getattr(c, "dt_fim_vigencia", None) or
                  getattr(c, "dt_vigencia_atual", None) or
                  getattr(c, "dt_vigencia_final", None))
        if dt_vig:
            li = doc.add_paragraph(style="List Bullet")
            li.add_run("Final da Vigencia: ").bold = True
            li.add_run(fmt_date_br(dt_vig))

        for fld, label in [("banco","Banco"), ("agencia","Agencia"),
                            ("conta_corrente","Conta"), ("nr_sei","NR SEI")]:
            v = getattr(c, fld, None)
            if v:
                li = doc.add_paragraph(style="List Bullet")
                li.add_run(f"{label}: ").bold = True
                li.add_run(str(v))

        sb = getattr(c, "saldo_bancario", None)
        if sb is not None:
            li = doc.add_paragraph(style="List Bullet")
            li.add_run("Saldo Bancario: ").bold = True
            txt = fmt_money(sb)
            dts = getattr(c, "dt_saldo", None)
            if dts:
                txt += f" (atualizado em {fmt_date_br(dts)})"
            li.add_run(txt)

        li = doc.add_paragraph(style="List Bullet")
        li.add_run("Situacao atual: ").bold = True
        li.add_run(sit)

    # === DOC ===
    add_title(f"RELATORIO DE MONITORAMENTO - {mun.nome}/{mun.uf}")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run(data_label)

    # PARTE 1
    if p1:
        add_section("PARTE 1 - DEMANDAS EM BRASILIA")
        grupos = group_by_orgao(p1, "fed", parl_map)
        for orgao, lst in sorted(grupos.items()):
            add_orgao(orgao)
            for c, parl in lst:
                add_convenio(c, parl, "federal")

    # PARTE 2
    if p2_fed or p2_est:
        add_section("PARTE 2 - DEMANDAS DO MUNICIPIO")
        if p2_fed:
            grupos = group_by_orgao(p2_fed, "fed", parl_map)
            for orgao, lst in sorted(grupos.items()):
                add_orgao(orgao)
                for c, parl in lst:
                    add_convenio(c, parl, "federal")
        if p2_est:
            grupos = group_by_orgao(p2_est, "est", parl_map)
            for orgao, lst in sorted(grupos.items()):
                add_orgao(orgao)
                for c, parl in lst:
                    add_convenio(c, parl, "estadual")

    # PARTE 3
    if p3_fed or p3_est:
        add_section("PARTE 3 - PRESTACOES DE CONTAS EM ANALISE/APROVADAS")
        if p3_fed:
            grupos = group_by_orgao(p3_fed, "fed", parl_map)
            for orgao, lst in sorted(grupos.items()):
                add_orgao(orgao)
                for c, parl in lst:
                    add_convenio(c, parl, "federal")
        if p3_est:
            grupos = group_by_orgao(p3_est, "est", parl_map)
            for orgao, lst in sorted(grupos.items()):
                add_orgao(orgao)
                for c, parl in lst:
                    add_convenio(c, parl, "estadual")

    # PARTE 4
    if p4:
        add_section("PARTE 4 - PROPOSTAS VOLUNTARIAS")
        grupos = group_by_orgao(p4, "fed", parl_map)
        for orgao, lst in sorted(grupos.items()):
            add_orgao(orgao)
            for c, parl in lst:
                add_convenio(c, parl, "federal")

    # Footer
    doc.add_paragraph()
    foot = doc.add_paragraph()
    foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = foot.add_run("Setor SHS Quadra 6, Conjunto A, Bloco E, Sala 624, Asa Sul, CEP 70.316.902, Brasilia/DF.")
    fr.font.size = Pt(8)
    fr.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    buf = io.BytesIO()
    doc.save(buf); buf.seek(0)
    fname = f"RM_{mun.nome.replace(' ','_')}_{today.strftime('%Y%m%d')}.docx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ===================== EXPORT PDF =====================
@router.get("/rm-pdf")
async def export_rm_pdf(
    municipio_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Gera RM em PDF (reportlab) no padrao Freitas."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib.colors import HexColor
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
    except ImportError:
        raise HTTPException(500, "reportlab nao instalado. Adicione ao requirements.txt")

    mun, federais, estaduais, parl_map = await fetch_data(db, municipio_id)

    p1, p2_fed, p2_est, p3_fed, p3_est, p4 = [], [], [], [], [], []
    for c in federais:
        cat = categorize_part(c, "federal")
        if cat == 1: p1.append(c)
        elif cat == 2: p2_fed.append(c)
        elif cat == 3: p3_fed.append(c)
        elif cat == 4: p4.append(c)
    for c in estaduais:
        cat = categorize_part(c, "estadual")
        if cat == 2: p2_est.append(c)
        elif cat == 3: p3_est.append(c)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    title_st = ParagraphStyle("title", parent=styles["Title"], fontSize=14,
                              textColor=HexColor("#0B1F3B"), alignment=TA_CENTER, spaceAfter=12)
    section_st = ParagraphStyle("section", parent=styles["Heading2"], fontSize=12,
                                textColor=HexColor("#1F4E79"), spaceAfter=6)
    orgao_st = ParagraphStyle("orgao", parent=styles["Heading3"], fontSize=11,
                              spaceBefore=8, spaceAfter=4, leftIndent=0)
    item_st = ParagraphStyle("item", parent=styles["Normal"], fontSize=10,
                             leftIndent=0.4*cm, spaceAfter=2)
    bullet_st = ParagraphStyle("bullet", parent=styles["Normal"], fontSize=9.5,
                               leftIndent=1*cm, bulletIndent=0.6*cm)

    today = date.today()
    story = [Paragraph(f"RELATORIO DE MONITORAMENTO - {mun.nome}/{mun.uf}", title_st)]
    story.append(Paragraph(f"Brasilia/DF, {today.day:02d} de {MESES_PT.get(today.month,'')} de {today.year}",
                           ParagraphStyle("date", parent=styles["Normal"], alignment=TA_CENTER, fontSize=10)))
    story.append(Spacer(1, 0.3*cm))

    def render_part(titulo, fed_list, est_list=None):
        if not fed_list and not est_list:
            return
        story.append(Paragraph(titulo, section_st))
        if fed_list:
            grupos = group_by_orgao(fed_list, "fed", parl_map)
            for orgao, lst in sorted(grupos.items()):
                story.append(Paragraph(f"● {orgao}", orgao_st))
                for c, parl in lst:
                    add_convenio_pdf(c, parl, "federal")
        if est_list:
            grupos = group_by_orgao(est_list, "est", parl_map)
            for orgao, lst in sorted(grupos.items()):
                story.append(Paragraph(f"● {orgao}", orgao_st))
                for c, parl in lst:
                    add_convenio_pdf(c, parl, "estadual")

    def add_convenio_pdf(c, parl, esfera):
        nr = (getattr(c, "nr_convenio", None) or getattr(c, "nr_sigcon", None) or "-")
        ano = getattr(c, "ano", None) or ""
        objeto = (getattr(c, "objeto", None) or getattr(c, "objetivo", None) or "-")
        vg = fmt_money(getattr(c, "valor_global", None) or getattr(c, "valor_total", None))
        vr = fmt_money(getattr(c, "valor_repasse", None) or getattr(c, "valor_concedente", None))
        vc = fmt_money(getattr(c, "valor_contrapartida", None))
        sit = resolve_status(c, esfera)
        dt_vig = (getattr(c, "dt_fim_vigencia", None) or
                  getattr(c, "dt_vigencia_atual", None) or
                  getattr(c, "dt_vigencia_final", None))

        story.append(Paragraph(f"<b>Proposta:</b> {nr}{f' - {ano}' if ano else ''}", item_st))
        bullets = [
            f"<b>Objeto:</b> {objeto}",
            f"<b>Parlamentar responsavel pela indicacao:</b> {parl}",
            f"<b>Valor global:</b> {vg}",
            f"<b>Valor de repasse:</b> {vr}",
            f"<b>Valor de contrapartida:</b> {vc}",
        ]
        if dt_vig: bullets.append(f"<b>Final da Vigencia:</b> {fmt_date_br(dt_vig)}")
        for fld, label in [("banco","Banco"), ("agencia","Agencia"),
                            ("conta_corrente","Conta"), ("nr_sei","NR SEI")]:
            v = getattr(c, fld, None)
            if v: bullets.append(f"<b>{label}:</b> {v}")
        sb = getattr(c, "saldo_bancario", None)
        if sb is not None:
            txt = fmt_money(sb)
            dts = getattr(c, "dt_saldo", None)
            if dts: txt += f" (atualizado em {fmt_date_br(dts)})"
            bullets.append(f"<b>Saldo Bancario:</b> {txt}")
        bullets.append(f"<b>Situacao atual:</b> {sit}")
        for b in bullets:
            story.append(Paragraph(f"➢ {b}", bullet_st))
        story.append(Spacer(1, 0.15*cm))

    render_part("PARTE 1 - DEMANDAS EM BRASILIA", p1, None)
    render_part("PARTE 2 - DEMANDAS DO MUNICIPIO", p2_fed, p2_est)
    render_part("PARTE 3 - PRESTACOES DE CONTAS EM ANALISE/APROVADAS", p3_fed, p3_est)
    render_part("PARTE 4 - PROPOSTAS VOLUNTARIAS", p4, None)

    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(
        "<font size='8' color='#666666'>Setor SHS Quadra 6, Conjunto A, Bloco E, Sala 624, Asa Sul, CEP 70.316.902, Brasilia/DF.</font>",
        ParagraphStyle("foot", parent=styles["Normal"], alignment=TA_CENTER)))

    doc.build(story); buf.seek(0)
    fname = f"RM_{mun.nome.replace(' ','_')}_{today.strftime('%Y%m%d')}.pdf"
    return StreamingResponse(buf, media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ===================== RESUMO PENDENCIAS XLSX =====================
@router.get("/pendencias-xlsx")
async def export_pendencias_xlsx(
    municipio_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Resumo de Pendencias em Excel: convenios pendentes (PARTE 1 + vigencia
    proxima do fim sem desembolso). Para reuniao com o cliente."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        raise HTTPException(500, "openpyxl nao instalado")

    mun, federais, estaduais, parl_map = await fetch_data(db, municipio_id)

    # Filtrar apenas pendencias: PARTE 1 (federais pendentes brasilia) +
    # convenios com vigencia <= 90 dias e sem desembolso completo
    today = date.today()
    pendencias = []
    for c in federais:
        cat = categorize_part(c, "federal")
        dt_vig = c.dt_fim_vigencia
        val_emp = float(c.valor_empenhado or 0)
        val_des = float(c.valor_desembolsado or 0)
        val_glob = float(c.valor_global or 0)

        eh_pendencia = False
        tipo_pend = ""
        if cat == 1:
            eh_pendencia = True
            tipo_pend = "Pendente em Brasilia"
        elif dt_vig and (dt_vig - today).days <= 90 and (dt_vig - today).days >= 0:
            if val_des < val_glob:
                eh_pendencia = True
                tipo_pend = f"Vigencia em {(dt_vig - today).days} dias"
        elif dt_vig and dt_vig < today and val_des == 0:
            eh_pendencia = True
            tipo_pend = "Vigencia vencida sem desembolso"

        if eh_pendencia:
            pendencias.append({
                "esfera": "Federal", "tipo_pendencia": tipo_pend,
                "nr": c.nr_convenio, "orgao": c.orgao_concedente,
                "objeto": c.objeto, "ano": c.ano,
                "parlamentar": parl_map["fed"].get(c.id) or "-",
                "valor_global": val_glob, "valor_empenhado": val_emp,
                "valor_desembolsado": val_des,
                "saldo_a_executar": val_glob - val_des,
                "dt_fim_vigencia": c.dt_fim_vigencia,
                "dias_restantes": (dt_vig - today).days if dt_vig else None,
                "situacao": resolve_status(c, "federal"),
            })

    for c in estaduais:
        dt_vig = c.dt_vigencia_atual or c.dt_vigencia_final
        val_glob = float(c.valor_total or 0)
        val_rep = float(c.valor_repassado or 0)
        if dt_vig and (dt_vig - today).days <= 90 and (dt_vig - today).days >= 0:
            if val_rep < val_glob:
                pendencias.append({
                    "esfera": "Estadual",
                    "tipo_pendencia": f"Vigencia em {(dt_vig - today).days} dias",
                    "nr": c.nr_sigcon, "orgao": c.orgao_concedente,
                    "objeto": c.objeto, "ano": c.ano,
                    "parlamentar": parl_map["est"].get(c.id) or "-",
                    "valor_global": val_glob, "valor_empenhado": 0,
                    "valor_desembolsado": val_rep,
                    "saldo_a_executar": val_glob - val_rep,
                    "dt_fim_vigencia": dt_vig,
                    "dias_restantes": (dt_vig - today).days,
                    "situacao": resolve_status(c, "estadual"),
                })

    # Ordenar: dias restantes asc (mais urgente primeiro), depois valor desc
    pendencias.sort(key=lambda x: (x["dias_restantes"] if x["dias_restantes"] is not None else 9999,
                                    -x["valor_global"]))

    wb = Workbook()
    ws = wb.active
    ws.title = "Pendencias"

    headers = ["Esfera", "Tipo Pendencia", "Nr Convenio", "Orgao", "Ano",
               "Parlamentar", "Objeto", "Valor Global", "Valor Empenhado",
               "Valor Desembolsado", "Saldo a Executar", "Vigencia Final",
               "Dias Restantes", "Situacao"]
    bold = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", start_color="0B1F3B")
    border = Border(*[Side(style="thin", color="CCCCCC")]*4)
    for col, h in enumerate(headers, 1):
        cell = ws.cell(1, col, h)
        cell.font = bold; cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border

    for row_idx, p in enumerate(pendencias, 2):
        ws.cell(row_idx, 1, p["esfera"])
        ws.cell(row_idx, 2, p["tipo_pendencia"])
        ws.cell(row_idx, 3, p["nr"] or "-")
        ws.cell(row_idx, 4, p["orgao"] or "-")
        ws.cell(row_idx, 5, p["ano"])
        ws.cell(row_idx, 6, p["parlamentar"])
        ws.cell(row_idx, 7, (p["objeto"] or "-")[:200])
        ws.cell(row_idx, 8, p["valor_global"]).number_format = 'R$ #,##0.00'
        ws.cell(row_idx, 9, p["valor_empenhado"]).number_format = 'R$ #,##0.00'
        ws.cell(row_idx, 10, p["valor_desembolsado"]).number_format = 'R$ #,##0.00'
        ws.cell(row_idx, 11, p["saldo_a_executar"]).number_format = 'R$ #,##0.00'
        ws.cell(row_idx, 12, p["dt_fim_vigencia"])
        if p["dt_fim_vigencia"]:
            ws.cell(row_idx, 12).number_format = "DD/MM/YYYY"
        ws.cell(row_idx, 13, p["dias_restantes"])
        ws.cell(row_idx, 14, p["situacao"])
        # Highlight rows com vigencia <= 30 dias
        if p["dias_restantes"] is not None and 0 <= p["dias_restantes"] <= 30:
            for col in range(1, 15):
                ws.cell(row_idx, col).fill = PatternFill("solid", start_color="FFE5E5")
        elif p["dias_restantes"] is not None and p["dias_restantes"] < 0:
            for col in range(1, 15):
                ws.cell(row_idx, col).fill = PatternFill("solid", start_color="FF9999")

    # Larguras
    widths = [10, 22, 15, 30, 6, 25, 50, 14, 14, 14, 14, 12, 8, 35]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64+i) if i<=26 else 'A'+chr(64+i-26)].width = w

    # Aba 2: resumo agregado
    ws2 = wb.create_sheet("Resumo")
    ws2.cell(1, 1, f"Resumo de Pendencias - {mun.nome}/{mun.uf}").font = Font(bold=True, size=14)
    ws2.cell(2, 1, f"Gerado em {today.strftime('%d/%m/%Y')}")
    ws2.cell(4, 1, "Total de pendencias").font = Font(bold=True)
    ws2.cell(4, 2, len(pendencias))
    ws2.cell(5, 1, "Soma a executar").font = Font(bold=True)
    ws2.cell(5, 2, sum(p["saldo_a_executar"] for p in pendencias)).number_format = 'R$ #,##0.00'
    ws2.cell(6, 1, "Vigencia <= 30 dias").font = Font(bold=True)
    ws2.cell(6, 2, sum(1 for p in pendencias
                       if p["dias_restantes"] is not None and 0 <= p["dias_restantes"] <= 30))
    ws2.cell(7, 1, "Vigencia vencida").font = Font(bold=True)
    ws2.cell(7, 2, sum(1 for p in pendencias
                       if p["dias_restantes"] is not None and p["dias_restantes"] < 0))
    for col in (1, 2):
        ws2.column_dimensions[chr(64+col)].width = 30

    buf = io.BytesIO()
    wb.save(buf); buf.seek(0)
    fname = f"Pendencias_{mun.nome.replace(' ','_')}_{today.strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
