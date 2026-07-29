"""Painel de Indicadores - BI — modulo NATIVO (mesmo app/login/banco).

Superficie executiva READ-ONLY com escopo AUTOMATICO por usuario:
  - municipio/consorcio (1 no user_municipios) -> so o proprio;
  - assessoria/parceiro (N) -> seletor + CONSOLIDADO (visao geral da carteira).

Gate: resolve_scope (services/bi.py) — ensure_municipio_access no modo unico,
allowed_municipio_ids no consolidado. Reusa os nucleos de calculo (bi_kpis,
cauc, parlamentares, convenios, status_changes) — para 1 municipio o resultado
bate byte-a-byte com /api/painel/*.

Namespace SEPARADO de /api/painel/* (que segue vivo ate o corte). Montado so
quando BI_MODULE=true (main.py) — flag OFF => 404, zero mudanca de comportamento.
"""
from __future__ import annotations
import os
import json
import hashlib
import secrets
import asyncio
import time
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from services.auth import get_current_user, hash_password, create_kiosk_token
from services.bi import (
    resolve_scope, scope_signature, bi_kpis, bi_cauc_rollup, bi_saude_rollup,
    anos_list, anos_signature,
)
from services.bi_abas import (
    bi_estaduais, bi_transferegov, bi_parlamentares_detalhe, bi_documentos, bi_execucao,
)
from models.user import User
from routers.cauc import fetch_cauc_situacao
from routers.parlamentares import aggregate_parlamentares
from routers.convenios import query_alertas_vigencia, query_prestacao_contas
from routers.status_changes import listar_core

router = APIRouter(prefix="/api/bi", tags=["bi"])


def _periodo(ano: Optional[int], anos: Optional[list[int]]) -> Optional[list[int]]:
    """Periodo efetivo da requisicao. `ano` (legado, 1 valor) e `anos` (mandato
    inteiro) se somam — o frontend novo manda so `anos`."""
    return anos_list((anos or []) + ([ano] if ano else []))


# --------------------------------------------------------------------------
# Cache TTL em memoria do overview (por-worker). Chave = escopo+ano+live.
# Um wallboard polando a cada 30-60s quase nao toca o banco. Stale <= TTL.
# --------------------------------------------------------------------------
_OVERVIEW_TTL = 45  # segundos
_OVERVIEW_CACHE: dict[str, tuple[float, dict]] = {}


def _cache_get(key: str) -> Optional[dict]:
    hit = _OVERVIEW_CACHE.get(key)
    if hit and (time.monotonic() - hit[0]) < _OVERVIEW_TTL:
        return hit[1]
    return None


def _cache_put(key: str, payload: dict) -> None:
    now = time.monotonic()
    _OVERVIEW_CACHE[key] = (now, payload)
    # poda simples p/ nao crescer sem limite (escopos distintos sao poucos)
    if len(_OVERVIEW_CACHE) > 256:
        for k, (ts, _) in list(_OVERVIEW_CACHE.items()):
            if now - ts >= _OVERVIEW_TTL:
                _OVERVIEW_CACHE.pop(k, None)


# Single-flight: requests concorrentes p/ a MESMA chave fria compartilham UMA
# computacao (colapsa o "stampede" no cold start / virada de TTL).
_INFLIGHT: dict[str, "asyncio.Future"] = {}


async def _compute_overview(db: AsyncSession, ids: list[int], cons: bool, single: bool,
                            ano: Optional[list[int]], live: bool) -> dict:
    """Monta o payload do overview SEQUENCIALMENTE na sessao do request. NAO usar
    asyncio.gather com sessoes proprias aqui: abrir N AsyncSession por request
    esgota o pool compartilhado (pool_size+overflow=15) e derruba TODO o app,
    inclusive /auth/login. As queries sao indexadas/set-based e o cache TTL torna
    o miss raro — sequencial e barato e seguro."""
    kpis = await bi_kpis(db, ids, ano)
    semaforo = await fetch_cauc_situacao(db, ids[0]) if single else await bi_cauc_rollup(db, ids)
    saude = await bi_saude_rollup(db, ids)
    if single:
        ranking = await aggregate_parlamentares(db, municipio_id=ids[0], ano=ano, incluir_plano_acao=live)
    else:
        ranking = await aggregate_parlamentares(db, municipio_ids=ids, ano=ano, incluir_plano_acao=live)
    mudancas = await listar_core(db, ids, 30, 8)
    execucao = await bi_execucao(db, ids, ano)
    return {
        "consolidado": cons,
        "municipios_count": len(ids),
        "municipio_ids": ids,
        "ano": ano[0] if (ano and len(ano) == 1) else None,
        "anos": ano or [],
        "kpis": kpis,
        "execucao": execucao,
        "semaforo": semaforo,
        "saude": saude,
        "top_parlamentares": ranking["items"][:8],
        "ultimas_mudancas": mudancas.get("items", []),
        "ttl": _OVERVIEW_TTL,
    }


