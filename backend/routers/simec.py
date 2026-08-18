"""SIMEC PAR - consulta publica MEC.

Endpoints (todos requerem auth):
  GET /api/simec/dimensoes?municipio_id=  -> Sintese PAR por dimensao
  GET /api/simec/liberacoes?municipio_id=&ano=&programa=  -> Liberacoes de recursos
  GET /api/simec/resumo?municipio_id=     -> totais por programa e ano
  GET /api/simec/termos?municipio_id=     -> Termos de Compromisso (o instrumento)

Os dados sao alimentados por DOIS coletores, de duas telas do MEC:
  - ingestion/simec_par.py    -> dimensoes + liberacoes (os PAGAMENTOS: OB, data)
  - ingestion/simec_termos.py -> termos de compromisso (o INSTRUMENTO)
Fonte original: simec.mec.gov.br/cte/relatoriopublico/impressao.php e
                simec.mec.gov.br/par/carregaTermos.php (ambas publicas).
"""
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from services.auth import get_current_user, ensure_municipio_access, ensure_tela
from services.registro_rotas import exige
from models.user import User

router = APIRouter(prefix="/api/simec", tags=["simec"])


def _clean(s):
    """Remove U+FFFD (acentos corrompidos vindos do cp1252 do SIMEC)."""
    if not isinstance(s, str):
        return s
    return s.replace("�", "").replace("  ", " ").strip()


@router.get("/dimensoes", dependencies=[exige("simec.ver")])
async def dimensoes(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Sintese do PAR por dimensao (contagem de indicadores por pontuacao 1-4)."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "simec")
    r = await db.execute(text("""
        SELECT dimensao, score_4, score_3, score_2, score_1, score_na, updated_at
        FROM simec_par_dimensoes
        WHERE municipio_id = :mun
        ORDER BY dimensao
    """), {"mun": municipio_id})
    items = []
    for row in r.fetchall():
        total = (row[1] or 0) + (row[2] or 0) + (row[3] or 0) + (row[4] or 0) + (row[5] or 0)
        items.append({
            "dimensao": _clean(row[0]),
            "score_4": row[1], "score_3": row[2], "score_2": row[3],
            "score_1": row[4], "score_na": row[5],
            "total": total,
            "atualizado_em": row[6].isoformat() if row[6] else None,
        })
    return {"items": items, "total": len(items)}


@router.get("/liberacoes", dependencies=[exige("simec.ver")])
async def liberacoes(
    municipio_id: int = Query(...),
    ano: Optional[int] = Query(None),
    programa: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Liberacoes de recursos MEC (PNAE, PNATE, QUOTA, PDDE, etc)."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "simec")
    where = ["municipio_id = :mun"]
    params: dict = {"mun": municipio_id}
    if ano:
        where.append("ano = :ano"); params["ano"] = ano
    if programa:
        where.append("programa = :prog"); params["prog"] = programa
    sql = f"""
        SELECT programa, programa_full, dt_pgto, ob, valor, parcela,
               descricao, banco, agencia, conta, ano, updated_at
        FROM simec_par_liberacoes
        WHERE {' AND '.join(where)}
        ORDER BY dt_pgto DESC NULLS LAST, programa
    """
    r = await db.execute(text(sql), params)
    items = [{
        "programa": _clean(row[0]),
        "programa_full": _clean(row[1]),
        "dt_pgto": row[2].isoformat() if row[2] else None,
        "ob": row[3],
        "valor": float(row[4]) if row[4] is not None else None,
        "parcela": row[5],
        "descricao": _clean(row[6]),
        "banco": _clean(row[7]),
        "agencia": row[8],
        "conta": row[9],
        "ano": row[10],
        "atualizado_em": row[11].isoformat() if row[11] else None,
    } for row in r.fetchall()]
    last = max((i["atualizado_em"] for i in items if i["atualizado_em"]), default=None)
    return {"items": items, "total": len(items), "atualizado_em": last}


@router.get("/termos", dependencies=[exige("simec.ver")])
async def termos(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Termos de Compromisso do PAR — o INSTRUMENTO, nao o pagamento.

    Irmao de /liberacoes e o oposto dele: la estao as OBs (quanto ja saiu); aqui,
    o termo que as origina (processo, tipo do objeto, vigencia, valor). Um
    municipio pode ter TC vigente com ZERO liberacao — e exatamente o caso que o
    relatorio precisa apontar, e que olhar so as liberacoes esconde.

    `vencido` sai calculado do banco (nao do navegador): a data do cliente pode
    estar errada, e "vencido" aqui vira alerta na tela.
    """
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "simec")
    r = await db.execute(text("""
        SELECT processo, nr_documento, tipo_documento, tipo_objeto,
               dt_validacao, periodo_pagamento, vigencia_txt, dt_vigencia,
               valor_termo, quantidade_obra, updated_at
        FROM simec_termos
        WHERE municipio_id = :mun
        ORDER BY dt_vigencia ASC NULLS LAST, processo
    """), {"mun": municipio_id})
    hoje = date.today()
    items = []
    for row in r.fetchall():
        dt_vig = row[7]
        # dias < 0 = vencido ha N dias; None = o portal nao trouxe data legivel
        # (a coluna vem como texto livre, ex.: "30/12/2024 - (-595 dias)").
        dias = (dt_vig - hoje).days if dt_vig else None
        items.append({
            "processo": _clean(row[0]),
            "nr_documento": _clean(row[1]),
            "tipo_documento": _clean(row[2]),
            "tipo_objeto": _clean(row[3]),
            "dt_validacao": row[4].isoformat() if row[4] else None,
            "periodo_pagamento": _clean(row[5]),
            "vigencia_txt": _clean(row[6]),
            "dt_vigencia": dt_vig.isoformat() if dt_vig else None,
            "dias_vigencia": dias,
            "vencido": (dias is not None and dias < 0),
            "valor_termo": float(row[8]) if row[8] is not None else None,
            "quantidade_obra": _clean(row[9]),
            "atualizado_em": row[10].isoformat() if row[10] else None,
        })
    last = max((i["atualizado_em"] for i in items if i["atualizado_em"]), default=None)
    return {
        "items": items,
        "total": len(items),
        "vencidos": sum(1 for i in items if i["vencido"]),
        "valor_total": sum(i["valor_termo"] or 0 for i in items),
        "atualizado_em": last,
    }


@router.get("/resumo", dependencies=[exige("simec.ver")])
async def resumo(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Totais por programa e por ano (para sumario rapido na tela)."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "simec")
    rp = await db.execute(text("""
        SELECT programa, COUNT(*), COALESCE(SUM(valor), 0)
        FROM simec_par_liberacoes
        WHERE municipio_id = :mun
        GROUP BY programa
        ORDER BY SUM(valor) DESC NULLS LAST
    """), {"mun": municipio_id})
    por_programa = [{"programa": _clean(r[0]), "qtde": r[1], "total": float(r[2] or 0)}
                    for r in rp.fetchall()]

    ra = await db.execute(text("""
        SELECT ano, COUNT(*), COALESCE(SUM(valor), 0)
        FROM simec_par_liberacoes
        WHERE municipio_id = :mun AND ano IS NOT NULL
        GROUP BY ano
        ORDER BY ano DESC
    """), {"mun": municipio_id})
    por_ano = [{"ano": r[0], "qtde": r[1], "total": float(r[2] or 0)}
               for r in ra.fetchall()]

    return {
        "por_programa": por_programa,
        "por_ano": por_ano,
        "total_geral": sum(p["total"] for p in por_programa),
    }
