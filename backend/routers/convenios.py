"""Convenios estaduais (SIGCON-MG).

Apos refactor lean, mantemos apenas a esfera estadual. Federal foi removida.
"""
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_, text
from datetime import date, timedelta
from typing import Optional
from database import get_db
from models import ConvenioEstadual
from schemas.convenio import ConvenioResponse, ConvenioListResponse, ConvenioStats, AlertaVigencia
from services.auth import get_current_user, ensure_municipio_access, ensure_tela
from services.audit import registrar
# Trava de permissao em MODO AVISO. `ensure_dono` responde a pergunta que
# `ensure_tela` nao responde: "este id e de um municipio que a pessoa enxerga?".
from services import authz
from services.registro_rotas import exige
from services.bi import anos_list
from models.user import User
import math
import os
import re

router = APIRouter(prefix="/api/convenios", tags=["convenios"])


def _dias_restantes_sigcon(c: ConvenioEstadual, computed):
    """'Dias Restantes de Vigencia' — usa o valor OFICIAL do SIGCON quando existe
    (raw_data.dias_restantes_str), que conta contra a vigencia EFETIVA (dias de
    vigencia a partir do inicio), e NAO contra o fim formal exibido — por isso o
    calculo (dt_vigencia_atual - hoje) diverge (ex.: SIGCON=50 vs calculo=58).
    Fallback: valor computado (CKAN/sem detalhe SIGCON)."""
    raw = c.raw_data if isinstance(c.raw_data, dict) else {}
    s = raw.get("dias_restantes_str")
    if s is not None and str(s).strip().lstrip("-").isdigit():
        return int(str(s).strip())
    return computed


def estadual_to_response(c: ConvenioEstadual) -> ConvenioResponse:
    dias = None
    if c.dt_vigencia_atual:
        dias = (c.dt_vigencia_atual - date.today()).days
    elif c.dt_vigencia_final:
        dias = (c.dt_vigencia_final - date.today()).days
    dias = _dias_restantes_sigcon(c, dias)
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


@router.get("/situacoes", dependencies=[exige("convenios.ver")])
async def list_situacoes(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "convenios")
    q = select(ConvenioEstadual.situacao).distinct().where(ConvenioEstadual.situacao.is_not(None))
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    # Exclui FNS (tem tela propria). Sem isso, situacoes exclusivas do FNS
    # ('Pago','Empenhado','Pendente') apareciam no filtro do SIGCON e casavam 0
    # convenios (a lista SIGCON exclui FNS) -> filtro "vazio".
    q = q.where(or_(ConvenioEstadual.fonte.is_(None), ~ConvenioEstadual.fonte.ilike("%FNS%")))
    r = await db.execute(q)
    return sorted({row[0].strip() for row in r.all() if row[0]})


@router.get("/anos", dependencies=[exige("convenios.ver")])
async def list_anos(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "convenios")
    # Mesma exclusao do listing: FNS mora na mesma tabela e tem tela propria.
    # Sem isso o dropdown oferecia 2010-2013 (so FNS) e a lista voltava vazia.
    q = (select(ConvenioEstadual.ano).distinct()
         .where(ConvenioEstadual.ano.is_not(None))
         .where(or_(ConvenioEstadual.fonte.is_(None), ~ConvenioEstadual.fonte.ilike("%FNS%"))))
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    r = await db.execute(q)
    return sorted({int(row[0]) for row in r.all() if row[0]}, reverse=True)


@router.get("", response_model=ConvenioListResponse,
            dependencies=[exige("convenios.ver")])
