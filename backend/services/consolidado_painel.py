"""O PAINEL DA CARTEIRA — a home do CONSOLIDADO (18/09/2026, PR 2 da série).

Uma linha por município, com o que muda a semana da assessoria:
  - regularidade FEDERAL (CAUC) e ESTADUAL (CAGEC/CHE);
  - convênio vencendo nos próximos 90 dias;
  - documento de regularidade vencendo nos próximos 30 dias;
  - emenda federal empenhada e SEM PAGAMENTO;
  - Radar: programas abertos para o município e onde ele está nomeado/indicado.
E, embaixo, as listas que dizem QUAL: vencimentos, documentos e Radar.

⚠️ CADA BLOCO É A CONTA DE UMA TELA QUE JÁ EXISTE, chamada com a lista da
carteira — nada é recalculado aqui ("mesmo dado, mesma conta em toda tela"):
  - CAUC ............ `services/bi.bi_cauc_rollup`
  - estadual ........ `cagec_situacao` com a regra do `_semaforo_cagec` (routers/bi.py):
                      o município só está em dia se NENHUMA entidade está irregular
  - vencimentos ..... `routers/convenios.query_alertas_vigencia`
  - documentos ...... `services/bi_abas.documentos_vencendo`
  - emendas ......... `routers/emendas_parlamentares._fontes_federais` +
                      `services/emendas_unificadas` (o grupo `parado` da aba Federais,
                      que ela chama de "Sem pagamento")
  - Radar ........... `_CTE_ABERTOS` + `_FILTRO_ABERTOS` de routers/programas_captacao
                      (o mesmo número do contador do menu de cada município)

⚠️ NUNCA TOTAL SOZINHO. O painel conta MUNICÍPIOS ("3 com pendência"), não soma
dinheiro da carteira: o número de um cliente lido como de outro é o risco que
tirou o "Consolidado (todos)" do seletor em 05/08/2026.

⚠️ "SEM DADO" NÃO É "EM DIA". Bloco sem coleta volta `None` e a tela escreve
"sem coleta"; estado sem cadastro coletado é "sem fonte". Nunca verde por falta
de informação.
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("consolidado")

DIAS_VENCIMENTO = 90
DIAS_DOCUMENTO = 30
LIMITE_LISTA = 80

# Cache curto por escopo: o painel varre a carteira inteira (dezenas de consultas
# por município) e a página é aberta várias vezes seguidas. Por processo, como o
# do overview do BI — com `--workers 2`, cada worker aquece o seu.
_CACHE_S = 120
_cache: dict[str, tuple[float, dict]] = {}


# ------------------------------------------------------------------ puras ---

def estadual_do_municipio(uf: str, linhas: list[tuple], ufs_cobertas: set[str]) -> dict:
    """Regularidade estadual de UM município. PURA.

    `linhas` = (principal, regular, pendencias_n) de cada entidade no
    `cagec_situacao`. Regra do `_semaforo_cagec`: cada cadastro trava o SEU
    convênio, então basta uma entidade irregular.
    """
    if uf not in ufs_cobertas:
        return {"cobertura": "sem_fonte", "regular": None, "pendencias": 0,
                "entidades_irregulares": 0}
    if not linhas:
        return {"cobertura": "sem_coleta", "regular": None, "pendencias": 0,
                "entidades_irregulares": 0}
    irregulares = sum(1 for _p, reg, _n in linhas if reg is False)
    pend = sum(int(n or 0) for _p, _r, n in linhas)
    regular = False if irregulares else (True if all(r is True for _p, r, _n in linhas) else None)
    return {"cobertura": "coberto", "regular": regular, "pendencias": pend,
            "entidades_irregulares": irregulares}


def atencao(linha: dict) -> int:
    """Quanto a linha pede atenção, para ordenar a tabela. PURA.

    Irregularidade trava repasse e vem primeiro; depois prazo curto; depois
    dinheiro parado. Sem dado não soma: "sem coleta" não é problema do cliente.
    """
    p = 0
    if (linha.get("cauc") or {}).get("regular") is False:
        p += 100
    if (linha.get("estadual") or {}).get("regular") is False:
        p += 100
    v = linha.get("vencimentos") or {}
    if v.get("proximo_dias") is not None and v["proximo_dias"] <= 30:
        p += 40
    p += 5 * int(v.get("n") or 0)
    p += 5 * int((linha.get("documentos") or {}).get("n") or 0)
    p += 10 * int((linha.get("emendas") or {}).get("sem_pagamento") or 0)
    p += 3 * int((linha.get("radar") or {}).get("nomeado") or 0)
    return p


# ---------------------------------------------------------------- montagem ---

async def _municipios(db: AsyncSession, ids: list[int]) -> list[dict]:
    rows = (await db.execute(text(
        "SELECT id, nome, upper(coalesce(uf, '')), "
        "regexp_replace(coalesce(cnpj, ''), '\\D', '', 'g') "
        "FROM municipios WHERE id = ANY(:ids) ORDER BY nome"), {"ids": ids})).fetchall()
    return [{"municipio_id": r[0], "nome": r[1], "uf": r[2], "cnpj": r[3]} for r in rows]


async def _estadual(db: AsyncSession, muns: list[dict]) -> dict[int, dict]:
    from services.cadastro_estadual import UFS_COM_CADASTRO_COLETADO
    ids = [m["municipio_id"] for m in muns]
    por: dict[int, list] = {}
    for r in (await db.execute(text(
            "SELECT municipio_id, COALESCE(principal, false), regular, "
            "COALESCE(pendencias, 0) FROM cagec_situacao WHERE municipio_id = ANY(:ids)"),
            {"ids": ids})).fetchall():
        por.setdefault(r[0], []).append((r[1], r[2], r[3]))
    return {m["municipio_id"]: estadual_do_municipio(m["uf"], por.get(m["municipio_id"], []),
                                                     set(UFS_COM_CADASTRO_COLETADO))
            for m in muns}


async def _radar(db: AsyncSession, m: dict) -> tuple[Optional[dict], list[dict]]:
    """Os programas abertos para UM município e onde ele está nomeado/indicado."""
    from routers import programas_captacao as R
    if not m["uf"]:
        return None, []
    rows = (await db.execute(text(
        R._CTE_ABERTOS
        + """        SELECT id_programa, nome, nomeado, porta_benef, porta_emenda,
               LEAST(CASE WHEN porta_receb  THEN dt_fim_receb  END,
                     CASE WHEN porta_emenda THEN dt_fim_emenda END,
                     CASE WHEN porta_benef  THEN dt_fim_benef  END) - hoje_br AS dias
          FROM base
