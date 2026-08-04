"""Monitor de FRESCOR das fontes de dados (admin).

Mostra, por fonte: quando os dados foram atualizados pela ultima vez (max
updated_at da tabela) e quando o coletor rodou pela ultima vez (ingestion_log),
com um status fresco/atrasado/critico. Serve p/ ver rapidamente o que esta
desatualizado e agir (ex.: sessao FNS expirada, credencial SIGCON invalida).
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from services.auth import get_current_user
from services.registro_rotas import exige
from models.user import User

router = APIRouter(prefix="/api/admin/freshness", tags=["admin"])

# (rotulo, SQL que retorna (max_timestamp, count), source no ingestion_log)
_SOURCES = [
    ("SIGCON — Convênios estaduais",
     "SELECT max(updated_at), count(*) FROM convenios_estadual WHERE fonte IS NULL OR fonte NOT ILIKE '%FNS%'",
     "sigcon_scraper"),
    ("FNS — Saúde (federal)",
     "SELECT max(updated_at), count(*) FROM convenios_estadual WHERE fonte ILIKE '%FNS%'",
     "fns"),
    ("SISMOB — Obras da Saúde",
     "SELECT max(updated_at), count(*) FROM sismob_obras WHERE ausente_desde IS NULL",
     "sismob"),
    ("TransfereGov — Voluntárias",
     "SELECT max(updated_at), count(*) FROM transferegov_propostas",
     "transferegov_voluntarias"),
    ("TransfereGov — PAC (Novo PAC)",
     "SELECT max(updated_at), count(*) FROM transferegov_pac",
     None),
    ("Emendas estaduais",
     "SELECT max(updated_at), count(*) FROM emendas_estaduais",
     None),
    ("CAUC — Regularidade federal",
     "SELECT max(data_pesquisa)::timestamptz, count(*) FROM cauc_situacao",
     "cauc"),
    ("Acordo FES — Dívida saúde",
     "SELECT NULL::timestamptz, count(*) FROM acordofes_credor",
     "acordofes"),
    ("SIMEC-PAR (MEC)",
     "SELECT max(updated_at), count(*) FROM simec_par_liberacoes",
     "simec_par"),
]


def _status(age_days: float | None) -> str:
    if age_days is None:
        return "desconhecido"
    if age_days <= 2:
        return "fresco"
    if age_days <= 7:
        return "atrasado"
    return "critico"


# `frescor.ver` — a chave do catalogo para este monitor ("Monitor de frescor dos
# dados"); o caminho e que ficou com o nome em ingles. A checagem de `role` logo
# abaixo continua valendo e nega SEMPRE, nos dois modos: a permissao e um
# segundo filtro, nao a substituicao dela.
@router.get("", dependencies=[exige("frescor.ver")])
async def freshness(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if current.role != "admin":
        raise HTTPException(403, "Apenas administradores acessam o monitor de frescor")
    now = datetime.now(timezone.utc)
    # ultima execucao por coletor (ingestion_log)
    runs: dict[str, datetime] = {}
    try:
        r = await db.execute(text("SELECT source, max(finished_at) FROM ingestion_log GROUP BY source"))
        for src, ts in r.fetchall():
            if ts:
                runs[src] = ts
    except Exception:
        pass

    out = []
    for label, sql, src in _SOURCES:
        last_data = None
        count = None
        try:
            row = (await db.execute(text(sql))).first()
            if row:
                last_data, count = row[0], row[1]
        except Exception:
            pass
        last_run = runs.get(src) if src else None
        # frescor = mais recente entre dado gravado e execucao do coletor
        cands = [t for t in (last_data, last_run) if t is not None]
        last = max(cands) if cands else None
        age_days = ((now - last).total_seconds() / 86400.0) if last else None
        out.append({
            "fonte": label,
            "ultimo_dado": last_data.isoformat() if last_data else None,
            "ultima_coleta": last_run.isoformat() if last_run else None,
            "referencia": last.isoformat() if last else None,
            "idade_dias": round(age_days, 1) if age_days is not None else None,
            "registros": count,
            "status": _status(age_days),
        })
    # ordena piores primeiro
    ordem = {"critico": 0, "desconhecido": 1, "atrasado": 2, "fresco": 3}
    out.sort(key=lambda x: (ordem.get(x["status"], 9), -(x["idade_dias"] or 0)))
    return {"gerado_em": now.isoformat(), "fontes": out}
