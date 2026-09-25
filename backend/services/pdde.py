"""PDDE — a conta da tela, numa função pura (`montar`), para o mesmo dado dar a
mesma conta em qualquer lugar que o leia.

Lê o que `ingestion/pdde_info.py` grava (saldo por conta e mês, situação da PC por
escola, suspensões) e o PDDE PAGO das liberações do FNDE por entidade
(`simec_par_liberacoes`, gravadas pela consulta `pls/simad` de
`ingestion/fnde_liberacoes.py` — as mesmas que a tela do SIMEC mostra no bloco das
escolas), que NÃO é coletado de novo: é somado aqui pelo CNPJ da caixa escolar.

As regras, todas aqui:

- **Entidade = quem tem a conta**: a caixa escolar/APM (UEx) ou a prefeitura (EEx),
  pelo CNPJ. As escolas (INEP) penduram na entidade que as executa.
- **Rede municipal** (a conta da tela, `rede=municipal`): a entidade é municipal se
  QUALQUER registro dela é da rede municipal (conta com "MUNICIPAL" nas redes,
  linha da PC que veio na consulta municipal, suspensão de escola municipal) ou se
  é a própria prefeitura. Caixa escolar que atende escola municipal E estadual
  entra — ela recebe pela escola municipal. As outras redes (estadual, particular)
  vêm em `outras_redes`, fora da conta, nunca descartadas.
- **Saldo** da entidade = soma das contas no mês de referência (conta + fundos +
  poupança + RDB/CDB). Cada conta é UMA linha no banco (o coletor já tirou a
  repetição por rede).
- **Parado**: saldo ≥ o valor previsto para o ANO inteiro (soma do "Valor Total
  Previsto" das escolas da entidade na PC do ano). Dinheiro que passa de um ano
  de repasse é dinheiro que a escola não gastou. Sem previsto, `parado` é None —
  "não dá para dizer", nunca "não está parado".
- **Suspensa**: tem linha no relatório de suspensão do ano — é a próxima parcela
  que não sai (a "situação da PC" é a posição em 01/01 e diz adimplente onde a
  suspensão diz inadimplente; ver a armadilha 6 do coletor).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

ZERO = Decimal("0")


def _f(v: Decimal | None) -> float | None:
    return None if v is None else round(float(v), 2)


def _iso_mes(m: date | None) -> str | None:
    return f"{m.year:04d}-{m.month:02d}" if m else None


def montar(*, cnpj_prefeitura: str, rede: str, mes_ref: date | None,
           saldo: list[dict], saldo_antigo: dict[str, Decimal] | None,
           prestacao: list[dict], suspensao: list[dict],
           recebido: dict[str, Decimal] | None) -> dict:
    """O corpo da resposta. `saldo`: as contas do mês de referência; `saldo_antigo`:
    {cnpj: saldo} de 6 meses antes (None = mês não carregado); `prestacao` e
    `suspensao`: as linhas do ano; `recebido`: {cnpj: PDDE liberado pelo FNDE no
    ano} (None = liberações do ano ainda não lidas para o município)."""
    ent: dict[str, dict] = {}

    def e(cnpj: str) -> dict:
        x = ent.get(cnpj)
        if x is None:
            x = ent[cnpj] = {
                "cnpj": cnpj, "nome": None, "prefeitura": cnpj == cnpj_prefeitura,
                "redes": set(), "municipal": cnpj == cnpj_prefeitura,
                "saldo": ZERO, "tem_saldo": False,
                "por_tipo": {"conta": ZERO, "fundos": ZERO, "poupanca": ZERO, "rdb_cdb": ZERO},
                "contas": [], "escolas": {}, "suspensoes": [], "previsto": ZERO,
                "tem_previsto": False, "situacoes": set(),
            }
        return x

    for c in saldo:
        x = e(c["cnpj"])
        x["nome"] = x["nome"] or c["razao_social"]
        x["redes"].update(c["redes"])
        x["municipal"] = x["municipal"] or "municipal" in c["redes"]
        total = c["saldo_conta"] + c["saldo_fundos"] + c["saldo_poupanca"] + c["saldo_rdb_cdb"]
        x["saldo"] += total
        x["tem_saldo"] = True
        for k, col in (("conta", "saldo_conta"), ("fundos", "saldo_fundos"),
                       ("poupanca", "saldo_poupanca"), ("rdb_cdb", "saldo_rdb_cdb")):
            x["por_tipo"][k] += c[col]
        x["contas"].append({"banco": c["banco"], "agencia": c["agencia"], "conta": c["conta"],
                            "programa": c["programa"], "saldo": _f(total)})

    for p in prestacao:
        # A escola sem UEx é executada pela EEx (a prefeitura, na rede municipal).
        dono = p["uex_cnpj"] or p["eex_cnpj"]
        if not dono:
            continue
        x = e(dono)
        if p["municipal"]:
            x["municipal"] = True
            x["redes"].add("municipal")
        if dono == p["eex_cnpj"] and not p["uex_cnpj"]:
            x["nome"] = x["nome"] or p["eex_nome"]
        esc = x["escolas"].setdefault(p["escola_inep"] or p["escola_nome"], {
            "inep": p["escola_inep"], "nome": p["escola_nome"], "programas": [],
            "previsto": ZERO, "situacao_uex": None, "situacao_eex": None,
            "suspensa_pc": False, "eex": p["eex_nome"],
        })
        if p["programa"] and p["programa"] not in esc["programas"]:
            esc["programas"].append(p["programa"])
        if p["valor_previsto"] is not None:
            esc["previsto"] += p["valor_previsto"]
            x["previsto"] += p["valor_previsto"]
            x["tem_previsto"] = True
        esc["situacao_uex"] = esc["situacao_uex"] or p["uex_situacao"]
        esc["situacao_eex"] = esc["situacao_eex"] or p["eex_situacao"]
        esc["suspensa_pc"] = esc["suspensa_pc"] or bool(p["uex_suspensa"] or p["eex_suspensa"])
        for s in (p["uex_situacao"], p["eex_situacao"]):
            if s:
                x["situacoes"].add(s)

    sem_executora = []
    for s in suspensao:
        item = {"escola_inep": s["escola_inep"], "escola_nome": s["escola_nome"],
                "programa": s["programa"], "destinacao": s["destinacao"], "tipo": s["tipo"],
                "rede": s["rede"]}
        if not s["uex_cnpj"]:
            if rede == "todas" or s["rede"] == "municipal":
                sem_executora.append(item)
            continue
        x = e(s["uex_cnpj"])
        x["nome"] = x["nome"] or s["uex_nome"]
        x["redes"].add(s["rede"])
        if s["rede"] == "municipal":
            x["municipal"] = True
        x["suspensoes"].append(item)

    entidades, fora = [], {"saldo": ZERO, "entidades": 0, "suspensas": 0}
    for x in ent.values():
        na_conta = rede == "todas" or x["municipal"]
        if not na_conta:
            fora["saldo"] += x["saldo"]
            fora["entidades"] += 1
            fora["suspensas"] += bool(x["suspensoes"])
            continue
        previsto = x["previsto"] if x["tem_previsto"] else None
        parado = (None if not previsto or not x["tem_saldo"]
                  else x["saldo"] >= previsto)
        antigo = None if saldo_antigo is None else saldo_antigo.get(x["cnpj"])
        entidades.append({
            "cnpj": x["cnpj"], "nome": x["nome"], "prefeitura": x["prefeitura"],
            "redes": sorted(x["redes"]), "municipal": x["municipal"],
            "saldo": _f(x["saldo"]) if x["tem_saldo"] else None,
            "saldo_por_tipo": {k: _f(v) for k, v in x["por_tipo"].items()},
            "saldo_6_meses_antes": _f(antigo),
            "previsto_ano": _f(previsto),
            "parado": parado,
            "recebido_ano": (None if recebido is None else _f(recebido.get(x["cnpj"]))),
            "contas": sorted(x["contas"], key=lambda c: -(c["saldo"] or 0)),
            "escolas": sorted(({**esc, "previsto": _f(esc["previsto"])}
                               for esc in x["escolas"].values()),
                              key=lambda s: s["nome"] or ""),
            "suspensoes": x["suspensoes"],
            "suspensa": bool(x["suspensoes"]),
            "situacoes_pc": sorted(x["situacoes"]),
        })
    # Suspensas primeiro (é a parcela que não vem), depois o maior saldo parado.
    entidades.sort(key=lambda x: (not x["suspensa"], not x["parado"], -(x["saldo"] or 0)))

    escolas_suspensas = {(s["escola_inep"] or s["escola_nome"]) for x in entidades
                         for s in x["suspensoes"]} | {
        (s["escola_inep"] or s["escola_nome"]) for s in sem_executora}
    tipos: dict[str, set] = defaultdict(set)
    for x in entidades:
        for s in x["suspensoes"]:
            tipos[s["tipo"]].add(s["escola_inep"] or s["escola_nome"])
    for s in sem_executora:
        tipos[s["tipo"]].add(s["escola_inep"] or s["escola_nome"])

    # A PREFEITURA como EEx: se ela estiver inadimplente ou suspensa, toda escola
    # municipal que ela executa (as sem UEx e as que dependem dela) para junto.
    da_pref = [p for p in prestacao if cnpj_prefeitura and p["eex_cnpj"] == cnpj_prefeitura]
    eex = None if not da_pref else {
        "situacoes": sorted({p["eex_situacao"] for p in da_pref if p["eex_situacao"]}),
        "suspensa": any(p["eex_suspensa"] for p in da_pref),
        "escolas": len({p["escola_inep"] or p["escola_nome"] for p in da_pref}),
    }

    saldo_total = sum((Decimal(str(x["saldo"])) for x in entidades if x["saldo"] is not None),
                      ZERO)
    parados = [x for x in entidades if x["parado"]]
    com_lib = [x for x in entidades if x["recebido_ano"] is not None]
    return {
        "rede": rede,
        "mes_referencia": _iso_mes(mes_ref),
        "totais": {
            "saldo": _f(saldo_total),
            "entidades": len(entidades),
            "contas": sum(len(x["contas"]) for x in entidades),
            "escolas": len({s["inep"] or s["nome"] for x in entidades for s in x["escolas"]}),
            "escolas_suspensas": len(escolas_suspensas),
            "entidades_paradas": len(parados),
            "saldo_parado": _f(sum((Decimal(str(x["saldo"])) for x in parados), ZERO)),
            "previsto_ano": _f(sum((Decimal(str(x["previsto_ano"])) for x in entidades
                                    if x["previsto_ano"] is not None), ZERO)),
            # Nenhuma executora com liberação = None, e não zero: a tela diz "sem
            # liberação de PDDE no ano" por executora; o total zero seria lido
            # como "o FNDE não pagou nada", que a ausência de linha não prova.
            "recebido_ano": _f(sum((Decimal(str(x["recebido_ano"])) for x in com_lib), ZERO))
            if com_lib else None,
            "entidades_com_liberacao": len(com_lib),
        },
        "prefeitura_eex": eex,
        "suspensoes_por_tipo": sorted(({"tipo": k, "escolas": len(v)} for k, v in tipos.items()),
                                      key=lambda t: -t["escolas"]),
        "sem_executora": sem_executora,
        "entidades": entidades,
        "outras_redes": None if rede == "todas" else {
            "saldo": _f(fora["saldo"]), "entidades": fora["entidades"],
            "suspensas": fora["suspensas"]},
    }
