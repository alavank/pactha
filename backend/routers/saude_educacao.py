"""SIOPS, SIOPE e instrumentos do SUS — mais uma leitura da tela de regularidade.

Mesma tela (`cauc`) e mesma chave (`cauc.ver`) do CAUC e do SICONFI, pelo mesmo
motivo escrito em `routers/siconfi.py`: para o gestor é uma pergunta só ("estou em
condição de receber?"), e estes dados são o DETALHE de quatro itens do próprio
CAUC — 3.2.3 (SIOPE), 3.2.4 (SIOPS), 5.1 (mínimo em educação) e 5.2 (mínimo em
saúde). Conceder o CAUC sem o detalhe dele não é escolha que alguém queira fazer.

⚠️ `tem_dados: false` NÃO é "está em dia": é "ainda não coletamos". A regra (cor,
prazo, parcial × anual) mora em `services/saude_educacao.py`, a mesma que o
painel e o push usam para não avisar "vence em N dias" de um bimestre já entregue.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.registro_rotas import exige

router = APIRouter(prefix="/api/saude-educacao", tags=["saude-educacao"])


async def fetch_saude_educacao(db: AsyncSession, municipio_id: int,
                               hoje: date | None = None) -> dict:
    """Núcleo, SEM gate — reusável pelo painel como `fetch_siconfi`."""
    from services.bi_abas import _data_br
    from services.saude_educacao import CAUC_ENVIO, montar

    hoje = hoje or date.today()
    bims = (await db.execute(text("""
        SELECT sistema, ano, bimestre, entregue, data_entrega, recibo, pct_aplicado,
               numerador, denominador, atualizado_em
          FROM saude_educacao_bimestre WHERE municipio_id = :m
    """), {"m": municipio_id})).mappings().all()
    instr = (await db.execute(text("""
        SELECT instrumento, ano, periodo, situacao, atualizado_em
          FROM sus_instrumentos_planejamento WHERE municipio_id = :m
    """), {"m": municipio_id})).mappings().all()

    if not bims and not instr:
        return {
            "tem_dados": False,
            "motivo": ("O SIOPS, o SIOPE e os instrumentos de planejamento do SUS deste "
                       "município ainda não foram consultados. A coleta é diária e "
                       "automática; se esta mensagem persistir, a fonte pode estar "
                       "indisponível."),
        }

    # A validade que o CAUC mostra nos itens de envio: é o que permite dizer, ao
    # lado do item, "essa validade já foi cumprida — o extrato é que atrasou".
    validades = {}
    cauc = (await db.execute(text("SELECT itens FROM cauc_situacao WHERE municipio_id = :m"),
                             {"m": municipio_id})).scalar()
    if isinstance(cauc, dict):
        for codigo in CAUC_ENVIO:
            d = _data_br(cauc.get(codigo))
            if d:
                validades[codigo] = d

    out = montar([dict(b) for b in bims], [dict(i) for i in instr], hoje, validades)
    datas = [r["atualizado_em"] for r in list(bims) + list(instr) if r["atualizado_em"]]
    out["atualizado_em"] = max(datas).isoformat() if datas else None
    return out


@router.get("", dependencies=[exige("cauc.ver")])
async def situacao(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Bimestres do SIOPS e do SIOPE (entrega, prazo, % aplicado) e a situação do
    Plano, PAS, RDQA e RAG no DigiSUS."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "cauc")
    return await fetch_saude_educacao(db, municipio_id)
