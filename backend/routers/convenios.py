from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, case
from datetime import date, timedelta
from typing import Optional
from database import get_db
from models import ConvenioFederal, ConvenioEstadual, Emenda, Parlamentar
from schemas.convenio import ConvenioResponse, ConvenioListResponse, ConvenioStats, AlertaVigencia
from services.auth import get_current_user
import math

router = APIRouter(prefix="/api/convenios", tags=["convenios"])


def federal_to_response(c: ConvenioFederal) -> ConvenioResponse:
    dias = None
    if c.dt_fim_vigencia:
        dias = (c.dt_fim_vigencia - date.today()).days
    return ConvenioResponse(
        id=c.id,
        esfera="federal",
        nr_convenio=c.nr_convenio,
        municipio_id=c.municipio_id,
        orgao_concedente=c.orgao_concedente,
        objeto=c.objeto,
        situacao=c.situacao,
        valor_total=float(c.valor_global) if c.valor_global else None,
        valor_repasse=float(c.valor_repasse) if c.valor_repasse else None,
        valor_empenhado=float(c.valor_empenhado) if c.valor_empenhado else None,
        valor_desembolsado=float(c.valor_desembolsado) if c.valor_desembolsado else None,
        valor_contrapartida=float(c.valor_contrapartida) if c.valor_contrapartida else None,
        dt_inicio=c.dt_inicio,
        dt_fim_vigencia=c.dt_fim_vigencia,
        dias_restantes=dias,
        ano=c.ano,
        programa=c.programa,
        fonte=c.fonte,
        tipo_programa=c.tipo_programa,
        banco=c.banco,
        agencia=c.agencia,
        conta_corrente=c.conta_corrente,
        saldo_bancario=float(c.saldo_bancario) if c.saldo_bancario else None,
        dt_saldo=c.dt_saldo,
        nr_sei=c.nr_sei,
        dt_empenho=c.dt_empenho,
        dt_desembolso=c.dt_desembolso,
    )


def estadual_to_response(c: ConvenioEstadual) -> ConvenioResponse:
    dias = None
    if c.dt_vigencia_atual:
        dias = (c.dt_vigencia_atual - date.today()).days
    elif c.dt_vigencia_final:
        dias = (c.dt_vigencia_final - date.today()).days
    # Numeros SIGCON: extrai os 3 identificadores principais (Proposta/Plano/Instrumento)
    # do raw_data (scraper preenche tudo) com fallback inteligente para CKAN bulk:
    # - CKAN guarda nr_instrumento em nr_sigcon (formato 10 digits/YYYY)
    # - CKAN guarda nr_plano em raw_data.nr_plano_sigcon ou nr_plano_trabalho col
    raw = c.raw_data if isinstance(c.raw_data, dict) else {}
    import re
    nr_proposta = raw.get("nr_proposta")
    nr_instrumento = raw.get("nr_instrumento")
    nr_plano = c.nr_plano_trabalho
    # Heuristicas para CKAN bulk (raw_data costuma vir vazio):
    # - nr_instrumento SIGCON: 8-12 digits + "/" + 4-digit year (ex: "1481000677/2026")
    # - nr_proposta SIGCON:   6 digits + "/" + 4-digit year       (ex: "001030/2026")
    # - nr_plano_trabalho real eh um inteiro curto (5-7 digits sem barra)
    if not nr_instrumento and c.nr_sigcon and re.match(r"^\d{8,12}/\d{4}$", c.nr_sigcon):
        nr_instrumento = c.nr_sigcon
    # Se nr_plano_trabalho tem cara de proposta (6 digitos / ano), reatribui
    if not nr_proposta and nr_plano and re.match(r"^\d{6}/\d{4}$", nr_plano):
        nr_proposta = nr_plano
        nr_plano = None  # nao mostra na coluna Plano pra evitar duplicacao
    # Fallback adicional: raw_data.nr_plano_sigcon tambem eh proposta
    if not nr_proposta:
        rps = raw.get("nr_plano_sigcon")
        if rps and re.match(r"^\d{6}/\d{4}$", rps):
            nr_proposta = rps
    return ConvenioResponse(
        id=c.id,
        esfera="estadual",
        nr_sigcon=c.nr_sigcon,
        municipio_id=c.municipio_id,
        orgao_concedente=c.orgao_concedente,
        objeto=c.objeto,
        situacao=c.situacao,
        valor_total=float(c.valor_total) if c.valor_total else None,
        valor_repasse=float(c.valor_concedente) if c.valor_concedente else None,
        valor_empenhado=float(c.valor_emenda_parlamentar) if c.valor_emenda_parlamentar else None,
        valor_desembolsado=float(c.valor_repassado) if c.valor_repassado else None,
        valor_contrapartida=float(c.valor_contrapartida) if c.valor_contrapartida else None,
        dt_inicio=c.dt_vigencia_inicial,
        dt_fim_vigencia=c.dt_vigencia_atual or c.dt_vigencia_final,
        dias_restantes=dias,
        ano=c.ano,
        etapa_sigcon=c.etapa_sigcon,
        etapa_sigcon_nr=c.etapa_sigcon_nr,
        fonte=c.fonte,
        tipo_programa=c.tipo_programa,
        banco=c.banco,
        agencia=c.agencia,
        conta_corrente=c.conta_corrente,
        saldo_bancario=float(c.saldo_bancario) if c.saldo_bancario else None,
        dt_saldo=c.dt_saldo,
        nr_sei=c.nr_sei,
        dt_empenho=c.dt_empenho,
        dt_desembolso=c.dt_desembolso,
        nr_proposta=nr_proposta or None,
        nr_plano_trabalho=nr_plano,
        nr_instrumento=nr_instrumento or None,
        nr_siafi=c.nr_siafi,
    )


