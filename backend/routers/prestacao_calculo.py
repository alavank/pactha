"""
Frente 1 da PR: Calculo automatico de prestacao de contas (NF x Plano de Trabalho).

Atende a dor da Marcia (1-2h por prestacao manual em Excel).

Fluxo:
1. POST /prestacao-calculo/{prestacao_id}/plano (XLSX) -> popula itens do plano
2. POST /prestacao-calculo/{prestacao_id}/notas (XLSX) -> popula NFs entregues pelo cliente
3. POST /prestacao-calculo/{prestacao_id}/auto-link -> tenta linkar NF -> item plano por descricao/fornecedor
4. GET  /prestacao-calculo/{prestacao_id}/comparativo -> JSON com % executado por item, saldo, alertas
5. GET  /prestacao-calculo/{prestacao_id}/comparativo-xlsx -> Excel pronto pra revisar
"""
import io
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from database import get_db
from models import PrestacaoContas, PlanoTrabalho, NotaFiscal, ConvenioFederal, ConvenioEstadual, Municipio
from services.auth import get_current_user

router = APIRouter(prefix="/api/prestacao-calculo", tags=["prestacao"])


def _norm(s):
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFKD", str(s).upper())
                   if not unicodedata.combining(c)).strip()


def _parse_money(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    s = str(v).strip().replace("R$", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def _parse_date(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v.date()
    if hasattr(v, "year"):  # already date
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


# ===================== TEMPLATES =====================
@router.get("/template-plano-xlsx")
async def template_plano(_=Depends(get_current_user)):
    """Baixa template XLSX do plano de trabalho."""
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = "Plano"
    headers = ["item", "categoria", "quantidade", "valor_unitario",
               "valor_planejado", "observacao"]
    for i, h in enumerate(headers, 1): ws.cell(1, i, h)
    # Exemplo
    ws.append(["Aquisicao de UBS Movel", "Material Permanente", 1, 250000, 250000, ""])
    ws.append(["Manutencao predial", "Servico Terceiros", 12, 5000, 60000, "Mensal por 12 meses"])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="template_plano_trabalho.xlsx"'},
    )


@router.get("/template-nf-xlsx")
async def template_nf(_=Depends(get_current_user)):
    """Baixa template XLSX das notas fiscais."""
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = "Notas"
    headers = ["nf_numero", "nf_serie", "fornecedor_nome", "fornecedor_cnpj",
               "descricao", "valor", "dt_emissao", "dt_pagamento"]
    for i, h in enumerate(headers, 1): ws.cell(1, i, h)
    ws.append(["12345", "1", "Hospitalar XPTO LTDA", "12345678000190",
               "Aquisicao de UBS Movel", 250000, "2026-03-15", "2026-04-10"])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="template_notas_fiscais.xlsx"'},
    )


# ===================== UPLOADS =====================
@router.post("/{prestacao_id}/plano")
async def upload_plano(
    prestacao_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Upload XLSX com itens do plano de trabalho aprovado."""
    pres = await db.get(PrestacaoContas, prestacao_id)
    if not pres:
        raise HTTPException(404, "Prestacao nao encontrada")
    import pandas as pd
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "Arquivo > 10 MB")
    try:
        df = pd.read_excel(io.BytesIO(content), dtype=object)
    except Exception as e:
        raise HTTPException(400, f"Falha ao ler XLSX: {e}")

    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    if "valor_planejado" not in df.columns:
        raise HTTPException(400, "Coluna 'valor_planejado' obrigatoria")

    # Substituir todos os itens deste plano
    await db.execute(text("DELETE FROM plano_trabalho WHERE prestacao_id=:p"), {"p": prestacao_id})

    inserted = 0
    for _, row in df.iterrows():
        item = str(row.get("item") or "").strip()
        valor = _parse_money(row.get("valor_planejado"))
        if not item or valor is None:
            continue
        await db.execute(text("""
            INSERT INTO plano_trabalho
              (prestacao_id, item, categoria, quantidade, valor_unitario, valor_planejado, observacao)
            VALUES (:p, :i, :c, :q, :vu, :vp, :o)
        """), {
            "p": prestacao_id, "i": item[:500],
            "c": str(row.get("categoria") or "")[:100] or None,
            "q": _parse_money(row.get("quantidade")),
            "vu": _parse_money(row.get("valor_unitario")),
            "vp": valor,
            "o": str(row.get("observacao") or "") or None,
        })
        inserted += 1
    await db.commit()
    return {"prestacao_id": prestacao_id, "itens_inseridos": inserted}


@router.post("/{prestacao_id}/notas")
async def upload_notas(
    prestacao_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Upload XLSX com NFs entregues pelo cliente."""
    pres = await db.get(PrestacaoContas, prestacao_id)
    if not pres:
        raise HTTPException(404, "Prestacao nao encontrada")
    import pandas as pd
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "Arquivo > 10 MB")
    try:
        df = pd.read_excel(io.BytesIO(content), dtype=object)
    except Exception as e:
        raise HTTPException(400, f"Falha ao ler XLSX: {e}")

    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    if "valor" not in df.columns:
        raise HTTPException(400, "Coluna 'valor' obrigatoria")

    # Substituir NFs nao validadas (mantém as ja validadas por seguranca)
    await db.execute(text(
        "DELETE FROM notas_fiscais WHERE prestacao_id=:p AND validada = FALSE"
    ), {"p": prestacao_id})

    inserted = 0
    for _, row in df.iterrows():
        valor = _parse_money(row.get("valor"))
        if valor is None:
            continue
        await db.execute(text("""
            INSERT INTO notas_fiscais
              (prestacao_id, nf_numero, nf_serie, fornecedor_nome, fornecedor_cnpj,
               descricao, valor, dt_emissao, dt_pagamento)
            VALUES (:p, :n, :s, :fn, :fc, :d, :v, :de, :dp)
        """), {
            "p": prestacao_id,
            "n": str(row.get("nf_numero") or "")[:50] or None,
            "s": str(row.get("nf_serie") or "")[:20] or None,
            "fn": str(row.get("fornecedor_nome") or "")[:300] or None,
            "fc": re.sub(r"\D", "", str(row.get("fornecedor_cnpj") or ""))[:20] or None,
            "d": str(row.get("descricao") or "") or None,
            "v": valor,
            "de": _parse_date(row.get("dt_emissao")),
            "dp": _parse_date(row.get("dt_pagamento")),
        })
        inserted += 1
    await db.commit()
    return {"prestacao_id": prestacao_id, "notas_inseridas": inserted}


# ===================== AUTO-LINK NF -> ITEM =====================
@router.post("/{prestacao_id}/auto-link")
async def auto_link(
    prestacao_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Tenta vincular cada NF a um item do plano por similaridade
    (descricao bate com palavras do item OU valor exato). NFs ja vinculadas
    manualmente nao sao tocadas."""
    plano = (await db.execute(
        select(PlanoTrabalho).where(PlanoTrabalho.prestacao_id == prestacao_id)
    )).scalars().all()
    if not plano:
        raise HTTPException(400, "Plano de trabalho vazio - faca upload primeiro")

    nfs = (await db.execute(
        select(NotaFiscal)
        .where(NotaFiscal.prestacao_id == prestacao_id)
        .where(NotaFiscal.plano_item_id.is_(None))
    )).scalars().all()

    items_idx = []
    for it in plano:
        words = set(_norm(it.item).split()) - {"DE","DA","DO","DOS","DAS","E","COM","PARA"}
        items_idx.append((it.id, words, float(it.valor_planejado or 0)))

    linked = 0
    for nf in nfs:
        desc = _norm(f"{nf.descricao or ''} {nf.fornecedor_nome or ''}")
        nf_words = set(desc.split()) - {"DE","DA","DO","DOS","DAS","E","COM","PARA"}
        valor = float(nf.valor or 0)

        best = None; best_score = 0
        for iid, iwords, iv in items_idx:
            if not iwords: continue
            common = iwords & nf_words
            score = len(common) / max(len(iwords), 1)
            # Bonus se valor da NF == valor planejado (item unico)
            if iv > 0 and abs(valor - iv) / iv < 0.05:
                score += 0.5
            if score > best_score:
                best = iid; best_score = score

        if best and best_score >= 0.4:
            await db.execute(text(
                "UPDATE notas_fiscais SET plano_item_id=:i WHERE id=:n"
            ), {"i": best, "n": nf.id})
            linked += 1
    await db.commit()
    return {"prestacao_id": prestacao_id, "nfs_linkadas": linked, "nfs_orfas": len(nfs) - linked}


# ===================== COMPARATIVO =====================
async def _build_comparativo(prestacao_id: int, db: AsyncSession):
    """Monta estrutura de comparativo NF x plano."""
    pres = await db.get(PrestacaoContas, prestacao_id)
    if not pres:
        raise HTTPException(404, "Prestacao nao encontrada")

    # Convenio info
    conv_info = {}
    if pres.convenio_federal_id:
        cf = await db.get(ConvenioFederal, pres.convenio_federal_id)
        if cf:
            conv_info = {"esfera": "federal", "nr": cf.nr_convenio,
                         "objeto": cf.objeto, "valor_global": float(cf.valor_global or 0)}
    elif pres.convenio_estadual_id:
        ce = await db.get(ConvenioEstadual, pres.convenio_estadual_id)
        if ce:
            conv_info = {"esfera": "estadual", "nr": ce.nr_sigcon,
                         "objeto": ce.objeto, "valor_global": float(ce.valor_total or 0)}

    plano = (await db.execute(
        select(PlanoTrabalho).where(PlanoTrabalho.prestacao_id == prestacao_id)
        .order_by(PlanoTrabalho.id)
    )).scalars().all()
    nfs = (await db.execute(
        select(NotaFiscal).where(NotaFiscal.prestacao_id == prestacao_id)
    )).scalars().all()

    # Agrupar NFs por item
    nfs_por_item = {}
    nfs_orfas = []
    for nf in nfs:
        if nf.plano_item_id:
            nfs_por_item.setdefault(nf.plano_item_id, []).append(nf)
        else:
            nfs_orfas.append(nf)

    itens = []
    total_planejado = 0; total_executado = 0
    for it in plano:
        nfs_it = nfs_por_item.get(it.id, [])
        executado = sum(float(n.valor or 0) for n in nfs_it)
        planejado = float(it.valor_planejado or 0)
        saldo = planejado - executado
        pct = (executado / planejado * 100) if planejado else 0
        alertas = []
        if executado > planejado * 1.05:
            alertas.append(f"EXCESSO: NFs somam R$ {executado:,.2f} > planejado R$ {planejado:,.2f}")
        if executado < planejado * 0.5 and planejado > 0:
            alertas.append("Execucao abaixo de 50%")
        if not nfs_it:
            alertas.append("Sem NFs")
        itens.append({
            "item_id": it.id, "item": it.item, "categoria": it.categoria,
            "valor_planejado": planejado, "valor_executado": executado,
            "saldo": saldo, "pct_execucao": round(pct, 1),
            "qtd_nfs": len(nfs_it),
            "nfs": [{"id": n.id, "nf_numero": n.nf_numero, "fornecedor": n.fornecedor_nome,
                     "valor": float(n.valor or 0), "dt_emissao": n.dt_emissao,
                     "validada": n.validada} for n in nfs_it],
            "alertas": alertas,
        })
        total_planejado += planejado; total_executado += executado

    return {
        "prestacao_id": prestacao_id,
        "convenio": conv_info,
        "totais": {
            "planejado": total_planejado, "executado": total_executado,
            "saldo": total_planejado - total_executado,
            "pct_execucao": round(total_executado / total_planejado * 100, 1) if total_planejado else 0,
        },
        "itens": itens,
        "nfs_orfas": [{"id": n.id, "nf_numero": n.nf_numero, "valor": float(n.valor or 0),
                        "fornecedor": n.fornecedor_nome, "descricao": n.descricao}
                       for n in nfs_orfas],
        "soma_nfs_orfas": sum(float(n.valor or 0) for n in nfs_orfas),
    }


@router.get("/{prestacao_id}/comparativo")
async def get_comparativo(
    prestacao_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """JSON com comparativo NF x plano por item."""
    return await _build_comparativo(prestacao_id, db)


@router.get("/{prestacao_id}/comparativo-xlsx")
async def get_comparativo_xlsx(
    prestacao_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Excel com comparativo NF x plano formatado para revisao da Marcia."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    data = await _build_comparativo(prestacao_id, db)

    wb = Workbook()
    ws = wb.active; ws.title = "Comparativo"
    bold_white = Font(bold=True, color="FFFFFF")
    fill_header = PatternFill("solid", start_color="0B1F3B")
    border = Border(*[Side(style="thin", color="CCCCCC")]*4)

    # Cabecalho
    headers = ["#", "Item", "Categoria", "Planejado R$", "Executado R$",
               "Saldo R$", "% Exec", "Qtd NFs", "Alertas"]
    for i, h in enumerate(headers, 1):
        c = ws.cell(1, i, h); c.font = bold_white; c.fill = fill_header
        c.alignment = Alignment(horizontal="center", wrap_text=True); c.border = border

    row = 2
    for idx, it in enumerate(data["itens"], 1):
        ws.cell(row, 1, idx)
        ws.cell(row, 2, it["item"])
        ws.cell(row, 3, it["categoria"] or "-")
        ws.cell(row, 4, it["valor_planejado"]).number_format = 'R$ #,##0.00'
        ws.cell(row, 5, it["valor_executado"]).number_format = 'R$ #,##0.00'
        ws.cell(row, 6, it["saldo"]).number_format = 'R$ #,##0.00'
        ws.cell(row, 7, it["pct_execucao"]).number_format = '0.0"%"'
        ws.cell(row, 8, it["qtd_nfs"])
        ws.cell(row, 9, "; ".join(it["alertas"]))
        # Highlight alertas
        if "EXCESSO" in (ws.cell(row, 9).value or ""):
            for c in range(1, 10):
                ws.cell(row, c).fill = PatternFill("solid", start_color="FFCCCC")
        elif "Sem NFs" in (ws.cell(row, 9).value or ""):
            for c in range(1, 10):
                ws.cell(row, c).fill = PatternFill("solid", start_color="FFF4CC")
        row += 1

    # Linha total
    t = data["totais"]
    ws.cell(row, 2, "TOTAL").font = Font(bold=True)
    ws.cell(row, 4, t["planejado"]).number_format = 'R$ #,##0.00'
    ws.cell(row, 5, t["executado"]).number_format = 'R$ #,##0.00'
    ws.cell(row, 6, t["saldo"]).number_format = 'R$ #,##0.00'
    ws.cell(row, 7, t["pct_execucao"]).number_format = '0.0"%"'
    for c in range(1, 10):
        ws.cell(row, c).fill = PatternFill("solid", start_color="0B1F3B")
        ws.cell(row, c).font = Font(bold=True, color="FFFFFF")

    widths = [4, 50, 20, 14, 14, 14, 8, 8, 40]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64+i)].width = w

    # Aba 2: NFs orfas
    ws2 = wb.create_sheet("NFs Sem Vinculo")
    ws2.cell(1, 1, "NFs sem item de plano vinculado").font = Font(bold=True, size=12)
    ws2.cell(2, 1, f"Soma R$ {data['soma_nfs_orfas']:,.2f}").font = Font(bold=True)
    headers2 = ["NF", "Fornecedor", "Descricao", "Valor"]
    for i, h in enumerate(headers2, 1):
        c = ws2.cell(4, i, h); c.font = bold_white; c.fill = fill_header
    for r, nf in enumerate(data["nfs_orfas"], 5):
        ws2.cell(r, 1, nf["nf_numero"] or "-")
        ws2.cell(r, 2, nf["fornecedor"] or "-")
        ws2.cell(r, 3, (nf["descricao"] or "-")[:200])
        ws2.cell(r, 4, nf["valor"]).number_format = 'R$ #,##0.00'
    for col, w in enumerate([15, 35, 50, 14], 1):
        ws2.column_dimensions[chr(64+col)].width = w

    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    fname = f"comparativo_prestacao_{prestacao_id}_{date.today().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ===================== VALIDACAO MANUAL =====================
@router.put("/nf/{nf_id}/validar")
async def validar_nf(
    nf_id: int,
    validada: bool = True,
    obs: str = "",
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Marca uma NF como validada (ou desfaz)."""
    nf = await db.get(NotaFiscal, nf_id)
    if not nf:
        raise HTTPException(404, "NF nao encontrada")
    nf.validada = validada
    nf.obs_validacao = obs[:500] if obs else None
    await db.commit()
    return {"id": nf_id, "validada": validada}


@router.put("/nf/{nf_id}/vincular/{plano_item_id}")
async def vincular_nf(
    nf_id: int,
    plano_item_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Vincula NF a um item especifico do plano (override do auto-link)."""
    nf = await db.get(NotaFiscal, nf_id)
    if not nf:
        raise HTTPException(404, "NF nao encontrada")
    item = await db.get(PlanoTrabalho, plano_item_id)
    if not item:
        raise HTTPException(404, "Item do plano nao encontrado")
    nf.plano_item_id = plano_item_id
    await db.commit()
    return {"id": nf_id, "plano_item_id": plano_item_id}
