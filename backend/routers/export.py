from fastapi import APIRouter, Depends, Query
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
    format: str = Query("xlsx", regex="^(xlsx)$"),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
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


@router.get("/emendas")
async def export_emendas(
    municipio_id: Optional[int] = None,
    format: str = Query("xlsx", regex="^(xlsx)$"),
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
