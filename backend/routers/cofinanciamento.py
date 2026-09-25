"""Cofinanciamento estadual da saúde — o que o Estado repassa ao fundo municipal.

⚠️ O VALOR DESTA TELA ESTÁ NA DIFERENÇA, não no total. Na Atenção Primária, o
que importa é `valor_teto - valor`: é dinheiro que o município deixa de receber
por indicador de desempenho (ISF), e que ele PODE reverter. Na Vigilância, o que
importa é a parcela com `liberado = false`: dinheiro parado.

Por isso o endpoint devolve os dois agregados prontos — se cada tela tivesse de
calcular, uma delas calcularia diferente.

Minas (24/09/2026) mora em `GET /api/cofinanciamento/mg`: outra fonte (as ordens
de pagamento por Resolução SES), mesma pergunta, mesma tela e mesma chave.
⭐ RIO GRANDE DO SUL (`/fes-rs`, 24/09/2026): a mesma tela, outra fonte e outro
formato. A SES-RS publica o PAGAMENTO (planilha mensal do Fundo Estadual de
Saúde, `ingestion/fes_rs.py`), não teto × desempenho. O que vale ali:
- o total pago ao FUNDO MUNICIPAL, por programa e por mês — é o da prefeitura;
- as RETENÇÕES do fundo (CONASEMS, multa de auditoria, pagamento a maior): é
  dinheiro que não chegou, e é o destaque;
- os hospitais e entidades sediados no município (ASSISTIR, MAC e SUS Gaúcho vão
  direto a eles) num bloco à parte, FORA do total — como `convenios_estadual_outros`.
A conta mora em `resumo_fes_rs` (pura, testada); a tela só desenha.
"""
import logging
from collections import defaultdict
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.registro_rotas import exige

router = APIRouter(prefix="/api/cofinanciamento", tags=["cofinanciamento"])
logger = logging.getLogger("cofinanciamento")


@router.get("", dependencies=[exige("cofinanciamento.ver")])
async def listar(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "cofinanciamento")
    vazio = {"tem_dados": False, "fonte": None,
             "primaria": {"itens": [], "perdido_total": 0, "teto_total": 0},
             "vigilancia": {"itens": [], "travado_total": 0, "travadas": 0,
                            "liberado_total": 0}}
    if not municipio_id:
        return vazio

    ap = (await db.execute(text("""
        SELECT competencia, valor_teto, valor, perc_receber, indicador, fechado, ano
        FROM cofinanciamento_saude
        WHERE municipio_id = :m AND tipo = 'atencao_primaria'
        ORDER BY ano DESC NULLS LAST, competencia DESC
    """), {"m": municipio_id})).fetchall()

    vg = (await db.execute(text("""
        SELECT competencia, programa, valor, liberado, data_ref, ano
        FROM cofinanciamento_saude
        WHERE municipio_id = :m AND tipo = 'vigilancia'
        ORDER BY liberado NULLS FIRST, data_ref DESC NULLS LAST
    """), {"m": municipio_id})).fetchall()

    if not ap and not vg:
        return vazio

    fonte = (await db.execute(text(
        "SELECT max(fonte) FROM cofinanciamento_saude WHERE municipio_id = :m"
    ), {"m": municipio_id})).scalar()

    itens_ap = [{
        "competencia": r[0],
        "valor_teto": float(r[1]) if r[1] is not None else None,
        "valor": float(r[2]) if r[2] is not None else None,
        "perdido": (float(r[1]) - float(r[2]))
                   if (r[1] is not None and r[2] is not None) else None,
        "perc_receber": float(r[3]) if r[3] is not None else None,
        "indicador": float(r[4]) if r[4] is not None else None,
        "fechado": r[5], "ano": r[6],
    } for r in ap]

    itens_vg = [{
        "competencia": r[0], "programa": r[1],
        "valor": float(r[2]) if r[2] is not None else None,
        "liberado": r[3],
        "data_ref": r[4].isoformat() if r[4] else None,
        "ano": r[5],
    } for r in vg]

    travadas = [i for i in itens_vg if i["liberado"] is False]
    return {
        "tem_dados": True,
        "fonte": fonte,
        "primaria": {
            "itens": itens_ap,
            "perdido_total": sum(i["perdido"] or 0 for i in itens_ap),
            "teto_total": sum(i["valor_teto"] or 0 for i in itens_ap),
        },
        "vigilancia": {
            "itens": itens_vg,
            "travadas": len(travadas),
            "travado_total": sum(i["valor"] or 0 for i in travadas),
            "liberado_total": sum(i["valor"] or 0 for i in itens_vg
                                  if i["liberado"] is True),
        },
    }