""" + R._FILTRO_ABERTOS),
        {"uf": m["uf"], "nat": R.NATUREZA_PREFEITURA, "cnpj": m["cnpj"]})).fetchall()
    indic: dict[str, list] = {}
    if m["cnpj"] and rows:
        for a in (await db.execute(text(
                "SELECT id_programa, parlamentar, solicitante, valor "
                "FROM programas_captacao_apoiadores "
                "WHERE cnpj = :c AND id_programa = ANY(:ids)"),
                {"c": m["cnpj"], "ids": [r[0] for r in rows]})).fetchall():
            indic.setdefault(a[0], []).append(
                {"parlamentar": a[1], "solicitante": a[2],
                 "valor": float(a[3]) if a[3] is not None else None})
    lista = []
    for r in rows:
        if not (r[2] or r[0] in indic):
            continue
        lista.append({"municipio_id": m["municipio_id"], "municipio": m["nome"],
                      "id_programa": r[0], "programa": r[1],
                      "beneficiario": bool(r[3]), "dias": r[5],
                      "indicacoes": indic.get(r[0], [])})
    resumo = {"abertos": len(rows),
              "nomeado": sum(1 for r in rows if r[2]),
              "indicado": len(indic),
              "proximo_dias": min((r[5] for r in rows if r[5] is not None), default=None)}
    return resumo, lista


async def _emendas(db: AsyncSession, mid: int) -> Optional[dict]:
    from routers.emendas_parlamentares import _fontes_federais
    from services.emendas_unificadas import totais, unificar_federais
    f = await _fontes_federais(db, mid)
    linhas = unificar_federais((f["carteira"] or {}).get("items") or [], f["te"],
                               f["parcerias"], f["indicadas"], f["voluntarias"])
    t = totais(linhas)
    return {"n": t["emendas"], "sem_pagamento": t["parado_n"],
            "nao_consultadas": t["nao_consultadas_n"],
            "estado": (f["carteira"] or {}).get("estado")}


async def montar(db: AsyncSession, ids: list[int], limite: Optional[int] = LIMITE_LISTA) -> dict:
    """`limite` corta as três listas para a TELA; a planilha pede `None` (tudo)."""
    chave = ",".join(map(str, sorted(ids))) + f"|{limite}"
    agora = time.monotonic()
    hit = _cache.get(chave)
    if hit and agora - hit[0] < _CACHE_S:
        return hit[1]

    from routers.convenios import query_alertas_vigencia
    from services.bi import bi_cauc_rollup
    from services.bi_abas import documentos_vencendo

    muns = await _municipios(db, ids)
    indisponivel: list[str] = []

    async def bloco(nome, coro, padrao):
        """Um bloco que falha vira `indisponivel`, e não derruba o painel — e a
        tela diz qual ficou de fora, em vez de mostrar zero."""
        try:
            return await coro
        except Exception as e:  # noqa: BLE001
            log.exception(f"consolidado: bloco {nome} falhou: {e}")
            try:
                await db.rollback()
            except Exception:
                pass
            if nome not in indisponivel:
                indisponivel.append(nome)
            return padrao

    cauc = await bloco("cauc", bi_cauc_rollup(db, ids), {"por_municipio": []})
    cauc_por = {c["municipio_id"]: c for c in cauc.get("por_municipio", [])}
    estadual = await bloco("estadual", _estadual(db, muns), {})
    venc = await bloco("vencimentos",
                       query_alertas_vigencia(db, municipio_ids=ids, dias=DIAS_VENCIMENTO), [])
    venc = [v.model_dump() if hasattr(v, "model_dump") else dict(v) for v in venc]
    docs = await bloco("documentos", documentos_vencendo(db, ids, DIAS_DOCUMENTO), [])

    linhas, radar_lista = [], []
    for m in muns:
        mid = m["municipio_id"]
        c = cauc_por.get(mid)
        vs = [v for v in venc if v.get("municipio_id") == mid]
        ds = [d for d in docs if d.get("municipio_id") == mid]
        radar, lista = await bloco("radar", _radar(db, m), (None, []))
        radar_lista.extend(lista)
        emendas = await bloco("emendas", _emendas(db, mid), None)
        linha = {
            "municipio_id": mid, "nome": m["nome"], "uf": m["uf"],
            "cauc": ({"regular": c["regular"], "pendencias": c["pendencias"]} if c else None),
            "estadual": estadual.get(mid),
            "vencimentos": {"n": len(vs),
                            "proximo_dias": min((v["dias_restantes"] for v in vs), default=None)},
            "documentos": {"n": len(ds),
                           "proximo_dias": min((d["dias_restantes"] for d in ds), default=None)},
            "emendas": emendas,
            "radar": radar,
        }
        linha["atencao"] = atencao(linha)
        linhas.append(linha)

    linhas.sort(key=lambda l: (-l["atencao"], l["nome"]))
    radar_lista.sort(key=lambda r: (r["dias"] if r["dias"] is not None else 9999, r["municipio"]))

    def _venc(v):
        d = v.get("dt_fim_vigencia")
        return {"municipio_id": v.get("municipio_id"), "municipio": v.get("municipio_nome"),
                "esfera": v.get("esfera"),
                "numero": v.get("nr_convenio") or v.get("nr_sigcon"),
                "objeto": v.get("objeto"), "orgao": v.get("orgao_concedente"),
                "fim": d.isoformat() if isinstance(d, date) else d,
                "dias": v.get("dias_restantes"), "situacao": v.get("situacao")}

    payload = {
        "municipios_na_carteira": len(ids),
        "gerado_em": date.today().isoformat(),
        "indisponivel": indisponivel,
        "municipios": linhas,
        "resumo": {
            "cauc_irregulares": sum(1 for l in linhas if (l["cauc"] or {}).get("regular") is False),
            "cauc_sem_dado": sum(1 for l in linhas if l["cauc"] is None),
            "estadual_irregulares": sum(1 for l in linhas if (l["estadual"] or {}).get("regular") is False),
            "com_vencimento_30": sum(1 for l in linhas if (l["vencimentos"]["proximo_dias"] is not None
                                                          and l["vencimentos"]["proximo_dias"] <= 30)),
            "com_sem_pagamento": sum(1 for l in linhas if ((l["emendas"] or {}).get("sem_pagamento") or 0) > 0),
            "com_radar_nomeado": sum(1 for l in linhas if ((l["radar"] or {}).get("nomeado") or 0) > 0
                                     or ((l["radar"] or {}).get("indicado") or 0) > 0),
        },
        "vencimentos": [_venc(v) for v in venc[:limite]],
        "vencimentos_total": len(venc),
        "documentos": docs[:limite],
        "documentos_total": len(docs),
        "radar": radar_lista[:limite],
        "radar_total": len(radar_lista),
    }
    _cache[chave] = (agora, payload)
    return payload
