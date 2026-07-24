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
)
from models.user import User
from routers.cauc import fetch_cauc_situacao
from routers.parlamentares import aggregate_parlamentares
from routers.convenios import query_alertas_vigencia, query_prestacao_contas
from routers.status_changes import listar_core

router = APIRouter(prefix="/api/bi", tags=["bi"])


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
                            ano: Optional[int], live: bool) -> dict:
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
    return {
        "consolidado": cons,
        "municipios_count": len(ids),
        "municipio_ids": ids,
        "ano": ano,
        "kpis": kpis,
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
    live: bool = Query(False, description="Inclui o RP9 federal AO VIVO (lento; nao usar no polling da TV)"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ids, cons = await resolve_scope(db, current, municipio_id)
    single = (not cons) and len(ids) == 1

    cache_key = f"{scope_signature(ids, cons)}|a={ano or 0}|l={int(live)}"
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
    live: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ids, cons = await resolve_scope(db, current, municipio_id)
    if (not cons) and len(ids) == 1:
        return await aggregate_parlamentares(db, municipio_id=ids[0], ano=ano, incluir_plano_acao=live)
    return await aggregate_parlamentares(db, municipio_ids=ids, ano=ano, incluir_plano_acao=live)


@router.get("/alertas")
async def alertas(
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ids, cons = await resolve_scope(db, current, municipio_id)
    if (not cons) and len(ids) == 1:
        vig = await query_alertas_vigencia(db, ids[0], 120, ano)
        prest = await query_prestacao_contas(db, ids[0], 90, ano)
    else:
        vig = await query_alertas_vigencia(db, None, 120, ano, municipio_ids=ids)
        prest = await query_prestacao_contas(db, None, 90, ano, municipio_ids=ids)
    return {
        "vigencia": [a.model_dump() for a in vig],
        "prestacao": [a.model_dump() for a in prest],
    }


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
    kind: str = Query("resumo"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Resumo executivo em linguagem leiga (IA/Haiku) com cache por input_hash.
    Sem ANTHROPIC_API_KEY -> disponivel=false e o frontend usa texto por template."""
    ids, cons = await resolve_scope(db, current, municipio_id)
    single = (not cons) and len(ids) == 1

    kpis = await bi_kpis(db, ids, ano)
    cauc = await bi_cauc_rollup(db, ids)
    if single:
        ranking = await aggregate_parlamentares(db, municipio_id=ids[0], ano=ano, incluir_plano_acao=False)
        mrow = (await db.execute(text("SELECT nome FROM municipios WHERE id = :m"), {"m": ids[0]})).first()
        nome = mrow[0] if mrow else f"Municipio {ids[0]}"
        cauc_regular = cauc["por_municipio"][0]["regular"] if cauc["por_municipio"] else None
        mid_key = ids[0]
    else:
        ranking = await aggregate_parlamentares(db, municipio_ids=ids, ano=ano, incluir_plano_acao=False)
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
    if single:
        kind_key = kind
    else:
        sig = hashlib.sha256(scope_signature(ids, cons).encode("utf-8")).hexdigest()[:16]
        kind_key = f"bi:{sig}:{kind}"

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
