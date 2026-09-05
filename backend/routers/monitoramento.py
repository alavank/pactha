"""Monitoramento mensal de convênios — Decreto Estadual (RS) nº 56.939/2023.

A REGRA NÃO MORA AQUI. Ela é uma função pura em `services/monitoramento_rs.py`,
consumida também pelo push ao prefeito e pelo Painel de Indicadores — se cada um
contasse por conta própria, um dia a tela e a notificação passariam a discordar
sobre o mesmo prazo. Aqui fica só o I/O: buscar convênios e registros, e chamar.

⚠️ GATE: `convenios.ver` e a tela `convenios`, e não uma chave nova. O
monitoramento **é** a execução do convênio — uma permissão separada permitiria a
um administrador conceder "Convênios" e esconder justamente o que suspende a
parcela. Mesma doutrina do `routers/cagec.py`, que reusa `cauc.ver` porque CAUC e
cadastro estadual são as duas colunas da mesma tela.

⚠️ ESTA ROTA NÃO É SÓ DO RS por acidente de implementação: ela responde para
qualquer município, e simplesmente não encontra convênio em execução onde não há
fonte estadual coletada. Se outro estado criar obrigação equivalente, o que muda
é o coletor — não este arquivo.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.monitoramento_rs import avaliar
from services.registro_rotas import exige

router = APIRouter(prefix="/api/monitoramento", tags=["monitoramento"])

# Fontes de convênio ESTADUAL sujeitas à obrigação. Hoje só a gaúcha: em MG o
# SIGCON não tem registro mensal equivalente, e cobrar um município mineiro por
# um decreto do RS seria inventar obrigação.
FONTES_COM_MONITORAMENTO = ("CAGE-RS",)


async def fetch_monitoramento(db: AsyncSession, municipio_id: int,
                              hoje: date | None = None) -> dict:
    """Núcleo sem gate de auth — reusado pelo endpoint (após `ensure_tela`) e,
    quando entrar, pelo Painel de Indicadores. Mesmo desenho do
    `fetch_cagec_situacao`."""
    convenios = [
        {
            "chave": r[0],
            "convenio_id": r[1],
            "rotulo": (r[2] or r[0] or "")[:120],
            "situacao": r[3],
            "dt_inicio": r[4],
            "dt_fim": r[5],
        }
        for r in (await db.execute(text("""
            SELECT nr_sigcon, id, orgao_concedente, situacao,
                   dt_vigencia_inicial, coalesce(dt_vigencia_atual, dt_vigencia_final)
              FROM convenios_estadual
             WHERE municipio_id = :m AND fonte = ANY(:fontes)
        """), {"m": municipio_id, "fontes": list(FONTES_COM_MONITORAMENTO)})).fetchall()
    ]

    registros = {
        (r[0], r[1]) for r in (await db.execute(text("""
            SELECT chave, competencia FROM monitoramento_convenios
             WHERE municipio_id = :m
        """), {"m": municipio_id})).fetchall()
    }

    # ⭐ A pergunta que desarma o falso alarme de estreia: este município JÁ teve
    # algum registro? Sem isso, um tenant sem credencial PCPRS abriria numa
    # parede vermelha inteiramente falsa. Ver o cabeçalho de
    # `services/monitoramento_rs.py`.
    tem_algum = bool(registros)

    calamidade = (await db.execute(text(
        "SELECT calamidade_ate FROM municipios WHERE id = :m"),
        {"m": municipio_id})).scalar()

    r = avaliar(convenios, registros, hoje=hoje,
                calamidade_ate=calamidade, tem_algum_registro=tem_algum)
    # `Pendencia` é dataclass; a rota devolve JSON.
    r["pendencias"] = [
        {"chave": p.chave, "convenio_id": p.convenio_id, "rotulo": p.rotulo,
         "meses_em_atraso": p.meses_em_atraso, "competencias": p.atrasadas,
         "nivel": p.nivel, "regime": p.regime, "prazo": p.prazo_do_mes}
        for p in r["pendencias"]
    ]
    r["decreto"] = "Decreto Estadual (RS) nº 56.939/2023"
    return r


@router.get("", dependencies=[exige("monitoramento.ver")])
async def monitoramento(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Situação do município no Sistema de Monitoramento de Convênios (RS).

    `estado='nao_conectado'` significa que a fonte ainda não foi ligada — NÃO
    que o município esteja em dia nem em atraso."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "monitoramento")
    return await fetch_monitoramento(db, municipio_id)
