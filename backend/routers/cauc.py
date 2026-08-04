"""CAUC — regularidade fiscal FEDERAL do municipio (STN).

Mostra, por municipio, se ele esta apto a receber transferencias voluntarias
da Uniao: exigencias regulares (validade) vs pendencias ("!"). Dados de
`cauc_situacao` (ingestao `ingestion/cauc_ingest.py`, dados abertos do Tesouro).
"""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from services.auth import get_current_user, ensure_municipio_access, ensure_tela
from models.user import User
from services import authz
from services.registro_rotas import exige

router = APIRouter(prefix="/api/cauc", tags=["cauc"])

# O catalogo (GRUPOS, LABELS, _classifica) mora em services/cauc_catalogo.py
# para que o cron de alertas possa usa-lo sem importar FastAPI e o engine.
# Reexportado aqui porque este modulo ja era o endereco conhecido deles.
from services.cauc_catalogo import GRUPOS, GRUPOS_GLOSSA, LABELS, _classifica  # noqa: F401



@router.get("", dependencies=[exige("cauc.ver")])
async def situacao(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Situacao do municipio no CAUC (regularidade fiscal federal)."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "cauc")
    return await fetch_cauc_situacao(db, municipio_id)


async def fetch_cauc_situacao(db: AsyncSession, municipio_id: int) -> dict:
    """Nucleo da consulta CAUC, SEM gate de auth. Reusado pelo endpoint /api/cauc
    (apos ensure_tela) e pelo Painel Executivo do prefeito (gated so por municipio)."""
    row = (await db.execute(text("""
        SELECT nome, uf, ibge, cod_siafi, populacao, data_pesquisa,
               itens, pendencias, pendencias_codigos, regular, atualizado_em
        FROM cauc_situacao WHERE municipio_id = :m
    """), {"m": municipio_id})).first()
    if not row:
        return {"tem_dados": False}

    itens_raw = row[6] if isinstance(row[6], dict) else {}
    itens = []
    for codigo, valor in itens_raw.items():
        tipo, status, validade, nota = _classifica(valor)
        raiz = codigo.split(".")[0]
        itens.append({
            "codigo": codigo,
            "grupo": GRUPOS.get(raiz, "Outras"),
            # Glosa do grupo: o titulo e o LITERAL do extrato (para casar na
            # conferencia), a glosa e a traducao (para quem nao vive o extrato).
            "grupo_glossa": GRUPOS_GLOSSA.get(raiz, ""),
            "label": LABELS.get(codigo, f"Exigencia {codigo}"),
            "valor": valor,
            "tipo": tipo,
            # `status` e `validade` sao DUAS COLUNAS no extrato, e aqui tambem:
            # antes vinham grudados numa frase ("Regular ate 31/07/26"), que nao
            # casava com o documento na hora de conferir linha a linha.
            "status": status,
            "validade": validade,
            "nota": nota,
        })
    # ordena por codigo (numerico por segmento)
    def _key(it):
        return [int(x) if x.isdigit() else 0 for x in it["codigo"].split(".")]
    itens.sort(key=_key)

    return {
        "tem_dados": True,
        "nome": row[0], "uf": row[1], "ibge": row[2], "cod_siafi": row[3],
        "populacao": row[4],
        "data_pesquisa": row[5].isoformat() if row[5] else None,
        "regular": row[9],
        "pendencias": row[7],
        "pendencias_codigos": list(row[8] or []),
        "itens": itens,
        "atualizado_em": row[10].isoformat() if row[10] else None,
    }


@router.post("/refresh", dependencies=[exige("cauc.atualizar")])
async def refresh(
    current: User = Depends(get_current_user),
):
    """Dispara a ingestao do CAUC manualmente (dados abertos do Tesouro)."""
    # Antes bastava estar LOGADO. Isto nao e uma leitura: baixa o CSV do Tesouro
    # e reescreve `cauc_situacao` do tenant inteiro, numa VPS burstable (~0,6
    # vCPU) — qualquer conta sem uma unica tela podia derrubar o sistema para
    # todo mundo apertando isto em sequencia.
    #
    # So a TELA, e nao municipio: a ingestao e do dataset inteiro do Tesouro e
    # nao aceita recorte por municipio (ver ingestion/cauc_ingest.py), entao nao
    # ha municipio a exigir — exigir um seria inventar um parametro que o
    # endpoint nao tem.
    authz.exigir_tela(current, "cauc")
    from ingestion.cauc_ingest import ingest
    import anyio
    n = await anyio.to_thread.run_sync(ingest)
    return {"ok": True, "municipios": n}