# ── MG: o fundo a fundo estadual pelas Resoluções SES (24/09/2026) ─────────────
# ⚠️ OUTRA FONTE, OUTRO FORMATO. Goiás publica teto × pago por quadrimestre; Minas
# publica cada ORDEM DE PAGAMENTO por Resolução (`ingestion/ses_mg_resolucoes.py`).
# A tela é a mesma («Cofinanciamento Saúde», chave `cofinanciamento`) porque a
# pergunta é a mesma: quanto o fundo estadual repassa ao fundo municipal. A conta
# (o que soma e o que fica à parte) mora em `services/ses_mg_fundo.py`.

_COLS_PG = ("tipo", "id_fonte", "ano_empenho", "categoria", "cod_atividade", "atividade",
            "cod_upg", "upg", "num_empenho", "num_ob", "data_pagamento", "valor", "banco",
            "agencia", "conta", "cnpj_credor", "razao_credor", "do_municipio", "resolucao")


@router.get("/mg", dependencies=[exige("cofinanciamento.ver")])
async def fundo_a_fundo_mg(
    municipio_id: Optional[int] = None,
    ano: Optional[int] = Query(None, ge=2019, le=2100),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    from services.ses_mg_fundo import monta

    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "cofinanciamento")
    vazio = {"tem_dados": False, "anos": [], "ano": None}
    if not municipio_id:
        return vazio
    cob = (await db.execute(text("""
        SELECT ano, max(coletado_em), max(fonte_atualizada_em),
               count(*) FILTER (WHERE tipo = 'orcamentario'), count(*) FILTER (WHERE tipo = 'restos')
          FROM ses_mg_cobertura WHERE municipio_id = :m
         GROUP BY ano ORDER BY ano DESC
    """), {"m": municipio_id})).fetchall()
    if not cob:
        return vazio
    anos = [r[0] for r in cob]
    ano = ano if ano in anos else anos[0]
    c = next(r for r in cob if r[0] == ano)

    pgs = (await db.execute(text(f"""
        SELECT {", ".join(_COLS_PG)} FROM ses_mg_pagamentos
         WHERE municipio_id = :m AND ano_pagamento = :a
    """), {"m": municipio_id, "a": ano})).fetchall()
    pagamentos = [dict(zip(_COLS_PG, r)) for r in pgs]

    # A indicação da SEGOV (emendas_mg) de cada Resolução SES — a chave é
    # (nº da Resolução, conta) e o casamento é feito em `monta`.
    inds = (await db.execute(text("""
        SELECT nr_indicacao, nome_responsavel, valor_indicacao, valor_pago,
               raw_data->>'instrumento', raw_data->>'conta'
          FROM emendas_estaduais
         WHERE municipio_id = :m AND tipo_indicacao ILIKE 'resolu%ses%'
           AND raw_data->>'conta' IS NOT NULL
    """), {"m": municipio_id})).fetchall()
    indicacoes = [{"nr_indicacao": r[0], "autor": r[1],
                   "valor_indicacao": float(r[2]) if r[2] is not None else None,
                   "valor_pago_segov": float(r[3]) if r[3] is not None else None,
                   "instrumento": r[4], "conta": r[5]} for r in inds]

    fes = (await db.execute(text("""
        SELECT cnpj, ano_empenho, num_empenho, sum(divida_atual), max(resolucao)
          FROM acordofes_empenho WHERE municipio_id = :m
         GROUP BY cnpj, ano_empenho, num_empenho
    """), {"m": municipio_id})).fetchall()
    empenhos_fes = {(r[0], r[1], r[2]): {"divida_atual": float(r[3] or 0), "resolucao": r[4]}
                    for r in fes}

    return {
        "tem_dados": True, "anos": anos, "ano": ano,
        "coletado_em": c[1].isoformat() if c[1] else None,
        "fonte_atualizada_em": c[2].isoformat() if c[2] else None,
        "lido_orcamentario": bool(c[3]), "lido_restos": bool(c[4]),
        **monta(pagamentos, indicacoes, empenhos_fes),
    }


