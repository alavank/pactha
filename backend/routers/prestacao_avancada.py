"""
Endpoints avancados de Prestacao de Contas:
- Calculo automatico (executado vs aprovado)
- Checklist de documentos vs plano de trabalho
- Relatorio especifico de prestacao em PDF/HTML
"""
from datetime import date, datetime
from typing import Optional
from html import escape

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models import (
    PrestacaoContas, PrestacaoDocumento,
    ConvenioFederal, ConvenioEstadual, Municipio,
)
from services.auth import get_current_user

router = APIRouter(prefix="/api/prestacao", tags=["prestacao-avancada"])


# Documentos OBRIGATORIOS por tipo de convenio.
# Baseado no manual de prestacao de contas SIGCON-MG e TransfereGov.
DOCUMENTOS_PADRAO = {
    "estadual": [
        "Plano de Trabalho aprovado",
        "Termo de Convenio assinado",
        "Comprovante de abertura conta especifica",
        "Extratos bancarios mensais",
        "Notas fiscais / faturas",
        "Comprovantes de pagamento",
        "Relatorio de execucao fisico-financeira",
        "Conciliacao bancaria",
        "Termo de aceitacao do objeto (obra)",
        "Comprovante devolucao saldo (se houver)",
        "Relatorio de cumprimento do objeto",
    ],
    "federal": [
        "Plano de Trabalho aprovado",
        "Termo de Convenio assinado",
        "Comprovante de abertura conta especifica",
        "Extratos bancarios mensais",
        "Notas fiscais / faturas",
        "Comprovantes de pagamento",
        "Relatorio de execucao fisico-financeira",
        "Conciliacao bancaria",
        "Demonstrativo de execucao da receita e despesa",
        "Termo de aceitacao do objeto",
        "Comprovante devolucao saldo (se houver)",
    ],
}


def fmt_money(v):
    if v is None:
        return "R$ 0,00"
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def fmt_date(d):
    if not d:
        return "-"
    if isinstance(d, str):
        try:
            d = datetime.fromisoformat(d).date()
        except Exception:
            return d
    try:
        return d.strftime("%d/%m/%Y")
    except Exception:
        return str(d)


