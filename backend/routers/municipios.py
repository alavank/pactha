from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text, or_
from datetime import date, datetime, timedelta
from database import get_db
from models import Municipio, ConvenioEstadual
from models.user import User
from schemas.municipio import MunicipioResponse, MunicipioSummary
from services.auth import get_current_user, ensure_municipio_access
from services import authz
from services.registro_rotas import declarado

router = APIRouter(prefix="/api/municipios", tags=["municipios"])

# ⚠️ O resumo soma DUAS fontes no mesmo cartao — SIGCON (`convenios_estadual`) e
# TransfereGov (`transferegov_propostas`) —, entao a exigencia honesta e "uma das
# duas", e nao as duas. `exige()` cobra TODAS as chaves que recebe: com ele, quem
# so tem TransfereGov perderia a home do sistema. Por isso a rota usa
# `declarado()` (que so registra) e a decisao mora no corpo, com `authz.pode`.
_RESUMO_PERMISSOES = ("convenios.ver", "transferegov.ver")


def _parse_dt(s) -> date | None:
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s).strip()[:10], fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


@router.get("", response_model=list[MunicipioResponse])
async def list_municipios(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    q = select(Municipio).where(Municipio.active == True)
    # Escopo: nao-admin so ve os municipios atribuidos a ele
    allowed = getattr(current, "allowed_municipio_ids", None)
    if allowed is not None:
        if not allowed:
            return []
        q = q.where(Municipio.id.in_(allowed))
    result = await db.execute(q.order_by(Municipio.nome))
    return [MunicipioResponse.model_validate(m) for m in result.scalars().all()]


@router.get("/{municipio_id}/summary", response_model=MunicipioSummary,
            dependencies=[declarado(*_RESUMO_PERMISSOES)])
async def municipio_summary(
    municipio_id: int,
    ano: int | None = Query(None, description="Filtra os KPIs por ano (None=todos)"),
    anos: list[int] | None = Query(None, description="Multi-select de ano"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    if not any(authz.pode(current, chave) for chave in _RESUMO_PERMISSOES):
        authz.negar(current, tipo="permissao",
                    exigido=" ou ".join(_RESUMO_PERMISSOES),
                    possui=authz.permissoes_de(current),
                    mensagem="Voce nao tem permissao para esta acao")
    return await summary_core(db, municipio_id, ano=ano, anos=anos)


# ⚠️ SEPARADO DA ROTA DE PROPOSITO, e a separacao e uma trava, nao arrumacao.
#
# `routers/painel.py` monta a home do Painel chamando esta logica. Enquanto ela
# morava DENTRO do endpoint, chamar o endpoint como funcao arrastava junto a
# checagem acima — e as rotas de /api/painel/*, que declaram `bi.ver`, passavam a
# exigir TAMBEM `convenios.ver` ou `transferegov.ver` sem declarar nem uma coisa
# nem outra. MEDIDO: em `AUTHZ_MODO=bloqueio`, um prefeito com exatamente
# `bi.ver` — a concessao honesta para "ele ve o Painel" — levava 403 em
# /visao, /timeline e /narrativa, e o front engole o erro num `.catch()`.
#
# O nucleo nao recebe `current` e nao checa nada: quem checa e a PORTA. Cada
# rota que o usa declara a propria exigencia, e ninguem herda exigencia por
# acidente de import. Mesmo desenho de `status_changes.listar_core`, que
# `routers/bi.py` ja consumia por esta mesma razao.
async def summary_core(
    db: AsyncSession,
    municipio_id: int,
    ano: int | None = None,
    anos: list[int] | None = None,
) -> MunicipioSummary:
    result = await db.execute(select(Municipio).where(Municipio.id == municipio_id))
    mun = result.scalar_one_or_none()
    if not mun:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Municipio nao encontrado")

    # Filtro de ano — SIGCON usa a coluna `ano`; TransfereGov deriva do sufixo do
    # numero_proposta ("xxx/AAAA"). None = todos os anos.
    # convenios_estadual guarda SIGCON-MG *e* FNS (saude, federal). O KPI
    # "Convenios Estaduais" e as vigencias sao so do SIGCON — sem este filtro
    # Piracema/Sao Tiago apareciam com convenios estaduais tendo zero SIGCON.
    _anos = anos or ([ano] if ano else [])

    def _ano_est(q):
        q = q.where(or_(ConvenioEstadual.fonte.is_(None),
                        ~ConvenioEstadual.fonte.ilike("%FNS%")))
        return q.where(ConvenioEstadual.ano.in_(_anos)) if _anos else q
    anos_txt = [str(a) for a in _anos]
    vol_ano_sql = " AND split_part(numero_proposta, '/', 2) = ANY(:anos_txt)" if _anos else ""

    est_count = await db.execute(_ano_est(
        select(func.count()).select_from(ConvenioEstadual).where(ConvenioEstadual.municipio_id == municipio_id)
    ))
    est_valor = await db.execute(_ano_est(
        select(func.coalesce(func.sum(ConvenioEstadual.valor_total), 0))
        .where(ConvenioEstadual.municipio_id == municipio_id)
    ))

    hoje = date.today()
    limite120 = hoje + timedelta(days=120)
    limite60 = hoje + timedelta(days=60)
    # Vencidos ha +90 dias -> prestacao de contas obrigatoria
    venc90 = hoje - timedelta(days=90)
    alertas120 = await db.execute(_ano_est(
        select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id == municipio_id)
        .where(ConvenioEstadual.dt_vigencia_atual <= limite120)
        .where(ConvenioEstadual.dt_vigencia_atual >= hoje)
    ))
    alertas60 = await db.execute(_ano_est(
        select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id == municipio_id)
        .where(ConvenioEstadual.dt_vigencia_atual <= limite60)
        .where(ConvenioEstadual.dt_vigencia_atual >= hoje)
    ))
    prest_contas = await db.execute(_ano_est(
        select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id == municipio_id)
        .where(ConvenioEstadual.dt_vigencia_atual < venc90)
    ))

    # TransfereGov Voluntarias (dt_fim_vigencia eh string dd/mm/yyyy -> parse em Python)
    vol_params: dict = {"m": municipio_id}
    if _anos:
        vol_params["anos_txt"] = anos_txt
    vol = await db.execute(text(
        "SELECT dt_fim_vigencia, COALESCE(valor_global, valor_repasse, 0) "
        "FROM transferegov_propostas WHERE municipio_id = :m" + vol_ano_sql
    ), vol_params)
    vol_rows = vol.fetchall()
    total_vol = len(vol_rows)
    vol_120 = vol_60 = vol_prest = 0
    vol_valor = 0.0
    for (dtf, val) in vol_rows:
        try:
            vol_valor += float(val or 0)
        except (TypeError, ValueError):
            pass
        d = _parse_dt(dtf)
        if not d:
            continue
        if hoje <= d <= limite120:
            vol_120 += 1
            if d <= limite60:
                vol_60 += 1
        elif d < venc90:
            vol_prest += 1

    prest_est = prest_contas.scalar()
    return MunicipioSummary(
        municipio=MunicipioResponse.model_validate(mun),
        total_convenios_estadual=est_count.scalar(),
        valor_total_estadual=float(est_valor.scalar()),
        valor_total_federal=vol_valor,
        total_voluntarias=total_vol,
        alertas_vigencia=alertas120.scalar() + vol_120,
        alertas_vigencia_60d=alertas60.scalar() + vol_60,
        alertas_prestacao_contas=prest_est + vol_prest,
        alertas_prestacao_contas_estadual=prest_est,
        alertas_prestacao_contas_federal=vol_prest,
    )
