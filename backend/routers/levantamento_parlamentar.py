"""
Gerador de Levantamento de Indicacoes por Parlamentar.
Identico ao modelo Freitas (PDF Piracema/MG 2022-2026).

Estrutura:
- Cabecalho com municipio, periodo e KPIs
- Resumo por parlamentar (qtd, total repasse, situacao predominante)
- Detalhamento por parlamentar (objeto, ano, orgao, valor, situacao)
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import date
from typing import Optional
from collections import Counter, defaultdict

from database import get_db
from models import ConvenioFederal, ConvenioEstadual, Municipio, Emenda, Parlamentar
from services.auth import get_current_user

router = APIRouter(prefix="/api/levantamento-parlamentar", tags=["relatorio"])

MESES_PT = {
    1: "Janeiro", 2: "Fevereiro", 3: "Marco", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


def fmt_money(v):
    if v is None:
        return "R$ 0,00"
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def situacao_class(sit: str) -> str:
    """Retorna classe CSS baseada na situacao."""
    s = (sit or "").lower()
    if any(k in s for k in ["pago", "concluido", "concluído", "aprovada", "execuc"]):
        return "sit-pago"
    if any(k in s for k in ["entregue", "executado"]):
        return "sit-entregue"
    if any(k in s for k in ["analise", "análise", "elabora"]):
        return "sit-analise"
    if any(k in s for k in ["pendente", "proposta"]):
        return "sit-pendente"
    if "promessa" in s:
        return "sit-promessa"
    if any(k in s for k in ["anulado", "cancelado", "rescindido"]):
        return "sit-cancelado"
    return "sit-default"


def normaliza_situacao(sit: str) -> str:
    """Mapeia situacao do banco para rotulo do relatorio."""
    if not sit:
        return "-"
    s = sit.lower()
    if "pago" in s or "concluido" in s or "concluído" in s:
        return "Pago"
    if "entregue" in s:
        return "Entregue"
    if "analise" in s or "análise" in s:
        return "Em analise"
    if "pendente" in s or "proposta" in s:
        return "Pendente"
    if "promessa" in s:
        return "Promessa"
    if "anulado" in s or "cancelado" in s:
        return "Cancelado"
    if "execuc" in s or "vigor" in s:
        return "Pago"
    return sit.capitalize()


@router.get("")
async def gerar_levantamento_parlamentar(
    municipio_id: int,
    ano_inicio: Optional[int] = None,
    ano_fim: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Gera levantamento de indicacoes agrupado por parlamentar."""
    mun = await db.get(Municipio, municipio_id)
    if not mun:
        raise HTTPException(status_code=404, detail="Municipio nao encontrado")

    # Default: ultimos 5 anos completos (corresponde ao escopo Freitas 2022-2026).
    # Sem isso, a API trazia indicacoes 2009-2018 (ex.: "RELATOR GERAL" R$ 4M/2018)
    # que polui o relatorio.
    today_year = date.today().year
    if ano_inicio is None:
        ano_inicio = today_year - 4
    if ano_fim is None:
        ano_fim = today_year

    # Carregar todos os convenios
    fed_q = await db.execute(
        select(ConvenioFederal).where(ConvenioFederal.municipio_id == municipio_id)
    )
    federais = {c.id: c for c in fed_q.scalars().all()}

    est_q = await db.execute(
        select(ConvenioEstadual).where(ConvenioEstadual.municipio_id == municipio_id)
    )
    estaduais = {c.id: c for c in est_q.scalars().all()}

    # Carregar emendas com parlamentar
    em_q = await db.execute(
        select(Emenda, Parlamentar.nome)
        .select_from(Emenda.__table__.join(
            Parlamentar.__table__, Emenda.parlamentar_id == Parlamentar.id
        ))
        .where(Emenda.municipio_id == municipio_id)
    )
    emendas_raw = em_q.all()

    def get_real_year(c, esfera, fallback_ano=None):
        """Retorna ano real do convenio. Estaduais SIGCON tem ano partition off,
        usar dt_publicacao quando disponivel."""
        if esfera == "estadual":
            dp = getattr(c, "dt_publicacao", None)
            if dp:
                return dp.year
        a = getattr(c, "ano", None) or fallback_ano
        # SIGCON ano_particao 2050+ corresponde a 2020+
        if a and a >= 2050:
            return a - 30
        return a

    # Construir lista de indicacoes (linhas do relatorio)
    indicacoes = []  # cada item: dict(parlamentar, objeto, ano, orgao, valor, situacao, esfera)

    convenios_com_emenda_fed = set()
    convenios_com_emenda_est = set()

    for em, parl_nome in emendas_raw:
        c = None
        esfera = None
        if em.convenio_federal_id and em.convenio_federal_id in federais:
            c = federais[em.convenio_federal_id]
            esfera = "federal"
            convenios_com_emenda_fed.add(c.id)
        elif em.convenio_estadual_id and em.convenio_estadual_id in estaduais:
            c = estaduais[em.convenio_estadual_id]
            esfera = "estadual"
            convenios_com_emenda_est.add(c.id)

        # ano real (SIGCON ano_particao corrigido)
        ano = get_real_year(c, esfera, em.ano) if c else em.ano

        # filtro de ano
        if ano_inicio and ano and ano < ano_inicio:
            continue
        if ano_fim and ano and ano > ano_fim:
            continue

        if c is None:
            # emenda sem convenio vinculado, ainda assim conta como indicacao
            indicacoes.append({
                "parlamentar": parl_nome or "Nao identificado",
                "objeto": (em.tipo or "Indicacao parlamentar"),
                "ano": ano or "",
                "orgao": em.funcao or "-",
                "valor": float(em.valor or 0),
                "situacao": "Pendente",
                "esfera": em.esfera or "federal",
            })
            continue

        if esfera == "federal":
            objeto = (c.objeto or "-")[:200]
            orgao = c.orgao_concedente or c.programa or "Min. Fazenda"
            valor = float(em.valor or c.valor_repasse or c.valor_global or 0)
            sit = c.situacao or "-"
        else:
            objeto = (c.objeto or c.objetivo or "-")[:200]
            orgao = c.orgao_concedente or "SES - MG"
            valor = float(em.valor or c.valor_concedente or c.valor_total or 0)
            sit = c.situacao or "-"

        indicacoes.append({
            "parlamentar": parl_nome or "Nao identificado",
            "objeto": objeto,
            "ano": ano or "",
            "orgao": orgao,
            "valor": valor,
            "situacao": normaliza_situacao(sit),
            "esfera": esfera,
        })

    # Convenios SEM emenda vinculada -> agrupar como "Sem indicacao identificada"
    for c in federais.values():
        if c.id in convenios_com_emenda_fed:
            continue
        ano = get_real_year(c, "federal")
        if ano_inicio and ano and ano < ano_inicio:
            continue
        if ano_fim and ano and ano > ano_fim:
            continue
        indicacoes.append({
            "parlamentar": "Sem indicacao identificada",
            "objeto": (c.objeto or "-")[:200],
            "ano": ano or "",
            "orgao": c.orgao_concedente or c.programa or "-",
            "valor": float(c.valor_repasse or c.valor_global or 0),
            "situacao": normaliza_situacao(c.situacao or ""),
            "esfera": "federal",
        })

    for c in estaduais.values():
        if c.id in convenios_com_emenda_est:
            continue
        ano = get_real_year(c, "estadual")
        if ano_inicio and ano and ano < ano_inicio:
            continue
        if ano_fim and ano and ano > ano_fim:
            continue
        indicacoes.append({
            "parlamentar": "Sem indicacao identificada",
            "objeto": (c.objeto or c.objetivo or "-")[:200],
            "ano": ano or "",
            "orgao": c.orgao_concedente or "SIGCON-MG",
            "valor": float(c.valor_concedente or c.valor_total or 0),
            "situacao": normaliza_situacao(c.situacao or ""),
            "esfera": "estadual",
        })

    # Agrupar por parlamentar
    grupos = defaultdict(list)
    for ind in indicacoes:
        grupos[ind["parlamentar"]].append(ind)

    # Resumo por parlamentar
    resumo = []
    for parl, itens in grupos.items():
        total = sum(i["valor"] for i in itens)
        sits = [i["situacao"] for i in itens if i["situacao"] not in ("-", "")]
        sit_predom = Counter(sits).most_common(1)[0][0] if sits else "-"
        resumo.append({
            "parlamentar": parl,
            "qtd": len(itens),
            "total": total,
            "situacao": sit_predom,
            "itens": sorted(itens, key=lambda x: (x["ano"] or 0, -x["valor"])),
        })
    # Ordenar por valor desc, "Sem indicacao identificada" no fim
    resumo.sort(key=lambda x: (x["parlamentar"] == "Sem indicacao identificada", -x["total"]))

    # KPIs
    total_indicacoes = len(indicacoes)
    parlamentares_distintos = len([r for r in resumo if r["parlamentar"] != "Sem indicacao identificada"])
    pagos_entregues = sum(
        1 for i in indicacoes
        if i["situacao"].lower() in ("pago", "entregue")
    )
    soma_total = sum(i["valor"] for i in indicacoes)

    # Periodo (ja garantido nao-None acima)
    periodo = f"{ano_inicio} - {ano_fim}"

    today = date.today()
    data_label = f"{today.day:02d} de {MESES_PT.get(today.month, '')} de {today.year}"

    # ===== HTML =====
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Levantamento de Indicacoes - {mun.nome}</title>
<style>
  @page {{ size: A4; margin: 1.5cm 1.5cm 2cm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: 'Calibri', Arial, sans-serif; font-size: 10pt; color: #000; margin: 0; }}
  .header-banner {{
    background: #0b1f3b; color: #fff; padding: 22px 24px; margin-bottom: 18px;
    border-radius: 4px;
  }}
  .header-banner h1 {{ margin: 0; font-size: 18pt; letter-spacing: 0.5px; }}
  .header-banner .sub {{ font-size: 10pt; opacity: 0.85; margin-top: 4px; }}
  .kpis {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 22px; }}
  .kpi {{ border: 1px solid #cfd8e3; border-radius: 4px; padding: 10px 12px; text-align: center; background: #f8fafc; }}
  .kpi .lbl {{ font-size: 8.5pt; color: #5a6b7f; text-transform: none; }}
  .kpi .val {{ font-size: 16pt; font-weight: bold; color: #0b1f3b; margin-top: 4px; }}
  h2.section {{ font-size: 12pt; color: #1f4e79; margin: 20px 0 10px; font-weight: bold; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 9.5pt; }}
  table.resumo th {{ background: #4472c4; color: #fff; padding: 8px 10px; text-align: left; font-size: 10pt; }}
  table.resumo th.num, table.resumo td.num {{ text-align: center; }}
  table.resumo th.val, table.resumo td.val {{ text-align: right; }}
  table.resumo td {{ padding: 7px 10px; border-bottom: 1px solid #e5e7eb; }}
  table.resumo tr.total td {{ background: #0b1f3b; color: #fff; font-weight: bold; }}
  .parl-header {{
    background: #4472c4; color: #fff; padding: 9px 14px; border-radius: 3px 3px 0 0;
    display: flex; justify-content: space-between; align-items: center;
    margin-top: 16px; font-weight: bold; font-size: 11pt;
  }}
  table.detalhe {{ border: 1px solid #cfd8e3; border-top: none; }}
  table.detalhe th {{ background: #2e75b6; color: #fff; padding: 6px 10px; text-align: left; font-size: 9pt; font-weight: 600; }}
  table.detalhe th.num, table.detalhe td.num {{ text-align: center; }}
  table.detalhe th.val, table.detalhe td.val {{ text-align: right; }}
  table.detalhe td {{ padding: 6px 10px; border-bottom: 1px solid #eef2f7; vertical-align: top; }}
  table.detalhe tr.subtotal td {{ background: #1f4e79; color: #fff; font-weight: bold; }}
  .sit-pago {{ color: #0b8043; font-weight: 600; }}
  .sit-entregue {{ color: #1565c0; font-weight: 600; }}
  .sit-analise {{ color: #d97706; font-weight: 600; }}
  .sit-pendente {{ color: #9c27b0; font-weight: 600; }}
  .sit-promessa {{ color: #ef6c00; font-weight: 600; }}
  .sit-cancelado {{ color: #c62828; font-weight: 600; }}
  .sit-default {{ color: #555; }}
  .footer {{ position: fixed; bottom: 0.6cm; left: 0; right: 0; text-align: center;
            font-size: 7.5pt; color: #666; border-top: 1px solid #ddd; padding-top: 6px; }}
  @media print {{
    .parl-block {{ page-break-inside: avoid; }}
    h2.section {{ page-break-after: avoid; }}
  }}
</style>
</head>
<body>

<div class="header-banner">
  <h1>LEVANTAMENTO DE INDICACOES POR PARLAMENTAR</h1>
  <div class="sub">{mun.nome}/MG &middot; {periodo} &middot; Freitas &amp; Associados</div>
</div>

<div class="kpis">
  <div class="kpi"><div class="lbl">Total de indicacoes</div><div class="val">{total_indicacoes}</div></div>
  <div class="kpi"><div class="lbl">Parlamentares distintos</div><div class="val">{parlamentares_distintos}</div></div>
  <div class="kpi"><div class="lbl">Pagos / Entregues</div><div class="val">{pagos_entregues}</div></div>
  <div class="kpi"><div class="lbl">Soma dos repasses</div><div class="val">{fmt_money(soma_total)}</div></div>
</div>

<h2 class="section">Resumo por parlamentar &mdash; total de repasses</h2>
<table class="resumo">
  <thead>
    <tr>
      <th>Parlamentar</th>
      <th class="num">Qtd.</th>
      <th class="val">Total repasse</th>
      <th>Situacao predominante</th>
    </tr>
  </thead>
  <tbody>
"""
    for r in resumo:
        cls = situacao_class(r["situacao"])
        html += (
            f'<tr>'
            f'<td>{r["parlamentar"]}</td>'
            f'<td class="num">{r["qtd"]}</td>'
            f'<td class="val"><strong>{fmt_money(r["total"])}</strong></td>'
            f'<td><span class="{cls}">{r["situacao"]}</span></td>'
            f'</tr>'
        )
    html += (
        f'<tr class="total">'
        f'<td>TOTAL GERAL</td>'
        f'<td class="num">{total_indicacoes}</td>'
        f'<td class="val">{fmt_money(soma_total)}</td>'
        f'<td></td>'
        f'</tr>'
    )
    html += """
  </tbody>
</table>

<h2 class="section">Detalhamento por parlamentar</h2>
"""
    for r in resumo:
        html += f"""
<div class="parl-block">
  <div class="parl-header">
    <span>{r["parlamentar"]}</span>
    <span>{fmt_money(r["total"])}</span>
  </div>
  <table class="detalhe">
    <thead>
      <tr>
        <th style="width:48%">Objeto / Programa</th>
        <th class="num" style="width:7%">Ano</th>
        <th style="width:22%">Ministerio / Orgao</th>
        <th class="val" style="width:13%">Valor repasse</th>
        <th style="width:10%">Situacao</th>
      </tr>
    </thead>
    <tbody>
"""
        for it in r["itens"]:
            cls = situacao_class(it["situacao"])
            html += (
                f'<tr>'
                f'<td>{it["objeto"]}</td>'
                f'<td class="num">{it["ano"]}</td>'
                f'<td>{it["orgao"]}</td>'
                f'<td class="val"><strong>{fmt_money(it["valor"])}</strong></td>'
                f'<td><span class="{cls}">{it["situacao"]}</span></td>'
                f'</tr>'
            )
        html += (
            f'<tr class="subtotal">'
            f'<td colspan="3">Subtotal &mdash; {r["parlamentar"]}</td>'
            f'<td class="val">{fmt_money(r["total"])}</td>'
            f'<td></td>'
            f'</tr>'
        )
        html += """
    </tbody>
  </table>
</div>
"""

    html += f"""
<div class="footer">
  Freitas &amp; Associados &middot; Levantamento de Indicacoes &mdash; {mun.nome}/MG &middot; {data_label}
  &middot; Setor SHS Quadra 6, Conjunto A, Bloco E, Sala 624, Asa Sul, Brasilia/DF
</div>

</body>
</html>
"""

    filename = f"Levantamento_{mun.nome.replace(' ', '_')}_{ano_inicio}_{ano_fim}.html"
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
