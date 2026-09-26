"""Assistência social — FNAS: o saldo de cada conta do fundo municipal, os repasses
do FNAS e as emendas com o parlamentar (painel do MDS).

Lê o que `ingestion/fnas_suas.py` grava. Uma tela (`fnas`), uma rota sob `fnas.ver`.

⚠️ A CONTA É UMA SÓ: `services/fnas.py::montar` (mês de referência, parado, meses
de repasse).

⚠️ "Ainda não coletado" ≠ "o fundo não tem saldo": sem linha em `fnas_carga`,
`coletado: false`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.fnas import montar, ym_menos
from services.registro_rotas import exige

router = APIRouter(prefix="/api/fnas", tags=["fnas"])


@router.get("", dependencies=[exige("fnas.ver")])
async def fnas(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Contas do fundo no mês mais novo publicado, com o saldo de 12 meses antes, o
    repassado em 12 meses, a última OB e as emendas que caíram em cada uma."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "fnas")
    if (await db.execute(text("SELECT 1 FROM municipios WHERE id = :m"),
                         {"m": municipio_id})).first() is None:
        raise HTTPException(404, "Município não encontrado")
    cargas = {r["app"]: r for r in (await db.execute(text(
        "SELECT app, historico, linhas, painel_em, lido_em FROM fnas_carga "
        "WHERE municipio_id = :m"), {"m": municipio_id})).mappings().all()}
    if not cargas:
        return {"coletado": False}

    mes_ref = (await db.execute(text(
        "SELECT max(ano_mes) FROM fnas_saldo_conta WHERE municipio_id = :m"),
        {"m": municipio_id})).scalar()
    saldos, repasses, ultimos = [], [], {}
    if mes_ref:
        saldos = [dict(r) for r in (await db.execute(text("""
            SELECT ano_mes, cnpj, tipo_entidade, agencia, conta, bloco, tipo_conta,
                   vl_conta_corrente, vl_poupanca, vl_fundos, vl_cdb_rdb, vl_total
              FROM fnas_saldo_conta WHERE municipio_id = :m AND ano_mes >= :ini
        """), {"m": municipio_id, "ini": ym_menos(mes_ref, 12)})).mappings().all()]
        ini = ym_menos(mes_ref, 11)
        repasses = [dict(r) for r in (await db.execute(text("""
            SELECT ano, mes, bloco, piso, programa, ob, dt_ob, conta, valor
              FROM fnas_repasse
             WHERE municipio_id = :m AND ano * 100 + coalesce(mes, 0) BETWEEN :ini AND :fim
        """), {"m": municipio_id, "ini": ini, "fim": mes_ref})).mappings().all()]
        ultimos = {r[0]: r[1] for r in (await db.execute(text("""
            SELECT conta, max(dt_ob) FROM fnas_repasse
             WHERE municipio_id = :m AND conta IS NOT NULL GROUP BY conta
        """), {"m": municipio_id})).all()}
    emendas = [dict(r) for r in (await db.execute(text("""
        SELECT parlamentar, partido, tipo_emenda, programa, ano, valor, dt_ob, ob, conta
          FROM fnas_emenda WHERE municipio_id = :m
    """), {"m": municipio_id})).mappings().all()]

    corpo = montar(saldos=saldos, repasses=repasses, ultimos=ultimos, emendas=emendas)

    def quando(app: str) -> dict | None:
        c = cargas.get(app)
        if not c:
            return None
        return {"lido_em": c["lido_em"].isoformat() if c["lido_em"] else None,
                "painel_em": c["painel_em"].isoformat() if c["painel_em"] else None,
                "historico": c["historico"]}

    corpo.update({"coletado": True, "cargas": {a: quando(a) for a in ("saldo", "repasse", "emenda")}})
    return corpo
