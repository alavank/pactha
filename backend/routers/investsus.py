"""InvestSUS — os repasses federais de saúde que caem no Fundo Municipal.

A fonte é fechada (login no autorizador do DATASUS) e ainda não há coletor: o
que esta rota entrega hoje é o conteúdo curado de `services/investsus_conteudo`
mais UM dado vivo — se a credencial deste município já está no Cofre.

⚠️ O `aviso` vai na resposta e a tela é obrigada a mostrá-lo. Conteúdo estático
sem ressalva se passa por monitoramento, e numa tela de dinheiro de saúde isso é
pior que tela vazia: o gestor concluiria que seria avisado de um repasse que
ninguém está vigiando.

⚠️ Gate `investsus.ver` + tela `investsus`. A permissão herda de `consultas` na
migration, então quem já via o FNS vê esta tela sem concessão nova — decisão
registrada em `add_permissoes_por_acao.sql`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.investsus_conteudo import (
    AVISO, BLOCOS, BLOQUEIO_MFA, CONFERIR, LINKS, RESUMO, SUBTITULO, TITULO,
)
from services.registro_rotas import exige

router = APIRouter(prefix="/api/investsus", tags=["investsus"])


@router.get("", dependencies=[exige("investsus.ver")])
async def investsus(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Conteúdo do InvestSUS + situação da credencial deste município."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "investsus")

    row = (await db.execute(text(
        "SELECT nome, cnpj FROM municipios WHERE id = :m"), {"m": municipio_id})).first()
    if row is None:
        raise HTTPException(404, "Município não encontrado")

    # ⭐ O ÚNICO DADO VIVO DA TELA. A credencial pode estar guardada com escopo
    # DESTE município ou com escopo da instância (municipio_id NULL) — o Cofre
    # aceita os dois, e os coletores também. Contar só as do município daria
    # "não cadastrada" num tenant de um município só, onde a credencial legítima
    # está no escopo geral. É o arranjo real do Monte Sião.
    cred = (await db.execute(text("""
        SELECT count(*) FILTER (WHERE municipio_id = :m),
               count(*) FILTER (WHERE municipio_id IS NULL)
          FROM cofre_senhas
         WHERE automation_key = 'investsus'
            OR sistema ILIKE 'InvestSUS%'
    """), {"m": municipio_id})).first()
    do_municipio, da_instancia = (cred[0] or 0), (cred[1] or 0)

    return {
        "tem_dados": True,
        "aviso": AVISO,
        "titulo": TITULO,
        "subtitulo": SUBTITULO,
        "resumo": RESUMO,
        "blocos": BLOCOS,
        "conferir": CONFERIR,
        "links": LINKS,
        "coleta_automatica": False,
        # Medido em 17/08: a credencial funciona, o SCPA é que exige MFA ainda
        # não cadastrado. É pendência do município, e a tela precisa dizer qual.
        "bloqueio": BLOQUEIO_MFA,
        "municipio": {
            "nome": row[0],
            "cnpj": row[1],
            "credencial_cadastrada": bool(do_municipio or da_instancia),
            "credencial_escopo": ("municipio" if do_municipio
                                  else "instancia" if da_instancia else None),
        },
    }
