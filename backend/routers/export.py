from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from io import BytesIO
from database import get_db
from models import ConvenioFederal, ConvenioEstadual, Emenda, Parlamentar
from services.auth import get_current_user
import openpyxl
from datetime import date

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/convenios")
async def export_convenios(
    municipio_id: Optional[int] = None,
    esfera: Optional[str] = None,
    format: str = Query("xlsx", pattern="^(xlsx|pdf)$"),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    if format == "pdf":
        return await _export_convenios_pdf(municipio_id, esfera, db)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Convenios"

    headers = [
        "Esfera", "Nr Convenio", "Orgao Concedente", "Objeto",
        "Situacao", "Valor Total", "Valor Empenhado", "Valor Desembolsado",
        "Inicio Vigencia", "Fim Vigencia", "Dias Restantes", "Ano",
    ]
    ws.append(headers)

    # Federal
    if esfera in (None, "federal"):
        q = select(ConvenioFederal)
        if municipio_id:
            q = q.where(ConvenioFederal.municipio_id == municipio_id)
        result = await db.execute(q)
        for c in result.scalars().all():
            dias = (c.dt_fim_vigencia - date.today()).days if c.dt_fim_vigencia else None
            ws.append([
                "Federal", c.nr_convenio, c.orgao_concedente,
                c.objeto[:200] if c.objeto else "",
                c.situacao, float(c.valor_global) if c.valor_global else 0,
                float(c.valor_empenhado) if c.valor_empenhado else 0,
                float(c.valor_desembolsado) if c.valor_desembolsado else 0,
                str(c.dt_inicio) if c.dt_inicio else "",
                str(c.dt_fim_vigencia) if c.dt_fim_vigencia else "",
                dias, c.ano,
            ])

    # Estadual
    if esfera in (None, "estadual"):
        q = select(ConvenioEstadual)
        if municipio_id:
            q = q.where(ConvenioEstadual.municipio_id == municipio_id)
        result = await db.execute(q)
        for c in result.scalars().all():
            dt_vig = c.dt_vigencia_atual or c.dt_vigencia_final
            dias = (dt_vig - date.today()).days if dt_vig else None
            ws.append([
                "Estadual", c.nr_sigcon, c.orgao_concedente,
                c.objeto[:200] if c.objeto else "",
                c.situacao, float(c.valor_total) if c.valor_total else 0,
                float(c.valor_emenda_parlamentar) if c.valor_emenda_parlamentar else 0,
                float(c.valor_repassado) if c.valor_repassado else 0,
                str(c.dt_vigencia_inicial) if c.dt_vigencia_inicial else "",
                str(dt_vig) if dt_vig else "",
                dias, c.ano,
            ])

    # Style header
    from openpyxl.styles import Font, PatternFill
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")

    # Auto-width
    for col in ws.columns:
        max_length = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_length + 2, 50)

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=convenios_pacta.xlsx"},
    )


