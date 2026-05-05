"""
Upload manual de CSV/XLSX para fontes sem API publica.
Suporta: FNS, SIMEC, SISMOB, SUAS.

Template CSV esperado:
  nr_convenio,orgao_concedente,objeto,situacao,valor_total,dt_inicio,dt_fim_vigencia,municipio_ibge

Template XLSX com mesmas colunas.
"""
import io
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from datetime import datetime
import pandas as pd

from database import get_db
from models import ConvenioFederal, Municipio
from services.auth import get_current_user

router = APIRouter(prefix="/api/upload", tags=["upload"])


FONTES_VALIDAS = ["FNS", "InvestSUS", "SIMEC", "SISMOB", "Estrutura SUAS", "CIMEC", "Outros"]

TEMPLATE_COLUMNS = [
    "nr_convenio",
    "orgao_concedente",
    "objeto",
    "situacao",
    "valor_global",
    "valor_repasse",
    "valor_contrapartida",
    "dt_inicio",
    "dt_fim_vigencia",
    "municipio_ibge",
    "ano",
    "parlamentar_indicacao",
    "tipo_programa",
    "banco",
    "agencia",
    "conta_corrente",
    "saldo_bancario",
    "dt_saldo",
    "nr_sei",
    "dt_empenho",
    "dt_desembolso",
]


def parse_date(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v.date()
    s = str(v).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


def parse_decimal(v):
    if v is None or str(v).strip() == "":
        return None
    s = str(v).strip().replace("R$", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


@router.get("/template")
async def download_template(
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
    _=Depends(get_current_user),
):
    """Baixa template de upload (csv ou xlsx)."""
    example1 = {
        "nr_convenio": "989480/2025",
        "orgao_concedente": "Ministerio da Saude",
        "objeto": "Cama Hospitalar Tipo Fawler Eletrica",
        "situacao": "Empenhado",
        "valor_global": "200800.00",
        "valor_repasse": "200800.00",
        "valor_contrapartida": "0",
        "dt_inicio": "2025-12-18",
        "dt_fim_vigencia": "2026-04-21",
        "municipio_ibge": "3107406",
        "ano": "2025",
        "parlamentar_indicacao": "Domingos Savio",
        "tipo_programa": "Incremento MAC",
        "banco": "Caixa Economica Federal",
        "agencia": "1060-0",
        "conta_corrente": "574194984-0",
        "saldo_bancario": "0.00",
        "dt_saldo": "2026-04-10",
        "nr_sei": "",
        "dt_empenho": "2025-12-18",
        "dt_desembolso": "",
    }
    df = pd.DataFrame([example1])

    if format == "csv":
        output = io.StringIO()
        df.to_csv(output, index=False, sep=";", encoding="utf-8")
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode("utf-8-sig")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=template_upload_pacta.csv"},
        )
    else:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Convenios")
        output.seek(0)
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=template_upload_pacta.xlsx"},
        )


@router.post("/convenios")
async def upload_convenios(
    file: UploadFile = File(...),
    fonte: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Upload CSV/XLSX com convenios de fontes externas (FNS, SIMEC, etc)."""
    if fonte not in FONTES_VALIDAS:
        raise HTTPException(status_code=400, detail=f"Fonte deve ser uma de: {FONTES_VALIDAS}")

    content = await file.read()
    filename = file.filename.lower() if file.filename else ""

    try:
        if filename.endswith(".csv"):
            try:
                df = pd.read_csv(io.BytesIO(content), sep=";", encoding="utf-8-sig", dtype=str)
            except Exception:
                df = pd.read_csv(io.BytesIO(content), sep=",", encoding="utf-8-sig", dtype=str)
        elif filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(content), dtype=str)
        else:
            raise HTTPException(status_code=400, detail="Formato deve ser CSV ou XLSX")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao ler arquivo: {e}")

    # Normalize column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Get municipio mapping
    mun_result = await db.execute(select(Municipio))
    mun_by_ibge = {m.ibge_code: m.id for m in mun_result.scalars().all()}

    inserted = 0
    errors = []

    for idx, row in df.iterrows():
        try:
            ibge = str(row.get("municipio_ibge", "")).strip()
            if not ibge or ibge not in mun_by_ibge:
                errors.append(f"Linha {idx+2}: IBGE '{ibge}' nao encontrado")
                continue

            nr = str(row.get("nr_convenio", "")).strip() or f"UPLOAD-{fonte}-{idx}"

            # Check if exists
            from sqlalchemy import select as sqlselect
            existing = await db.execute(
                sqlselect(ConvenioFederal).where(ConvenioFederal.nr_convenio == nr)
            )
            exists = existing.scalar_one_or_none()

            data = {
                "nr_convenio": nr,
                "municipio_id": mun_by_ibge[ibge],
                "orgao_concedente": str(row.get("orgao_concedente", "") or "")[:500],
                "objeto": str(row.get("objeto", "") or "")[:2000],
                "situacao": str(row.get("situacao", "") or "")[:200],
                "valor_global": parse_decimal(row.get("valor_global") or row.get("valor_total")),
                "valor_repasse": parse_decimal(row.get("valor_repasse")),
                "valor_contrapartida": parse_decimal(row.get("valor_contrapartida")),
                "dt_inicio": parse_date(row.get("dt_inicio")),
                "dt_fim_vigencia": parse_date(row.get("dt_fim_vigencia")),
                "ano": int(row["ano"]) if row.get("ano") and str(row["ano"]).strip().isdigit() else None,
                "fonte": fonte,
                "tipo_programa": str(row.get("tipo_programa", "") or "")[:100] or None,
                "banco": str(row.get("banco", "") or "")[:100] or None,
                "agencia": str(row.get("agencia", "") or "")[:20] or None,
                "conta_corrente": str(row.get("conta_corrente", "") or "")[:50] or None,
                "saldo_bancario": parse_decimal(row.get("saldo_bancario")),
                "dt_saldo": parse_date(row.get("dt_saldo")),
                "nr_sei": str(row.get("nr_sei", "") or "")[:100] or None,
                "dt_empenho": parse_date(row.get("dt_empenho")),
                "dt_desembolso": parse_date(row.get("dt_desembolso")),
            }

            if exists:
                for k, v in data.items():
                    if k != "nr_convenio":
                        setattr(exists, k, v)
            else:
                db.add(ConvenioFederal(**data))

            inserted += 1
        except Exception as e:
            errors.append(f"Linha {idx+2}: {str(e)[:100]}")

    await db.commit()

    return {
        "inseridos": inserted,
        "fonte": fonte,
        "erros": errors[:20],
        "total_erros": len(errors),
    }


@router.get("/fontes-upload")
async def list_fontes_upload():
    """Lista fontes disponiveis para upload manual."""
    return FONTES_VALIDAS
