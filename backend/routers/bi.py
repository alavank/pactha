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
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from services.auth import get_current_user, hash_password, create_kiosk_token, ensure_tela
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

# Sentinela de "carteira toda" usada pelo frontend (BiScopeContext). O backend
# guarda o escopo do Modo Tela como texto porque quem o interpreta e a tela;
# aqui ele so precisa ir e voltar sem ser reinterpretado.
CONSOLIDADO = "__all__"


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
        model=os.getenv("PACTHA_AI_MODEL_TEXTO", "claude-sonnet-5"),
        max_tokens=600,
        # Sonnet 5 liga raciocinio adaptativo quando `thinking` e OMITIDO (o
        # Haiku nao ligava). Numa frase curta de painel isso so somaria latencia
        # e tokens, entao desligamos de proposito e usamos effort baixo: aqui o
        # modelo apenas REDIGE — os numeros ja vem calculados do backend.
        thinking={"type": "disabled"},
        output_config={"effort": "low"},
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
        "Nao invente numeros. Nao invente ROTULOS: use apenas as descricoes que "
        "aparecem nos dados e nunca atribua um valor a uma area, tema, programa, "
        "orgao ou pessoa que nao esteja explicito ali (ex.: nao escreva 'para "
        "educacao' ou 'para saude' se o dado nao disser a que se refere; nesse "
        "caso diga apenas 'em repasses federais'). "
        "Responda APENAS um array JSON de 2 a 4 strings."
    )
    resp = await client.messages.create(
        model=os.getenv("PACTHA_AI_MODEL_TEXTO", "claude-sonnet-5"),
        max_tokens=500,
        # Sonnet 5 liga raciocinio adaptativo quando `thinking` e OMITIDO (o
        # Haiku nao ligava). Numa frase curta de painel isso so somaria latencia
        # e tokens, entao desligamos de proposito e usamos effort baixo: aqui o
        # modelo apenas REDIGE — os numeros ja vem calculados do backend.
        thinking={"type": "disabled"},
        output_config={"effort": "low"},
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
# MODO TELA — filtro POR USUARIO e link publico curto.
#
# Regra do produto: cada gestor e um ambiente. O que o secretario de Saude
# filtra vale para a TV DELE e para o link publico DELE; ninguem altera o que o
# outro ve. Por isso o filtro e chaveado por `user_id` e o link guarda o dono.
#
# O link publico nao leva mais o JWT na URL. Antes iam ~300 chars impossiveis de
# ditar, e revogar exigia desativar o usuario de quiosque — que era
# COMPARTILHADO entre todo mundo, entao derrubava a TV dos outros junto. Agora a
# URL leva um slug de 12 chars, o token mora no banco e cada link morre sozinho.
# --------------------------------------------------------------------------

class FiltroTelaIn(BaseModel):
    scope: str = CONSOLIDADO
    anos: list[int] = []
    aba: Optional[str] = None


class TelaLinkIn(BaseModel):
    nome: Optional[str] = None
    dias: int = 365
    # 'tela' = TV de parede (segue o filtro do dono em tempo real)
    # 'mobile' = app de celular (filtro PROPRIO no aparelho)
    kind: str = "tela"


def _caminho_link(slug: str, kind: str) -> str:
    """Rota da superficie. Curta nas duas porque o link e ditado/colado a mao."""
    return f"/m/{slug}" if kind == "mobile" else f"/t/{slug}"


def _anos_csv(anos: list[int]) -> str:
    """Normaliza pelo MESMO filtro do anos_list (1990<n<2100) para nao gravar
    lixo que depois volta como periodo valido."""
    return ",".join(str(a) for a in (anos_list(anos) or []))


def _csv_anos(csv: Optional[str]) -> list[int]:
    return anos_list(csv or "") or []


async def _ensure_kiosk_user(db: AsyncSession, owner: User, slug: str) -> int:
    """Usuario 'viewer' sintetico por LINK (antes era um por municipio,
    compartilhado entre todos os gestores). Um por link e o que torna a
    revogacao real: desativar este usuario mata o token daquele link e so dele
    — os outros links do mesmo dono seguem no ar.

    Espelha os municipios do dono: a TV nunca enxerga mais que quem a publicou."""
    email = f"kiosk-u{owner.id}-{slug}@painel.local"
    urow = (await db.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email})).first()
    if urow:
        uid = urow[0]
        await db.execute(text("UPDATE users SET active = true, role = 'viewer' WHERE id = :u"), {"u": uid})
    else:
        ph = hash_password(secrets.token_urlsafe(24))
        r = (await db.execute(text(
            "INSERT INTO users (email, name, password_hash, role, active, must_change_password) "
            "VALUES (:e, :n, :p, 'viewer', true, false) RETURNING id"
        ), {"e": email, "n": f"Quiosque de {owner.name or owner.email}", "p": ph})).first()
        uid = r[0]
    # concede a tela BI (consistencia; os endpoints /api/bi/* gateiam por municipio)
    await db.execute(text(
        "INSERT INTO user_telas (user_id, tela) VALUES (:u, 'bi') ON CONFLICT DO NOTHING"
    ), {"u": uid})
    # Espelha o escopo do dono a cada emissao (admin = carteira ativa inteira).
    await db.execute(text("DELETE FROM user_municipios WHERE user_id = :u"), {"u": uid})
    if owner.role == "admin":
        await db.execute(text(
            "INSERT INTO user_municipios (user_id, municipio_id) "
            "SELECT :u, id FROM municipios WHERE active = true ON CONFLICT DO NOTHING"
        ), {"u": uid})
    else:
        await db.execute(text(
            "INSERT INTO user_municipios (user_id, municipio_id) "
            "SELECT :u, municipio_id FROM user_municipios WHERE user_id = :o ON CONFLICT DO NOTHING"
        ), {"u": uid, "o": owner.id})
    return uid