# --------------------------------------------------------------------------
# Overview (payload unico do dashboard e da TV) — 1 round-trip
# --------------------------------------------------------------------------

@router.get("/overview")
async def overview(
    municipio_id: Optional[int] = Query(None, description="1 municipio; ausente = consolidado do escopo"),
    ano: Optional[int] = Query(None, description="Filtra KPIs por ano (None=todos)"),
    anos: Optional[list[int]] = Query(None, description="Varios anos (mandato); soma-se a `ano`"),
    live: bool = Query(False, description="Inclui o RP9 federal AO VIVO (lento; nao usar no polling da TV)"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ids, cons = await resolve_scope(db, current, municipio_id)
    single = (not cons) and len(ids) == 1
    ano = _periodo(ano, anos)

    cache_key = f"{scope_signature(ids, cons)}|a={anos_signature(ano)}|l={int(live)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # single-flight (get/create sem await entre eles = atomico no loop async)
    inflight = _INFLIGHT.get(cache_key)
    if inflight is not None:
        return await inflight
    fut = asyncio.get_event_loop().create_future()
    _INFLIGHT[cache_key] = fut
    try:
        payload = await _compute_overview(db, ids, cons, single, ano, live)
        _cache_put(cache_key, payload)
        if not fut.done():
            fut.set_result(payload)
        return payload
    except Exception as e:
        if not fut.done():
            fut.set_exception(e)
        raise
    finally:
        _INFLIGHT.pop(cache_key, None)


# --------------------------------------------------------------------------
# Wrappers finos (drilldowns) — usam a sessao do request (sequenciais, sem gather)
# --------------------------------------------------------------------------

@router.get("/semaforo")
async def semaforo(
    municipio_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ids, cons = await resolve_scope(db, current, municipio_id)
    if (not cons) and len(ids) == 1:
        return await fetch_cauc_situacao(db, ids[0])
    return await bi_cauc_rollup(db, ids)


@router.get("/parlamentares")
async def parlamentares(
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None),
    anos: Optional[list[int]] = Query(None),
    live: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ids, cons = await resolve_scope(db, current, municipio_id)
    periodo = _periodo(ano, anos)
    if (not cons) and len(ids) == 1:
        return await aggregate_parlamentares(db, municipio_id=ids[0], ano=periodo, incluir_plano_acao=live)
    return await aggregate_parlamentares(db, municipio_ids=ids, ano=periodo, incluir_plano_acao=live)


@router.get("/alertas")
async def alertas(
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None),
    anos: Optional[list[int]] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ids, cons = await resolve_scope(db, current, municipio_id)
    periodo = _periodo(ano, anos)
    if (not cons) and len(ids) == 1:
        vig = await query_alertas_vigencia(db, ids[0], 120, periodo)
        prest = await query_prestacao_contas(db, ids[0], 90, periodo)
    else:
        vig = await query_alertas_vigencia(db, None, 120, periodo, municipio_ids=ids)
        prest = await query_prestacao_contas(db, None, 90, periodo, municipio_ids=ids)
    execucao = await bi_execucao(db, ids, periodo)
    return {
        "vigencia": [a.model_dump() for a in vig],
        "prestacao": [a.model_dump() for a in prest],
        "execucao": execucao,
    }


# --------------------------------------------------------------------------
# Abas do painel — 1 request = 1 aba inteira (a TV troca de aba a cada ~15s e
# nao pode disparar uma cascata). Cada uma tem o mesmo cache TTL do overview.
# --------------------------------------------------------------------------

async def _aba_cacheada(key: str, fn):
    """Cache TTL + single-flight compartilhados por todas as abas."""
    cached = _cache_get(key)
    if cached is not None:
        return cached
    inflight = _INFLIGHT.get(key)
    if inflight is not None:
        return await inflight
    fut = asyncio.get_event_loop().create_future()
    _INFLIGHT[key] = fut
    try:
        payload = await fn()
        _cache_put(key, payload)
        if not fut.done():
            fut.set_result(payload)
        return payload
    except Exception as e:
        if not fut.done():
            fut.set_exception(e)
        raise
    finally:
        _INFLIGHT.pop(key, None)


@router.get("/estaduais")
async def aba_estaduais(
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None),
    anos: Optional[list[int]] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Aba 'Verbas Estaduais': convenios SIGCON-MG + emendas estaduais."""
    ids, cons = await resolve_scope(db, current, municipio_id)
    periodo = _periodo(ano, anos)
    key = f"est|{scope_signature(ids, cons)}|a={anos_signature(periodo)}"
    return await _aba_cacheada(key, lambda: bi_estaduais(db, ids, periodo))


@router.get("/transferegov")
async def aba_transferegov(
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None),
    anos: Optional[list[int]] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Aba 'TransfereGov': voluntarias + Novo PAC + o que esta em execucao."""
    ids, cons = await resolve_scope(db, current, municipio_id)
    periodo = _periodo(ano, anos)
    key = f"tg|{scope_signature(ids, cons)}|a={anos_signature(periodo)}"
    return await _aba_cacheada(key, lambda: bi_transferegov(db, ids, periodo))


@router.get("/parlamentares/detalhe")
async def aba_parlamentares_detalhe(
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None),
    anos: Optional[list[int]] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Aba 'Parlamentares': cada parlamentar com as emendas que mandou —
    destinacao (pra quem) e finalidade (pra que), que e o detalhe que o
    prefeito cobra na tela."""
    ids, cons = await resolve_scope(db, current, municipio_id)
    periodo = _periodo(ano, anos)
    key = f"parld|{scope_signature(ids, cons)}|a={anos_signature(periodo)}"
    return await _aba_cacheada(key, lambda: bi_parlamentares_detalhe(db, ids, periodo))


@router.get("/documentos")
async def aba_documentos(
    municipio_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Aba 'Documentacao': CAUC (federal, coletado) e CAGEC (estadual, ainda
    nao integrado — devolve disponivel=false em vez de fingir que esta em dia)."""
    ids, cons = await resolve_scope(db, current, municipio_id)
    key = f"doc|{scope_signature(ids, cons)}"
    return await _aba_cacheada(key, lambda: bi_documentos(db, ids))


# --------------------------------------------------------------------------
# Aba FNS — consulta AO VIVO no portal do Fundo Nacional de Saude, ja resolvida
# no backend p/ VARIOS anos. Cache proprio (TTL maior): o portal e lento e a
# TV volta nesta aba a cada rodada do slideshow.
# --------------------------------------------------------------------------

_FNS_TTL = 900  # 15 min
_FNS_CACHE: dict[str, tuple[float, dict]] = {}


def _ano_corrente() -> int:
    from datetime import date as _date
    return _date.today().year


@router.get("/fns")
async def aba_fns(
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None),
    anos: Optional[list[int]] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Aba 'Fundo Nacional de Saude'. SEM filtro de ano, abre no ano corrente
    ja consultado (o gestor nao deveria ter que clicar em 'consultar' para ver
    o ano em que esta). Aceita varios anos."""
    ids, cons = await resolve_scope(db, current, municipio_id)
    periodo = _periodo(ano, anos) or [_ano_corrente()]

    key = f"fns|{scope_signature(ids, cons)}|a={anos_signature(periodo)}"
    hit = _FNS_CACHE.get(key)
    if hit and (time.monotonic() - hit[0]) < _FNS_TTL:
        return hit[1]

    from routers.fns import consultar_fns

    muns = (await db.execute(text(
        "SELECT id, nome, uf FROM municipios WHERE id = ANY(:ids) ORDER BY nome"
    ), {"ids": ids})).fetchall()

    por_ano: dict[int, dict] = {a: {"ano": a, "total": 0, "valor_proposta": 0.0,
                                    "valor_pago": 0.0, "valor_pagar": 0.0} for a in periodo}
    itens: list[dict] = []
    erros: list[str] = []
    for m in muns:
        for a in periodo:
            try:
                res = await consultar_fns(db, m.nome, a, m.uf or "MG", tamanho=200)
            except Exception as e:
                erros.append(f"{m.nome}/{a}: {str(getattr(e, 'detail', e))[:120]}")
                continue
            agg = por_ano[a]
            t = res.get("totais") or {}
            agg["total"] += res.get("total") or 0
            agg["valor_proposta"] += float(t.get("valor_proposta") or 0)
            agg["valor_pago"] += float(t.get("valor_pago") or 0)
            agg["valor_pagar"] += float(t.get("valor_pagar") or 0)
            for it in res.get("items") or []:
                itens.append({**it, "ano": a, "municipio": m.nome})

    itens.sort(key=lambda i: -(i.get("valor_proposta") or 0))
    payload = {
        "anos": periodo,
        "por_ano": [por_ano[a] for a in periodo],
        "itens": itens[:80],
        "total": len(itens),
        "totais": {
            "valor_proposta": sum(v["valor_proposta"] for v in por_ano.values()),
            "valor_pago": sum(v["valor_pago"] for v in por_ano.values()),
            "valor_pagar": sum(v["valor_pagar"] for v in por_ano.values()),
        },
        "disponivel": bool(itens) or not erros,
        "erros": erros[:5],
        "ttl": _FNS_TTL,
    }
    _FNS_CACHE[key] = (time.monotonic(), payload)
    if len(_FNS_CACHE) > 64:
        now = time.monotonic()
        for k, (ts, _) in list(_FNS_CACHE.items()):
            if now - ts >= _FNS_TTL:
                _FNS_CACHE.pop(k, None)
    return payload


@router.get("/timeline")
async def timeline(
    municipio_id: Optional[int] = Query(None),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ids, _cons = await resolve_scope(db, current, municipio_id)
    return await listar_core(db, ids, days, limit)


# --------------------------------------------------------------------------
# Narrativa (IA/Haiku) com cache por input_hash — self-contained (nao depende
# de painel.py, que sera removido no corte). Degrada sem ANTHROPIC_API_KEY.
# --------------------------------------------------------------------------

def _money_br(v) -> str:
    v = float(v or 0)
    if abs(v) >= 1_000_000:
        return ("R$ %.1f mi" % (v / 1_000_000)).replace(".", ",")
    if abs(v) >= 1_000:
        return "R$ %.0f mil" % (v / 1_000)
    return "R$ %.0f" % v


async def _gerar_narrativa(dados: dict, kind: str, api_key: str) -> str:
    """Uma chamada Haiku (sem tools/thinking) que traduz os numeros em 2-4 frases
    de linguagem leiga para o gestor. NAO reusa o tool-loop pesado do ai.py."""
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)
    total = (dados["estadual"] or 0) + (dados["federal"] or 0)
    top_txt = "; ".join(f'{t["n"]} ({_money_br(t["v"])})' for t in dados["top"]) or "sem registro"
    ano_txt = str(dados["ano"]) if dados["ano"] else "todos os anos"
    cauc_txt = "em dia, sem pendencias" if dados["cauc_regular"] else f'{dados["cauc_pend"]} pendencia(s)'
    system = (
        "Voce explica dados de captacao de recursos publicos para um GESTOR leigo, em "
        "portugues do Brasil. Linguagem simples e direta, tom institucional, positivo mas "
        "honesto. Sem jargao tecnico. Responda em 2 a 4 frases curtas. Nao invente numeros "
        "alem dos fornecidos."
    )
    prompt = (
        f"Carteira: {dados['municipio']}. Periodo: {ano_txt}.\n"
        f"Total captado: {_money_br(total)} (estadual {_money_br(dados['estadual'])}, "
        f"federal {_money_br(dados['federal'])}).\n"
        f"{dados['voluntarias']} propostas federais; {dados['convenios_est']} convenios estaduais.\n"
        f"CAUC (documentacao federal): {cauc_txt}.\n"
        f"Prestacoes de contas vencidas: {dados['prestacao']}. Convenios vencendo: {dados['vigencia']}.\n"
        f"Parlamentares que mais destinaram recurso: {top_txt}.\n\n"
        "Escreva um resumo executivo destacando o impacto (quanto entrou, quem ajudou) e os "
        "pontos de atencao (documentacao, prazos)."
    )
    resp = await client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    if getattr(resp, "stop_reason", None) == "refusal":
        raise RuntimeError("refusal")
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()


@router.get("/narrativa")
async def narrativa(
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None),
    anos: Optional[list[int]] = Query(None),
    kind: str = Query("resumo"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Resumo executivo em linguagem leiga (IA/Haiku) com cache por input_hash.
    Sem ANTHROPIC_API_KEY -> disponivel=false e o frontend usa texto por template."""
    ids, cons = await resolve_scope(db, current, municipio_id)
    single = (not cons) and len(ids) == 1
    periodo = _periodo(ano, anos)
    ano = periodo[0] if (periodo and len(periodo) == 1) else None

    kpis = await bi_kpis(db, ids, periodo)
    cauc = await bi_cauc_rollup(db, ids)
    if single:
        ranking = await aggregate_parlamentares(db, municipio_id=ids[0], ano=periodo, incluir_plano_acao=False)
        mrow = (await db.execute(text("SELECT nome FROM municipios WHERE id = :m"), {"m": ids[0]})).first()
        nome = mrow[0] if mrow else f"Municipio {ids[0]}"
        cauc_regular = cauc["por_municipio"][0]["regular"] if cauc["por_municipio"] else None
        mid_key = ids[0]
    else:
        ranking = await aggregate_parlamentares(db, municipio_ids=ids, ano=periodo, incluir_plano_acao=False)
        nome = f"{len(ids)} municipios da carteira"
        cauc_regular = (cauc["com_dados"] > 0 and cauc["com_pendencia"] == 0)
        mid_key = 0
    cauc_pend = cauc["pendencias_total"]

    top = [
        {"n": t["nome_display"], "v": t["valor_total"]}
        for t in ranking["items"]
        if "MUNICIPIO" not in (t.get("nome_normalizado") or "") and "PREFEITURA" not in (t.get("nome_normalizado") or "")
    ][:3]
    dados = {
        "municipio": nome,
        "ano": ano,
        "anos": periodo or [],
        "estadual": kpis["valor_total_estadual"],
        "federal": kpis["valor_total_federal"],
        "voluntarias": kpis["total_voluntarias"],
        "convenios_est": kpis["total_convenios_estadual"],
        "prestacao": kpis["alertas_prestacao_contas"],
        "vigencia": kpis["alertas_vigencia"],
        "cauc_regular": cauc_regular,
        "cauc_pend": cauc_pend,
        "top": top,
    }
    input_hash = hashlib.sha256(
        json.dumps(dados, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    ano_key = ano or 0
    # single: compartilha o cache com o painel (mesmos numeros -> mesmo input_hash).
    # consolidado: mid_key=0 seria UMA linha p/ TODAS as carteiras (admin + cada
    # assessoria) -> thrash. Isola por assinatura do escopo na chave `kind`.
    #
    # MULTI-ANO: a coluna `ano` da tabela so guarda 1 valor, entao um periodo de
    # varios anos vai com ano_key=0 e o periodo entra no `kind` — senao 2021-2024
    # e 2022-2025 dividiriam a MESMA linha e ficariam se sobrescrevendo.
    periodo_key = "" if (not periodo or len(periodo) == 1) else f":p{anos_signature(periodo)}"
    if single:
        kind_key = f"{kind}{periodo_key}"
    else:
        sig = hashlib.sha256(scope_signature(ids, cons).encode("utf-8")).hexdigest()[:16]
        kind_key = f"bi:{sig}:{kind}{periodo_key}"

    row = (await db.execute(text(
        "SELECT texto, input_hash, gerado_em FROM painel_narrativa_cache "
        "WHERE municipio_id = :m AND ano = :a AND kind = :k"
    ), {"m": mid_key, "a": ano_key, "k": kind_key})).first()
    if row and row[1] == input_hash and row[0]:
        return {"texto": row[0], "kind": kind, "cache": True, "disponivel": True,
                "gerado_em": row[2].isoformat() if row[2] else None}

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"texto": None, "kind": kind, "cache": False, "disponivel": False}
    try:
        texto = await _gerar_narrativa(dados, kind, api_key)
    except Exception as e:
        return {"texto": None, "kind": kind, "cache": False, "disponivel": False, "erro": str(e)[:80]}

    await db.execute(text(
        "INSERT INTO painel_narrativa_cache (municipio_id, ano, kind, texto, input_hash, gerado_em) "
        "VALUES (:m, :a, :k, :t, :h, NOW()) "
        "ON CONFLICT (municipio_id, ano, kind) DO UPDATE SET texto = :t, input_hash = :h, gerado_em = NOW()"
    ), {"m": mid_key, "a": ano_key, "k": kind_key, "t": texto, "h": input_hash})
    await db.commit()
    return {"texto": texto, "kind": kind, "cache": False, "disponivel": True}


# --------------------------------------------------------------------------
# Insights por ABA (IA) — LISTA de mensagens curtas p/ o cabecalho do Modo Tela
# rodar em slideshow. Uma aba costuma ter mais de uma coisa importante pra dizer.
# Sem ANTHROPIC_API_KEY cai num texto por template (a faixa nunca fica vazia).
# --------------------------------------------------------------------------

ABAS_INSIGHT = ("geral", "parlamentares", "transferegov", "estaduais", "documentos", "fns")


async def _fatos_da_aba(db: AsyncSession, ids: list[int], cons: bool, aba: str,
                        periodo: Optional[list[int]]) -> tuple[dict, list[str]]:
    """(fatos p/ a IA, mensagens de fallback por template). Os fatos sao poucos
    e ja resumidos — a IA nao recebe a base inteira."""
    periodo_txt = ", ".join(str(a) for a in periodo) if periodo else "todos os anos"
    if aba == "parlamentares":
        d = await bi_parlamentares_detalhe(db, ids, periodo)
        top = d["itens"][:3]
        fatos = {
            "aba": "parlamentares", "periodo": periodo_txt,
            "total_parlamentares": d["total"], "valor_total": d["valor_total"],
            "top": [{"nome": t["nome"], "valor": t["valor_total"],
                     "emendas": t["total_lancamentos"]} for t in top],
        }
        tpl = [f"{d['total']} parlamentares destinaram {_money_br(d['valor_total'])} ao município em {periodo_txt}."]
        if top:
            tpl.append(f"Maior destinação: {top[0]['nome']} — {_money_br(top[0]['valor_total'])} "
                       f"em {top[0]['total_lancamentos']} lançamento(s).")
        return fatos, tpl

    if aba == "transferegov":
        d = await bi_transferegov(db, ids, periodo)
        v = d["voluntarias"]
        fatos = {"aba": "transferegov", "periodo": periodo_txt,
                 "propostas": v["total"], "valor": v["valor_total"],
                 "em_execucao": v.get("em_execucao", 0),
                 "situacoes": v["por_situacao"][:4], "pac": d["pac"]["total"]}
        tpl = [f"{v['total']} propostas federais somando {_money_br(v['valor_total'])} ({periodo_txt})."]
        if v.get("em_execucao"):
            tpl.append(f"{v['em_execucao']} instrumento(s) em execução neste momento.")
        return fatos, tpl

    if aba == "estaduais":
        d = await bi_estaduais(db, ids, periodo)
        c, e = d["convenios"], d["emendas"]
        fatos = {"aba": "estaduais", "periodo": periodo_txt,
                 "convenios": c["total"], "valor_convenios": c["valor_total"],
                 "repassado": c.get("valor_repassado", 0),
                 "emendas": e["total"], "valor_emendas": e["valor_total"],
                 "orgaos": c["por_orgao"][:3]}
        tpl = [f"{c['total']} convênios estaduais somando {_money_br(c['valor_total'])} ({periodo_txt})."]
        if e["total"]:
            tpl.append(f"{e['total']} indicações de emenda estadual, {_money_br(e['valor_total'])}.")
        return fatos, tpl

    if aba == "documentos":
        d = await bi_documentos(db, ids)
        c = d["cauc"]
        fatos = {"aba": "documentos", "regulares": c["regulares"],
                 "municipios": c["total_municipios"], "pendencias": c["pendencias_total"],
                 "pendentes": [{"nome": m["nome"], "itens": [i["label"] for i in m["itens_pendentes"][:3]]}
                               for m in c["por_municipio"] if m["pendencias"]][:3]}
        if c["pendencias_total"]:
            tpl = [f"{c['pendencias_total']} pendência(s) no CAUC bloqueiam novas transferências voluntárias."]
        else:
            tpl = ["Documentação federal (CAUC) em dia — município apto a receber transferências voluntárias."]
        tpl.append("CAGEC (cadastro estadual) ainda não é coletado automaticamente pelo PACTHA.")
        return fatos, tpl

    if aba == "fns":
        fatos = {"aba": "fns", "periodo": periodo_txt}
        return fatos, [f"Fundo Nacional de Saúde — propostas de {periodo_txt}."]

    # geral
    kpis = await bi_kpis(db, ids, periodo)
    cauc = await bi_cauc_rollup(db, ids)
    exe = await bi_execucao(db, ids, periodo)
    fatos = {
        "aba": "geral", "periodo": periodo_txt,
        "estadual": kpis["valor_total_estadual"], "federal": kpis["valor_total_federal"],
        "vigencia_120d": kpis["alertas_vigencia"], "vigencia_60d": kpis["alertas_vigencia_60d"],
        "prestacao_vencida": kpis["alertas_prestacao_contas"],
        "cauc_pendencias": cauc["pendencias_total"],
        "em_execucao": exe["total"], "valor_em_execucao": exe["valor_total"],
    }
    total = (kpis["valor_total_estadual"] or 0) + (kpis["valor_total_federal"] or 0)
    tpl = [f"Total captado no período ({periodo_txt}): {_money_br(total)}."]
    if kpis["alertas_vigencia_60d"]:
        tpl.append(f"{kpis['alertas_vigencia_60d']} convênio(s) vencem nos próximos 60 dias.")
    if kpis["alertas_prestacao_contas"]:
        tpl.append(f"{kpis['alertas_prestacao_contas']} prestação(ões) de contas em atraso.")
    return fatos, tpl


async def _gerar_insights(fatos: dict, api_key: str) -> list[str]:
    """2 a 4 frases INDEPENDENTES (uma por item) — o cabecalho da TV mostra uma
    de cada vez. Cada frase precisa fazer sentido sozinha."""
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)
    system = (
        "Voce escreve avisos curtos para um PAINEL DE TV lido por um prefeito. "
        "Portugues do Brasil, linguagem simples, tom institucional e direto. "
        "Cada aviso e uma frase UNICA de no maximo 140 caracteres, faz sentido "
        "sozinho (a TV mostra um de cada vez) e traz um numero ou um nome concreto. "
        "Priorize o que exige acao (prazo, pendencia) antes do que e so resultado. "
        "Nao invente numeros. Responda APENAS um array JSON de 2 a 4 strings."
    )
    resp = await client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=500,
        system=system,
        messages=[{"role": "user", "content": json.dumps(fatos, ensure_ascii=False)}],
    )
    if getattr(resp, "stop_reason", None) == "refusal":
        raise RuntimeError("refusal")
    txt = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    ini, fim = txt.find("["), txt.rfind("]")
    if ini >= 0 and fim > ini:
        msgs = json.loads(txt[ini:fim + 1])
    else:  # modelo respondeu em linhas soltas
        msgs = [ln.strip(" -•\t") for ln in txt.splitlines() if len(ln.strip()) > 15]
    return [str(m).strip() for m in msgs if str(m).strip()][:4]


@router.get("/insights")
async def insights(
    aba: str = Query("geral"),
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None),
    anos: Optional[list[int]] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Mensagens curtas da IA sobre a aba aberta (slideshow do cabecalho)."""
    if aba not in ABAS_INSIGHT:
        raise HTTPException(status_code=400, detail=f"aba invalida: {aba}")
    ids, cons = await resolve_scope(db, current, municipio_id)
    periodo = _periodo(ano, anos)

    fatos, template = await _fatos_da_aba(db, ids, cons, aba, periodo)
    input_hash = hashlib.sha256(
        json.dumps(fatos, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()

    # A PK da tabela guarda 1 `ano`; um periodo com varios anos entra no `kind`
    # (senao 2021-2024 e 2022-2025 brigariam pela mesma linha).
    sig = hashlib.sha256(scope_signature(ids, cons).encode("utf-8")).hexdigest()[:16]
    periodo_key = "" if (not periodo or len(periodo) == 1) else f":p{anos_signature(periodo)}"
    kind_key = f"bi:ins:{sig}:{aba}{periodo_key}"
    mid_key = ids[0] if ((not cons) and len(ids) == 1) else 0
    ano_key = (periodo[0] if periodo and len(periodo) == 1 else 0)

    row = (await db.execute(text(
        "SELECT texto, input_hash FROM painel_narrativa_cache "
        "WHERE municipio_id = :m AND ano = :a AND kind = :k"
    ), {"m": mid_key, "a": ano_key, "k": kind_key})).first()
    if row and row[1] == input_hash and row[0]:
        try:
            return {"aba": aba, "mensagens": json.loads(row[0]), "cache": True, "disponivel": True}
        except (ValueError, TypeError):
            pass

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"aba": aba, "mensagens": template, "cache": False, "disponivel": False, "fonte": "template"}
    try:
        msgs = await _gerar_insights(fatos, api_key)
    except Exception as e:
        return {"aba": aba, "mensagens": template, "cache": False, "disponivel": False,
                "fonte": "template", "erro": str(e)[:80]}
    if not msgs:
        return {"aba": aba, "mensagens": template, "cache": False, "disponivel": False, "fonte": "template"}

    await db.execute(text(
        "INSERT INTO painel_narrativa_cache (municipio_id, ano, kind, texto, input_hash, gerado_em) "
        "VALUES (:m, :a, :k, :t, :h, NOW()) "
        "ON CONFLICT (municipio_id, ano, kind) DO UPDATE SET texto = :t, input_hash = :h, gerado_em = NOW()"
    ), {"m": mid_key, "a": ano_key, "k": kind_key,
        "t": json.dumps(msgs, ensure_ascii=False), "h": input_hash})
    await db.commit()
    return {"aba": aba, "mensagens": msgs, "cache": False, "disponivel": True, "fonte": "ia"}


# --------------------------------------------------------------------------
# Token de quiosque (TV liga sem senha) — ADMIN. Aceita municipio unico OU
# consolidado (escopa um usuario viewer a todos os municipios ativos).
# --------------------------------------------------------------------------

class KioskIn(BaseModel):
    municipio_id: Optional[int] = None  # None = TV consolidada (carteira toda)
    dias: int = 365


async def _ensure_viewer(db: AsyncSession, email: str, nome: str) -> int:
    urow = (await db.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email})).first()
    if urow:
        uid = urow[0]
        await db.execute(text("UPDATE users SET active = true, role = 'viewer' WHERE id = :u"), {"u": uid})
    else:
        ph = hash_password(secrets.token_urlsafe(24))
        r = (await db.execute(text(
            "INSERT INTO users (email, name, password_hash, role, active, must_change_password) "
            "VALUES (:e, :n, :p, 'viewer', true, false) RETURNING id"
        ), {"e": email, "n": nome, "p": ph})).first()
        uid = r[0]
    # concede a tela BI (consistencia; os endpoints /api/bi/* gateiam por municipio)
    await db.execute(text(
        "INSERT INTO user_telas (user_id, tela) VALUES (:u, 'bi') ON CONFLICT DO NOTHING"
    ), {"u": uid})
    return uid


@router.post("/kiosk-tokens")
async def criar_kiosk_token(
    body: KioskIn,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Emite token de longa duracao p/ a TV ligar sem login. Cria/reusa um usuario
    'viewer' escopado (1 municipio OU todos os ativos = consolidado). Somente admin."""
    if current.role != "admin":
        raise HTTPException(status_code=403, detail="Apenas admin emite token de quiosque")

    if body.municipio_id is not None:
        mrow = (await db.execute(text(
            "SELECT nome FROM municipios WHERE id = :m AND active = true"
        ), {"m": body.municipio_id})).first()
        if not mrow:
            raise HTTPException(status_code=404, detail="Municipio nao encontrado")
        email = f"kiosk-{body.municipio_id}@painel.local"
        uid = await _ensure_viewer(db, email, f"Quiosque {mrow[0]}")
        await db.execute(text(
            "INSERT INTO user_municipios (user_id, municipio_id) VALUES (:u, :m) ON CONFLICT DO NOTHING"
        ), {"u": uid, "m": body.municipio_id})
        escopo = mrow[0]
    else:
        slug = get_settings().INSTANCE_SLUG or "default"
        email = f"kiosk-bi-{slug}@painel.local"
        uid = await _ensure_viewer(db, email, "Quiosque BI (consolidado)")
        # escopa a TV a TODOS os municipios ativos (a carteira do tenant)
        await db.execute(text(
            "INSERT INTO user_municipios (user_id, municipio_id) "
            "SELECT :u, id FROM municipios WHERE active = true "
            "ON CONFLICT DO NOTHING"
        ), {"u": uid})
        escopo = "consolidado (todos os municipios ativos)"

    await db.commit()
    token = create_kiosk_token(uid, body.dias)
    return {
        "token": token,
        "municipio_id": body.municipio_id,
        "escopo": escopo,
        "dias": body.dias,
        "user_email": email,
        "instrucoes": "Na TV, acesse /bi/tv?kiosk=<token> (ou cole o token em localStorage.pactha_token).",
    }


# --------------------------------------------------------------------------
# Push web + preferencias (perfil executivo). Escritas permitidas ao readonly
# via READONLY_WRITE_ALLOW (services/auth.py). Reusa as tabelas painel_*.
# --------------------------------------------------------------------------

class PushSubIn(BaseModel):
    municipio_id: int
    endpoint: str
    p256dh: str
    auth: str
    ua: Optional[str] = None


class PrefsIn(BaseModel):
    cauc_vencendo: bool = True
    nova_emenda: bool = True
    prazo_prestacao: bool = True
    mudanca_status: bool = True
    vigencia_60d: bool = True


@router.get("/vapid-public-key")
async def vapid_public_key(current: User = Depends(get_current_user)):
    return {"key": os.getenv("VAPID_PUBLIC_KEY") or ""}


@router.post("/push/subscribe")
async def push_subscribe(
    body: PushSubIn,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # valida que o municipio esta no escopo do usuario
    _ids, _cons = await resolve_scope(db, current, body.municipio_id)
    await db.execute(text(
        "INSERT INTO painel_push_subscriptions (user_id, municipio_id, endpoint, p256dh, auth, ua) "
        "VALUES (:u, :m, :e, :p, :a, :ua) "
        "ON CONFLICT (endpoint) DO UPDATE SET p256dh = :p, auth = :a, ua = :ua, "
        "municipio_id = :m, user_id = :u, last_ok_at = NULL"
    ), {"u": current.id, "m": body.municipio_id, "e": body.endpoint,
        "p": body.p256dh, "a": body.auth, "ua": body.ua})
    await db.commit()
    return {"ok": True}


@router.delete("/push/subscribe")
async def push_unsubscribe(
    endpoint: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    await db.execute(text(
        "DELETE FROM painel_push_subscriptions WHERE endpoint = :e AND user_id = :u"
    ), {"e": endpoint, "u": current.id})
    await db.commit()
    return {"ok": True}


@router.get("/preferencias")
async def get_preferencias(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    row = (await db.execute(text(
        "SELECT cauc_vencendo, nova_emenda, prazo_prestacao, mudanca_status, vigencia_60d "
        "FROM painel_preferencias WHERE user_id = :u"
    ), {"u": current.id})).first()
    if not row:
        return {"cauc_vencendo": True, "nova_emenda": True, "prazo_prestacao": True,
                "mudanca_status": True, "vigencia_60d": True}
    return {"cauc_vencendo": row[0], "nova_emenda": row[1], "prazo_prestacao": row[2],
            "mudanca_status": row[3], "vigencia_60d": row[4]}


@router.put("/preferencias")
async def put_preferencias(
    body: PrefsIn,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    await db.execute(text(
        "INSERT INTO painel_preferencias (user_id, cauc_vencendo, nova_emenda, prazo_prestacao, "
        "mudanca_status, vigencia_60d, updated_at) VALUES (:u, :a, :b, :c, :d, :e, NOW()) "
        "ON CONFLICT (user_id) DO UPDATE SET cauc_vencendo = :a, nova_emenda = :b, "
        "prazo_prestacao = :c, mudanca_status = :d, vigencia_60d = :e, updated_at = NOW()"
    ), {"u": current.id, "a": body.cauc_vencendo, "b": body.nova_emenda,
        "c": body.prazo_prestacao, "d": body.mudanca_status, "e": body.vigencia_60d})
    await db.commit()
    return {"ok": True}
