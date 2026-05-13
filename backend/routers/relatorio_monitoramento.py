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
from services.status_resolver import resolve_status

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

# Codigo de orgao (5 digitos) -> Nome do Ministerio/Secretaria
# Cobre os principais que aparecem em SICONV/TransfereGov
ORGAO_NOMES = {
    "20000": "Casa Civil PR",
    "22000": "Min. Agricultura, Pecuaria e Abastecimento",
    "24000": "Min. Ciencia, Tecnologia e Inovacao",
    "26000": "Min. Educacao",
    "28000": "Min. Defesa",
    "30000": "Min. Justica e Seguranca Publica",
    "30201": "Min. Educacao - FNDE",
    "32000": "Min. Trabalho e Previdencia",
    "33000": "Min. Previdencia Social",
    "34000": "Min. Comunicacoes",
    "36000": "Min. Saude",
    "36201": "Min. Saude - FNS",
    "38000": "Min. Meio Ambiente",
    "39000": "Min. Transportes",
    "40000": "Min. Industria, Comercio Exterior e Servicos",
    "41000": "Min. Cultura",
    "42000": "Min. Esporte",
    "44000": "Min. Turismo",
    "47000": "Min. Planejamento e Orcamento",
    "49000": "Min. Desenvolvimento Agrario",
    "51000": "Min. Esportes",
    "52000": "Min. Defesa - FAB/EB/MB",
    "53000": "Min. Integracao e Desenvolvimento Regional",
    "54000": "Min. Desenvolvimento Social, Familia e Combate a Fome",
    "55000": "Min. Cidades",
    "56000": "Min. Direitos Humanos e Cidadania",
    "57000": "Min. Mulheres",
    "58000": "Min. Igualdade Racial",
    "59000": "Min. Povos Indigenas",
    "73000": "Min. Pesca e Aquicultura",
    "74000": "Min. Empreendedorismo (MEI)",
}


def resolve_orgao_nome(orgao_raw: str | None) -> str:
    """Converte codigo numerico em nome de ministerio. Mantem nome se ja vem texto."""
    if not orgao_raw:
        return "Outros"
    s = str(orgao_raw).strip()
    # Se for so digitos -> e codigo, tentar mapear
    if s.isdigit():
        return ORGAO_NOMES.get(s, f"Orgao {s}")
    # Se vem com codigo no inicio (ex "51000 - Esportes"), pega tudo
    parts = s.split(" - ", 1)
    if len(parts) == 2 and parts[0].strip().isdigit():
        nome = ORGAO_NOMES.get(parts[0].strip())
        return nome if nome else parts[1].strip()
    return s


# Siglas de orgaos estaduais MG (para tela /convenios)
SIGLAS_ESTADUAIS = {
    "SECRETARIA DE ESTADO DE SAUDE": "SES",
    "SECRETARIA DE ESTADO DE GOVERNO": "SEGOV",
    "SECRETARIA DE ESTADO DE EDUCACAO": "SEE",
    "SECRETARIA DE ESTADO DE DESENVOLVIMENTO ECONOMICO": "SEDE",
    "SECRETARIA DE ESTADO DE DESENVOLVIMENTO SOCIAL": "SEDESE",
    "SECRETARIA DE ESTADO DE INFRAESTRUTURA": "SEINFRA",
    "SECRETARIA DE ESTADO DE AGRICULTURA": "SEAPA",
    "SECRETARIA DE ESTADO DE CULTURA": "SECULT",
    "SECRETARIA DE ESTADO DE ESPORTES": "SEESP",
    "SECRETARIA DE ESTADO DE TURISMO": "SETUR",
    "SECRETARIA DE ESTADO DE MEIO AMBIENTE": "SEMAD",
    "SECRETARIA DE ESTADO DE PLANEJAMENTO": "SEPLAG",
}


def sigla_orgao(orgao: str | None) -> str:
    if not orgao: return "-"
    s = str(orgao).upper().strip()
    for key, sig in SIGLAS_ESTADUAIS.items():
        if s.startswith(key):
            return sig
    # Fallback: pega iniciais (max 8)
    return orgao[:30]


def get_dt_vigencia(c, esfera):
    """Retorna data de vigencia, normalizando entre federal e estadual."""
    if esfera == "federal":
        return getattr(c, "dt_fim_vigencia", None)
    else:
        return getattr(c, "dt_vigencia_atual", None) or getattr(c, "dt_vigencia_final", None)