@router.get("/tela-filtros")
async def get_tela_filtros(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Filtro corrente do PROPRIO usuario. A janela do Modo Tela le daqui quando
    esta noutro navegador/aparelho, onde o BroadcastChannel nao alcanca."""
    row = (await db.execute(text(
        "SELECT scope, anos, aba FROM bi_tela_filtros WHERE user_id = :u"
    ), {"u": current.id})).first()
    if not row:
        # `existe: false` importa: sem ele a tela aberta por um link antigo
        # (?kiosk=<jwt>&scope=...) leria este default e jogaria fora o filtro que
        # veio na URL, regredindo o link que ja estava colado numa TV.
        return {"existe": False, "scope": CONSOLIDADO, "anos": [], "aba": None}
    return {"existe": True, "scope": row[0], "anos": _csv_anos(row[1]), "aba": row[2]}


@router.put("/tela-filtros")
async def put_tela_filtros(
    body: FiltroTelaIn,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Publica o filtro do usuario. O painel chama isto a cada mudanca de periodo
    ou de municipio — e o que faz a TV e o link publico virarem junto."""
    await db.execute(text(
        "INSERT INTO bi_tela_filtros (user_id, scope, anos, aba, updated_at) "
        "VALUES (:u, :s, :a, :b, NOW()) "
        "ON CONFLICT (user_id) DO UPDATE SET scope = :s, anos = :a, aba = :b, updated_at = NOW()"
    ), {"u": current.id, "s": (body.scope or CONSOLIDADO)[:40],
        "a": _anos_csv(body.anos), "b": (body.aba or None)})
    await db.commit()
    return {"ok": True}


@router.post("/tela-links")
async def criar_tela_link(
    body: TelaLinkIn,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Gera um link publico CURTO para a TV. Permissao propria (`bi_link`): quem
    pode ver o Modo Tela nao necessariamente pode publicar dado para fora."""
    ensure_tela(current, "bi_link")
    kind = "mobile" if (body.kind or "tela").lower() == "mobile" else "tela"
    dias = max(1, min(int(body.dias or 365), 3650))
    slug = secrets.token_urlsafe(9)[:12]  # 12 chars, ~72 bits: curto e nao chutavel
    uid = await _ensure_kiosk_user(db, current, slug)
    token = create_kiosk_token(uid, dias)
    # Expiracao calculada em Python de proposito: `make_interval(days => :d)`
    # mistura a notacao de argumento nomeado do Postgres com o bind do
    # SQLAlchemy, e nao ha ganho nenhum em arriscar isso no driver.
    expira = datetime.now(timezone.utc) + timedelta(days=dias)
    await db.execute(text(
        "INSERT INTO bi_tela_links (slug, owner_id, kiosk_user_id, municipio_id, token, nome, expira_em, kind) "
        "VALUES (:s, :o, :k, NULL, :t, :n, :e, :kind)"
    ), {"s": slug, "o": current.id, "k": uid, "t": token,
        "n": (body.nome or None), "e": expira, "kind": kind})
    await db.commit()
    return {"slug": slug, "caminho": _caminho_link(slug, kind), "kind": kind, "dias": dias}


@router.get("/tela-links")
async def listar_tela_links(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Links do PROPRIO usuario — ninguem lista nem revoga link alheio."""
    # Revogado NAO aparece: o link esta morto (404 e token desativado) e nao ha
    # nada a fazer com ele. Antes ficava na lista para sempre, sem marca alguma —
    # ao recarregar o modal, um link que o gestor acabou de apagar reaparecia, e o
    # botao de copiar entregava uma URL que nao abre.
    rows = (await db.execute(text(
        "SELECT slug, nome, criado_em, expira_em, revogado, ultimo_acesso, kind "
        "FROM bi_tela_links WHERE owner_id = :u AND NOT revogado "
        "ORDER BY criado_em DESC LIMIT 50"
    ), {"u": current.id})).fetchall()
    return [{
        "slug": r[0], "caminho": _caminho_link(r[0], r[6] or "tela"),
        "kind": r[6] or "tela", "nome": r[1],
        "criado_em": r[2].isoformat() if r[2] else None,
        "expira_em": r[3].isoformat() if r[3] else None,
        "revogado": r[4],
        "ultimo_acesso": r[5].isoformat() if r[5] else None,
    } for r in rows]


@router.delete("/tela-links/{slug}")
async def revogar_tela_link(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Revoga o link. So o dono revoga o proprio.

    Marcar `revogado` sozinho nao bastaria: quem ja tivesse extraido o token do
    localStorage da TV continuaria batendo na API por mais 365 dias. Como o
    usuario de quiosque e por LINK, desativa-lo mata o token daquele link — e
    so dele."""
    row = (await db.execute(text(
        "UPDATE bi_tela_links SET revogado = TRUE WHERE slug = :s AND owner_id = :u "
        "RETURNING kiosk_user_id"
    ), {"s": slug, "u": current.id})).first()
    if not row:
        await db.rollback()
        raise HTTPException(status_code=404, detail="Link nao encontrado")
    await db.execute(text("UPDATE users SET active = false WHERE id = :k"), {"k": row[0]})
    await db.commit()
    return {"ok": True}


@router.get("/tela-pub/{slug}")
async def resolver_tela_link(slug: str, db: AsyncSession = Depends(get_db)):
    """PUBLICO — o slug e o segredo. A TV chama isto ao abrir e a cada poll:
    devolve o token de quiosque e o FILTRO VIGENTE DO DONO. E por aqui que
    "mudou o periodo no sistema" vira "mudou na TV" mesmo noutro aparelho, onde
    o BroadcastChannel nunca chegaria."""
    row = (await db.execute(text(
        "SELECT l.token, l.owner_id, l.municipio_id, l.revogado, l.expira_em, "
        "       f.scope, f.anos, f.aba, l.kind "
        "FROM bi_tela_links l "
        "LEFT JOIN bi_tela_filtros f ON f.user_id = l.owner_id "
        "WHERE l.slug = :s"
    ), {"s": slug})).first()
    if not row or row[3]:
        raise HTTPException(status_code=404, detail="Link invalido ou revogado")
    if row[4] is not None and row[4] < datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="Link expirado")
    # Throttle proposital: a TV chama isto a cada 10s, o dia inteiro. Gravar a
    # cada chamada seriam ~8.600 escritas/dia por televisao, so para mexer num
    # carimbo que ninguem le com essa precisao. De 5 em 5 minutos basta.
    await db.execute(text(
        "UPDATE bi_tela_links SET ultimo_acesso = NOW() WHERE slug = :s "
        "AND (ultimo_acesso IS NULL OR ultimo_acesso < NOW() - INTERVAL '5 minutes')"
    ), {"s": slug})
    await db.commit()
    # municipio_id preenchido = link fixado num municipio; NULL = segue o dono.
    # O NULL e o caso da assessoria: trocou de municipio no sistema, a TV vai
    # junto. Quem barra excesso e o resolve_scope dos endpoints de dado, que so
    # aceita municipio dentro do escopo do usuario de quiosque.
    scope = str(row[2]) if row[2] is not None else (row[5] or CONSOLIDADO)
    return {
        "token": row[0],
        "scope": scope,
        "anos": _csv_anos(row[6]),
        "aba": row[7],
        # 'mobile' usa isto como SEMENTE e depois manda em si; 'tela' segue o
        # dono a cada poll. Quem decide e a superficie, nao o servidor.
        "kind": row[8] or "tela",
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