async def _export_convenios_pdf(municipio_id, esfera, db):
    """Generate simple HTML-based PDF (no external deps)."""
    from sqlalchemy import select
    from datetime import date as ddate
    rows = []

    if esfera in (None, "federal"):
        q = select(ConvenioFederal)
        if municipio_id:
            q = q.where(ConvenioFederal.municipio_id == municipio_id)
        result = await db.execute(q)
        for c in result.scalars().all():
            rows.append({
                "esfera": "Federal", "nr": c.nr_convenio,
                "orgao": c.orgao_concedente or "-",
                "objeto": (c.objeto or "")[:120],
                "situacao": c.situacao or "-",
                "valor": float(c.valor_global) if c.valor_global else 0,
                "vigencia": str(c.dt_fim_vigencia) if c.dt_fim_vigencia else "-",
            })

    if esfera in (None, "estadual"):
        q = select(ConvenioEstadual)
        if municipio_id:
            q = q.where(ConvenioEstadual.municipio_id == municipio_id)
        result = await db.execute(q)
        for c in result.scalars().all():
            dt_v = c.dt_vigencia_atual or c.dt_vigencia_final
            rows.append({
                "esfera": "Estadual", "nr": c.nr_sigcon,
                "orgao": c.orgao_concedente or "-",
                "objeto": (c.objeto or "")[:120],
                "situacao": c.situacao or "-",
                "valor": float(c.valor_total) if c.valor_total else 0,
                "vigencia": str(dt_v) if dt_v else "-",
            })

    total_valor = sum(r["valor"] for r in rows)
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Relatorio PACTA</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 30px; color: #333; }}
  h1 {{ color: #1f4e79; border-bottom: 2px solid #1f4e79; padding-bottom: 10px; }}
  .meta {{ color: #666; margin-bottom: 20px; font-size: 12px; }}
  .summary {{ background: #f0f4f8; padding: 12px; border-radius: 6px; margin-bottom: 20px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
  th {{ background: #1f4e79; color: white; padding: 8px; text-align: left; }}
  td {{ padding: 6px 8px; border-bottom: 1px solid #eee; }}
  tr:nth-child(even) {{ background: #f9f9f9; }}
  .right {{ text-align: right; }}
  .badge {{ display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 10px; }}
  .fed {{ background: #dbeafe; color: #1e40af; }}
  .est {{ background: #e0e7ff; color: #4338ca; }}
</style></head><body>
<h1>PACTA - Relatorio de Convenios</h1>
<div class="meta">Gerado em {ddate.today().strftime('%d/%m/%Y')} | Total de registros: {len(rows)}</div>
<div class="summary"><strong>Valor Total:</strong> R$ {total_valor:,.2f}</div>
<table>
<thead><tr><th>Esfera</th><th>Numero</th><th>Orgao</th><th>Objeto</th><th>Situacao</th><th class="right">Valor</th><th>Vigencia</th></tr></thead>
<tbody>
"""
    from html import escape as _esc
    for r in rows:
        cls = "fed" if r["esfera"] == "Federal" else "est"
        html += f"""<tr>
<td><span class="badge {cls}">{_esc(r['esfera'])}</span></td>
<td>{_esc(str(r['nr'] or '-'))}</td>
<td>{_esc(str(r['orgao']))}</td>
<td>{_esc(str(r['objeto']))}</td>
<td>{_esc(str(r['situacao']))}</td>
<td class="right">R$ {r['valor']:,.2f}</td>
<td>{_esc(str(r['vigencia']))}</td>
</tr>
"""
    html += "</tbody></table></body></html>"

    return Response(
        content=html, media_type="text/html",
        headers={"Content-Disposition": "inline; filename=convenios_pacta.html"},
    )


@router.get("/pendencias")
async def export_pendencias(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Relatorio de pendencias: convenios vencendo + prestacoes em diligencia + documentos faltantes."""
    from models import PrestacaoContas, PrestacaoDocumento
    from datetime import timedelta

    wb = openpyxl.Workbook()

    # Sheet 1: Convenios vencendo
    ws1 = wb.active
    ws1.title = "Vigencias proximas"
    ws1.append(["Esfera", "Numero", "Orgao", "Objeto", "Vigencia", "Dias Restantes", "Valor", "Situacao"])

    limite = date.today() + timedelta(days=120)

    q = select(ConvenioFederal).where(
        ConvenioFederal.dt_fim_vigencia <= limite,
        ConvenioFederal.dt_fim_vigencia >= date.today(),
    )
    if municipio_id:
        q = q.where(ConvenioFederal.municipio_id == municipio_id)
    for c in (await db.execute(q)).scalars().all():
        dias = (c.dt_fim_vigencia - date.today()).days
        ws1.append([
            "Federal", c.nr_convenio, c.orgao_concedente or "-",
            (c.objeto or "")[:200], str(c.dt_fim_vigencia), dias,
            float(c.valor_global) if c.valor_global else 0, c.situacao or "-",
        ])

    q = select(ConvenioEstadual).where(
        ConvenioEstadual.dt_vigencia_atual <= limite,
        ConvenioEstadual.dt_vigencia_atual >= date.today(),
    )
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    for c in (await db.execute(q)).scalars().all():
        dias = (c.dt_vigencia_atual - date.today()).days
        ws1.append([
            "Estadual", c.nr_sigcon, c.orgao_concedente or "-",
            (c.objeto or "")[:200], str(c.dt_vigencia_atual), dias,
            float(c.valor_total) if c.valor_total else 0, c.situacao or "-",
        ])

    # Sheet 2: Documentos pendentes
    ws2 = wb.create_sheet("Documentos pendentes")
    ws2.append(["Convenio", "Etapa", "Documento", "Status"])

    q = select(PrestacaoContas, PrestacaoDocumento).join(
        PrestacaoDocumento, PrestacaoDocumento.prestacao_id == PrestacaoContas.id
    ).where(PrestacaoDocumento.enviado == False)  # noqa
    if municipio_id:
        q = q.where(PrestacaoContas.municipio_id == municipio_id)

    for prest, doc in (await db.execute(q)).all():
        ws2.append([
            f"#{prest.id}", f"{prest.etapa_atual}/16 - {prest.etapa_nome or ''}",
            doc.documento_nome, "Pendente",
        ])

    # Style headers
    from openpyxl.styles import Font, PatternFill
    for sheet in [ws1, ws2]:
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="C00000", end_color="C00000", fill_type="solid")
        for col in sheet.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            sheet.column_dimensions[col[0].column_letter].width = min(max_len + 2, 50)

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=pendencias_pacta.xlsx"},
    )


@router.get("/emendas")
async def export_emendas(
    municipio_id: Optional[int] = None,
    format: str = Query("xlsx", pattern="^(xlsx)$"),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Emendas"

    headers = ["Nr Emenda", "Parlamentar", "Partido", "Esfera", "Valor", "Ano", "Tipo", "Funcao"]
    ws.append(headers)

    q = (
        select(Emenda, Parlamentar.nome, Parlamentar.partido)
        .outerjoin(Parlamentar, Parlamentar.id == Emenda.parlamentar_id)
    )
    if municipio_id:
        q = q.where(Emenda.municipio_id == municipio_id)
    q = q.order_by(Emenda.ano.desc())

    result = await db.execute(q)
    for emenda, nome, partido in result.all():
        ws.append([
            emenda.nr_emenda, nome, partido, emenda.esfera,
            float(emenda.valor) if emenda.valor else 0,
            emenda.ano, emenda.tipo, emenda.funcao,
        ])

    from openpyxl.styles import Font, PatternFill
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=emendas_pacta.xlsx"},
    )
