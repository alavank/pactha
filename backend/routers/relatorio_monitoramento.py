"""
Gerador de Relatorio de Monitoramento (RM) - 4 partes.
Identico ao modelo da Freitas Consultoria.

Parte 1: Demandas em Brasilia (federais pendentes empenho/desembolso ano corrente)
Parte 2: Demandas do Municipio (federais + estaduais em execucao/em vigor)
Parte 3: Prestacoes de contas + pagamentos historicos
Parte 4: Propostas voluntarias
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import date, datetime
from typing import Optional
import locale

from database import get_db
from models import ConvenioFederal, ConvenioEstadual, Municipio, Emenda, Parlamentar
from services.auth import get_current_user

router = APIRouter(prefix="/api/relatorio-monitoramento", tags=["relatorio"])


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


MESES_PT = {
    1: "Janeiro", 2: "Fevereiro", 3: "Marco", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


def get_dt_vigencia(c, esfera):
    """Retorna data de vigencia, normalizando entre federal e estadual."""
    if esfera == "federal":
        return getattr(c, "dt_fim_vigencia", None)
    else:
        return getattr(c, "dt_vigencia_atual", None) or getattr(c, "dt_vigencia_final", None)


def categorize_part(c, esfera):
    """Determina em qual parte do relatorio o convenio entra."""
    sit = (c.situacao or "").lower()
    ano_atual = date.today().year
    dt_vig = get_dt_vigencia(c, esfera)

    # Parte 4: Propostas voluntarias
    if "proposta" in sit and "voluntar" in sit:
        return 4
    if "proposta" in sit and ("enviado" in sit or "analise" in sit):
        return 4

    # Parte 1: Demandas em Brasilia (federais pendentes ano atual)
    if esfera == "federal":
        ano = c.ano or 0
        if ano >= ano_atual - 1:
            if "pendente" in sit or "empenh" in sit or sit in ("", "em analise"):
                if "concluid" not in sit and "pago" not in sit and "realiz" not in sit:
                    return 1

    # Parte 3: Prestacoes / pagamentos historicos
    if "prestacao" in sit or "concluido" in sit or "encerr" in sit or "pago" in sit or "anulado" in sit:
        return 3
    if dt_vig and dt_vig < date.today():
        return 3

    # Parte 2: Demandas em execucao
    return 2


async def get_emenda_parlamentar(db: AsyncSession, conv_id: int, esfera: str) -> Optional[str]:
    """Busca o nome do parlamentar da emenda vinculada ao convenio."""
    if esfera == "federal":
        q = select(Parlamentar.nome).select_from(
            Emenda.__table__.join(Parlamentar.__table__, Emenda.parlamentar_id == Parlamentar.id)
        ).where(Emenda.convenio_federal_id == conv_id).limit(1)
    else:
        q = select(Parlamentar.nome).select_from(
            Emenda.__table__.join(Parlamentar.__table__, Emenda.parlamentar_id == Parlamentar.id)
        ).where(Emenda.convenio_estadual_id == conv_id).limit(1)
    r = await db.execute(q)
    nome = r.scalar()
    return nome


def render_convenio_federal(c, parlamentar_nome=None):
    """Renderiza um bloco de convenio federal no formato Freitas."""
    parl = parlamentar_nome or c.proponente_nome or "Programa"
    objeto = c.objeto or "-"

    sit_html = c.situacao or "Em andamento"
    extra_situacao = []
    if c.dt_empenho:
        extra_situacao.append(f"Empenhado em {fmt_date(c.dt_empenho)}")
    if c.dt_desembolso:
        extra_situacao.append(f"Pagamento realizado em {fmt_date(c.dt_desembolso)}")

    sit_full = sit_html
    if extra_situacao:
        sit_full = ". ".join([sit_html] + extra_situacao)

    html = f"""
    <div class="convenio">
      <p class="conv-num">{'Convenio' if c.nr_convenio and 'PROPOSTA' not in (c.objeto or '').upper() else 'Proposta'}: <strong>{c.nr_convenio}</strong>
        {f' - {c.ano}' if c.ano else ''}</p>
      <ul>
        <li><strong>Objeto:</strong> {objeto}</li>
        <li><strong>Parlamentar responsavel pela indicacao:</strong> {parl}</li>
        <li><strong>Valor global:</strong> {fmt_money(c.valor_global)}</li>
        <li><strong>Valor de repasse:</strong> {fmt_money(c.valor_repasse)}</li>
        <li><strong>Valor de contrapartida:</strong> {fmt_money(c.valor_contrapartida)}</li>
    """
    if c.dt_fim_vigencia:
        html += f'<li><strong>Final da Vigencia:</strong> {fmt_date(c.dt_fim_vigencia)}</li>'
    if c.banco:
        html += f'<li><strong>Banco:</strong> {c.banco}</li>'
    if c.agencia:
        html += f'<li><strong>Agencia:</strong> {c.agencia}</li>'
    if c.conta_corrente:
        html += f'<li><strong>Conta:</strong> {c.conta_corrente}</li>'
    if c.saldo_bancario is not None:
        sb = fmt_money(c.saldo_bancario)
        if c.dt_saldo:
            sb += f" Atualizado em {fmt_date(c.dt_saldo)}"
        html += f'<li><strong>Saldo Bancario:</strong> {sb}</li>'
    if c.nr_sei:
        html += f'<li><strong>NR SEI:</strong> {c.nr_sei}</li>'
    html += f"""
        <li><strong>Situacao atual:</strong> {sit_full}</li>
      </ul>
    </div>
    """
    return html


def render_convenio_estadual(c, parlamentar_nome=None):
    """Renderiza um bloco de convenio estadual no formato Freitas (SIGCON, SIG, SES, SEINFRA, etc)."""
    parl = parlamentar_nome or "Verificar"
    objeto = c.objeto or "-"

    sit_full = c.situacao or "Em andamento"
    if c.dt_desembolso:
        sit_full += f". Pagamento realizado em {fmt_date(c.dt_desembolso)}"

    label = "Convenio" if c.nr_sigcon and "SIGCON" not in (c.fonte or "") else "Proposta"
    if c.resolucao:
        label = "Indicacao"

    html = f"""
    <div class="convenio">
      <p class="conv-num">{label}: <strong>{c.nr_sigcon or c.nr_indicacao or '-'}</strong></p>
      <ul>
        <li><strong>Objeto:</strong> {objeto}</li>
        <li><strong>Parlamentar responsavel pela indicacao:</strong> {parl}</li>
        <li><strong>Valor global:</strong> {fmt_money(c.valor_total)}</li>
        <li><strong>Valor de repasse:</strong> {fmt_money(c.valor_concedente)}</li>
        <li><strong>Valor de contrapartida:</strong> {fmt_money(c.valor_contrapartida)}</li>
    """
    dt_fim = c.dt_vigencia_atual or c.dt_vigencia_final
    if dt_fim:
        html += f'<li><strong>Final da Vigencia:</strong> {fmt_date(dt_fim)}</li>'
    if c.banco:
        html += f'<li><strong>Banco:</strong> {c.banco}</li>'
    if c.agencia:
        html += f'<li><strong>Agencia:</strong> {c.agencia}</li>'
    if c.conta_corrente:
        html += f'<li><strong>Conta:</strong> {c.conta_corrente}</li>'
    if c.saldo_bancario is not None:
        html += f'<li><strong>Saldo Bancario:</strong> {fmt_money(c.saldo_bancario)}</li>'
    if c.nr_sei:
        html += f'<li><strong>NR SEI:</strong> {c.nr_sei}</li>'
    html += f"""
        <li><strong>Situacao Atual:</strong> {sit_full}</li>
      </ul>
    </div>
    """
    return html


@router.get("")
async def gerar_relatorio_monitoramento(
    municipio_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Gera o Relatorio de Monitoramento (RM) em HTML estruturado em 4 partes."""
    mun = await db.get(Municipio, municipio_id)
    if not mun:
        raise HTTPException(status_code=404, detail="Municipio nao encontrado")

    # Buscar todos os convenios do municipio
    fed_q = await db.execute(
        select(ConvenioFederal).where(ConvenioFederal.municipio_id == municipio_id)
    )
    federais = list(fed_q.scalars().all())

    est_q = await db.execute(
        select(ConvenioEstadual).where(ConvenioEstadual.municipio_id == municipio_id)
    )
    estaduais = list(est_q.scalars().all())

    # Categorizar em 4 partes
    parte1, parte2_fed, parte2_est, parte3_fed, parte3_est, parte4 = [], [], [], [], [], []
    for c in federais:
        p = categorize_part(c, "federal")
        if p == 1:
            parte1.append(c)
        elif p == 2:
            parte2_fed.append(c)
        elif p == 3:
            parte3_fed.append(c)
        elif p == 4:
            parte4.append(c)
    for c in estaduais:
        p = categorize_part(c, "estadual")
        if p == 2:
            parte2_est.append(c)
        elif p == 3:
            parte3_est.append(c)
        # Estaduais raramente caem em parte 1 ou 4

    # Pre-load parlamentares para cada convenio (evitar N+1)
    parl_map = {}
    em_q = await db.execute(
        select(Emenda.convenio_federal_id, Emenda.convenio_estadual_id, Parlamentar.nome)
        .select_from(Emenda.__table__.join(Parlamentar.__table__, Emenda.parlamentar_id == Parlamentar.id))
        .where(Emenda.municipio_id == municipio_id)
    )
    for fed_id, est_id, nome in em_q.all():
        if fed_id:
            parl_map[("fed", fed_id)] = nome
        if est_id:
            parl_map[("est", est_id)] = nome

    # Ordenar federais por orgao (para agrupar visualmente)
    def sort_key_fed(c):
        return (c.orgao_concedente or "ZZ", c.ano or 0)

    parte1.sort(key=sort_key_fed)
    parte2_fed.sort(key=sort_key_fed)
    parte3_fed.sort(key=sort_key_fed)

    # Build HTML
    today = date.today()
    mes_nome = MESES_PT.get(today.month, "")
    titulo_data = f"Brasilia/DF, {today.day:02d} de {mes_nome} de {today.year}"

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Relatorio de Monitoramento - {mun.nome}</title>
<style>
  @page {{ size: A4; margin: 1.5cm 1.5cm 2cm; }}
  body {{ font-family: 'Calibri', Arial, sans-serif; font-size: 11pt; color: #000; line-height: 1.4; }}
  h1 {{ text-align: center; font-size: 14pt; color: #1f4e79; margin: 10px 0; }}
  h2 {{ font-size: 13pt; color: #1f4e79; margin-top: 25px; border-bottom: 2px solid #1f4e79; padding-bottom: 4px; }}
  h3 {{ font-size: 12pt; color: #2e75b6; margin-top: 18px; margin-bottom: 8px; }}
  h4 {{ font-size: 11pt; color: #2e75b6; margin-top: 14px; margin-bottom: 6px; }}
  .data-titulo {{ text-align: center; font-style: italic; margin: 5px 0 20px; }}
  .convenio {{ margin: 12px 0; padding-left: 10px; border-left: 2px solid #d9e2f3; }}
  .conv-num {{ margin: 4px 0; font-size: 11pt; }}
  ul {{ margin: 4px 0 8px 0; padding-left: 25px; }}
  li {{ margin: 2px 0; font-size: 10.5pt; }}
  .footer {{ position: fixed; bottom: 1cm; left: 0; right: 0; text-align: center;
            font-size: 8pt; color: #666; }}
  .empty {{ font-style: italic; color: #888; padding: 10px; }}
  .summary-stats {{ background: #f0f4f8; padding: 10px; border-radius: 4px; margin: 10px 0; font-size: 10pt; }}
  @media print {{
    h2 {{ page-break-after: avoid; }}
    .convenio {{ page-break-inside: avoid; }}
  }}
</style>
</head>
<body>

<h1>RELATORIO DE MONITORAMENTO - {mun.nome.upper()}/MG - PARTE 1 - DEMANDAS EM BRASILIA</h1>
<p class="data-titulo">{titulo_data}</p>

<div class="summary-stats">
  <strong>Resumo:</strong>
  Federais: {len(federais)} | Estaduais: {len(estaduais)} | Total: {len(federais) + len(estaduais)} convenios
</div>

<h2>INSTRUMENTOS DE REPASSE FEDERAIS</h2>
"""

    # PARTE 1 - agrupar por orgao
    if parte1:
        current_orgao = None
        for c in parte1:
            orgao = c.orgao_concedente or "Outros"
            if orgao != current_orgao:
                html += f'<h3>● {orgao}</h3>'
                current_orgao = orgao
            parl = parl_map.get(("fed", c.id))
            html += render_convenio_federal(c, parl)
    else:
        html += '<p class="empty">Nenhuma demanda pendente em Brasilia no momento.</p>'

    # PARTE 2
    html += f"""
<div style="page-break-before: always;"></div>
<h1>RELATORIO DE MONITORAMENTO - PARTE 2 - DEMANDAS DO MUNICIPIO</h1>
<h2>INSTRUMENTOS DE REPASSE FEDERAIS</h2>
"""
    if parte2_fed:
        current_orgao = None
        for c in parte2_fed:
            orgao = c.orgao_concedente or "Outros"
            if orgao != current_orgao:
                html += f'<h3>● {orgao}</h3>'
                current_orgao = orgao
            parl = parl_map.get(("fed", c.id))
            html += render_convenio_federal(c, parl)
    else:
        html += '<p class="empty">Nenhum convenio federal em execucao.</p>'

    html += '<h2>INSTRUMENTOS DE REPASSE ESTADUAIS</h2>'
    if parte2_est:
        current_orgao = None
        for c in parte2_est:
            orgao = c.orgao_concedente or "SIGCON"
            if orgao != current_orgao:
                html += f'<h3>{orgao}</h3>'
                current_orgao = orgao
            parl = parl_map.get(("est", c.id))
            html += render_convenio_estadual(c, parl)
    else:
        html += '<p class="empty">Nenhum convenio estadual em execucao.</p>'

    # PARTE 3
    html += f"""
<div style="page-break-before: always;"></div>
<h1>RELATORIO DE MONITORAMENTO - PARTE 3 - PRESTACOES DE CONTAS EM ANALISE/APROVADAS - PAGAMENTOS REALIZADOS</h1>
<h2>INSTRUMENTOS DE REPASSE FEDERAIS</h2>
"""
    if parte3_fed:
        current_orgao = None
        for c in parte3_fed:
            orgao = c.orgao_concedente or "Outros"
            if orgao != current_orgao:
                html += f'<h3>● {orgao}</h3>'
                current_orgao = orgao
            parl = parl_map.get(("fed", c.id))
            html += render_convenio_federal(c, parl)
    else:
        html += '<p class="empty">Nenhuma prestacao de contas federal historica.</p>'

    html += '<h2>INSTRUMENTOS DE REPASSE ESTADUAIS</h2>'
    if parte3_est:
        current_orgao = None
        for c in parte3_est:
            orgao = c.orgao_concedente or "SIGCON"
            if orgao != current_orgao:
                html += f'<h3>{orgao}</h3>'
                current_orgao = orgao
            parl = parl_map.get(("est", c.id))
            html += render_convenio_estadual(c, parl)
    else:
        html += '<p class="empty">Nenhuma prestacao de contas estadual historica.</p>'

    # PARTE 4
    html += f"""
<div style="page-break-before: always;"></div>
<h1>PARTE 4 - PROPOSTAS VOLUNTARIAS</h1>
"""
    if parte4:
        current_orgao = None
        for c in parte4:
            orgao = c.orgao_concedente or "Outros"
            if orgao != current_orgao:
                html += f'<h3>● {orgao}</h3>'
                current_orgao = orgao
            parl = parl_map.get(("fed", c.id))
            html += render_convenio_federal(c, parl)
    else:
        html += '<p class="empty">Nenhuma proposta voluntaria pendente.</p>'

    html += f"""
<div class="footer">
  Relatorio gerado pela plataforma PACTA em {today.strftime("%d/%m/%Y")} - Setor SHS Quadra 6, Conjunto A, Bloco E, Sala 624, Asa Sul, CEP: 70.316.902, Brasilia/DF.
</div>

</body>
</html>
"""

    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'inline; filename="RM_{mun.nome.replace(" ", "_")}_{today.strftime("%d-%m-%Y")}.html"'
        },
    )
