"""As telas gaúchas de conteúdo curado — FUNRIGS, emendas estaduais e TCE-RS.

Um router para os três porque compartilham exatamente a mesma natureza: assunto
que entra no PACTHA pela regra do roadmap do RS (`docs/MAPA_RS.md` §13), mas cuja
fonte não é coletável hoje. O que muda entre eles é o conteúdo, não a mecânica.

⚠️ CADA RESPOSTA CARREGA O SEU `aviso`, e a tela é obrigada a mostrá-lo. Não é
rodapé nem nota de rodapé: sem ele, conteúdo estático se passa por monitoramento.

⚠️ Só respondem para município do RS. São assuntos do Estado; mostrá-los a uma
prefeitura de outra UF seria oferecer porta que não abre.

⚠️ Gate `convenios.ver` + tela `convenios` — os três são o funil de onde nasce
(ou de onde se perde) a transferência estadual. Mesma razão da Consulta Popular e
do catálogo de programas.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.conteudo_rs import (
    AVISO_EMENDAS, AVISO_FUNRIGS, AVISO_TCE, EMENDAS, FUNRIGS, TCE,
)
from services.registro_rotas import exige

router = APIRouter(prefix="/api/rs", tags=["conteudo-rs"])

_FORA_DO_RS = ("Este conteúdo trata de programas e obrigações do Estado do Rio "
               "Grande do Sul e não se aplica a este município.")


async def _guarda(db: AsyncSession, current: User, municipio_id: int) -> bool:
    """Auth + escopo + UF. Devolve True quando o município é do RS."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "convenios")
    uf = (await db.execute(text(
        "SELECT upper(coalesce(uf, '')) FROM municipios WHERE id = :m"),
        {"m": municipio_id})).scalar()
    if uf is None:
        raise HTTPException(404, "Município não encontrado")
    return uf == "RS"


@router.get("/funrigs", dependencies=[exige("convenios.ver")])
async def funrigs(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Plano Rio Grande / FUNRIGS — exigências do fundo a fundo da reconstrução."""
    if not await _guarda(db, current, municipio_id):
        return {"tem_dados": False, "motivo": _FORA_DO_RS}
    # A data-limite da calamidade é o único campo VIVO desta tela: ela muda o
    # comportamento do alarme do Decreto 56.939 (prazo de 120 dias em vez do
    # dia 15). Mostrá-la aqui deixa visível se o município a tem cadastrada.
    row = (await db.execute(text(
        "SELECT calamidade_ate, fundo_reconstrucao, fundo_reconstrucao_obs "
        "FROM municipios WHERE id = :m"), {"m": municipio_id})).first()
    return {
        "tem_dados": True,
        "aviso": AVISO_FUNRIGS,
        **FUNRIGS,
        "municipio": {
            "calamidade_ate": row[0].isoformat() if row and row[0] else None,
            "fundo_reconstrucao": row[1] if row else None,
            "fundo_reconstrucao_obs": row[2] if row else None,
        },
    }


@router.get("/emendas", dependencies=[exige("convenios.ver")])
async def emendas(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Emendas parlamentares estaduais do RS — e por que elas NÃO são impositivas."""
    if not await _guarda(db, current, municipio_id):
        return {"tem_dados": False, "motivo": _FORA_DO_RS}
    return {"tem_dados": True, "aviso": AVISO_EMENDAS, **EMENDAS}


@router.get("/tce", dependencies=[exige("convenios.ver")])
async def tce(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """TCE-RS — as remessas obrigatórias, e o que o LicitaCon já mostra.

    ⚠️ ESTA TELA DEIXOU DE SER SÓ CURADORIA. O calendário de remessas continua
    sendo conteúdo (é norma, não muda toda semana), mas as licitações e os
    contratos vêm agora do `ingestion/tce_rs.py`, que lê os dados abertos do
    próprio Tribunal. As duas coisas convivem no mesmo payload e a tela precisa
    dizer qual é qual — `aviso` fala do conteúdo curado, `licitacon` traz dado
    coletado com data.
    """
    if not await _guarda(db, current, municipio_id):
        return {"tem_dados": False, "motivo": _FORA_DO_RS}
    codigo = (await db.execute(text(
        "SELECT tce_orgao_codigo FROM municipios WHERE id = :m"),
        {"m": municipio_id})).scalar()
    return {"tem_dados": True, "aviso": AVISO_TCE, **TCE,
            "municipio": {"tce_orgao_codigo": codigo},
            "licitacon": await _licitacon(db, municipio_id)}


async def _licitacon(db: AsyncSession, municipio_id: int) -> dict:
    """Licitações e contratos coletados do LicitaCon, resumidos por ano.

    ⚠️ `coletado: false` NÃO é "o município não licita". Pode ser bloqueio de IP
    (o TCE-RS devolve 403 para faixa de datacenter) ou código de órgão ainda não
    descoberto. A tela precisa dizer isso, senão afirma sobre a prefeitura uma
    coisa que ela não sabe."""
    lic = (await db.execute(text("""
        SELECT ano_licitacao, count(*), sum(vl_licitacao), sum(vl_homologado),
               max(atualizado_em)
          FROM tce_rs_licitacoes WHERE municipio_id = :m
         GROUP BY ano_licitacao ORDER BY ano_licitacao DESC LIMIT 6
    """), {"m": municipio_id})).fetchall()
    con = (await db.execute(text("""
        SELECT ano_contrato, count(*), sum(vl_contrato), max(atualizado_em)
          FROM tce_rs_contratos WHERE municipio_id = :m
         GROUP BY ano_contrato ORDER BY ano_contrato DESC LIMIT 6
    """), {"m": municipio_id})).fetchall()

    if not lic and not con:
        return {"coletado": False}

    # Os contratos que ainda estão de pé — é o que o gestor precisa ver antes de
    # assinar o próximo, e o que vence junto com a vigência do convênio.
    vigentes = (await db.execute(text("""
        SELECT nr_contrato, ano_contrato, ds_objeto, vl_contrato,
               dt_final_vigencia, nr_documento, link_licitacon
          FROM tce_rs_contratos
         WHERE municipio_id = :m AND dt_final_vigencia >= CURRENT_DATE
         ORDER BY dt_final_vigencia LIMIT 10
    """), {"m": municipio_id})).fetchall()

    carimbos = [r[4] for r in lic if r[4]] + [r[3] for r in con if r[3]]
    return {
        "coletado": True,
        "atualizado_em": max(carimbos).isoformat() if carimbos else None,
        "licitacoes_por_ano": [{
            "ano": r[0], "total": r[1],
            "valor_estimado": float(r[2]) if r[2] is not None else None,
            # ⚠️ Soma só do que FOI homologado. Certame em andamento entra na
            # contagem e não na soma — por isso os dois números não fecham, e
            # isso é a verdade, não defeito.
            "valor_homologado": float(r[3]) if r[3] is not None else None,
        } for r in lic],
        "contratos_por_ano": [{
            "ano": r[0], "total": r[1],
            "valor": float(r[2]) if r[2] is not None else None,
        } for r in con],
        "contratos_vigentes": [{
            "numero": f"{r[0]}/{r[1]}",
            "objeto": r[2],
            "valor": float(r[3]) if r[3] is not None else None,
            "vigencia_ate": r[4].isoformat() if r[4] else None,
            "contratado_documento": r[5],
            "link": r[6],
        } for r in vigentes],
    }