@router.get("/situacoes")
async def list_situacoes(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Distinct situacoes from both federal and estadual, optionally filtered by municipio."""
    situacoes = set()

    q1 = select(ConvenioFederal.situacao).distinct().where(ConvenioFederal.situacao.is_not(None))
    if municipio_id:
        q1 = q1.where(ConvenioFederal.municipio_id == municipio_id)
    r1 = await db.execute(q1)
    for row in r1.all():
        if row[0]:
            situacoes.add(row[0].strip())

    q2 = select(ConvenioEstadual.situacao).distinct().where(ConvenioEstadual.situacao.is_not(None))
    if municipio_id:
        q2 = q2.where(ConvenioEstadual.municipio_id == municipio_id)
    r2 = await db.execute(q2)
    for row in r2.all():
        if row[0]:
            situacoes.add(row[0].strip())

    return sorted(situacoes)


@router.get("/anos")
async def list_anos(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Distinct years with convenios."""
    anos = set()

    q1 = select(ConvenioFederal.ano).distinct().where(ConvenioFederal.ano.is_not(None))
    if municipio_id:
        q1 = q1.where(ConvenioFederal.municipio_id == municipio_id)
    r1 = await db.execute(q1)
    for row in r1.all():
        if row[0]:
            anos.add(int(row[0]))

    q2 = select(ConvenioEstadual.ano).distinct().where(ConvenioEstadual.ano.is_not(None))
    if municipio_id:
        q2 = q2.where(ConvenioEstadual.municipio_id == municipio_id)
    r2 = await db.execute(q2)
    for row in r2.all():
        if row[0]:
            anos.add(int(row[0]))

    return sorted(anos, reverse=True)


@router.get("", response_model=ConvenioListResponse)
async def list_convenios(
    municipio_id: Optional[int] = None,
    esfera: Optional[str] = None,
    ano: Optional[int] = None,
    situacao: Optional[str] = None,
    fonte: Optional[str] = None,
    fontes: Optional[list[str]] = Query(None, description="Multi-select fonte (alternativa a 'fonte' single)"),
    parlamentar_id: Optional[int] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    items = []
    total = 0

    # Federal
    if esfera in (None, "federal"):
        q = select(ConvenioFederal)
        q_count = select(func.count()).select_from(ConvenioFederal)
        if municipio_id:
            q = q.where(ConvenioFederal.municipio_id == municipio_id)
            q_count = q_count.where(ConvenioFederal.municipio_id == municipio_id)
        if ano:
            q = q.where(ConvenioFederal.ano == ano)
            q_count = q_count.where(ConvenioFederal.ano == ano)
        if situacao:
            q = q.where(ConvenioFederal.situacao.ilike(f"%{situacao}%"))
            q_count = q_count.where(ConvenioFederal.situacao.ilike(f"%{situacao}%"))
        if fontes:
            q = q.where(ConvenioFederal.fonte.in_(fontes))
            q_count = q_count.where(ConvenioFederal.fonte.in_(fontes))
        elif fonte:
            q = q.where(ConvenioFederal.fonte == fonte)
            q_count = q_count.where(ConvenioFederal.fonte == fonte)
        if search:
            # Busca em campos textuais + chaves do raw_data (JSONB)
            term = f"%{search}%"
            search_filter = or_(
                ConvenioFederal.objeto.ilike(term),
                ConvenioFederal.nr_convenio.ilike(term),
                ConvenioFederal.raw_data["nr_proposta"].astext.ilike(term),
                ConvenioFederal.raw_data["nr_plano"].astext.ilike(term),
                ConvenioFederal.raw_data["nr_instrumento"].astext.ilike(term),
                ConvenioFederal.raw_data["nr_siafi"].astext.ilike(term),
            )
            q = q.where(search_filter)
            q_count = q_count.where(search_filter)
        if parlamentar_id:
            q = q.join(Emenda, Emenda.convenio_federal_id == ConvenioFederal.id).where(
                Emenda.parlamentar_id == parlamentar_id
            )
            q_count = q_count.join(Emenda, Emenda.convenio_federal_id == ConvenioFederal.id).where(
                Emenda.parlamentar_id == parlamentar_id
            )

        count_result = await db.execute(q_count)
        total += count_result.scalar()

        # Default: mais recentes primeiro (evita lixo historico de 1997 no topo).
        # Para 'todos', o sort combined em Python aplica logica de vigencia depois.
        q = q.order_by(ConvenioFederal.dt_inicio.desc().nullslast())
        if esfera == "federal":
            q = q.offset((page - 1) * per_page).limit(per_page)
        result = await db.execute(q)
        items.extend([federal_to_response(c) for c in result.scalars().all()])

    # Estadual
    if esfera in (None, "estadual"):
        q = select(ConvenioEstadual)
        q_count = select(func.count()).select_from(ConvenioEstadual)
        if municipio_id:
            q = q.where(ConvenioEstadual.municipio_id == municipio_id)
            q_count = q_count.where(ConvenioEstadual.municipio_id == municipio_id)
        if ano:
            q = q.where(ConvenioEstadual.ano == ano)
            q_count = q_count.where(ConvenioEstadual.ano == ano)
        if situacao:
            q = q.where(ConvenioEstadual.situacao.ilike(f"%{situacao}%"))
            q_count = q_count.where(ConvenioEstadual.situacao.ilike(f"%{situacao}%"))
        if fontes:
            # SIGCON estadual tem fonte=NULL ou 'SIGCON-MG'. Adicionar mapeamento.
            est_fontes = []
            for f in fontes:
                if f.upper() == "SIGCON":
                    est_fontes.extend(["SIGCON-MG", "SIGCON"])
                else:
                    est_fontes.append(f)
            from sqlalchemy import or_ as _or, and_ as _and
            cond = ConvenioEstadual.fonte.in_(est_fontes)
            if "SIGCON" in [f.upper() for f in fontes] or "SIGCON-MG" in fontes:
                cond = _or(cond, ConvenioEstadual.fonte.is_(None))
            q = q.where(cond)
            q_count = q_count.where(cond)
        elif fonte:
            q = q.where(ConvenioEstadual.fonte == fonte)
            q_count = q_count.where(ConvenioEstadual.fonte == fonte)
        if search:
            # Busca em colunas dedicadas + chaves raw_data (JSONB) usando ->>
            term = f"%{search}%"
            search_filter = or_(
                ConvenioEstadual.objeto.ilike(term),
                ConvenioEstadual.nr_sigcon.ilike(term),
                ConvenioEstadual.nr_siafi.ilike(term),
                ConvenioEstadual.nr_plano_trabalho.ilike(term),
                ConvenioEstadual.raw_data["nr_proposta"].astext.ilike(term),
                ConvenioEstadual.raw_data["nr_instrumento"].astext.ilike(term),
                ConvenioEstadual.raw_data["nr_plano"].astext.ilike(term),
                ConvenioEstadual.raw_data["nr_plano_sigcon"].astext.ilike(term),
            )
            q = q.where(search_filter)
            q_count = q_count.where(search_filter)

        count_result = await db.execute(q_count)
        total += count_result.scalar()

        q = q.order_by(ConvenioEstadual.dt_publicacao.desc().nullslast())
        if esfera == "estadual":
            q = q.offset((page - 1) * per_page).limit(per_page)
        result = await db.execute(q)
        items.extend([estadual_to_response(c) for c in result.scalars().all()])

    # Sort combined:
    # 1) Vigentes (dias_restantes >= 0) primeiro, ordenados ASC (mais urgentes primeiro)
    # 2) Vencidos (dias_restantes < 0) ordenados DESC (menos vencido = mais recente primeiro)
    # 3) NULL (sem data) por ultimo
    # Isso evita que convenios de 1997 (-10271 dias) ocupem o topo da lista.
    def _sort_key(x):
        d = x.dias_restantes
        if d is None:
            return (2, 0)
        if d >= 0:
            return (0, d)          # vigente: urgencia ASC
        return (1, -d)             # vencido: |dias| ASC (mais recente primeiro)
    items.sort(key=_sort_key)

    # Paginate combined
    if esfera is None:
        start = (page - 1) * per_page
        items = items[start:start + per_page]

    pages = math.ceil(total / per_page) if total > 0 else 1
    return ConvenioListResponse(items=items, total=total, page=page, per_page=per_page, pages=pages)


@router.get("/stats", response_model=ConvenioStats)
async def convenio_stats(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    stats = ConvenioStats()

    # Federal stats
    q = select(
        func.count().label("cnt"),
        func.coalesce(func.sum(ConvenioFederal.valor_global), 0).label("total"),
        func.coalesce(func.sum(ConvenioFederal.valor_empenhado), 0).label("empenhado"),
        func.coalesce(func.sum(ConvenioFederal.valor_desembolsado), 0).label("desembolsado"),
    )
    if municipio_id:
        q = q.where(ConvenioFederal.municipio_id == municipio_id)
    result = await db.execute(q)
    row = result.one()
    fed_count = row.cnt
    stats.total_convenios += fed_count
    stats.valor_total += float(row.total)
    stats.valor_empenhado += float(row.empenhado)
    stats.valor_desembolsado += float(row.desembolsado)
    stats.por_esfera["federal"] = fed_count

    # Estadual stats
    q = select(
        func.count().label("cnt"),
        func.coalesce(func.sum(ConvenioEstadual.valor_total), 0).label("total"),
    )
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    result = await db.execute(q)
    row = result.one()
    est_count = row.cnt
    stats.total_convenios += est_count
    stats.valor_total += float(row.total)
    stats.por_esfera["estadual"] = est_count

    # Por situacao federal
    q = select(ConvenioFederal.situacao, func.count()).group_by(ConvenioFederal.situacao)
    if municipio_id:
        q = q.where(ConvenioFederal.municipio_id == municipio_id)
    result = await db.execute(q)
    for sit, cnt in result.all():
        if sit:
            stats.por_situacao[sit] = stats.por_situacao.get(sit, 0) + cnt

    return stats


@router.get("/alertas", response_model=list[AlertaVigencia])
async def alertas_vigencia(
    municipio_id: Optional[int] = None,
    dias: int = Query(120, ge=1),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    limite = date.today() + timedelta(days=dias)
    alertas = []

    # Federal
    q = select(ConvenioFederal).where(
        ConvenioFederal.dt_fim_vigencia <= limite,
        ConvenioFederal.dt_fim_vigencia >= date.today(),
    )
    if municipio_id:
        q = q.where(ConvenioFederal.municipio_id == municipio_id)
    q = q.order_by(ConvenioFederal.dt_fim_vigencia.asc())
    result = await db.execute(q)
    for c in result.scalars().all():
        dias_rest = (c.dt_fim_vigencia - date.today()).days
        alertas.append(AlertaVigencia(
            id=c.id, esfera="federal", nr_convenio=c.nr_convenio,
            objeto=c.objeto, orgao_concedente=c.orgao_concedente,
            dt_fim_vigencia=c.dt_fim_vigencia, dias_restantes=dias_rest,
            valor_total=float(c.valor_global) if c.valor_global else None,
            situacao=c.situacao,
        ))

    # Estadual
    q = select(ConvenioEstadual).where(
        ConvenioEstadual.dt_vigencia_atual <= limite,
        ConvenioEstadual.dt_vigencia_atual >= date.today(),
    )
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    q = q.order_by(ConvenioEstadual.dt_vigencia_atual.asc())
    result = await db.execute(q)
    for c in result.scalars().all():
        dias_rest = (c.dt_vigencia_atual - date.today()).days
        alertas.append(AlertaVigencia(
            id=c.id, esfera="estadual", nr_sigcon=c.nr_sigcon,
            objeto=c.objeto, orgao_concedente=c.orgao_concedente,
            dt_fim_vigencia=c.dt_vigencia_atual, dias_restantes=dias_rest,
            valor_total=float(c.valor_total) if c.valor_total else None,
            situacao=c.situacao,
        ))

    alertas.sort(key=lambda x: x.dias_restantes)
    return alertas


# Workflow SIGCON-MG (etapas oficiais do portal Pesquisa Unificada)
SIGCON_WORKFLOW = [
    "CADASTRAMENTO",
    "PREENCHIMENTO DE CHECKLIST",
    "VALIDACAO DA PROPOSTA PELO RESPONSAVEL LEGAL",
    "ANALISE - CHECKLIST DE CELEBRACAO",
    "RECEBIDO PELO ORGAO / ANALISE TECNICA / ADEQUACAO",
    "ANALISE JURIDICA",
    "AGUARDANDO ENVIO PARA SEGOV",
    "SEGOV ANALISE",
    "PLANO AUTORIZADO",
    "ANEXACAO DO INSTRUMENTO",
    "PROCESSO DE ASSINATURA - CONVENENTE/OSC",
    "PROCESSO DE ASSINATURA - CONCEDENTE/OEEP",
    "PROCESSO DE PUBLICACAO",
    "INSTRUMENTO CADASTRADO / VIGENTE",
    "INSTRUMENTO ENCERRADO",
]


def _norm_workflow(s: str) -> str:
    if not s: return ""
    import unicodedata as u
    return "".join(c for c in u.normalize("NFKD", s.upper()) if not u.combining(c)).strip()


def _build_workflow_state(situacao: str | None) -> dict:
    """Mapeia situacao atual -> indice no workflow + lista marcada."""
    sit_norm = _norm_workflow(situacao or "")
    # Aliases do banco -> nomes oficiais
    aliases = {
        "EM VIGOR": "INSTRUMENTO CADASTRADO / VIGENTE",
        "VIGENTE": "INSTRUMENTO CADASTRADO / VIGENTE",
        "ENCERRADO": "INSTRUMENTO ENCERRADO",
        "CADASTRAMENTO": "CADASTRAMENTO",
        "PREENCHIMENTO CHECKLIST": "PREENCHIMENTO DE CHECKLIST",
        "ANALISE CELEBRACAO": "ANALISE - CHECKLIST DE CELEBRACAO",
        "ANALISE TECNICA": "RECEBIDO PELO ORGAO / ANALISE TECNICA / ADEQUACAO",
        "PLANO AUTORIZADO": "PLANO AUTORIZADO",
        "PROPOSTA/PLANO DE TRABALHO ENVIADO PARA ANALISE": "PREENCHIMENTO DE CHECKLIST",
        "PROPOSTA/PLANO DE TRABALHO REJEITADOS": "ANALISE - CHECKLIST DE CELEBRACAO",
    }
    target = aliases.get(sit_norm, sit_norm)
    cur_idx = -1
    for i, step in enumerate(SIGCON_WORKFLOW):
        if _norm_workflow(step) == target:
            cur_idx = i
            break
    return {
        "current_index": cur_idx,
        "current_label": situacao,
        "steps": [
            {"label": s, "completed": cur_idx >= i, "current": cur_idx == i}
            for i, s in enumerate(SIGCON_WORKFLOW)
        ],
    }


@router.get("/estadual/{conv_id}")
async def get_convenio_estadual_detail(
    conv_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Detalhes ricos de um convenio estadual: campos + workflow SIGCON + raw_data util."""
    q = select(ConvenioEstadual).where(ConvenioEstadual.id == conv_id)
    r = await db.execute(q)
    c = r.scalar_one_or_none()
    if not c:
        from fastapi import HTTPException
        raise HTTPException(404, "Convenio nao encontrado")

    raw = c.raw_data if isinstance(c.raw_data, dict) else {}
    import re
    nr_proposta = raw.get("nr_proposta")
    nr_instrumento = raw.get("nr_instrumento")
    if not nr_instrumento and c.nr_sigcon and re.match(r"^\d{8,12}/\d{4}$", c.nr_sigcon):
        nr_instrumento = c.nr_sigcon

    # Vigencia em dias (dt_fim - dt_ini)
    dias_vig = None
    if c.dt_vigencia_inicial and (c.dt_vigencia_atual or c.dt_vigencia_final):
        dt_fim = c.dt_vigencia_atual or c.dt_vigencia_final
        dias_vig = (dt_fim - c.dt_vigencia_inicial).days

    dias_rest = None
    dias_rest_label = None
    if c.dt_vigencia_atual or c.dt_vigencia_final:
        dt_fim = c.dt_vigencia_atual or c.dt_vigencia_final
        dias_rest = (dt_fim - date.today()).days
        if dias_rest < 0:
            dias_rest_label = "VENCIDO"

    return {
        "id": c.id,
        "esfera": "estadual",
        "nr_convenio_publicado": c.nr_sigcon,
        "nr_siafi": c.nr_siafi,
        "nr_proposta": nr_proposta,
        "nr_plano_trabalho": c.nr_plano_trabalho,
        "nr_instrumento": nr_instrumento,
        "status": c.situacao,
        "dt_assinatura": c.dt_assinatura,
        "dt_publicacao": c.dt_publicacao,
        "dias_vigencia_atual": dias_vig,
        "vigencia_inicial": c.dt_vigencia_inicial,
        "vigencia_atual": c.dt_vigencia_atual or c.dt_vigencia_final,
        "dias_restantes": dias_rest,
        "dias_restantes_label": dias_rest_label,
        "titulo": c.objeto,
        "objetivo": c.objetivo,
        "prestacao_contas": raw.get("prestacao_contas") or raw.get("status_prestacao"),
        "concedente_orgao": c.orgao_concedente,
        "convenente_nome": c.convenente_nome or raw.get("convenente"),
        "municipio_nome": raw.get("municipio"),
        "tipo_convenente": raw.get("tipo_beneficiario") or raw.get("tipo_convenente") or "ADMINISTRACAO MUNICIPAL",
        "valor_concedente": float(c.valor_concedente) if c.valor_concedente else None,
        "valor_contrapartida": float(c.valor_contrapartida) if c.valor_contrapartida else None,
        "valor_total": float(c.valor_total) if c.valor_total else None,
        "responsaveis": raw.get("responsaveis") or raw.get("responsavel"),
        "proposta_vigencia": raw.get("proposta_vigencia") or raw.get("prop_vigencia"),
        "valor_dotacao_complementar": raw.get("valor_dotacao_complementar") or raw.get("vr_dotacao_compl"),
        "fase_etapa_status": raw.get("fase_etapa_status") or raw.get("fase_etapa") or c.situacao,
        "setor": raw.get("setor"),
        "data_criacao": raw.get("data_criacao") or raw.get("dt_criacao"),
        "qt_alteracoes": c.qt_alteracoes if hasattr(c, "qt_alteracoes") else 0,
        "ano": c.ano,
        "tp_instrumento": c.tp_instrumento or raw.get("tipo"),
        "fonte": c.fonte,
        "workflow": _build_workflow_state(c.situacao),
        "raw_data": raw,
    }


@router.get("/federal/{conv_id}")
async def get_convenio_federal_detail(
    conv_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Detalhes de convenio federal (sem workflow SIGCON, mas mesma estrutura)."""
    q = select(ConvenioFederal).where(ConvenioFederal.id == conv_id)
    r = await db.execute(q)
    c = r.scalar_one_or_none()
    if not c:
        from fastapi import HTTPException
        raise HTTPException(404, "Convenio nao encontrado")
    raw = c.raw_data if isinstance(c.raw_data, dict) else {}
    dias_rest = (c.dt_fim_vigencia - date.today()).days if c.dt_fim_vigencia else None
    return {
        "id": c.id,
        "esfera": "federal",
        "nr_convenio_publicado": c.nr_convenio,
        "nr_siafi": raw.get("nr_siafi"),
        "nr_proposta": raw.get("nr_proposta") or raw.get("ID_PROPOSTA"),
        "nr_plano_trabalho": raw.get("nr_plano"),
        "status": c.situacao,
        "dt_assinatura": c.dt_inicio,
        "dt_publicacao": c.dt_inicio,
        "vigencia_inicial": c.dt_inicio,
        "vigencia_atual": c.dt_fim_vigencia,
        "dias_restantes": dias_rest,
        "dias_restantes_label": "VENCIDO" if dias_rest is not None and dias_rest < 0 else None,
        "titulo": c.objeto,
        "concedente_orgao": c.orgao_concedente,
        "convenente_nome": c.proponente_nome,
        "valor_repasse": float(c.valor_repasse) if c.valor_repasse else None,
        "valor_contrapartida": float(c.valor_contrapartida) if c.valor_contrapartida else None,
        "valor_total": float(c.valor_global) if c.valor_global else None,
        "valor_empenhado": float(c.valor_empenhado) if c.valor_empenhado else None,
        "valor_desembolsado": float(c.valor_desembolsado) if c.valor_desembolsado else None,
        "ano": c.ano,
        "programa": c.programa,
        "fonte": c.fonte,
        "workflow": _build_workflow_state(c.situacao),
        "raw_data": raw,
    }
