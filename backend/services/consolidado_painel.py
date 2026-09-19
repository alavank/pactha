"""OS BLOCOS DO CONSOLIDADO — Regularidade e Radar da carteira.

Nasceu (PR 2, 19/09/2026) como um "painel da carteira" numa página só, com
regularidade, vencimentos, emendas e Radar empilhados. O dono conferiu e pediu
para DIVIDIR por assunto (19/09/2026): "convênio que vence em 90 dias não tem a
ver com regularidade". Ficou:
  - REGULARIDADE ... CAUC e cadastro estadual por município, e os documentos de
                     regularidade vencendo em 30 dias (aba própria na tela);
  - RADAR .......... programas abertos por município, e onde ele está nomeado
                     como beneficiário ou tem emenda indicada.
Vencimentos viraram a aba VIGÊNCIAS (a mesma tela de bolhas que saiu do Painel de
Indicadores) e "emenda sem pagamento" mora em RELATÓRIOS.

⚠️ CADA BLOCO É A CONTA DE UMA TELA QUE JÁ EXISTE, chamada com a lista da
carteira — nada é recalculado aqui ("mesmo dado, mesma conta em toda tela"):
  - CAUC ............ `services/bi.bi_cauc_rollup`
  - estadual ........ `cagec_situacao` com a regra do `_semaforo_cagec` (routers/bi.py):
                      o município só está em dia se NENHUMA entidade está irregular
  - documentos ...... `services/bi_abas.documentos_vencendo`
  - Radar ........... `_CTE_ABERTOS` + `_FILTRO_ABERTOS` de routers/programas_captacao
                      (o mesmo número do contador do menu de cada município)

⚠️ NUNCA TOTAL SOZINHO: os resumos contam MUNICÍPIOS ("3 de 42"), não somam
dinheiro — o risco que tirou o "Consolidado (todos)" do seletor em 05/08/2026.

⚠️ "SEM DADO" NÃO É "EM DIA". Bloco sem coleta volta `None` e a tela escreve
"sem coleta"; estado sem cadastro coletado é "sem fonte". Nunca verde por falta
de informação.
"""
from __future__ import annotations

import logging
import time
import unicodedata
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("consolidado")


def _chave_nome(nome: Optional[str]) -> str:
    """Ordem alfabética de gente: sem acento e sem caixa ("Araújos" antes de
    "Arcos"; um "Á" não vai para depois do "Z", como no `sort` cru)."""
    s = unicodedata.normalize("NFKD", nome or "")
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()

DIAS_DOCUMENTO = 30
LIMITE_LISTA = 80

# Cache curto por escopo e bloco: cada bloco varre a carteira inteira e a aba é
# aberta várias vezes seguidas. Por processo, como o do overview do BI — com
# `--workers 2`, cada worker aquece o seu.
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
    """Quanto uma linha da REGULARIDADE pede atenção, para ordenar. PURA.

    Irregularidade trava repasse e vem primeiro; depois documento vencendo logo.
    Sem dado não soma: "sem coleta" não é problema do cliente.
    """
    p = 0
    if (linha.get("cauc") or {}).get("regular") is False:
        p += 100
    if (linha.get("estadual") or {}).get("regular") is False:
        p += 100
    d = linha.get("documentos") or {}
    if d.get("proximo_dias") is not None and d["proximo_dias"] <= 7:
        p += 40
    p += 5 * int(d.get("n") or 0)
    return p


# ------------------------------------------------------------- utilitários ---

async def _municipios(db: AsyncSession, ids: list[int]) -> list[dict]:
    rows = (await db.execute(text(
        "SELECT id, nome, upper(coalesce(uf, '')), "
        "regexp_replace(coalesce(cnpj, ''), '\\D', '', 'g') "
        "FROM municipios WHERE id = ANY(:ids) ORDER BY nome"), {"ids": ids})).fetchall()
    return [{"municipio_id": r[0], "nome": r[1], "uf": r[2], "cnpj": r[3]} for r in rows]


def _cacheado(bloco: str, ids: list[int], limite: Optional[int]):
    chave = f"{bloco}|{','.join(map(str, sorted(ids)))}|{limite}"
    hit = _cache.get(chave)
    return chave, (hit[1] if hit and time.monotonic() - hit[0] < _CACHE_S else None)


async def _tenta(db: AsyncSession, nome: str, coro, padrao, indisponivel: list[str]):
    """Um bloco que falha vira `indisponivel` e não derruba a aba — e a tela diz
    qual ficou de fora, em vez de mostrar zero."""
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


