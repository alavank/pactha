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
            "licitacon": await _licitacon(db, municipio_id),
            "obras": await _obras(db, municipio_id)}


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
               dt_final_vigencia, nr_documento, link_licitacon,
               nm_contratado, vl_atual
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
            "contratado": r[7],
            # ⚠️ O valor DEPOIS dos aditivos. Vem só do coletor do portal e só
            # quando o detalhe daquele contrato já foi buscado — `None` aqui é
            # "ainda não perguntei", não "não teve aditivo". A tela mostra a
            # diferença apenas quando ela existe.
            "valor_atual": float(r[8]) if r[8] is not None else None,
        } for r in vigentes],
    }


async def _obras(db: AsyncSession, municipio_id: int) -> dict:
    """LicitaCon Obras — a execução da obra e o convênio que a pagou.

    ⚠️ `coletado: false` com zero obra NÃO é "o município não tem obra". O
    LicitaCon Obras é de 2024 e município pequeno pode não ter obra sujeita a
    registro: Nova Palma tem 0 e Santa Maria, 120. A tela precisa dizer isso —
    e a diferença entre "não coletamos" e "coletamos e não há" está no `status`
    da rodada, não nesta contagem."""
    linhas = (await db.execute(text("""
        SELECT o.id_obra, o.ds_objeto, o.ds_situacao_obra, o.nm_contratado,
               o.vl_atual, o.vl_total_medido, o.pc_financeiro_exec,
               o.pc_executado, o.dt_fim_vigencia, o.dt_evento_paralisacao,
               o.ds_motivo_paralisacao, o.qt_medicoes, o.dt_ultima_medicao,
               o.nr_contrato, o.ano_contrato, o.atualizado_em
          FROM tce_rs_obras o
         WHERE o.municipio_id = :m
         ORDER BY (o.dt_evento_paralisacao IS NOT NULL) DESC,
                  o.vl_atual DESC NULLS LAST
         LIMIT 20
    """), {"m": municipio_id})).fetchall()

    recursos = (await db.execute(text("""
        SELECT id_obra, ds_tp_recurso, ds_fonte_recurso, ds_convenio_contrato,
               vl_recurso, vl_contrapartida, cod_tp_recurso
          FROM tce_rs_obras_recursos
         WHERE municipio_id = :m
         ORDER BY vl_recurso DESC NULLS LAST
    """), {"m": municipio_id})).fetchall()

    if not linhas:
        return {"coletado": False}

    por_obra: dict[int, list] = {}
    for r in recursos:
        por_obra.setdefault(r[0], []).append({
            "tipo": r[1], "fonte": r[2], "convenio": r[3],
            "valor": float(r[4]) if r[4] is not None else None,
            "contrapartida": float(r[5]) if r[5] is not None else None,
            # FDL/EST/PRO — o código é o que permite à tela separar convênio
            # federal de estadual sem depender do texto, que a fonte escreve
            # como quer.
            "codigo": r[6],
        })

    carimbos = [r[15] for r in linhas if r[15]]
    return {
        "coletado": True,
        "atualizado_em": max(carimbos).isoformat() if carimbos else None,
        "total": len(linhas),
        "paralisadas": sum(1 for r in linhas if r[9]),
        "com_origem_declarada": len(por_obra),
        "obras": [{
            "id": r[0],
            "objeto": r[1],
            "situacao": r[2],
            "contratado": r[3],
            "valor": float(r[4]) if r[4] is not None else None,
            "medido": float(r[5]) if r[5] is not None else None,
            # ⚠️ DOIS PERCENTUAIS, e eles divergem: numa obra real de Santa
            # Maria o financeiro está em 90,6% e o físico em 0,0, porque o órgão
            # mede o pagamento e não alimenta o avanço da obra. Mostrar um pelo
            # outro inventaria execução que ninguém declarou.
            "pc_financeiro": float(r[6]) if r[6] is not None else None,
            "pc_fisico": float(r[7]) if r[7] is not None else None,
            "vigencia_ate": r[8].isoformat() if r[8] else None,
            "paralisada_em": r[9].isoformat() if r[9] else None,
            "motivo_paralisacao": r[10],
            "medicoes": r[11],
            "ultima_medicao": r[12].isoformat() if r[12] else None,
            "contrato": f"{r[13]}/{r[14]}" if r[13] and r[14] else None,
            "recursos": por_obra.get(r[0], []),
        } for r in linhas],
    }
