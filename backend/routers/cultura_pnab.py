"""PNAB 2027 — mais uma leitura da tela de regularidade: o município vai continuar
recebendo a Política Nacional Aldir Blanc?

Mesma tela (`cauc`) e mesma chave (`cauc.ver`) do CAUC, do SICONFI e de saúde e
educação, pelo mesmo motivo escrito em `routers/siconfi.py`: para o gestor é uma
pergunta só ("estou em condição de receber?"). A regra (Lei 14.399/2022, art. 6º,
§ 8º) e a conta moram em `services/cultura_pnab.py`.

⚠️ `situacao: sem_dado` NÃO é "está em dia": é "o SNC ainda não foi lido".
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.cultura_pnab import ACAO_PNAB, montar
from services.registro_rotas import exige

router = APIRouter(prefix="/api/cultura-pnab", tags=["cultura-pnab"])


@router.get("", dependencies=[exige("cauc.ver")])
async def cultura_pnab(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Situação do fundo de cultura para o PNAB de 2027: o registro no SNC e para onde
    o PNAB dos últimos 12 meses foi (CGU)."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "cauc")
    m = (await db.execute(text("SELECT coalesce(cnpj, '') FROM municipios WHERE id = :m"),
                          {"m": municipio_id})).first()
    if m is None:
        raise HTTPException(404, "Município não encontrado")
    cnpj = re.sub(r"\D", "", m[0]).zfill(14) if re.sub(r"\D", "", m[0]) else ""
    snc = (await db.execute(text("""
        SELECT situacao, data_publicacao, componentes, fundo_registrado, lido_em
          FROM snc_cultura WHERE municipio_id = :m
    """), {"m": municipio_id})).mappings().first()
    # 12 meses a partir do mês mais novo que a CGU tem PARA ESTE município — nunca
    # da data de hoje (o arquivo do mês corrente é parcial; ver cgu_transferencias).
    pnab = [dict(r) for r in (await db.execute(text("""
        WITH ult AS (SELECT max(mes) AS m FROM cgu_transferencias WHERE municipio_id = :m)
        SELECT lpad(regexp_replace(coalesce(favorecido_doc, ''), '\\D', '', 'g'), 14, '0')
                 AS favorecido_doc,
               max(favorecido_nome) AS favorecido_nome, sum(valor) AS valor
          FROM cgu_transferencias, ult
         WHERE municipio_id = :m AND acao_codigo = :acao
           AND mes > ult.m - INTERVAL '12 months'
         GROUP BY 1
    """), {"m": municipio_id, "acao": ACAO_PNAB})).mappings().all()]
    corpo = montar(snc=dict(snc) if snc else None, pnab=pnab, cnpj_prefeitura=cnpj)
    corpo["regra"] = ("Lei 14.399/2022, art. 6º, § 8º (Lei 15.132/2025): a partir de 2027, "
                      "só recebe o PNAB o ente que dispuser de fundo de cultura.")
    return corpo
