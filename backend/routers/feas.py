"""Assistência social — Estado (FEAS): o que o Fundo Estadual de Assistência Social
pagou ao município (MG e RS), pela despesa aberta do Estado.

Lê o que `ingestion/feas_estadual.py` grava. Uma tela (`feas`), uma rota sob `feas.ver`.

⚠️ A CONTA É UMA SÓ: `services/feas.py::montar`.

⚠️ Três estados diferentes, que a tela distingue: o Estado do município não é coberto
(`cobertura: false` — só MG e RS hoje); coberto mas ainda não lido (`coletado:
false`); lido e sem pagamento (lista vazia, que no RS é comum).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.feas import montar
from services.registro_rotas import exige

router = APIRouter(prefix="/api/feas", tags=["feas"])

BRT = timezone(timedelta(hours=-3))
UFS_COBERTAS = ("MG", "RS")


@router.get("", dependencies=[exige("feas.ver")])
async def feas(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Pagamentos do FEAS ao fundo municipal e à prefeitura, no ano e no anterior."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "feas")
    m = (await db.execute(text(
        "SELECT upper(coalesce(uf, '')), coalesce(cnpj, '') FROM municipios WHERE id = :m"),
        {"m": municipio_id})).first()
    if m is None:
        raise HTTPException(404, "Município não encontrado")
    uf = m[0]
    if uf not in UFS_COBERTAS:
        return {"cobertura": False, "uf": uf}
    cargas = (await db.execute(text(
        "SELECT recurso, lido_em FROM feas_carga WHERE uf = :uf ORDER BY recurso"),
        {"uf": uf})).all()
    if not cargas:
        return {"cobertura": True, "coletado": False, "uf": uf}
    hoje = datetime.now(BRT).date()
    pagamentos = [dict(r) for r in (await db.execute(text("""
        SELECT ano, mes, data, documento, favorecido_cnpj, favorecido_nome, acao,
               modalidade, valor
          FROM feas_pagamento
         WHERE municipio_id = :m AND uf = :uf AND ano >= :ant
    """), {"m": municipio_id, "uf": uf, "ant": hoje.year - 1})).mappings().all()]
    cnpj = re.sub(r"\D", "", m[1]).zfill(14) if re.sub(r"\D", "", m[1]) else ""
    corpo = montar(pagamentos=pagamentos, cnpj_prefeitura=cnpj, uf=uf, hoje=hoje)
    # Até onde a fonte chega: MG publica o ano corrente todo dia; o RS, um arquivo
    # por mês com ~1 mês de atraso — o mês mais novo lido vai para a tela.
    meses_rs = [c[0] for c in cargas if re.fullmatch(r"\d{6}", c[0])]
    corpo.update({
        "cobertura": True, "coletado": True, "uf": uf,
        "lido_em": max(c[1] for c in cargas).isoformat(),
        "publicado_ate": (f"{meses_rs[-1][4:]}/{meses_rs[-1][:4]}" if uf == "RS" and meses_rs else None),
    })
    return corpo
