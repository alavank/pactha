"""Convenios estaduais (SIGCON-MG).

Apos refactor lean, mantemos apenas a esfera estadual. Federal foi removida.
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_, text
from datetime import date, timedelta
from typing import Optional
from database import get_db
from models import ConvenioEstadual
from schemas.convenio import ConvenioResponse, ConvenioListResponse, ConvenioStats, AlertaVigencia
from services.auth import get_current_user
import math
import os
import re
import httpx

router = APIRouter(prefix="/api/convenios", tags=["convenios"])


def estadual_to_response(c: ConvenioEstadual) -> ConvenioResponse:
    dias = None
    if c.dt_vigencia_atual:
        dias = (c.dt_vigencia_atual - date.today()).days
    elif c.dt_vigencia_final:
        dias = (c.dt_vigencia_final - date.today()).days
    raw = c.raw_data if isinstance(c.raw_data, dict) else {}
    nr_proposta = raw.get("nr_proposta")
    nr_instrumento = raw.get("nr_instrumento")
    nr_plano = c.nr_plano_trabalho
    # Heuristicas para CKAN bulk (raw_data costuma vir vazio):
    # - nr_instrumento SIGCON: 8-12 digits + "/" + 4-digit year (ex: "1481000677/2026")
    # - nr_proposta SIGCON:   6 digits + "/" + 4-digit year       (ex: "001030/2026")
    # - nr_plano_trabalho real eh um inteiro curto (5-7 digits sem barra)
    if not nr_instrumento and c.nr_sigcon and re.match(r"^\d{8,12}/\d{4}$", c.nr_sigcon):
        nr_instrumento = c.nr_sigcon
    if not nr_proposta and nr_plano and re.match(r"^\d{6}/\d{4}$", nr_plano):
        nr_proposta = nr_plano
        nr_plano = None
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
    q = select(ConvenioEstadual.situacao).distinct().where(ConvenioEstadual.situacao.is_not(None))
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    r = await db.execute(q)
    return sorted({row[0].strip() for row in r.all() if row[0]})


@router.get("/anos")
async def list_anos(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    q = select(ConvenioEstadual.ano).distinct().where(ConvenioEstadual.ano.is_not(None))
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    r = await db.execute(q)
    return sorted({int(row[0]) for row in r.all() if row[0]}, reverse=True)


@router.get("", response_model=ConvenioListResponse)
async def list_convenios(
    municipio_id: Optional[int] = None,
    ano: Optional[int] = None,
    situacao: Optional[str] = None,
    situacoes: Optional[list[str]] = Query(None, description="Multi-select de situacao (match exato)"),
    fonte: Optional[str] = None,
    fontes: Optional[list[str]] = Query(None, description="Multi-select fonte"),
    vigencia: Optional[str] = Query(None, description="vence60 | vence120 | prestacao"),
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    q = select(ConvenioEstadual)
    q_count = select(func.count()).select_from(ConvenioEstadual)

    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
        q_count = q_count.where(ConvenioEstadual.municipio_id == municipio_id)
    if ano:
        q = q.where(ConvenioEstadual.ano == ano)
        q_count = q_count.where(ConvenioEstadual.ano == ano)
    if situacoes:
        q = q.where(ConvenioEstadual.situacao.in_(situacoes))
        q_count = q_count.where(ConvenioEstadual.situacao.in_(situacoes))
    elif situacao:
        q = q.where(ConvenioEstadual.situacao.ilike(f"%{situacao}%"))
        q_count = q_count.where(ConvenioEstadual.situacao.ilike(f"%{situacao}%"))
    if fontes:
        # SIGCON estadual tem fonte=NULL ou 'SIGCON-MG'. Adiciona mapeamento.
        est_fontes = []
        for f in fontes:
            if f.upper() == "SIGCON":
                est_fontes.extend(["SIGCON-MG", "SIGCON"])
            else:
                est_fontes.append(f)
        cond = ConvenioEstadual.fonte.in_(est_fontes)
        if "SIGCON" in [f.upper() for f in fontes] or "SIGCON-MG" in fontes:
            cond = or_(cond, ConvenioEstadual.fonte.is_(None))
        q = q.where(cond)
        q_count = q_count.where(cond)
    elif fonte:
        q = q.where(ConvenioEstadual.fonte == fonte)
        q_count = q_count.where(ConvenioEstadual.fonte == fonte)
    # Esta e a tela de CONVENIOS SIGCON-MG (estadual). convenios_estadual tambem
    # guarda PROPOSTAS do FNS (fonte=FNS, saude) — que NAO sao convenios e tem tela
    # propria. Exclui FNS por padrao, exceto se o caller pediu FNS explicitamente.
    _asked_fns = (fonte and "FNS" in fonte.upper()) or (fontes and any("FNS" in f.upper() for f in fontes))
    if not _asked_fns:
        _fns_excl = or_(ConvenioEstadual.fonte.is_(None), ~ConvenioEstadual.fonte.ilike("%FNS%"))
        q = q.where(_fns_excl)
        q_count = q_count.where(_fns_excl)
    if vigencia:
        hoje = date.today()
        vcond = None
        if vigencia == "vence60":
            vcond = and_(ConvenioEstadual.dt_vigencia_atual >= hoje,
                         ConvenioEstadual.dt_vigencia_atual <= hoje + timedelta(days=60))
        elif vigencia == "vence120":
            vcond = and_(ConvenioEstadual.dt_vigencia_atual >= hoje,
                         ConvenioEstadual.dt_vigencia_atual <= hoje + timedelta(days=120))
        elif vigencia == "prestacao":
            vcond = ConvenioEstadual.dt_vigencia_atual < hoje - timedelta(days=90)
        if vcond is not None:
            q = q.where(vcond)
            q_count = q_count.where(vcond)
    if search:
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

    total = (await db.execute(q_count)).scalar() or 0

    q = q.order_by(ConvenioEstadual.dt_publicacao.desc().nullslast())
    q = q.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(q)
    items = [estadual_to_response(c) for c in result.scalars().all()]

    # Sort: vigentes ASC primeiro, vencidos depois (|dias| ASC = mais recentes primeiro), NULL ao final
    def _sort_key(x):
        d = x.dias_restantes
        if d is None:
            return (2, 0)
        if d >= 0:
            return (0, d)
        return (1, -d)
    items.sort(key=_sort_key)

    pages = math.ceil(total / per_page) if total > 0 else 1
    return ConvenioListResponse(items=items, total=total, page=page, per_page=per_page, pages=pages)


@router.get("/stats", response_model=ConvenioStats)
async def convenio_stats(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    stats = ConvenioStats()

    q = select(
        func.count().label("cnt"),
        func.coalesce(func.sum(ConvenioEstadual.valor_total), 0).label("total"),
    )
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    row = (await db.execute(q)).one()
    stats.total_convenios = row.cnt
    stats.valor_total = float(row.total)
    stats.por_esfera["estadual"] = row.cnt

    q = select(ConvenioEstadual.situacao, func.count()).group_by(ConvenioEstadual.situacao)
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    for sit, cnt in (await db.execute(q)).all():
        if sit:
            stats.por_situacao[sit] = cnt

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

    q = select(ConvenioEstadual).where(
        ConvenioEstadual.dt_vigencia_atual <= limite,
        ConvenioEstadual.dt_vigencia_atual >= date.today(),
    )
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    q = q.order_by(ConvenioEstadual.dt_vigencia_atual.asc())
    for c in (await db.execute(q)).scalars().all():
        dias_rest = (c.dt_vigencia_atual - date.today()).days
        alertas.append(AlertaVigencia(
            id=c.id, esfera="estadual", nr_sigcon=c.nr_sigcon,
            objeto=c.objeto, orgao_concedente=c.orgao_concedente,
            dt_fim_vigencia=c.dt_vigencia_atual, dias_restantes=dias_rest,
            valor_total=float(c.valor_total) if c.valor_total else None,
            situacao=c.situacao,
        ))

    # TransfereGov Voluntarias (dt_fim_vigencia eh string dd/mm/yyyy)
    if municipio_id:
        from datetime import datetime as _dt
        vol = await db.execute(text("""
            SELECT numero_proposta, codigo_instrumento, objeto, orgao, situacao, dt_fim_vigencia
            FROM transferegov_propostas WHERE municipio_id = :m
        """), {"m": municipio_id})
        for row in vol.fetchall():
            dtf = None
            for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
                try:
                    dtf = _dt.strptime(str(row[5]).strip()[:10], fmt).date(); break
                except (ValueError, AttributeError, TypeError):
                    continue
            if not dtf or not (date.today() <= dtf <= limite):
                continue
            alertas.append(AlertaVigencia(
                id=0, esfera="voluntaria", nr_convenio=row[1] or row[0],
                nr_sigcon=row[0], objeto=row[2], orgao_concedente=row[3],
                dt_fim_vigencia=dtf, dias_restantes=(dtf - date.today()).days,
                valor_total=None, situacao=row[4],
            ))

    alertas.sort(key=lambda x: x.dias_restantes)
    return alertas


@router.get("/prestacao-contas", response_model=list[AlertaVigencia])
async def alertas_prestacao_contas(
    municipio_id: Optional[int] = None,
    dias: int = Query(90, ge=1, description="Dias minimos apos o vencimento"),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Convenios vencidos ha mais de `dias` (default 90) -> prestacao de contas obrigatoria."""
    corte = date.today() - timedelta(days=dias)
    alertas = []

    q = select(ConvenioEstadual).where(ConvenioEstadual.dt_vigencia_atual < corte)
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    q = q.order_by(ConvenioEstadual.dt_vigencia_atual.desc())
    for c in (await db.execute(q)).scalars().all():
        dias_rest = (c.dt_vigencia_atual - date.today()).days
        alertas.append(AlertaVigencia(
            id=c.id, esfera="estadual", nr_sigcon=c.nr_sigcon,
            objeto=c.objeto, orgao_concedente=c.orgao_concedente,
            dt_fim_vigencia=c.dt_vigencia_atual, dias_restantes=dias_rest,
            valor_total=float(c.valor_total) if c.valor_total else None,
            situacao=c.situacao,
        ))

    # TransfereGov Voluntarias (dt_fim_vigencia eh string dd/mm/yyyy)
    if municipio_id:
        from datetime import datetime as _dt
        vol = await db.execute(text("""
            SELECT numero_proposta, codigo_instrumento, objeto, orgao, situacao, dt_fim_vigencia
            FROM transferegov_propostas WHERE municipio_id = :m
        """), {"m": municipio_id})
        for row in vol.fetchall():
            dtf = None
            for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
                try:
                    dtf = _dt.strptime(str(row[5]).strip()[:10], fmt).date(); break
                except (ValueError, AttributeError, TypeError):
                    continue
            if not dtf or dtf >= corte:
                continue
            alertas.append(AlertaVigencia(
                id=0, esfera="voluntaria", nr_convenio=row[1] or row[0],
                nr_sigcon=row[0], objeto=row[2], orgao_concedente=row[3],
                dt_fim_vigencia=dtf, dias_restantes=(dtf - date.today()).days,
                valor_total=None, situacao=row[4],
            ))

    # Mais recentemente vencidos primeiro (|dias| menor primeiro)
    alertas.sort(key=lambda x: -x.dias_restantes)
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
    sit_norm = _norm_workflow(situacao or "")
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
    c = (await db.execute(q)).scalar_one_or_none()
    if not c:
        from fastapi import HTTPException
        raise HTTPException(404, "Convenio nao encontrado")

    raw = c.raw_data if isinstance(c.raw_data, dict) else {}
    nr_proposta = raw.get("nr_proposta")
    nr_instrumento = raw.get("nr_instrumento")
    if not nr_instrumento and c.nr_sigcon and re.match(r"^\d{8,12}/\d{4}$", c.nr_sigcon):
        nr_instrumento = c.nr_sigcon
    # Nº Convenio Publicado = numero do INSTRUMENTO (formato XXXXXXXXXX/YYYY).
    # Quando o registro veio do scraper, nr_sigcon eh o SIAFI numerico -> nao usar.
    nr_conv_pub = nr_instrumento or (c.nr_sigcon if c.nr_sigcon and "/" in c.nr_sigcon else None)

    dias_vig = None
    if c.dt_vigencia_inicial and (c.dt_vigencia_atual or c.dt_vigencia_final):
        dt_fim = c.dt_vigencia_atual or c.dt_vigencia_final
        dias_vig = (dt_fim - c.dt_vigencia_inicial).days

    dias_rest = None
    dias_rest_label = None
    if c.dt_vigencia_atual or c.dt_vigencia_final:
        dt_fim = c.dt_vigencia_atual or c.dt_vigencia_final
        dias_rest = (dt_fim - date.today()).days
        if dias_rest < -90:
            dias_rest_label = "VENCIDO +90 DIAS - PRESTACAO DE CONTAS"
        elif dias_rest < 0:
            dias_rest_label = "VENCIDO"

    return {
        "id": c.id,
        "esfera": "estadual",
        "nr_convenio_publicado": nr_conv_pub,
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


@router.post("/refresh-sigcon")
async def refresh_sigcon(
    _=Depends(get_current_user),
):
    """Dispara execucao on-demand do scraper SIGCON-MG via Railway API.

    O scraper roda como cron-job no service `pacta-cron-sigcon` (Dockerfile
    com Chromium + Playwright). Esse endpoint chama a mutation
    `serviceInstanceRedeploy` no Railway pra promover o ultimo build do cron,
    o que faz Railway iniciar nova instancia que executa
    `python ingestion/run_sigcon_cron.py` automaticamente.

    Levarah ~1-2min ate o resultado aparecer no banco. Frontend deve fazer
    polling em /municipios/{id}/summary apos o trigger.

    Requer env vars no pacta-api: RAILWAY_API_TOKEN, RAILWAY_CRON_SERVICE_ID,
    RAILWAY_ENVIRONMENT_ID.
    """
    token = os.getenv("RAILWAY_API_TOKEN")
    service_id = os.getenv("RAILWAY_CRON_SERVICE_ID")
    env_id = os.getenv("RAILWAY_ENVIRONMENT_ID")
    if not (token and service_id and env_id):
        raise HTTPException(503,
            "Refresh manual desabilitado: faltam env vars "
            "(RAILWAY_API_TOKEN, RAILWAY_CRON_SERVICE_ID, RAILWAY_ENVIRONMENT_ID).")

    mutation = (
        'mutation{serviceInstanceRedeploy('
        f'serviceId:"{service_id}",environmentId:"{env_id}"'
        ')}'
    )
    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(
                "https://backboard.railway.com/graphql/v2",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"query": mutation},
            )
            data = r.json()
            if data.get("errors"):
                raise HTTPException(502, f"Railway API: {data['errors'][0].get('message')}")
            if not data.get("data", {}).get("serviceInstanceRedeploy"):
                raise HTTPException(502, "Railway recusou redeploy")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Erro chamando Railway: {e}")

    return {
        "status": "triggered",
        "message": "Scraper SIGCON iniciado em background. Os dados serao atualizados em 1-2 minutos.",
        "service": "pacta-cron-sigcon",
    }