# ===========================================================================
# RS — Fundo Estadual de Saúde (SES-RS)
# ===========================================================================
FONTE_FES_RS = "SES-RS · Fundo Estadual de Saúde (saude.rs.gov.br/pagamentos-mes)"


def _f(v) -> float:
    return float(v or 0)


def resumo_fes_rs(linhas: list[dict]) -> dict:
    """Agrega as linhas de UM município e UM ano. Pura: a tela e o teste leem a
    mesma conta.

    ⚠️ `fundo` soma SÓ `fundo_municipal` — é o dinheiro da prefeitura. Hospitais
    e entidades vêm em `entidades`, com os totais deles, e NUNCA entram em
    `fundo.total_pago`. Retenção do fundo é perda (vai em destaque); a da
    entidade é quase toda tributo do prestador, e vem separada por tipo."""
    fundo = [ln for ln in linhas if ln["fundo_municipal"]]
    outros = [ln for ln in linhas if not ln["fundo_municipal"]]

    progs: dict[str, dict] = {}
    for ln in fundo:
        p = progs.setdefault(ln["projeto"] or "—", {
            "projeto": ln["projeto"] or "—", "pago": Decimal(0), "retido": Decimal(0),
            "fontes": set(), "sub": defaultdict(Decimal)})
        p["pago"] += ln["valor_pago"] or 0
        p["retido"] += ln["valor_retido"] or 0
        if ln.get("fonte_recurso") and ln["valor_pago"]:
            p["fontes"].add(ln["fonte_recurso"])
        if ln["valor_pago"]:
            p["sub"][ln["subprojeto"] or "—"] += ln["valor_pago"]
    programas = sorted((
        {"projeto": p["projeto"], "pago": _f(p["pago"]), "retido": _f(p["retido"]),
         "fontes": sorted(p["fontes"]),
         "subprojetos": sorted(({"subprojeto": s, "pago": _f(v)} for s, v in p["sub"].items()),
                               key=lambda x: -x["pago"])}
        for p in progs.values()), key=lambda x: -x["pago"])

    meses: dict[int, dict] = {}
    for ln in linhas:
        m = meses.setdefault(ln["mes"], {"mes": ln["mes"], "pago": Decimal(0),
                                         "retido": Decimal(0), "entidades": Decimal(0)})
        if ln["fundo_municipal"]:
            m["pago"] += ln["valor_pago"] or 0
            m["retido"] += ln["valor_retido"] or 0
        else:
            m["entidades"] += ln["valor_pago"] or 0
    serie = [{"mes": k, "pago": _f(v["pago"]), "retido": _f(v["retido"]),
              "entidades": _f(v["entidades"])} for k, v in sorted(meses.items())]

    retencoes = sorted((
        {"data": ln["data_pagamento"].isoformat() if ln.get("data_pagamento") else None,
         "mes": ln["mes"], "projeto": ln["projeto"], "subprojeto": ln["subprojeto"],
         "motivo": ln["motivo_retencao"], "tipo": ln["tipo_retencao"],
         "valor": _f(ln["valor_retido"]),
         "competencia": (f"{ln['competencia_mes']:02d}/{ln['competencia_ano']}"
                         if ln.get("competencia_mes") and ln.get("competencia_ano") else None),
         "historico": ln.get("historico")}
        for ln in fundo if ln["valor_retido"]),
        key=lambda x: (x["data"] or "", x["valor"]), reverse=True)
    por_motivo: dict[str, dict] = {}
    for r in retencoes:
        k = r["motivo"] or "sem motivo informado"
        m = por_motivo.setdefault(k, {"motivo": k, "tipo": r["tipo"], "valor": 0.0, "n": 0})
        m["valor"] = round(m["valor"] + r["valor"], 2)
        m["n"] += 1

    ents: dict[str, dict] = {}
    for ln in outros:
        e = ents.setdefault(ln["cod_credor"], {
            "credor": ln["credor"], "cod_credor": ln["cod_credor"], "pago": Decimal(0),
            "retido": Decimal(0), "retido_por_tipo": defaultdict(Decimal),
            "prog": defaultdict(Decimal)})
        e["pago"] += ln["valor_pago"] or 0
        if ln["valor_retido"]:
            e["retido"] += ln["valor_retido"]
            e["retido_por_tipo"][ln["tipo_retencao"] or "outra"] += ln["valor_retido"]
        if ln["valor_pago"]:
            e["prog"][ln["projeto"] or "—"] += ln["valor_pago"]
    entidades = sorted((
        {"credor": e["credor"], "cod_credor": e["cod_credor"], "pago": _f(e["pago"]),
         "retido": _f(e["retido"]),
         "retido_por_tipo": {k: _f(v) for k, v in e["retido_por_tipo"].items()},
         "programas": sorted(({"projeto": k, "pago": _f(v)} for k, v in e["prog"].items()),
                             key=lambda x: -x["pago"])}
        for e in ents.values()), key=lambda x: -x["pago"])

    credor_fundo = next((ln["credor"] for ln in fundo), None)
    return {
        "fundo": {
            "credor": credor_fundo,
            "total_pago": _f(sum((ln["valor_pago"] or 0 for ln in fundo), Decimal(0))),
            "total_retido": _f(sum((ln["valor_retido"] or 0 for ln in fundo), Decimal(0))),
            "programas": programas,
            "retencoes": retencoes,
            "retido_por_motivo": sorted(por_motivo.values(), key=lambda x: -x["valor"]),
        },
        "meses": serie,
        "entidades": {
            "total_pago": _f(sum((ln["valor_pago"] or 0 for ln in outros), Decimal(0))),
            "total_retido": _f(sum((ln["valor_retido"] or 0 for ln in outros), Decimal(0))),
            "itens": entidades,
        },
    }