def categorize_part(c, esfera):
    """Determina em qual parte do relatorio o convenio entra.
    Logica refinada para se aproximar do modelo Freitas:
    - Parte 1: Federais ano corrente, ainda pendentes em Brasilia (sem desembolso)
    - Parte 2: Em execucao ATIVA (vigencia futura, status nao final)
    - Parte 3: Concluidos, anulados, cancelados, prestacao em analise, vigencia vencida
    - Parte 4: Propostas voluntarias (proposta/plano de trabalho enviado)
    """
    sit = (c.situacao or "").lower()
    ano_atual = date.today().year
    dt_vig = get_dt_vigencia(c, esfera)
    has_desembolso = bool(getattr(c, "dt_desembolso", None))
    valor_desembolsado = float(getattr(c, "valor_desembolsado", 0) or 0)

    # --- PARTE 4: Propostas voluntarias ---
    if any(kw in sit for kw in ["proposta", "plano de trabalho"]):
        if any(kw in sit for kw in ["enviad", "analise", "voluntar", "elabora"]):
            return 4

    # --- PARTE 3: Historico (encerrados, prestacao, anulados, vigencia vencida) ---
    historico_keywords = [
        "concluido", "concluid", "encerr", "anulado", "anulada",
        "cancelado", "cancelada", "rescindido", "rescindida",
        "aprovada", "ressalvas", "recurso", "diligencia",
    ]
    if any(kw in sit for kw in historico_keywords):
        return 3
    # Vigencia vencida ha mais de 6 meses
    if dt_vig:
        dias_vencido = (date.today() - dt_vig).days
        if dias_vencido > 180:
            return 3
    # Pagamento ja realizado
    if "pago" in sit or "pagamento" in sit and "realiz" in sit:
        return 3
    if has_desembolso and (dt_vig and dt_vig < date.today()):
        return 3

    # --- PARTE 1 = SO FEDERAIS (Demandas em Brasilia) ---
    # Toda federal vai para Brasilia (Parte 1 ou 3 conforme execucao)
    # Estadual nunca vai pra PARTE 1.
    if esfera == "federal":
        ano = c.ano or 0
        # Federais pendentes (ano corrente +/-) -> PARTE 1
        if ano >= ano_atual - 1:
            pendente_keywords = ["pendente", "empenh", "aguardando", "analise", "elabora", "proposta"]
            if any(kw in sit for kw in pendente_keywords) or sit == "" or sit == "-":
                if not has_desembolso and valor_desembolsado == 0:
                    return 1
        # Federais em execucao com vigencia futura -> PARTE 1 tambem (todas demandas Brasilia)
        if dt_vig and dt_vig >= date.today():
            return 1
        return 3  # Federal historica

    # --- ESTADUAL: PARTE 2 (Demandas Municipio) se em execucao, senao PARTE 3 ---
    if dt_vig and dt_vig >= date.today():
        return 2
    if not dt_vig:
        return 3
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

    sit_full = resolve_status(c, "federal")

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

    sit_full = resolve_status(c, "estadual")

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
  <strong>Resumo Executivo:</strong><br>
  <span style="display:inline-block;margin:4px 8px 4px 0">Total geral: <strong>{len(federais) + len(estaduais)}</strong> convenios</span> |
  <span style="display:inline-block;margin:4px 8px">Federais: <strong>{len(federais)}</strong></span> |
  <span style="display:inline-block;margin:4px 8px">Estaduais: <strong>{len(estaduais)}</strong></span><br>
  <span style="display:inline-block;margin:4px 8px 4px 0">Parte 1 (Brasilia): <strong>{len(parte1)}</strong></span> |
  <span style="display:inline-block;margin:4px 8px">Parte 2 (Em execucao): <strong>{len(parte2_fed) + len(parte2_est)}</strong></span> |
  <span style="display:inline-block;margin:4px 8px">Parte 3 (Historico): <strong>{len(parte3_fed) + len(parte3_est)}</strong></span> |
  <span style="display:inline-block;margin:4px 8px">Parte 4 (Voluntarias): <strong>{len(parte4)}</strong></span>
</div>

<h2>INSTRUMENTOS DE REPASSE FEDERAIS</h2>
"""

    # PARTE 1 - agrupar por orgao
    if parte1:
        current_orgao = None
        for c in parte1:
            orgao = resolve_orgao_nome(c.orgao_concedente)
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
            orgao = resolve_orgao_nome(c.orgao_concedente)
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
            orgao = sigla_orgao(c.orgao_concedente) if c.orgao_concedente else "SIGCON-MG"
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
            orgao = resolve_orgao_nome(c.orgao_concedente)
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
            orgao = sigla_orgao(c.orgao_concedente) if c.orgao_concedente else "SIGCON-MG"
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
            orgao = resolve_orgao_nome(c.orgao_concedente)
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
