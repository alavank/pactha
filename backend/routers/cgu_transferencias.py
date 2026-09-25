"""Recursos recebidos por pasta — todo repasse da União ao município, mês a mês.

Lê o que `ingestion/cgu_transferencias.py` grava do arquivo de transferências do
Portal da Transparência (CGU). Uma tela (`cgu_transferencias`), uma rota sob
`cgu_transferencias.ver`, que devolve de uma vez o que a tela desenha: o total por
pasta no período, a série mensal, os favorecidos e o detalhe por ação e
favorecido (do período, ou de UM mês com `mes=AAAA-MM`).

⚠️ A CLASSIFICAÇÃO É UMA SÓ: `services/transferencias_pasta.py` (pasta e
favorecido). Ela é aplicada aqui, na leitura, e não gravada — então a mesma regra
vale para todo mês já carregado, e nenhuma tela soma diferente.

⚠️ O TOTAL É DO MUNICÍPIO (`quem=municipio`, o padrão): prefeitura, fundos,
secretarias e órgãos municipais. Escola (caixa escolar, APM — pode ser de escola
estadual) e entidade (em Santa Maria, a fundação de apoio da UFSM) vêm em
`por_grupo`, sempre, e só entram nas contas com `quem=todos`. Regra do dono: nada
é descartado, nada entra na conta como se fosse da prefeitura.

⚠️ MÊS PARCIAL: o corrente (e qualquer mês gravado enquanto corria) é parcial, e
as constitucionais (FPM, FUNDEB, ITR, royalties) só entram depois do fechamento —
`serie[].parcial` e `serie[].sem_constitucionais` dizem isso por mês, para a tela
avisar em vez de mostrar um "FPM zero".

⚠️ "Ainda não coletado" ≠ "o município não recebeu nada": sem linha em
`cgu_transferencias_carga`, `coletado: false`; mês da janela sem carga,
`serie[].coletado: false`.
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
from services.registro_rotas import exige
from services.transferencias_pasta import (
    DO_MUNICIPIO, GRUPOS, PASTAS, ROTULO_GRUPO, ROTULO_PASTA, grupo_favorecido, pasta,
)

router = APIRouter(prefix="/api/cgu-transferencias", tags=["cgu-transferencias"])

BRT = timezone(timedelta(hours=-3))
_ORDEM_PASTA = {k: i for i, (k, _) in enumerate(PASTAS)}


def _mes_menos(m: date, n: int) -> date:
    a, b = divmod(m.year * 12 + (m.month - 1) - n, 12)
    return date(a, b + 1, 1)


def _iso_mes(m: date) -> str:
    return f"{m.year:04d}-{m.month:02d}"


def _f(v: Decimal | None) -> float:
    return round(float(v or 0), 2)


def classificar(linhas, cnpj_prefeitura: str) -> list[dict]:
    """As linhas agregadas do banco com `pasta` e `grupo` — a regra única."""
    out = []
    for r in linhas:
        out.append({
            **r,
            "pasta": pasta(r["tipo_transferencia"], r["orgao_codigo"], r["funcao_codigo"],
                           r["subfuncao_codigo"], r["acao_codigo"]),
            "grupo": grupo_favorecido(r["favorecido_doc"], r["favorecido_nome"],
                                      r["tipo_favorecido"], r["orgao_codigo"], cnpj_prefeitura),
            "constitucional": (r["tipo_transferencia"] or "").lower().startswith("constitucionais"),
        })
    return out


def montar(linhas: list[dict], cargas: list[dict], corrente: date, meses: int,
           quem: str, mes_detalhe: date | None) -> dict:
    """O corpo da resposta, a partir das linhas JÁ classificadas. Função pura: é o
    que os testes exercitam, e a única conta da tela."""
    de = _mes_menos(corrente, meses - 1)
    carga = {c["mes"]: c for c in cargas}
    linhas = [x for x in linhas if x["mes"] >= de]

    por_grupo: dict[str, dict] = {}
    for x in linhas:
        g = por_grupo.setdefault(x["grupo"], {"total": Decimal("0"), "docs": set()})
        g["total"] += x["valor"]
        g["docs"].add(x["favorecido_doc"] or x["favorecido_nome"])
    conta = [x for x in linhas if quem == "todos" or x["grupo"] in DO_MUNICIPIO]

    pastas: dict[str, Decimal] = {}
    serie: dict[date, dict] = {}
    for x in conta:
        pastas[x["pasta"]] = pastas.get(x["pasta"], Decimal("0")) + x["valor"]
        s = serie.setdefault(x["mes"], {})
        s[x["pasta"]] = s.get(x["pasta"], Decimal("0")) + x["valor"]
    com_constitucionais = {x["mes"] for x in linhas if x["constitucional"]}

    meses_serie = []
    for n in range(meses - 1, -1, -1):
        m = _mes_menos(corrente, n)
        c = carga.get(m)
        por_pasta = serie.get(m, {})
        parcial = m >= corrente or (c is not None and not c["mes_fechado"])
        meses_serie.append({
            "mes": _iso_mes(m),
            "coletado": c is not None,
            "parcial": parcial,
            # Mês lido sem nenhuma linha constitucional: no corrente é a regra da
            # fonte; num fechado, é o arquivo que ainda não trouxe o FPM.
            "sem_constitucionais": c is not None and m not in com_constitucionais,
            "total": _f(sum(por_pasta.values(), Decimal("0"))),
            "por_pasta": {k: _f(v) for k, v in por_pasta.items()},
        })

    alvo = [x for x in conta if mes_detalhe is None or x["mes"] == mes_detalhe]
    det: dict[tuple, dict] = {}
    for x in alvo:
        k = (x["pasta"], x["orgao_nome"], x["acao_codigo"], x["acao_nome"],
             x["linguagem_cidada"], x["favorecido_doc"], x["favorecido_nome"], x["grupo"])
        d = det.setdefault(k, {"total": Decimal("0"), "meses": set()})
        d["total"] += x["valor"]
        d["meses"].add(x["mes"])
    detalhe = sorted(
        ({"pasta": k[0], "orgao": k[1], "acao_codigo": k[2], "acao": k[3],
          "linguagem_cidada": k[4], "favorecido_doc": k[5], "favorecido": k[6],
          "grupo": k[7], "total": _f(d["total"]), "meses": len(d["meses"])}
         for k, d in det.items()),
        key=lambda d: (_ORDEM_PASTA.get(d["pasta"], 99), -d["total"]))

    fav: dict[tuple, dict] = {}
    for x in linhas:
        k = (x["favorecido_doc"], x["favorecido_nome"], x["grupo"])
        f = fav.setdefault(k, {"total": Decimal("0"), "pastas": set()})
        f["total"] += x["valor"]
        f["pastas"].add(x["pasta"])
    favorecidos = sorted(
        ({"doc": k[0], "nome": k[1], "grupo": k[2], "rotulo_grupo": ROTULO_GRUPO[k[2]],
          "na_conta": quem == "todos" or k[2] in DO_MUNICIPIO, "total": _f(f["total"]),
          "pastas": sorted(f["pastas"], key=lambda p: _ORDEM_PASTA.get(p, 99))}
         for k, f in fav.items()),
        key=lambda f: -f["total"])

    total = sum(pastas.values(), Decimal("0"))
    return {
        "coletado": True,
        "quem": quem,
        "periodo": {"de": _iso_mes(de), "ate": _iso_mes(corrente), "meses": meses},
        "mes_corrente": _iso_mes(corrente),
        "mes_detalhe": _iso_mes(mes_detalhe) if mes_detalhe else None,
        "total": _f(total),
        "pastas": [{"chave": k, "rotulo": r, "total": _f(pastas.get(k))}
                   for k, r in PASTAS if pastas.get(k)],
        "por_grupo": [{"grupo": k, "rotulo": r, "total": _f(por_grupo[k]["total"]),
                       "favorecidos": len(por_grupo[k]["docs"]),
                       "na_conta": quem == "todos" or k in DO_MUNICIPIO}
                      for k, r in GRUPOS if k in por_grupo],
        "serie": meses_serie,
        "detalhe": detalhe,
        "favorecidos": favorecidos,
    }


@router.get("", dependencies=[exige("cgu_transferencias.ver")])
async def recursos_por_pasta(
    municipio_id: int = Query(...),
    meses: int = Query(12, ge=1, le=60),
    quem: str = Query("municipio", pattern="^(municipio|todos)$"),
    mes: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Os recursos recebidos pelo município, por pasta, nos últimos `meses` meses."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "cgu_transferencias")
    m = (await db.execute(text(
        "SELECT regexp_replace(coalesce(cnpj, ''), '\\D', '', 'g') FROM municipios WHERE id = :m"),
        {"m": municipio_id})).first()
    if m is None:
        raise HTTPException(404, "Município não encontrado")
    cargas = [dict(r) for r in (await db.execute(text("""
        SELECT mes, linhas, total, mes_fechado, carregado_em, siafi_municipio, siafi_origem
          FROM cgu_transferencias_carga WHERE municipio_id = :m ORDER BY mes DESC
    """), {"m": municipio_id})).mappings().all()]
    if not cargas:
        return {"coletado": False}

    corrente = datetime.now(BRT).date().replace(day=1)
    de = _mes_menos(corrente, meses - 1)
    mes_detalhe = None
    if mes:
        mes_detalhe = date(int(mes[:4]), int(mes[5:7]), 1)
        if not (de <= mes_detalhe <= corrente):
            raise HTTPException(422, "mês fora do período")
    linhas = (await db.execute(text("""
        SELECT mes, tipo_transferencia, tipo_favorecido, orgao_codigo, orgao_nome,
               funcao_codigo, subfuncao_codigo, acao_codigo, acao_nome, linguagem_cidada,
               favorecido_doc, favorecido_nome, sum(valor) AS valor
          FROM cgu_transferencias
         WHERE municipio_id = :m AND mes >= :de
         GROUP BY mes, tipo_transferencia, tipo_favorecido, orgao_codigo, orgao_nome,
                  funcao_codigo, subfuncao_codigo, acao_codigo, acao_nome, linguagem_cidada,
                  favorecido_doc, favorecido_nome
    """), {"m": municipio_id, "de": de})).mappings().all()

    corpo = montar(classificar([dict(r) for r in linhas], m[0]), cargas, corrente, meses,
                   quem, mes_detalhe)
    ultima = cargas[0]
    corpo["atualizado_em"] = max(c["carregado_em"] for c in cargas).isoformat()
    corpo["siafi"] = {"codigo": ultima["siafi_municipio"], "origem": ultima["siafi_origem"]}
    corpo["rotulos"] = {"pastas": ROTULO_PASTA, "grupos": ROTULO_GRUPO}
    return corpo