# ------------------------------------------------------------ regularidade ---

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


async def montar_regularidade(db: AsyncSession, ids: list[int],
                              limite: Optional[int] = LIMITE_LISTA) -> dict:
    """CAUC + estadual por município e os documentos vencendo em 30 dias.
    `limite` corta a lista de documentos para a TELA; a planilha pede `None`."""
    chave, hit = _cacheado("regularidade", ids, limite)
    if hit is not None:
        return hit
    from services.bi import bi_cauc_rollup
    from services.bi_abas import documentos_vencendo

    muns = await _municipios(db, ids)
    indisponivel: list[str] = []
    cauc = await _tenta(db, "cauc", bi_cauc_rollup(db, ids), {"por_municipio": []}, indisponivel)
    cauc_por = {c["municipio_id"]: c for c in cauc.get("por_municipio", [])}
    estadual = await _tenta(db, "estadual", _estadual(db, muns), {}, indisponivel)
    docs = await _tenta(db, "documentos", documentos_vencendo(db, ids, DIAS_DOCUMENTO), [],
                        indisponivel)

    linhas = []
    for m in muns:
        mid = m["municipio_id"]
        c = cauc_por.get(mid)
        ds = [d for d in docs if d.get("municipio_id") == mid]
        linha = {
            "municipio_id": mid, "nome": m["nome"], "uf": m["uf"],
            "cauc": ({"regular": c["regular"], "pendencias": c["pendencias"]} if c else None),
            "estadual": estadual.get(mid),
            "documentos": {"n": len(ds),
                           "proximo_dias": min((d["dias_restantes"] for d in ds), default=None)},
        }
        linha["atencao"] = atencao(linha)
        linhas.append(linha)
    linhas.sort(key=lambda l: (-l["atencao"], l["nome"]))

    payload = {
        "municipios_na_carteira": len(ids),
        "indisponivel": indisponivel,
        "municipios": linhas,
        "resumo": {
            "cauc_irregulares": sum(1 for l in linhas if (l["cauc"] or {}).get("regular") is False),
            "cauc_sem_dado": sum(1 for l in linhas if l["cauc"] is None),
            "estadual_irregulares": sum(1 for l in linhas if (l["estadual"] or {}).get("regular") is False),
            "com_documento_30": sum(1 for l in linhas if l["documentos"]["n"] > 0),
        },
        "documentos": docs[:limite],
        "documentos_total": len(docs),
    }
    _cache[chave] = (time.monotonic(), payload)
    return payload


# ------------------------------------------------------------------- radar ---

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


async def montar_radar(db: AsyncSession, ids: list[int],
                       limite: Optional[int] = LIMITE_LISTA) -> dict:
    """Por município: programas abertos, nomeado, indicado; e a lista dos
    programas onde algum cliente está nomeado ou com emenda indicada."""
    chave, hit = _cacheado("radar", ids, limite)
    if hit is not None:
        return hit
    muns = await _municipios(db, ids)
    indisponivel: list[str] = []
    linhas, programas = [], []
    for m in muns:
        radar, lista = await _tenta(db, "radar", _radar(db, m), (None, []), indisponivel)
        programas.extend(lista)
        linhas.append({"municipio_id": m["municipio_id"], "nome": m["nome"], "uf": m["uf"],
                       "radar": radar})
    # ORDEM ALFABÉTICA (dono, 19/09/2026). Era "mais nomeado/indicado primeiro",
    # e ninguém lia assim: o fim da lista, onde todos empatavam em "2 nomeado",
    # saía alfabético, e o dono achou que a lista inteira era — e que o Carandaí
    # (10 com dono, o primeiro) tinha sido "movido para o topo". A urgência mora
    # no selo de prazo de cada município, não na posição.
    linhas.sort(key=lambda l: _chave_nome(l["nome"]))
    programas.sort(key=lambda r: (r["dias"] if r["dias"] is not None else 9999, r["municipio"]))
    payload = {
        "municipios_na_carteira": len(ids),
        "indisponivel": indisponivel,
        "municipios": linhas,
        "resumo": {
            "com_nomeado_ou_indicado": sum(1 for l in linhas if ((l["radar"] or {}).get("nomeado") or 0)
                                           + ((l["radar"] or {}).get("indicado") or 0) > 0),
            "sem_uf": sum(1 for l in linhas if l["radar"] is None),
        },
        "programas": programas[:limite],
        "programas_total": len(programas),
    }
    _cache[chave] = (time.monotonic(), payload)
    return payload