@router.get("/fes-rs", dependencies=[exige("cofinanciamento.ver")])
async def fes_rs(
    municipio_id: Optional[int] = None,
    ano: Optional[int] = Query(None, ge=2000, le=2100),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "cofinanciamento")
    vazio = {"tem_dados": False, "fonte": FONTE_FES_RS, "anos": [], "ano": None}
    if not municipio_id:
        return vazio
    try:
        anos = [r[0] for r in (await db.execute(text(
            "SELECT DISTINCT ano FROM fes_rs_pagamentos WHERE municipio_id = :m "
            "ORDER BY ano DESC"), {"m": municipio_id})).fetchall()]
    except Exception:
        # Tabela ainda não criada (a migration roda no boot): tela vazia, não 500.
        await db.rollback()
        return vazio
    if not anos:
        return vazio
    ano = ano if ano in anos else anos[0]
    rows = (await db.execute(text("""
        SELECT mes, credor, cod_credor, fundo_municipal, projeto, subprojeto,
               fonte_recurso, competencia_ano, competencia_mes, data_pagamento,
               valor_pago, valor_retido, motivo_retencao, tipo_retencao, historico
          FROM fes_rs_pagamentos
         WHERE municipio_id = :m AND ano = :a
    """), {"m": municipio_id, "a": ano})).mappings().all()
    arq = (await db.execute(text(
        "SELECT max(pago_ate), max(lido_em) FROM fes_rs_arquivos WHERE ano = :a"),
        {"a": ano})).first()
    return {
        "tem_dados": True, "fonte": FONTE_FES_RS, "anos": anos, "ano": ano,
        "pago_ate": arq[0].isoformat() if arq and arq[0] else None,
        "lido_em": arq[1].isoformat() if arq and arq[1] else None,
        **resumo_fes_rs([dict(r) for r in rows]),
    }
