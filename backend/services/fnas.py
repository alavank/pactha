"""FNAS — a conta da tela «Assistência social — FNAS», numa função pura (`montar`),
para o mesmo dado dar a mesma conta em qualquer lugar que o leia.

Lê o que `ingestion/fnas_suas.py` grava do painel do MDS: o saldo de cada conta do
fundo por mês (`fnas_saldo_conta`), cada repasse (`fnas_repasse`) e as emendas com
o parlamentar (`fnas_emenda`). As regras, todas aqui:

- **Mês de referência** = o mês mais novo com saldo no banco (o painel publica com
  ~1 mês de atraso: em 26/09/2026, agosto). Nunca a data de hoje.
- **Saldo** da conta = `vl_total` (conta corrente + poupança + fundos + CDB/RDB),
  UMA linha por conta e mês (o coletor confere).
- **Repassado em 12 meses** = soma dos repasses de COMPETÊNCIA nos 12 meses que
  terminam no mês de referência, casados pela conta (sem os zeros à esquerda —
  armadilha 4 do coletor).
- **Parado**: saldo ≥ R$ 1.000, NENHUM repasse na conta em 12 meses e o saldo
  não caiu mais que 10% desde o mesmo mês do ano anterior — o dinheiro só rendeu
  juros. Sem o saldo de 12 meses antes, `parado` é None ("não dá para dizer"),
  nunca False.
- **Meses de repasse**: para a conta que recebe (bloco), saldo ÷ média mensal do
  repassado em 12 meses — quantos meses de repasse estão em conta. Não é regra do
  MDS; é a régua para o gestor comparar contas de tamanhos diferentes.
- **Emenda**: pendura na conta onde a OB caiu; a tela mostra o saldo que essa
  conta tem hoje.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

ZERO = Decimal("0")
PARADO_MINIMO = Decimal("1000")
QUEDA_TOLERADA = Decimal("0.9")


def _f(v: Decimal | None) -> float | None:
    return None if v is None else round(float(v), 2)


def ym_menos(ano_mes: int, n: int) -> int:
    a, m = divmod((ano_mes // 100) * 12 + (ano_mes % 100 - 1) - n, 12)
    return a * 100 + m + 1


def iso_mes(ano_mes: int | None) -> str | None:
    return f"{ano_mes // 100:04d}-{ano_mes % 100:02d}" if ano_mes else None


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def montar(*, saldos: list[dict], repasses: list[dict], ultimos: dict[str, date],
           emendas: list[dict]) -> dict:
    """`saldos`: as linhas dos 13 meses que terminam no mês mais novo; `repasses`:
    os repasses dos 12 meses de competência até o mês mais novo; `ultimos`:
    {conta: data da última OB} em todo o histórico; `emendas`: todas."""
    if not saldos:
        return {"mes_referencia": None, "totais": None, "contas": [], "repasses_12m": [],
                "emendas": [], "serie": []}
    mes_ref = max(s["ano_mes"] for s in saldos)
    mes_antes = ym_menos(mes_ref, 12)
    ini = ym_menos(mes_ref, 11)

    por_mes: dict[int, Decimal] = defaultdict(lambda: ZERO)
    antes: dict[tuple, Decimal] = {}
    atuais = []
    for s in saldos:
        por_mes[s["ano_mes"]] += s["vl_total"]
        if s["ano_mes"] == mes_ref:
            atuais.append(s)
        elif s["ano_mes"] == mes_antes:
            antes[(s["agencia"], s["conta"])] = antes.get((s["agencia"], s["conta"]), ZERO) + s["vl_total"]
    tem_antes = any(s["ano_mes"] == mes_antes for s in saldos)

    rep_conta: dict[str, Decimal] = defaultdict(lambda: ZERO)
    blocos: dict[str, dict] = {}
    for r in repasses:
        ym = (r["ano"] or 0) * 100 + (r["mes"] or 0)
        if not (ini <= ym <= mes_ref):
            continue
        if r.get("conta"):
            rep_conta[r["conta"]] += r["valor"]
        b = blocos.setdefault(r["bloco"] or "(sem bloco)", {"bloco": r["bloco"] or "(sem bloco)",
                                                            "total": ZERO, "obs": []})
        b["total"] += r["valor"]
        b["obs"].append({
            "competencia": f"{r['mes']:02d}/{r['ano']}" if r["mes"] else str(r["ano"]),
            "dt_ob": _iso(r["dt_ob"]), "ob": r["ob"], "piso": r["piso"],
            "programa": r["programa"], "conta": r["conta"], "valor": _f(r["valor"])})

    em_conta: dict[str, list] = defaultdict(list)
    for e in emendas:
        if e.get("conta"):
            em_conta[e["conta"]].append(e)

    contas = []
    for s in atuais:
        saldo = s["vl_total"]
        ant = antes.get((s["agencia"], s["conta"])) if tem_antes else None
        rep = rep_conta.get(s["conta"], ZERO)
        if ant is None:
            parado = None
        else:
            parado = saldo >= PARADO_MINIMO and rep == 0 and saldo >= ant * QUEDA_TOLERADA
        meses = round(float(saldo / (rep / 12)), 1) if rep > 0 else None
        contas.append({
            "agencia": s["agencia"], "conta": s["conta"], "cnpj": s["cnpj"],
            "tipo_entidade": s["tipo_entidade"], "bloco": s["bloco"], "nome": s["tipo_conta"],
            "saldo": _f(saldo),
            "por_tipo": {"conta_corrente": _f(s["vl_conta_corrente"]),
                         "poupanca": _f(s["vl_poupanca"]), "fundos": _f(s["vl_fundos"]),
                         "cdb_rdb": _f(s["vl_cdb_rdb"])},
            "saldo_12m_antes": _f(ant) if tem_antes else None,
            "repassado_12m": _f(rep),
            "ultimo_repasse": _iso(ultimos.get(s["conta"])),
            "meses_de_repasse": meses,
            "parado": parado,
            "emendas": [{"parlamentar": e["parlamentar"], "partido": e["partido"],
                         "ano": e["ano"], "valor": _f(e["valor"]), "dt_ob": _iso(e["dt_ob"]),
                         "tipo_emenda": e["tipo_emenda"]}
                        for e in sorted(em_conta.get(s["conta"], []),
                                        key=lambda x: (x["ano"] or 0), reverse=True)],
        })
    contas.sort(key=lambda c: (not c["parado"], -(c["saldo"] or 0)))

    saldo_conta = {c["conta"]: c["saldo"] for c in contas}
    lista_emendas = [{
        "parlamentar": e["parlamentar"], "partido": e["partido"], "tipo_emenda": e["tipo_emenda"],
        "programa": e["programa"], "ano": e["ano"], "valor": _f(e["valor"]),
        "dt_ob": _iso(e["dt_ob"]), "ob": e["ob"], "conta": e["conta"],
        "saldo_conta_hoje": saldo_conta.get(e["conta"]),
    } for e in sorted(emendas, key=lambda x: ((x["ano"] or 0), x["dt_ob"] or date.min), reverse=True)]

    blocos_l = sorted(blocos.values(), key=lambda b: -b["total"])
    for b in blocos_l:
        b["total"] = _f(b["total"])
        b["obs"].sort(key=lambda o: o["dt_ob"] or "", reverse=True)

    paradas = [c for c in contas if c["parado"]]
    saldo_total = sum((s["vl_total"] for s in atuais), ZERO)
    return {
        "mes_referencia": iso_mes(mes_ref),
        "totais": {
            "saldo": _f(saldo_total),
            "saldo_12m_antes": _f(por_mes[mes_antes]) if tem_antes else None,
            "contas": len(contas),
            "repassado_12m": _f(sum((r["valor"] for r in repasses
                                     if ini <= (r["ano"] or 0) * 100 + (r["mes"] or 0) <= mes_ref), ZERO)),
            "repassado_12m_desde": iso_mes(ini),
            "contas_paradas": len(paradas),
            "saldo_parado": round(sum(c["saldo"] or 0 for c in paradas), 2),
            "emendas": len(emendas),
            "emendas_valor": _f(sum((e["valor"] for e in emendas), ZERO)),
            "parlamentares": len({e["parlamentar"] for e in emendas}),
        },
        "contas": contas,
        "repasses_12m": blocos_l,
        "emendas": lista_emendas,
        "serie": [{"mes": iso_mes(m), "saldo": _f(v)} for m, v in sorted(por_mes.items())],
    }