@router.get("/{prestacao_id}/calculo")
async def calcular_prestacao(
    prestacao_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Calcula valores executados, divergencias, % de execucao."""
    p = await db.get(PrestacaoContas, prestacao_id)
    if not p:
        raise HTTPException(status_code=404, detail="Prestacao nao encontrada")

    # Buscar dados financeiros do convenio
    valores = {}
    if p.convenio_federal_id:
        c = await db.get(ConvenioFederal, p.convenio_federal_id)
        if c:
            valores = {
                "esfera": "federal",
                "nr_convenio": c.nr_convenio,
                "objeto": c.objeto,
                "valor_global": float(c.valor_global or 0),
                "valor_repasse": float(c.valor_repasse or 0),
                "valor_contrapartida": float(c.valor_contrapartida or 0),
                "valor_empenhado": float(c.valor_empenhado or 0),
                "valor_desembolsado": float(c.valor_desembolsado or 0),
                "saldo_bancario": float(c.saldo_bancario or 0),
                "dt_inicio": c.dt_inicio,
                "dt_fim": c.dt_fim_vigencia,
            }
    elif p.convenio_estadual_id:
        c = await db.get(ConvenioEstadual, p.convenio_estadual_id)
        if c:
            valores = {
                "esfera": "estadual",
                "nr_convenio": c.nr_sigcon,
                "objeto": c.objeto,
                "valor_global": float(c.valor_total or 0),
                "valor_repasse": float(c.valor_concedente or 0),
                "valor_contrapartida": float(c.valor_contrapartida or 0),
                "valor_empenhado": float(c.valor_repassado or 0),
                "valor_desembolsado": float(c.valor_repassado or 0),
                "saldo_bancario": float(c.saldo_bancario or 0),
                "dt_inicio": c.dt_vigencia_inicial,
                "dt_fim": c.dt_vigencia_atual or c.dt_vigencia_final,
            }

    if not valores:
        raise HTTPException(status_code=404, detail="Convenio vinculado nao encontrado")

    # Calculos
    aprovado = valores["valor_global"]
    repasse = valores["valor_repasse"]
    contrapartida = valores["valor_contrapartida"]
    empenhado = valores["valor_empenhado"]
    desembolsado = valores["valor_desembolsado"]
    saldo_banco = valores["saldo_bancario"]

    # Valor executado = desembolsado - saldo bancario (o que de fato foi pago)
    executado_estimado = max(0, desembolsado - saldo_banco)

    pct_empenhado = (empenhado / aprovado * 100) if aprovado > 0 else 0
    pct_desembolsado = (desembolsado / aprovado * 100) if aprovado > 0 else 0
    pct_executado = (executado_estimado / aprovado * 100) if aprovado > 0 else 0

    divergencia_repasse = aprovado - (repasse + contrapartida)
    saldo_a_executar = desembolsado - executado_estimado

    # Vigencia
    dias_restantes = None
    if valores["dt_fim"]:
        dt_fim = valores["dt_fim"]
        if isinstance(dt_fim, str):
            dt_fim = datetime.fromisoformat(dt_fim).date()
        dias_restantes = (dt_fim - date.today()).days

    return {
        "prestacao_id": prestacao_id,
        "convenio": valores,
        "calculos": {
            "valor_aprovado": aprovado,
            "valor_empenhado": empenhado,
            "valor_desembolsado": desembolsado,
            "valor_executado_estimado": executado_estimado,
            "saldo_bancario": saldo_banco,
            "saldo_a_executar": saldo_a_executar,
            "divergencia_repasse_contrapartida": divergencia_repasse,
            "pct_empenhado": round(pct_empenhado, 2),
            "pct_desembolsado": round(pct_desembolsado, 2),
            "pct_executado": round(pct_executado, 2),
            "dias_restantes_vigencia": dias_restantes,
        },
        "alertas": _gerar_alertas(valores, executado_estimado, dias_restantes),
    }


def _gerar_alertas(valores, executado, dias_restantes):
    alertas = []
    if dias_restantes is not None:
        if dias_restantes < 0:
            alertas.append({"nivel": "critico", "msg": f"Vigencia VENCIDA ha {abs(dias_restantes)} dias"})
        elif dias_restantes < 30:
            alertas.append({"nivel": "alto", "msg": f"Vigencia vence em {dias_restantes} dias"})
        elif dias_restantes < 120:
            alertas.append({"nivel": "medio", "msg": f"Vigencia vence em {dias_restantes} dias"})

    if valores["valor_global"] > 0:
        pct = (executado / valores["valor_global"]) * 100
        if pct < 50 and dias_restantes is not None and dias_restantes < 60:
            alertas.append({"nivel": "alto", "msg": f"Apenas {pct:.0f}% executado a {dias_restantes}d do fim"})

    if valores["saldo_bancario"] > valores["valor_desembolsado"] * 0.3:
        alertas.append({"nivel": "medio", "msg": "Saldo bancario alto - >30% do desembolsado parado"})

    return alertas


@router.get("/{prestacao_id}/checklist")
async def checklist_documentos(
    prestacao_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Retorna checklist de documentos esperados vs entregues."""
    p = await db.get(PrestacaoContas, prestacao_id)
    if not p:
        raise HTTPException(status_code=404, detail="Prestacao nao encontrada")

    esfera = "federal" if p.convenio_federal_id else "estadual"
    esperados = DOCUMENTOS_PADRAO.get(esfera, DOCUMENTOS_PADRAO["estadual"])

    # Documentos ja cadastrados
    docs_q = await db.execute(
        select(PrestacaoDocumento).where(PrestacaoDocumento.prestacao_id == prestacao_id)
    )
    docs_existentes = {d.documento_nome.lower(): d for d in docs_q.scalars().all()}

    checklist = []
    for nome in esperados:
        match = docs_existentes.get(nome.lower())
        checklist.append({
            "documento": nome,
            "status": "entregue" if (match and match.enviado) else ("cadastrado" if match else "faltando"),
            "doc_id": match.id if match else None,
            "dt_envio": match.dt_envio if match else None,
            "observacao": match.observacao if match else None,
        })

    # Documentos extras (nao previstos no padrao)
    nomes_padrao_lower = [n.lower() for n in esperados]
    extras = [
        {"documento": d.documento_nome, "status": "entregue" if d.enviado else "cadastrado",
         "doc_id": d.id, "dt_envio": d.dt_envio, "observacao": d.observacao}
        for n, d in docs_existentes.items() if n not in nomes_padrao_lower
    ]

    n_total = len(esperados)
    n_entregues = sum(1 for c in checklist if c["status"] == "entregue")
    n_faltando = sum(1 for c in checklist if c["status"] == "faltando")

    return {
        "prestacao_id": prestacao_id,
        "esfera": esfera,
        "checklist": checklist,
        "extras": extras,
        "completude": {
            "total_esperados": n_total,
            "entregues": n_entregues,
            "cadastrados_pendentes": n_total - n_entregues - n_faltando,
            "faltando": n_faltando,
            "pct_completude": round(n_entregues / n_total * 100, 1) if n_total else 0,
        },
    }


@router.post("/{prestacao_id}/checklist/auto-criar")
async def auto_criar_checklist(
    prestacao_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Cria documentos faltantes do padrao (status = nao enviado)."""
    p = await db.get(PrestacaoContas, prestacao_id)
    if not p:
        raise HTTPException(status_code=404, detail="Prestacao nao encontrada")

    esfera = "federal" if p.convenio_federal_id else "estadual"
    esperados = DOCUMENTOS_PADRAO.get(esfera, DOCUMENTOS_PADRAO["estadual"])

    docs_q = await db.execute(
        select(PrestacaoDocumento).where(PrestacaoDocumento.prestacao_id == prestacao_id)
    )
    existentes = {d.documento_nome.lower() for d in docs_q.scalars().all()}

    criados = 0
    for nome in esperados:
        if nome.lower() not in existentes:
            db.add(PrestacaoDocumento(
                prestacao_id=prestacao_id,
                documento_nome=nome,
                enviado=False,
            ))
            criados += 1
    await db.commit()
    return {"criados": criados, "total_esperados": len(esperados)}


@router.get("/{prestacao_id}/relatorio")
async def gerar_relatorio_prestacao(
    prestacao_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Gera relatorio especifico de prestacao em HTML imprimivel."""
    # Busca todos os dados
    calc = await calcular_prestacao(prestacao_id, db, _)
    cl = await checklist_documentos(prestacao_id, db, _)

    p = await db.get(PrestacaoContas, prestacao_id)
    mun = await db.get(Municipio, p.municipio_id) if p.municipio_id else None
    mun_nome = mun.nome if mun else "-"

    c = calc["convenio"]
    k = calc["calculos"]

    today = date.today()

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Relatorio de Prestacao - {escape(c.get('nr_convenio') or '-')}</title>
<style>
  @page {{ size: A4; margin: 1.5cm 1.5cm 2cm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: 'Calibri', Arial, sans-serif; font-size: 10.5pt; color: #000; margin: 0; }}
  .header {{ background: #0b1f3b; color: #fff; padding: 22px 24px; margin-bottom: 18px; border-radius: 4px; }}
  .header h1 {{ margin: 0; font-size: 16pt; }}
  .header .sub {{ font-size: 10pt; opacity: 0.9; margin-top: 4px; }}
  h2.sec {{ font-size: 12pt; color: #1f4e79; border-bottom: 2px solid #1f4e79; padding-bottom: 4px; margin: 22px 0 10px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 9.5pt; }}
  th {{ background: #4472c4; color: #fff; padding: 8px; text-align: left; font-weight: 600; }}
  td {{ padding: 6px 8px; border-bottom: 1px solid #e5e7eb; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 10px 0; }}
  .box {{ border: 1px solid #cfd8e3; border-radius: 4px; padding: 10px 12px; background: #f8fafc; }}
  .box .lbl {{ font-size: 9pt; color: #5a6b7f; }}
  .box .val {{ font-size: 13pt; font-weight: bold; color: #0b1f3b; margin-top: 3px; }}
  .alerta {{ padding: 10px; border-radius: 4px; margin: 6px 0; font-size: 10pt; }}
  .alerta.critico {{ background: #fee2e2; color: #991b1b; border-left: 3px solid #dc2626; }}
  .alerta.alto {{ background: #fef3c7; color: #92400e; border-left: 3px solid #d97706; }}
  .alerta.medio {{ background: #dbeafe; color: #1e40af; border-left: 3px solid #2563eb; }}
  .check {{ width: 16px; display: inline-block; }}
  .ok {{ color: #16a34a; font-weight: bold; }}
  .pendente {{ color: #d97706; }}
  .faltando {{ color: #dc2626; font-weight: bold; }}
  .footer {{ position: fixed; bottom: 0.6cm; left: 0; right: 0; text-align: center; font-size: 8pt; color: #666; }}
</style>
</head>
<body>

<div class="header">
  <h1>RELATORIO DE PRESTACAO DE CONTAS</h1>
  <div class="sub">{escape(mun_nome)}/MG &middot; Convenio {escape(c.get('nr_convenio') or '-')} &middot; Emitido em {today.strftime('%d/%m/%Y')}</div>
</div>

<h2 class="sec">1. Identificacao do Convenio</h2>
<table>
  <tr><th style="width:30%">Numero do Convenio</th><td>{escape(str(c.get('nr_convenio') or '-'))}</td></tr>
  <tr><th>Esfera</th><td>{escape(c['esfera'].upper())}</td></tr>
  <tr><th>Objeto</th><td>{escape(str(c.get('objeto') or '-'))[:500]}</td></tr>
  <tr><th>Vigencia</th><td>{fmt_date(c.get('dt_inicio'))} ate {fmt_date(c.get('dt_fim'))}</td></tr>
</table>

<h2 class="sec">2. Resumo Financeiro</h2>
<div class="grid">
  <div class="box"><div class="lbl">Valor Aprovado</div><div class="val">{fmt_money(k['valor_aprovado'])}</div></div>
  <div class="box"><div class="lbl">Valor Empenhado ({k['pct_empenhado']:.1f}%)</div><div class="val">{fmt_money(k['valor_empenhado'])}</div></div>
  <div class="box"><div class="lbl">Valor Desembolsado ({k['pct_desembolsado']:.1f}%)</div><div class="val">{fmt_money(k['valor_desembolsado'])}</div></div>
  <div class="box"><div class="lbl">Valor Executado ({k['pct_executado']:.1f}%)</div><div class="val">{fmt_money(k['valor_executado_estimado'])}</div></div>
  <div class="box"><div class="lbl">Saldo Bancario</div><div class="val">{fmt_money(k['saldo_bancario'])}</div></div>
  <div class="box"><div class="lbl">Saldo a Executar</div><div class="val">{fmt_money(k['saldo_a_executar'])}</div></div>
</div>

<h2 class="sec">3. Alertas</h2>
"""
    if calc["alertas"]:
        for a in calc["alertas"]:
            html += f'<div class="alerta {escape(a["nivel"])}"><strong>[{a["nivel"].upper()}]</strong> {escape(a["msg"])}</div>'
    else:
        html += '<p style="color: #16a34a;">Nenhum alerta - prestacao em conformidade.</p>'

    html += f"""
<h2 class="sec">4. Checklist de Documentos ({cl['completude']['entregues']}/{cl['completude']['total_esperados']} entregues - {cl['completude']['pct_completude']}%)</h2>
<table>
  <thead><tr><th style="width:50px">Status</th><th>Documento</th><th style="width:100px">Data Envio</th><th>Observacao</th></tr></thead>
  <tbody>
"""
    icons = {"entregue": '<span class="ok">[X]</span>', "cadastrado": '<span class="pendente">[~]</span>', "faltando": '<span class="faltando">[!]</span>'}
    for item in cl["checklist"]:
        st = item["status"]
        html += (
            f'<tr>'
            f'<td>{icons.get(st, "[ ]")}</td>'
            f'<td>{escape(item["documento"])}</td>'
            f'<td>{fmt_date(item["dt_envio"])}</td>'
            f'<td>{escape(str(item.get("observacao") or ""))}</td>'
            f'</tr>'
        )
    html += "</tbody></table>"

    if cl["extras"]:
        html += '<h3 style="font-size:11pt;color:#1f4e79;margin-top:14px;">Documentos adicionais</h3><table><tbody>'
        for item in cl["extras"]:
            st = item["status"]
            html += f'<tr><td style="width:50px">{icons.get(st)}</td><td>{escape(item["documento"])}</td><td>{fmt_date(item["dt_envio"])}</td></tr>'
        html += "</tbody></table>"

    html += f"""
<h2 class="sec">5. Status da Prestacao</h2>
<table>
  <tr><th style="width:30%">Etapa Atual</th><td>{p.etapa_atual} - {escape(p.etapa_nome or '-')}</td></tr>
  <tr><th>Status</th><td>{escape(p.status or '-')}</td></tr>
  <tr><th>Observacoes</th><td>{escape(p.observacoes or '-')}</td></tr>
</table>

<div class="footer">
  Freitas &amp; Associados &middot; PACTA &middot; Emitido em {today.strftime('%d/%m/%Y')}
</div>
</body>
</html>
"""

    fname = f"Prestacao_{c.get('nr_convenio', 'sem_nr')}_{today.strftime('%d-%m-%Y')}.html"
    return Response(content=html, media_type="text/html; charset=utf-8",
                    headers={"Content-Disposition": f'inline; filename="{fname}"'})
