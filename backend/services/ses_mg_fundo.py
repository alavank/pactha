"""Fundo a fundo estadual da saúde de MG — a conta da tela, num lugar só.

Lê o que `ingestion/ses_mg_resolucoes.py` grava em `ses_mg_pagamentos` e monta os
blocos da tela Cofinanciamento Saúde para município de Minas. As regras que
decidem o que SOMA ficam aqui, e não no componente, para que a tela, o PDF e quem
mais ler isto façam a mesma conta (regra do dono: mesmo dado, mesma conta):

- **Ordinário** = orçamentário, categoria `ordinario`, credor conferido como do
  município. É o total da tela, por programa (UPG).
- **Emenda** (UPG 666/675) fica À PARTE e NÃO soma no total: ela já soma em
  Emendas parlamentares › Estaduais (MG), pela indicação da SEGOV. Liga-se à
  indicação só pela chave (nº da Resolução, conta sem dígito) com UM resultado —
  sem chave, não casa.
- **Restos a pagar** à parte; o de empenho que está no Acordo FES é marcado pela
  chave (CNPJ, ano, nº do empenho) de `acordofes_empenho`, nunca somado à dívida.
- **Credor que não é o município** (consórcio, hospital) aparece listado, fora
  de toda conta.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from datetime import date

from ingestion.ses_mg_resolucoes import conta_sem_dv, resolucao_norm

CATEGORIAS_A_PARTE = ("emenda", "emenda_federal", "acordo_fes")


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def chave_indicacao(resolucao, conta) -> tuple | None:
    r, c = resolucao_norm(resolucao), conta_sem_dv(conta)
    return (r, c) if r and c else None


def indice_indicacoes(indicacoes: list[dict]) -> dict:
    """{(resolução, conta): indicação} — só a chave com UMA indicação."""
    por: dict = {}
    for ind in indicacoes:
        conta = re.sub(r"\D", "", str(ind.get("conta") or "")).lstrip("0")
        r = resolucao_norm(ind.get("instrumento"))
        if r and conta:
            por.setdefault((r, conta), []).append(ind)
    return {k: v[0] for k, v in por.items() if len(v) == 1}


def _pagamento(p: dict) -> dict:
    return {
        "id_fonte": p["id_fonte"], "data": p["data_pagamento"], "valor": _f(p["valor"]),
        "resolucao": p["resolucao"], "num_ob": p["num_ob"], "num_empenho": p["num_empenho"],
        "ano_empenho": p["ano_empenho"], "cod_upg": p["cod_upg"], "upg": p["upg"],
        "atividade": p["atividade"], "banco": p["banco"], "agencia": p["agencia"],
        "conta": p["conta"], "cnpj_credor": p["cnpj_credor"], "razao_credor": p["razao_credor"],
    }


def monta(pagamentos: list[dict], indicacoes: list[dict], empenhos_fes: dict) -> dict:
    """Blocos da tela a partir das linhas de UM município e UM ano de pagamento.

    `empenhos_fes`: {(cnpj, ano_empenho, num_empenho): {divida_atual, resolucao}}."""
    idx = indice_indicacoes(indicacoes)
    programas: "OrderedDict[str, dict]" = OrderedDict()
    a_parte = {c: {"total": 0.0, "n": 0, "pagamentos": []} for c in CATEGORIAS_A_PARTE}
    restos = {"total": 0.0, "n": 0, "total_acordo_fes": 0.0, "pagamentos": []}
    outros: "OrderedDict[str, dict]" = OrderedDict()
    ordinario_total, ordinario_n = 0.0, 0
    ligadas = 0

    for p in sorted(pagamentos, key=lambda x: (x["data_pagamento"] or date.min, x["id_fonte"]),
                    reverse=True):
        if not p["do_municipio"]:
            o = outros.setdefault(p["cnpj_credor"], {
                "cnpj": p["cnpj_credor"], "razao_social": p["razao_credor"],
                "total": 0.0, "n": 0})
            o["total"] += _f(p["valor"])
            o["n"] += 1
            continue
        item = _pagamento(p)
        if p["tipo"] == "restos":
            fes = empenhos_fes.get((p["cnpj_credor"], p["ano_empenho"], p["num_empenho"]))
            item["categoria"] = p["categoria"]
            item["acordo_fes"] = fes
            restos["total"] += item["valor"]
            restos["n"] += 1
            if fes:
                restos["total_acordo_fes"] += item["valor"]
            restos["pagamentos"].append(item)
            continue
        if p["categoria"] in a_parte:
            if p["categoria"] == "emenda":
                k = chave_indicacao(p["resolucao"], p["conta"])
                item["indicacao"] = idx.get(k) if k else None
                ligadas += 1 if item["indicacao"] else 0
            bloco = a_parte[p["categoria"]]
            bloco["total"] += item["valor"]
            bloco["n"] += 1
            bloco["pagamentos"].append(item)
            continue
        chave = p["cod_upg"] or "?"
        prog = programas.setdefault(chave, {
            "cod_upg": p["cod_upg"], "upg": p["upg"], "atividade": p["atividade"],
            "total": 0.0, "n": 0, "ultimo_pagamento": None, "pagamentos": []})
        prog["total"] += item["valor"]
        prog["n"] += 1
        if p["data_pagamento"] and (prog["ultimo_pagamento"] is None
                                    or p["data_pagamento"] > prog["ultimo_pagamento"]):
            prog["ultimo_pagamento"] = p["data_pagamento"]
        prog["pagamentos"].append(item)
        ordinario_total += item["valor"]
        ordinario_n += 1

    a_parte["emenda"]["ligadas"] = ligadas
    # Soma de float acumula resto (427662.7999999999): o centavo é arredondado
    # UMA vez, aqui, e não em cada tela.
    for bloco in (*a_parte.values(), restos, *programas.values(), *outros.values()):
        for k in ("total", "total_acordo_fes"):
            if k in bloco:
                bloco[k] = round(bloco[k], 2)
    return {
        "ordinario": {
            "total": round(ordinario_total, 2), "n": ordinario_n,
            "programas": sorted(programas.values(), key=lambda x: -x["total"]),
        },
        "emendas": a_parte["emenda"],
        "emendas_federais": a_parte["emenda_federal"],
        "acordo_fes": a_parte["acordo_fes"],
        "restos": restos,
        "outros_credores": sorted(outros.values(), key=lambda x: -x["total"]),
    }
