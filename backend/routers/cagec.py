"""CAGEC — Cadastro Geral de Convenentes de Minas Gerais (SIGCON-MG).

O par ESTADUAL do CAUC: sem CAGEC valido o municipio nao assina convenio com o
Estado. Fica ao lado do CAUC na tela de regularidade (mesma tela `cauc`), porque
para o gestor o assunto e um: "minha documentacao esta em dia?".

COLETA (ligada em 2026-07-30): `ingestion/cagec_scraper.py` preenche
`cagec_situacao` a partir da consulta **publica** do portal proprio do CAGEC
(www.cagec.mg.gov.br/convenente-web) — o CAGEC nao fica dentro do SIGCON-MG e
nao exige credencial, so o CNPJ do municipio. Quem ainda nao foi coletado (ou
cujo CNPJ nao conseguimos inferir) volta `tem_dados: false` com motivo legivel.

O payload sai no MESMO formato do CAUC (`itens` com
codigo/grupo/label/valor/tipo/status), entao a tela desenha as duas colunas sem
saber de onde veio cada uma.

DE ONDE VEM O DETALHE: da propria consulta publica sai o **CRC** (Certificado de
Registro Cadastral) em PDF, e ele **e emitido mesmo para municipio IRREGULAR** —
com as ~24 obrigacoes uma a uma, situacao e **data de validade de cada uma**,
mais CADIN-MG, SIAFI e o vencimento do mandato do representante legal. Ou seja,
da para dizer ao gestor O QUE destravar, e nao so que ele esta travado.
(Se o CRC falhar, o coletor grava so a situacao da linha — menos util, mas nunca
inventa detalhe que nao leu.)

`validade` NAO e a validade do certificado (o CRC nao tem uma): e a **data mais
proxima entre as obrigacoes ainda vigentes** — o proximo prazo que o municipio
precisa segurar para nao cair na irregularidade.
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
    "O CAGEC deste município ainda não foi coletado. A coleta é automática e usa o "
    "CNPJ do município; se ele ainda não foi identificado nas bases, consulte em "
    "www.cagec.mg.gov.br/convenente-web/consultaParceiros."
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
