"""Consulta Popular / COREDEs (RS) — o que a região votou, e como o município foi.

⚠️ GATE `convenios.ver` + tela `convenios`, e não uma chave nova. A Consulta
Popular é a PORTA DE ENTRADA do convênio estadual gaúcho: o projeto mais votado
na região vira, na prática, convênio com município. Quem pode ver a carteira de
convênios pode ver de onde ela nasce — e uma permissão separada entregaria ao
administrador a escolha de esconder o funil e mostrar só o resultado.

⚠️ E A TELA MOSTRA A DERROTA, NÃO SÓ A VITÓRIA. O campo que decide ação é
`status_municipio`: em 2026/2027, Santa Maria votou 153 e 141 vezes nas duas
demandas eleitas do COREDE Central e ficou **desclassificada nas duas** — ou
seja, ficou de fora de R$ 2,23 milhões da própria região por falta de
mobilização. Um painel que listasse só o que a região ganhou esconderia
exatamente o que o gestor precisa saber para agir no ano seguinte.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.registro_rotas import exige

router = APIRouter(prefix="/api/consulta-popular", tags=["consulta-popular"])


@router.get("", dependencies=[exige("convenios.ver")])
async def consulta_popular(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Demandas eleitas no COREDE do município, com a participação dele.

    `tem_dados: false` significa que a coleta ainda não rodou (ou que o município
    não é do RS) — nunca que a região não elegeu nada."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "convenios")

    linhas = (await db.execute(text("""
        SELECT corede, edicao, demanda_ordem, demanda, orgao, votos_corede,
               classificada, valor, votos_municipio, status_municipio,
               atualizado_em
          FROM consulta_popular_rs
         WHERE municipio_id = :m
         ORDER BY edicao DESC, demanda_ordem
    """), {"m": municipio_id})).fetchall()

    if not linhas:
        return {
            "tem_dados": False,
            "motivo": ("A Consulta Popular ainda não foi coletada para este "
                       "município. Ela é anual, por COREDE, e depende de o "
                       "conselho regional do município estar cadastrado."),
        }

    itens = [{
        "edicao": r[1], "ordem": r[2], "demanda": r[3], "orgao": r[4],
        "votos_corede": r[5], "classificada": r[6],
        "valor": float(r[7]) if r[7] is not None else None,
        "votos_municipio": r[8], "status_municipio": r[9],
        # `perdeu` é derivado aqui, e não no frontend, porque a mesma pergunta
        # aparece no BI e no push — a regra tem de ser uma só.
        "perdeu": (r[9] or "").strip().lower().startswith("desclass"),
    } for r in linhas]

    edicao = itens[0]["edicao"]
    do_ano = [i for i in itens if i["edicao"] == edicao]
    perdidas = [i for i in do_ano if i["perdeu"]]
    return {
        "tem_dados": True,
        "corede": linhas[0][0],
        "edicao": edicao,
        "atualizado_em": linhas[0][10].isoformat() if linhas[0][10] else None,
        "itens": itens,
        "resumo": {
            "demandas_eleitas": len(do_ano),
            # O total que a REGIÃO conquistou — o município participa dele só se
            # tiver se classificado.
            "valor_regiao": sum(i["valor"] or 0 for i in do_ano),
            "desclassificadas": len(perdidas),
            "valor_fora_do_alcance": sum(i["valor"] or 0 for i in perdidas),
            "votos_do_municipio": sum(i["votos_municipio"] or 0 for i in do_ano),
        },
    }