async def list_convenios(
    municipio_id: Optional[int] = None,
    # Os plurais convivem com os singulares de proposito: e o mesmo padrao de
    # `situacoes`/`situacao` e de routers/parlamentares.py. Link antigo, KPI do
    # dashboard e integracao que ainda mandam o singular continuam funcionando.
    ano: Optional[int] = None,
    anos: Optional[list[int]] = Query(None, description="Multi-select de ano"),
    situacao: Optional[str] = None,
    situacoes: Optional[list[str]] = Query(None, description="Multi-select de situacao (match exato)"),
    fonte: Optional[str] = None,
    fontes: Optional[list[str]] = Query(None, description="Multi-select fonte"),
    vigencia: Optional[str] = Query(None, description="vence60 | vence120 | prestacao"),
    vigencias: Optional[list[str]] = Query(None, description="Multi-select de vigencia (uniao)"),
    pagamento: Optional[str] = Query(None, description="pago | parcial | nao_pago (via valor_repassado)"),
    pagamentos: Optional[list[str]] = Query(None, description="Multi-select de pagamento (uniao)"),
    # PERIODO LIVRE. Filtra pelo FIM DA VIGENCIA — decisao do dono, e a mesma
    # semantica ja usada em routers/transferegov.py (`vig_fim_de`/`vig_fim_ate`),
    # porque e a pergunta que a equipe faz de verdade: "o que vence entre marco
    # e outubro". Um lado so e valido ("a partir de marco").
    vig_fim_de: Optional[date] = Query(None, description="Fim de vigencia >= esta data"),
    vig_fim_ate: Optional[date] = Query(None, description="Fim de vigencia <= esta data"),
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    # Teto igual ao das Emendas Estaduais (le=2000). A tela do SIGCON agrupa
    # por ano num cartao por exercicio, e com teto de 100 o cartao contava so
    # o que cabia na pagina — "12 convenio(s) nesta pagina" ao lado de uma
    # tela vizinha que mostra o ano inteiro. Sao dois menus colados.
    per_page: int = Query(20, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "convenios")
    q = select(ConvenioEstadual)
    q_count = select(func.count()).select_from(ConvenioEstadual)

    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
        q_count = q_count.where(ConvenioEstadual.municipio_id == municipio_id)
    _anos = anos or ([ano] if ano else [])
    if _anos:
        q = q.where(ConvenioEstadual.ano.in_(_anos))
        q_count = q_count.where(ConvenioEstadual.ano.in_(_anos))
    if situacoes:
        q = q.where(ConvenioEstadual.situacao.in_(situacoes))
        q_count = q_count.where(ConvenioEstadual.situacao.in_(situacoes))
    elif situacao:
        q = q.where(ConvenioEstadual.situacao.ilike(f"%{situacao}%"))
        q_count = q_count.where(ConvenioEstadual.situacao.ilike(f"%{situacao}%"))
    _pagamentos = pagamentos or ([pagamento] if pagamento else [])
    if _pagamentos:
        vr = ConvenioEstadual.valor_repassado
        vc = ConvenioEstadual.valor_concedente
        # UNIAO, nao intersecao: marcar "pago" e "parcial" tem que trazer os
        # dois grupos. Com AND o resultado seria sempre vazio, porque as
        # condicoes se excluem — filtro que devolve zero parece base sem dado.
        _regras = {
            "pago":     and_(vr.is_not(None), vr > 0, vc.is_not(None), vr >= vc),
            "parcial":  and_(vr.is_not(None), vr > 0, or_(vc.is_(None), vr < vc)),
            "nao_pago": or_(vr.is_(None), vr == 0),
        }
        conds = [_regras[p] for p in _pagamentos if p in _regras]
        if conds:
            pcond = conds[0] if len(conds) == 1 else or_(*conds)
            q = q.where(pcond)
            q_count = q_count.where(pcond)
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
    _vigencias = vigencias or ([vigencia] if vigencia else [])
    if _vigencias:
        hoje = date.today()
        dv = ConvenioEstadual.dt_vigencia_atual
        # UNIAO pelo mesmo motivo do pagamento. Note que "vence60" e um
        # SUBCONJUNTO de "vence120": marcar os dois e igual a marcar so o 120,
        # e isso e o esperado — nao ha o que "somar" alem do maior.
        _regras = {
            "vence30":   and_(dv >= hoje, dv <= hoje + timedelta(days=30)),
            "vence60":   and_(dv >= hoje, dv <= hoje + timedelta(days=60)),
            "vence90":   and_(dv >= hoje, dv <= hoje + timedelta(days=90)),
            "vence120":  and_(dv >= hoje, dv <= hoje + timedelta(days=120)),
            "prestacao": dv < hoje - timedelta(days=90),
        }
        conds = [_regras[v] for v in _vigencias if v in _regras]
        if conds:
            vcond = conds[0] if len(conds) == 1 else or_(*conds)
            q = q.where(vcond)
            q_count = q_count.where(vcond)
    if vig_fim_de or vig_fim_ate:
        # `dt_vigencia_atual` e a data que a tela mostra e a que o alerta usa;
        # `dt_vigencia_final` e o fim FORMAL, que diverge quando houve aditivo.
        # Filtrar pela primeira mantem o filtro coerente com a coluna "Fim da
        # Vigencia" — filtro que discorda da tela destroi a confianca no numero.
        dv = func.coalesce(ConvenioEstadual.dt_vigencia_atual,
                           ConvenioEstadual.dt_vigencia_final)
        if vig_fim_de:
            q = q.where(dv >= vig_fim_de)
            q_count = q_count.where(dv >= vig_fim_de)
        if vig_fim_ate:
            q = q.where(dv <= vig_fim_ate)
            q_count = q_count.where(dv <= vig_fim_ate)
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


@router.get("/stats", response_model=ConvenioStats,
            dependencies=[exige("convenios.ver")])
async def convenio_stats(
    municipio_id: Optional[int] = None,
    ano: Optional[int] = Query(None, description="Filtra por ano (None=todos)"),
    anos: Optional[list[int]] = Query(None, description="Multi-select de ano"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "convenios")
    _anos = anos or ([ano] if ano else [])
    stats = ConvenioStats()
    # FNS (saude) mora na mesma tabela mas nao e convenio estadual — fora dos KPIs.
    _sem_fns = or_(ConvenioEstadual.fonte.is_(None), ~ConvenioEstadual.fonte.ilike("%FNS%"))

    q = select(
        func.count().label("cnt"),
        func.coalesce(func.sum(ConvenioEstadual.valor_total), 0).label("total"),
    ).where(_sem_fns)
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    if _anos:
        q = q.where(ConvenioEstadual.ano.in_(_anos))
    row = (await db.execute(q)).one()
    stats.total_convenios = row.cnt
    stats.valor_total = float(row.total)
    stats.por_esfera["estadual"] = row.cnt

    q = (select(ConvenioEstadual.situacao, func.count())
         .where(_sem_fns).group_by(ConvenioEstadual.situacao))
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    if _anos:
        q = q.where(ConvenioEstadual.ano.in_(_anos))
    for sit, cnt in (await db.execute(q)).all():
        if sit:
            stats.por_situacao[sit] = cnt

    return stats


@router.get("/alertas", response_model=list[AlertaVigencia],
            dependencies=[exige("convenios.ver")])
async def alertas_vigencia(
    municipio_id: Optional[int] = None,
    dias: int = Query(120, ge=1),
    ano: Optional[int] = Query(None, description="Filtra por ano (None=todos)"),
    anos: Optional[list[int]] = Query(None, description="Multi-select de ano"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "convenios")
    # O nucleo ja normaliza com `anos_list()`, que aceita int OU lista — aqui
    # so falta a assinatura do FastAPI deixar a lista chegar.
    return await query_alertas_vigencia(db, municipio_id, dias, anos or ano)


async def query_alertas_vigencia(
    db: AsyncSession,
    municipio_id: Optional[int] = None,
    dias: int = 120,
    ano: Optional[int] = None,
    municipio_ids: Optional[list[int]] = None,
) -> list:
    """Nucleo dos alertas de vigencia (<= `dias`), SEM gate de auth. Reusado pelo
    endpoint /api/convenios/alertas e pelo Painel Executivo.

    `municipio_ids` (lista) = escopo CONSOLIDADO (`= ANY(:mids)`), usado quando
    `municipio_id` (unico) e None. Ambos None = todos (comportamento original).

    `ano` aceita int (legado) ou lista de anos — ver services.bi.anos_list."""
    _anos = anos_list(ano)
    limite = date.today() + timedelta(days=dias)
    alertas = []

    q = select(ConvenioEstadual).where(
        ConvenioEstadual.dt_vigencia_atual <= limite,
        ConvenioEstadual.dt_vigencia_atual >= date.today(),
    )
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    elif municipio_ids:
        q = q.where(ConvenioEstadual.municipio_id.in_(list(municipio_ids)))
    if _anos:
        q = q.where(ConvenioEstadual.ano.in_(_anos))
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
    if municipio_id or municipio_ids:
        from datetime import datetime as _dt
        if municipio_id:
            _mun_sql = "municipio_id = :m"; _vp = {"m": municipio_id}
        else:
            _mun_sql = "municipio_id = ANY(:mids)"; _vp = {"mids": list(municipio_ids)}
        _vsql = "AND split_part(numero_proposta, '/', 2) = ANY(:anos_txt)" if _anos else ""
        if _anos:
            _vp["anos_txt"] = [str(a) for a in _anos]
        vol = await db.execute(text(f"""
            SELECT numero_proposta, codigo_instrumento, objeto, orgao, situacao, dt_fim_vigencia
            FROM transferegov_propostas WHERE {_mun_sql} {_vsql}
        """), _vp)
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


@router.get("/prestacao-contas", response_model=list[AlertaVigencia],
            dependencies=[exige("convenios.ver")])
async def alertas_prestacao_contas(
    municipio_id: Optional[int] = None,
    dias: int = Query(90, ge=1, description="Dias minimos apos o vencimento"),
    ano: Optional[int] = Query(None, description="Filtra por ano (None=todos)"),
    anos: Optional[list[int]] = Query(None, description="Multi-select de ano"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Convenios vencidos ha mais de `dias` (default 90) -> prestacao de contas obrigatoria."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "convenios")
    return await query_prestacao_contas(db, municipio_id, dias, anos or ano)


async def query_prestacao_contas(
    db: AsyncSession,
    municipio_id: Optional[int] = None,
    dias: int = 90,
    ano: Optional[int] = None,
    municipio_ids: Optional[list[int]] = None,
) -> list:
    """Nucleo da prestacao de contas vencida (+`dias`), SEM gate de auth. Reusado
    pelo endpoint /api/convenios/prestacao-contas e pelo Painel Executivo.

    `municipio_ids` (lista) = escopo CONSOLIDADO (`= ANY(:mids)`), usado quando
    `municipio_id` (unico) e None. Ambos None = todos (comportamento original).

    `ano` aceita int (legado) ou lista de anos — ver services.bi.anos_list."""
    _anos = anos_list(ano)
    corte = date.today() - timedelta(days=dias)
    alertas = []

    q = select(ConvenioEstadual).where(ConvenioEstadual.dt_vigencia_atual < corte)
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    elif municipio_ids:
        q = q.where(ConvenioEstadual.municipio_id.in_(list(municipio_ids)))
    if _anos:
        q = q.where(ConvenioEstadual.ano.in_(_anos))
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
    if municipio_id or municipio_ids:
        from datetime import datetime as _dt
        if municipio_id:
            _mun_sql = "municipio_id = :m"; _vp = {"m": municipio_id}
        else:
            _mun_sql = "municipio_id = ANY(:mids)"; _vp = {"mids": list(municipio_ids)}
        _vsql = "AND split_part(numero_proposta, '/', 2) = ANY(:anos_txt)" if _anos else ""
        if _anos:
            _vp["anos_txt"] = [str(a) for a in _anos]
        vol = await db.execute(text(f"""
            SELECT numero_proposta, codigo_instrumento, objeto, orgao, situacao, dt_fim_vigencia
            FROM transferegov_propostas WHERE {_mun_sql} {_vsql}
        """), _vp)
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


@router.get("/estadual/{conv_id}", dependencies=[exige("convenios.ver")])
async def get_convenio_estadual_detail(
    conv_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Detalhes ricos de um convenio estadual: campos + workflow SIGCON + raw_data util."""
    # Este endpoint nao checava NADA alem de estar logado, enquanto a LISTA que
    # leva ate ele (`GET /api/convenios`) sempre checou as duas coisas. Quem
    # soubesse o id — e id e um inteiro sequencial — lia o convenio inteiro de
    # qualquer municipio do tenant: objeto, valores, dados bancarios (banco,
    # agencia, conta) e o `raw_data` cru do SIGCON.
    #
    # SAO DOIS GATES e o segundo nao e repeticao do primeiro. `ensure_tela` diz
    # que a pessoa pode mexer com SIGCON; `ensure_dono` diz que ESTE convenio
    # pertence a um municipio que ela enxerga. Sem o segundo, quem tem a tela
    # tem a tela do tenant INTEIRO — e "detalhe por id" e justamente onde isso
    # aparece, porque a listagem filtra por municipio e o detalhe nao filtrava
    # nada.
    authz.exigir_tela(current, "convenios")
    # Custa um SELECT de uma coluna so. Registro inexistente devolve None e NAO
    # vira 403: quem responde por "nao achei" continua sendo o 404 abaixo.
    await authz.ensure_dono(db, "convenios_estadual", "id", conv_id, current)
    q = select(ConvenioEstadual).where(ConvenioEstadual.id == conv_id)
    c = (await db.execute(q)).scalar_one_or_none()
    if not c:
        from fastapi import HTTPException
        raise HTTPException(404, "Convênio não encontrado")

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
    dias_rest = _dias_restantes_sigcon(c, dias_rest)  # valor oficial do SIGCON quando houver
    if dias_rest is not None:
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


@router.post("/refresh-sigcon", dependencies=[exige("convenios.atualizar")])
async def refresh_sigcon(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Enfileira execucao on-demand do scraper SIGCON-MG (sem depender de plataforma).

    Insere um job 'pending' na tabela `scraper_jobs`. O Worker (Scheduled Task
    no Coolify) roda `ingestion/run_queue_sigcon.py` a cada ~2min, consome o job
    (FOR UPDATE SKIP LOCKED) e executa `run_sigcon_cron.py`. Dedup: nao enfileira
    se ja houver um job 'pending'/'running'.

    Leva ~1-2min ate o resultado aparecer no banco. Frontend deve fazer polling
    em /municipios/{id}/summary apos o trigger.
    """
    # Coleta pesada disparada por quem quiser: o botao vive na tela do SIGCON,
    # mas o endpoint aceitava qualquer sessao autenticada. Uma coleta muda
    # situacao e valores de dezenas de convenios de uma vez e ocupa o worker.
    #
    # SO A TELA, sem municipio, e isso e deliberado: o job enfileirado nao tem
    # recorte de municipio nenhum (`INSERT INTO scraper_jobs (tipo, status)`) —
    # ele recoleta o tenant inteiro. Inventar um `municipio_id` aqui para poder
    # checa-lo seria mudar a logica do endpoint, e nao acrescentar gate.
    authz.exigir_tela(current, "convenios")
    row = (await db.execute(text(
        "INSERT INTO scraper_jobs (tipo, status) "
        "SELECT 'sigcon', 'pending' "
        "WHERE NOT EXISTS ("
        " SELECT 1 FROM scraper_jobs WHERE tipo = 'sigcon' AND status IN ('pending', 'running')"
        ") RETURNING id"
    ))).first()
    await db.commit()
    # Disparar coletor muda o dado que a prefeitura ve: uma coleta pode alterar
    # situacao e valores de dezenas de convenios de uma vez. O pedido fica
    # registrado inclusive quando ele NAO enfileira (dedup) — a pergunta que
    # aparece depois e "quem mandou atualizar antes do numero mudar", e um pedido
    # recusado por ja haver fila tambem responde isso.
    await registrar(
        db, action="coletor.disparo", user=current, request=request,
        target_type="scraper", target_id="sigcon", alvo_nome="SIGCON-MG",
        details={"fonte": "sigcon", "origem": "tela do usuário",
                 "enfileirado": row is not None,
                 "job_id": row[0] if row else None},
    )
    if row is None:
        return {
            "status": "already_queued",
            "message": "Uma atualização do SIGCON já está na fila ou em execução.",
        }
    return {
        "status": "triggered",
        "message": "Scraper SIGCON enfileirado. Os dados serão atualizados em 1-2 minutos.",
        "job_id": row[0],
    }
