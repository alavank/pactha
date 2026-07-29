"""Nucleo do Painel de Indicadores - BI: resolucao de escopo + agregacoes
SET-AWARE (multi-municipio) para a "visao consolidada" da assessoria.

Fica SEPARADO de routers/painel.py (que segue por-municipio, vivo em producao):
aqui concentramos tudo que precisa varrer um CONJUNTO de municipios com
`= ANY(:ids)`. Para um conjunto de 1 municipio o resultado e byte-identico ao
por-municipio (mesma matematica, mesmo filtro FNS/ano) — o que garante que
/api/bi/overview?municipio_id=X bata com /api/painel/X/visao.

Todas as funcoes sao READ-ONLY e sem gate de auth (o gate vive em resolve_scope
e no get_current_user do router).
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select, func, text, or_
from sqlalchemy.ext.asyncio import AsyncSession

from models import ConvenioEstadual
from models.user import User
from services.auth import ensure_municipio_access


# --------------------------------------------------------------------------
# Escopo
# --------------------------------------------------------------------------

async def resolve_scope(
    db: AsyncSession,
    user: User,
    municipio_id: Optional[int] = None,
    subset: Optional[list[int]] = None,
) -> tuple[list[int], bool]:
    """Resolve o CONJUNTO efetivo de municipios do usuario para o BI.

    - `municipio_id` informado -> escopo de 1 municipio (valida com
      ensure_municipio_access; admin passa, nao-admin precisa te-lo). is_consolidado=False.
    - `municipio_id` ausente -> CONSOLIDADO:
        admin (allowed=None) -> todos os municipios ativos (opcionalmente ∩ subset);
        nao-admin -> seu conjunto `allowed_municipio_ids` (vazio -> 403).
      NUNCA chama ensure_municipio_access(None) (que barraria o nao-admin).
    """
    if municipio_id is not None:
        ensure_municipio_access(user, municipio_id)
        return [int(municipio_id)], False

    subset_set: Optional[set[int]] = None
    if subset:
        try:
            subset_set = {int(x) for x in subset}
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="subset invalido")

    allowed = getattr(user, "allowed_municipio_ids", None)
    if allowed is None:  # admin -> todos os ativos
        rows = (await db.execute(
            text("SELECT id FROM municipios WHERE active = true"))).fetchall()
        ids = [r[0] for r in rows]
        if subset_set is not None:
            ids = [i for i in ids if i in subset_set]
    else:  # nao-admin -> conjunto atribuido
        ids = sorted(allowed)
        if subset_set is not None:
            ids = [i for i in ids if i in subset_set]
        if not ids:
            raise HTTPException(status_code=403, detail="Voce nao tem municipios no escopo")

    if not ids:
        raise HTTPException(status_code=404, detail="Nenhum municipio no escopo")
    return ids, True


def scope_signature(ids: list[int], is_consolidado: bool) -> str:
    """Chave estavel do escopo para o cache do overview (independe do usuario:
    dois usuarios com o mesmo conjunto compartilham cache)."""
    return ("c" if is_consolidado else "s") + ":" + ",".join(str(i) for i in sorted(ids))


# --------------------------------------------------------------------------
# Periodo (MULTI-ANO)
# --------------------------------------------------------------------------

def anos_list(v) -> Optional[list[int]]:
    """Normaliza o filtro de periodo para uma LISTA de anos (ou None = todos).

    Aceita o formato legado (`ano=2025`, int) e o novo (`anos=[2023,2024,2025]`)
    no MESMO parametro — o prefeito costuma querer o mandato inteiro, nao um ano.
    Vazio/None/lixo -> None (sem filtro), preservando o comportamento anterior."""
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return [int(v)] if int(v) else None
    if isinstance(v, str):
        v = [p for p in v.replace(";", ",").split(",")]
    out: set[int] = set()
    for x in v or []:
        try:
            n = int(str(x).strip())
        except (TypeError, ValueError):
            continue
        if 1990 < n < 2100:
            out.add(n)
    return sorted(out) or None


def anos_signature(anos: Optional[list[int]]) -> str:
    """Parte do periodo na chave de cache. None -> '0' (todos)."""
    return ",".join(str(a) for a in anos) if anos else "0"


# --------------------------------------------------------------------------
# Agregacoes SET-AWARE (espelham routers/municipios.municipio_summary etc.)
# --------------------------------------------------------------------------

def _parse_dt(s) -> Optional[date]:
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s).strip()[:10], fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


async def bi_kpis(db: AsyncSession, ids: list[int], ano=None) -> dict:
    """Versao SET dos KPIs de municipio_summary (routers/municipios.py:60-137).
    Soma sobre `ids`. Para ids=[X] devolve os MESMOS numeros do por-municipio.
    Nao inclui o objeto `municipio` (nao ha um so); adiciona `municipios_count`.

    `ano` aceita int (legado) OU lista de anos (mandato inteiro) — ver anos_list."""
    if not ids:
        return {
            "total_convenios_estadual": 0, "total_voluntarias": 0,
            "valor_total_estadual": 0.0, "valor_total_federal": 0.0,
            "alertas_vigencia": 0, "alertas_vigencia_60d": 0,
            "alertas_prestacao_contas": 0, "alertas_prestacao_contas_estadual": 0,
            "alertas_prestacao_contas_federal": 0, "municipios_count": 0,
        }

    anos = anos_list(ano)

    # convenios_estadual guarda SIGCON-MG *e* FNS (federal). KPI "estaduais" e as
    # vigencias sao so do SIGCON -> exclui FNS. None=todos os anos.
    def _ano_est(q):
        q = q.where(or_(ConvenioEstadual.fonte.is_(None),
                        ~ConvenioEstadual.fonte.ilike("%FNS%")))
        return q.where(ConvenioEstadual.ano.in_(anos)) if anos else q

    vol_ano_sql = " AND split_part(numero_proposta, '/', 2) = ANY(:anos_txt)" if anos else ""

    est_count = await db.execute(_ano_est(
        select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id.in_(ids))))
    est_valor = await db.execute(_ano_est(
        select(func.coalesce(func.sum(ConvenioEstadual.valor_total), 0))
        .where(ConvenioEstadual.municipio_id.in_(ids))))

    hoje = date.today()
    limite120 = hoje + timedelta(days=120)
    limite60 = hoje + timedelta(days=60)
    venc90 = hoje - timedelta(days=90)  # vencidos ha +90 -> prestacao obrigatoria

    alertas120 = await db.execute(_ano_est(
        select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id.in_(ids))
        .where(ConvenioEstadual.dt_vigencia_atual <= limite120)
        .where(ConvenioEstadual.dt_vigencia_atual >= hoje)))
    alertas60 = await db.execute(_ano_est(
        select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id.in_(ids))
        .where(ConvenioEstadual.dt_vigencia_atual <= limite60)
        .where(ConvenioEstadual.dt_vigencia_atual >= hoje)))
    prest_contas = await db.execute(_ano_est(
        select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id.in_(ids))
        .where(ConvenioEstadual.dt_vigencia_atual < venc90)))

    # TransfereGov Voluntarias (dt_fim_vigencia eh string dd/mm/yyyy -> parse em Python)
    vol_params: dict = {"ids": ids}
    if anos:
        vol_params["anos_txt"] = [str(a) for a in anos]
    vol = await db.execute(text(
        "SELECT dt_fim_vigencia, COALESCE(valor_global, valor_repasse, 0) "
        "FROM transferegov_propostas WHERE municipio_id = ANY(:ids)" + vol_ano_sql
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
    return {
        "total_convenios_estadual": est_count.scalar(),
        "valor_total_estadual": float(est_valor.scalar()),
        "valor_total_federal": vol_valor,
        "total_voluntarias": total_vol,
        "alertas_vigencia": alertas120.scalar() + vol_120,
        "alertas_vigencia_60d": alertas60.scalar() + vol_60,
        "alertas_prestacao_contas": prest_est + vol_prest,
        "alertas_prestacao_contas_estadual": prest_est,
        "alertas_prestacao_contas_federal": vol_prest,
        "municipios_count": len(ids),
    }


async def bi_cauc_rollup(db: AsyncSession, ids: list[int]) -> dict:
    """Rollup do semaforo CAUC sobre um conjunto de municipios. Para 1 municipio,
    `por_municipio` tem 1 linha (o frontend renderiza o mesmo gauge/segbar)."""
    if not ids:
        return {"total_municipios": 0, "com_dados": 0, "regulares": 0,
                "com_pendencia": 0, "pendencias_total": 0, "por_municipio": []}
    rows = (await db.execute(text(
        "SELECT municipio_id, nome, regular, pendencias, pendencias_codigos "
        "FROM cauc_situacao WHERE municipio_id = ANY(:ids)"
    ), {"ids": ids})).fetchall()
    por = []
    regulares = com_pend = pend_total = 0
    for r in rows:
        reg = r[2]
        pend = r[3] or 0
        por.append({
            "municipio_id": r[0], "nome": r[1], "regular": reg,
            "pendencias": pend, "pendencias_codigos": list(r[4] or []),
        })
        if reg:
            regulares += 1
        if pend:
            com_pend += 1
        pend_total += pend
    # ordena: irregulares/pendentes primeiro (o que exige atencao)
    por.sort(key=lambda x: (x["regular"] is True, x["nome"] or ""))
    return {
        "total_municipios": len(ids),
        "com_dados": len(rows),
        "regulares": regulares,
        "com_pendencia": com_pend,
        "pendencias_total": pend_total,
        "por_municipio": por,
    }


async def bi_saude_rollup(db: AsyncSession, ids: list[int]) -> Optional[dict]:
    """Divida do Fundo Estadual de Saude (Acordo FES/SES-MG) somada sobre o
    conjunto. Espelha painel.py:52-57; para ids=[X] === por-municipio. Linhas com
    municipio_id NULL (credor nao atribuido a municipio) ficam de fora."""
    if not ids:
        return None
    row = (await db.execute(text(
        "SELECT COALESCE(SUM(divida_atual),0), COALESCE(SUM(total_pago),0), "
        "COALESCE(SUM(divida_inicial),0) FROM acordofes_credor WHERE municipio_id = ANY(:ids)"
    ), {"ids": ids})).first()
    if row and (row[0] or row[1] or row[2]):
        return {"divida_atual": float(row[0] or 0), "pago": float(row[1] or 0),
                "inicial": float(row[2] or 0)}
    return None
