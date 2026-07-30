"""CAGEC — Cadastro Geral de Convenentes de Minas Gerais (SIGCON-MG).

O par ESTADUAL do CAUC: sem CAGEC valido o municipio nao assina convenio com o
Estado. Fica ao lado do CAUC na tela de regularidade (mesma tela `cauc`), porque
para o gestor o assunto e um: "minha documentacao esta em dia?".

ESTADO ATUAL — ANDAIME. Nenhum scraper alimenta `cagec_situacao` ainda; falta a
credencial do SIGCON-MG (uma por municipio, no Cofre com sistema='SIGCON-MG',
que o ingestion/sigcon_scraper.py ja usa para os convenios). Enquanto nao houver
linha, `tem_dados` volta false com um motivo legivel.

Por que o andaime existe agora: o payload ja sai no MESMO formato do CAUC
(`itens` com codigo/grupo/label/valor/tipo/status), entao ligar a coleta depois e
so preencher a tabela — a tela nao muda. E a alternativa (a tela nao ter a coluna)
esconderia do gestor que existe uma regularidade estadual a acompanhar.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import get_current_user, ensure_municipio_access, ensure_tela

router = APIRouter(prefix="/api/cagec", tags=["cagec"])

MOTIVO_SEM_COLETA = (
    "O CAGEC (cadastro de convenentes de MG) ainda nao e coletado automaticamente: "
    "depende da credencial do SIGCON-MG do municipio. Consulte pelo portal SIGCON-MG."
)


async def fetch_cagec_situacao(db: AsyncSession, municipio_id: int) -> dict:
    """Nucleo da consulta CAGEC, SEM gate de auth — reusado pelo endpoint (apos
    ensure_tela) e pelo Painel de Indicadores (gated so por municipio), igual ao
    fetch_cauc_situacao."""
    row = (await db.execute(text("""
        SELECT nome, uf, cnpj, situacao, regular, validade, itens,
               pendencias, pendencias_codigos, data_pesquisa, atualizado_em
        FROM cagec_situacao WHERE municipio_id = :m
    """), {"m": municipio_id})).first()

    if not row:
        return {"tem_dados": False, "motivo": MOTIVO_SEM_COLETA}

    itens = row[6] if isinstance(row[6], list) else []
    return {
        "tem_dados": True,
        "nome": row[0],
        "uf": row[1],
        "cnpj": row[2],
        "situacao": row[3],
        "regular": row[4],
        "validade": row[5].isoformat() if row[5] else None,
        "itens": itens,
        "pendencias": row[7] or 0,
        "pendencias_codigos": list(row[8] or []),
        "data_pesquisa": row[9].isoformat() if row[9] else None,
        "atualizado_em": row[10].isoformat() if row[10] else None,
    }


@router.get("")
async def situacao(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Situacao do municipio no CAGEC (regularidade estadual - MG).

    Mesma tela do CAUC (`cauc`): quem ve um ve o outro, porque e o mesmo assunto
    e nao faria sentido conceder metade da tela de regularidade."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "cauc")
    return await fetch_cagec_situacao(db, municipio_id)
