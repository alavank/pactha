"""PDDE — dinheiro nas escolas: o saldo parado na conta de cada escola e se ela
está suspensa para a próxima parcela.

Lê o que `ingestion/pdde_info.py` grava do PDDE Info (FNDE) e o PDDE PAGO das
liberações do FNDE por entidade (`simec_par_liberacoes`, da consulta `pls/simad` de
`ingestion/fnde_liberacoes.py`) — o MESMO dado que a tela do SIMEC mostra no bloco
das escolas, somado pelo CNPJ da caixa escolar, sem segunda coleta. Uma tela
(`pdde`), uma rota sob `pdde.ver`.

⚠️ A CONTA É UMA SÓ: `services/pdde.py::montar` (rede, saldo, parado, suspensa).

⚠️ "Ainda não coletado" ≠ "a escola não tem saldo": sem linha em `pdde_carga`,
`coletado: false`; saldo sem mês carregado, `mes_referencia: null`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.pdde import montar
from services.registro_rotas import exige

router = APIRouter(prefix="/api/pdde", tags=["pdde"])

BRT = timezone(timedelta(hours=-3))


def _mes_menos(m: date, n: int) -> date:
    a, b = divmod(m.year * 12 + (m.month - 1) - n, 12)
    return date(a, b + 1, 1)


@router.get("", dependencies=[exige("pdde.ver")])
async def pdde(
    municipio_id: int = Query(...),
    rede: str = Query("municipal", pattern="^(municipal|todas)$"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Por escola (entidade executora): saldo no mês de referência, se está parado,
    situação da prestação de contas e suspensões do ano."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "pdde")
    m = (await db.execute(text(
        "SELECT regexp_replace(coalesce(cnpj, ''), '\\D', '', 'g') FROM municipios WHERE id = :m"),
        {"m": municipio_id})).first()
    if m is None:
        raise HTTPException(404, "Município não encontrado")
    cargas = (await db.execute(text(
        "SELECT relatorio, referencia, linhas, carregado_em FROM pdde_carga "
        "WHERE municipio_id = :m"), {"m": municipio_id})).mappings().all()
    if not cargas:
        return {"coletado": False}

    hoje = datetime.now(BRT).date()
    meses = sorted((c["referencia"] for c in cargas if c["relatorio"] == "saldo"), reverse=True)
    mes_ref = meses[0] if meses else None
    anos = sorted({c["referencia"].year for c in cargas
                   if c["relatorio"] in ("prestacao", "suspensao")
                   and c["referencia"].year <= hoje.year}, reverse=True)
    ano = anos[0] if anos else hoje.year
    carga = {(c["relatorio"], c["referencia"]): c for c in cargas}

    def quando(rel: str, ref: date | None) -> str | None:
        c = carga.get((rel, ref)) if ref else None
        return c["carregado_em"].isoformat() if c else None

    saldo = []
    saldo_antigo = None
    if mes_ref:
        saldo = [dict(r) for r in (await db.execute(text("""
            SELECT cnpj, razao_social, banco, agencia, conta, programa, redes,
                   saldo_conta, saldo_fundos, saldo_poupanca, saldo_rdb_cdb
              FROM pdde_saldo WHERE municipio_id = :m AND mes = :mes
        """), {"m": municipio_id, "mes": mes_ref})).mappings().all()]
        antes = _mes_menos(mes_ref, 6)
        if ("saldo", antes) in carga:
            saldo_antigo = {r[0]: r[1] for r in (await db.execute(text("""
                SELECT cnpj, sum(saldo_conta + saldo_fundos + saldo_poupanca + saldo_rdb_cdb)
                  FROM pdde_saldo WHERE municipio_id = :m AND mes = :mes GROUP BY cnpj
            """), {"m": municipio_id, "mes": antes})).all()}
    ref_ano = date(ano, 1, 1)
    prestacao = [dict(r) for r in (await db.execute(text("""
        SELECT programa, escola_inep, escola_nome, eex_cnpj, eex_nome, eex_situacao,
               eex_suspensa, uex_cnpj, uex_situacao, uex_suspensa, valor_previsto, municipal
          FROM pdde_prestacao WHERE municipio_id = :m AND ano = :a
    """), {"m": municipio_id, "a": ano})).mappings().all()]
    suspensao = [dict(r) for r in (await db.execute(text("""
        SELECT rede, programa, destinacao, escola_inep, escola_nome, uex_cnpj, uex_nome, tipo
          FROM pdde_suspensao WHERE municipio_id = :m AND ano = :a
    """), {"m": municipio_id, "a": ano})).mappings().all()]

    # O PDDE PAGO no ano (liberações do FNDE, simad): None = o ano ainda não foi
    # lido para o município (`fnde_liberacoes_carga`) — a tela diz isso.
    recebido: dict[str, Decimal] | None = None
    lib = (await db.execute(text(
        "SELECT fechamento, atualizado_em FROM fnde_liberacoes_carga "
        "WHERE municipio_id = :m AND ano = :a"), {"m": municipio_id, "a": ano})).first()
    if lib:
        # Por CNPJ, com o `tipo_favorecido` (a guarda de `test_fnde_liberacoes.py`):
        # quem decide se a executora entra na conta aqui NÃO é o tipo pelo nome do
        # simad, é a REDE que o PDDE Info publica (`services/pdde.py`) — a caixa
        # escolar de escola estadual fica fora mesmo sendo "escola" nos dois.
        recebido = {}
        for cnpj, _tipo, total in (await db.execute(text("""
            SELECT cnpj_favorecido, tipo_favorecido, sum(valor) FROM simec_par_liberacoes
             WHERE municipio_id = :m AND ano = :a AND programa ILIKE 'PDDE%'
               AND cnpj_favorecido <> ''
             GROUP BY cnpj_favorecido, tipo_favorecido
        """), {"m": municipio_id, "a": ano})).all():
            recebido[cnpj] = recebido.get(cnpj, Decimal("0")) + total

    corpo = montar(cnpj_prefeitura=m[0], rede=rede, mes_ref=mes_ref, saldo=saldo,
                   saldo_antigo=saldo_antigo, prestacao=prestacao, suspensao=suspensao,
                   recebido=recebido)
    corpo.update({
        "coletado": True,
        "ano": ano,
        "saldo_carregado_em": quando("saldo", mes_ref),
        "prestacao_carregada_em": quando("prestacao", ref_ano),
        "suspensao_carregada_em": quando("suspensao", ref_ano),
        "meses_carregados": len(meses),
        "liberacoes_fnde": None if not lib else {
            "fechamento": lib[0].isoformat() if lib[0] else None,
            "lido_em": lib[1].isoformat() if lib[1] else None},
    })
    return corpo
