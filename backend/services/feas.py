"""FEAS — a conta da tela «Assistência social — Estado (FEAS)», numa função pura
(`montar`), para o mesmo dado dar a mesma conta em qualquer lugar que o leia.

Lê o que `ingestion/feas_estadual.py` grava da despesa aberta do Estado (MG e RS):
cada pagamento do Fundo Estadual de Assistência Social ao fundo municipal ou à
prefeitura. As regras, todas aqui:

- **Destino**: "fundo" quando o CNPJ favorecido NÃO é o da prefeitura (é o do fundo
  municipal, que veio do painel do FNAS); "prefeitura" quando é.
- **Por ação**: o total do ano corrente e do anterior, o último pagamento e há
  quantos dias ele saiu. O Piso Mineiro é mensal: ação de PISO sem pagamento há mais
  de 60 dias ganha `atrasado` — o repasse regular que parou de vir. No RS o Piso
  Gaúcho não tem calendário mensal cumprido (R$ 2,6 mi no Estado inteiro de janeiro a
  julho de 2026), então lá não há `atrasado`, só a data.
- **Estorno** entra negativo, como a fonte publica.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

ZERO = Decimal("0")
ATRASO_DIAS = 60


def _f(v: Decimal | None) -> float | None:
    return None if v is None else round(float(v), 2)


def chave_acao(acao: str | None) -> str:
    """A ação pelo CÓDIGO: o RS escreve a mesma ação de dois jeitos no mesmo ano
    ("197501022 COFINANCIAMENTO UNIFICADO..." e "197501022 Cofinanciamento
    Unificado...", Santa Maria 2025)."""
    s = (acao or "").strip()
    cod = s.split(" ", 1)[0]
    return cod if cod.isdigit() else (s.upper() or "(sem ação)")


def montar(*, pagamentos: list[dict], cnpj_prefeitura: str, uf: str, hoje: date) -> dict:
    ano, ant = hoje.year, hoje.year - 1
    por_acao: dict[str, dict] = {}
    tot = {ano: ZERO, ant: ZERO}
    destino_ano = {"fundo": ZERO, "prefeitura": ZERO}
    lista = []
    for p in sorted(pagamentos, key=lambda x: (x["data"] or date.min), reverse=True):
        destino = "prefeitura" if p["favorecido_cnpj"] == cnpj_prefeitura else "fundo"
        # A lista vem do mais novo para o mais velho: o nome da ação é o mais recente.
        a = por_acao.setdefault(chave_acao(p["acao"]), {
            "acao": p["acao"] or "(sem ação)", "ano": ZERO, "ano_anterior": ZERO,
            "ultimo": None, "pagamentos": 0, "destinos": set()})
        if p["ano"] == ano:
            a["ano"] += p["valor"]
            destino_ano[destino] += p["valor"]
        elif p["ano"] == ant:
            a["ano_anterior"] += p["valor"]
        if p["ano"] in tot:
            tot[p["ano"]] += p["valor"]
        a["pagamentos"] += 1
        a["destinos"].add(destino)
        if p["data"] and p["valor"] > 0 and (a["ultimo"] is None or p["data"] > a["ultimo"]):
            a["ultimo"] = p["data"]
        lista.append({
            "data": p["data"].isoformat() if p["data"] else None, "ano": p["ano"],
            "documento": p["documento"], "acao": a["acao"], "valor": _f(p["valor"]),
            "destino": destino, "favorecido": p["favorecido_nome"],
            "favorecido_cnpj": p["favorecido_cnpj"], "modalidade": p.get("modalidade"),
        })
    acoes = []
    for a in por_acao.values():
        dias = (hoje - a["ultimo"]).days if a["ultimo"] else None
        piso = "PISO" in (a["acao"] or "").upper()
        acoes.append({
            "acao": a["acao"], "ano": _f(a["ano"]), "ano_anterior": _f(a["ano_anterior"]),
            "ultimo": a["ultimo"].isoformat() if a["ultimo"] else None,
            "dias_desde_ultimo": dias, "pagamentos": a["pagamentos"],
            "destinos": sorted(a["destinos"]),
            "atrasado": bool(uf == "MG" and piso and dias is not None and dias > ATRASO_DIAS),
        })
    acoes.sort(key=lambda x: (-(x["ano"] or 0), -(x["ano_anterior"] or 0)))
    return {
        "ano": ano,
        "totais": {
            "ano": _f(tot[ano]), "ano_anterior": _f(tot[ant]),
            "fundo_ano": _f(destino_ano["fundo"]), "prefeitura_ano": _f(destino_ano["prefeitura"]),
            "pagamentos": len(lista),
            "ultimo": lista[0]["data"] if lista else None,
        },
        "acoes": acoes,
        "atrasadas": [a["acao"] for a in acoes if a["atrasado"]],
        "pagamentos": lista,
    }
