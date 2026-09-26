"""PNAB 2027 — o município vai continuar recebendo a Aldir Blanc? A conta da aba
«Cultura (PNAB)» da tela de Regularidade, numa função pura (`montar`).

A regra: Lei 14.399/2022, art. 6º, § 8º (incluído pela Lei 15.132/2025) — "A partir
de 2027, somente receberão os recursos previstos nesta Lei os entes federativos que
dispuserem de fundo de cultura, conforme regulamento". Até 2026 (§ 7º) o repasse vai
para a estrutura que o ente indicar.

Duas evidências de que o fundo existe, e a tela diz qual achou:
- **O dinheiro**: o PNAB dos últimos 12 meses (ação 00UV na planilha da CGU,
  `cgu_transferencias`) caiu num CNPJ que NÃO é o da prefeitura e cujo nome tem
  FUNDO e CULTURA — o fundo existe e já recebe.
- **O registro**: a "Lei do Fundo de Cultura" com documento no Sistema Nacional de
  Cultura (`snc_cultura`, `ingestion/snc_cultura.py`).

Situação:
- `ok`       — o PNAB já cai no fundo de cultura;
- `atencao`  — lei do fundo registrada no SNC, mas o PNAB ainda cai na prefeitura (ou
               não há PNAB no período): o fundo existe no papel, falta ele receber;
- `risco`    — nenhuma das duas: sem fundo de cultura à vista, o PNAB para em 2027;
- `sem_dado` — o SNC ainda não foi lido para o município (nunca "risco" por falta de
               leitura).
"""
from __future__ import annotations

import unicodedata
from decimal import Decimal

ACAO_PNAB = "00UV"


def _norm(s: str | None) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn").upper()


def e_fundo_de_cultura(nome: str | None) -> bool:
    n = _norm(nome)
    return "FUNDO" in n and "CULTURA" in n


def montar(*, snc: dict | None, pnab: list[dict], cnpj_prefeitura: str) -> dict:
    """`snc`: a linha de `snc_cultura` (None = não lido); `pnab`: [{favorecido_doc,
    favorecido_nome, valor}] somados nos últimos 12 meses."""
    favorecidos = []
    total = Decimal("0")
    no_fundo = Decimal("0")
    for p in pnab:
        fundo = p["favorecido_doc"] != cnpj_prefeitura and e_fundo_de_cultura(p["favorecido_nome"])
        total += p["valor"]
        if fundo:
            no_fundo += p["valor"]
        favorecidos.append({"cnpj": p["favorecido_doc"], "nome": p["favorecido_nome"],
                            "valor": round(float(p["valor"]), 2), "fundo_de_cultura": fundo})
    favorecidos.sort(key=lambda f: -f["valor"])
    recebe_no_fundo = no_fundo > 0
    registrado = bool(snc and snc.get("fundo_registrado"))
    if recebe_no_fundo:
        situacao = "ok"
    elif snc is None:
        situacao = "sem_dado"
    elif registrado:
        situacao = "atencao"
    else:
        situacao = "risco"
    return {
        "situacao": situacao,
        "fundo_registrado_snc": registrado if snc is not None else None,
        "recebe_no_fundo": recebe_no_fundo,
        "pnab_12m": round(float(total), 2),
        "favorecidos": favorecidos,
        "snc": None if snc is None else {
            "situacao": snc["situacao"],
            "data_publicacao": snc["data_publicacao"].isoformat() if snc.get("data_publicacao") else None,
            "componentes": snc["componentes"],
            "lido_em": snc["lido_em"].isoformat() if snc.get("lido_em") else None,
        },
    }
