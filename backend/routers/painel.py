"""Painel Executivo do prefeito — visao consolidada READ-ONLY por municipio.

Superficie SEPARADA do sistema operacional (o app dir `painel/` consome estes
endpoints). Gate SO por municipio (ensure_municipio_access), sem ensure_tela:
reusa os nucleos de calculo ja existentes (summary, cauc, parlamentares,
convenios, status_changes) sem acoplar o prefeito as telas operacionais.
"""
from __future__ import annotations
import os
import json
import hashlib
import secrets
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from services.auth import get_current_user, ensure_municipio_access, hash_password, create_kiosk_token
from models.user import User

from routers.municipios import municipio_summary
from routers.cauc import fetch_cauc_situacao
from routers.parlamentares import aggregate_parlamentares
from routers.convenios import query_alertas_vigencia, query_prestacao_contas
from routers import status_changes as _status_changes

router = APIRouter(prefix="/api/painel", tags=["painel"])


@router.get("/{municipio_id}/visao")
async def visao(
    municipio_id: int,
    ano: Optional[int] = Query(None, description="Filtra os KPIs por ano (None=todos)"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Payload consolidado da home do Painel: KPIs + semaforo CAUC + top
    parlamentares + ultimas mudancas. Um round-trip so p/ mobile/TV."""
    ensure_municipio_access(current, municipio_id)
    summary = await municipio_summary(municipio_id, ano, db, current)
    cauc = await fetch_cauc_situacao(db, municipio_id)
    ranking = await aggregate_parlamentares(
        db, municipio_id=municipio_id, ano=ano, incluir_plano_acao=False
    )
    mudancas = await _status_changes.listar(
        municipio_id=municipio_id, days=30, limit=8, db=db, current=current
    )
    # Saúde: dívida do Fundo Estadual de Saúde (Acordo FES/SES-MG) com o município.
    saude = None
    try:
        row = (await db.execute(text(
            "SELECT COALESCE(SUM(divida_atual),0), COALESCE(SUM(total_pago),0), "
            "COALESCE(SUM(divida_inicial),0) FROM acordofes_credor WHERE municipio_id = :m"
        ), {"m": municipio_id})).first()
        if row and (row[0] or row[1] or row[2]):
            saude = {"divida_atual": float(row[0] or 0), "pago": float(row[1] or 0), "inicial": float(row[2] or 0)}
    except Exception:
        saude = None
    return {
        "kpis": summary.model_dump(),
        "semaforo": {
            "tem_dados": cauc.get("tem_dados", False),
            "regular": cauc.get("regular"),
            "pendencias": cauc.get("pendencias", 0),
            "pendencias_codigos": cauc.get("pendencias_codigos", []),
        },
        "saude": saude,
        "top_parlamentares": ranking["items"][:8],
        "ultimas_mudancas": mudancas.get("items", []),
    }


@router.get("/{municipio_id}/semaforo")
async def semaforo(
    municipio_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Semaforo de regularidade (CAUC) completo: regular/pendencias + itens."""
    ensure_municipio_access(current, municipio_id)
    return await fetch_cauc_situacao(db, municipio_id)


@router.get("/{municipio_id}/ranking-parlamentares")
async def ranking_parlamentares(
    municipio_id: int,
    ano: Optional[int] = Query(None),
    live: bool = Query(False, description="Inclui o fetch AO VIVO do RP9 federal (mais lento)"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Ranking de quem destinou recurso ao municipio (cross-fonte)."""
    ensure_municipio_access(current, municipio_id)
    return await aggregate_parlamentares(
        db, municipio_id=municipio_id, ano=ano, incluir_plano_acao=live
    )


@router.get("/{municipio_id}/timeline")
async def timeline(
    municipio_id: int,
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Mudancas de status recentes (o que mexeu no municipio)."""
    ensure_municipio_access(current, municipio_id)
    return await _status_changes.listar(
        municipio_id=municipio_id, days=days, limit=limit, db=db, current=current
    )


@router.get("/{municipio_id}/alertas")
async def alertas(
    municipio_id: int,
    ano: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Prazos que exigem acao: vigencias vencendo (<=120d) + prestacao de contas (+90d)."""
    ensure_municipio_access(current, municipio_id)
    vig = await query_alertas_vigencia(db, municipio_id, 120, ano)
    prest = await query_prestacao_contas(db, municipio_id, 90, ano)
    return {
        "vigencia": [a.model_dump() for a in vig],
        "prestacao": [a.model_dump() for a in prest],
    }


@router.get("/{municipio_id}/narrativa")
async def narrativa(
    municipio_id: int,
    ano: Optional[int] = Query(None),
    kind: str = Query("resumo"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Resumo em linguagem leiga (IA/Haiku) com cache por input_hash. Degrada
    graciosamente: sem ANTHROPIC_API_KEY, devolve disponivel=false e o frontend
    usa o texto por template. GET grava o cache (nao e escrita do sistema)."""
    ensure_municipio_access(current, municipio_id)
    summary = await municipio_summary(municipio_id, ano, db, current)
    cauc = await fetch_cauc_situacao(db, municipio_id)
    ranking = await aggregate_parlamentares(db, municipio_id=municipio_id, ano=ano, incluir_plano_acao=False)
    top = [
        {"n": t["nome_display"], "v": t["valor_total"]}
        for t in ranking["items"]
        if "MUNICIPIO" not in (t.get("nome_normalizado") or "") and "PREFEITURA" not in (t.get("nome_normalizado") or "")
    ][:3]
    dados = {
        "municipio": summary.municipio.nome,
        "ano": ano,
        "estadual": summary.valor_total_estadual,
        "federal": summary.valor_total_federal,
        "voluntarias": summary.total_voluntarias,
        "convenios_est": summary.total_convenios_estadual,
        "prestacao": summary.alertas_prestacao_contas,
        "vigencia": summary.alertas_vigencia,
        "cauc_regular": cauc.get("regular"),
        "cauc_pend": cauc.get("pendencias"),
        "top": top,
    }
    input_hash = hashlib.sha256(json.dumps(dados, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    ano_key = ano or 0

    row = (await db.execute(text(
        "SELECT texto, input_hash, gerado_em FROM painel_narrativa_cache "
        "WHERE municipio_id = :m AND ano = :a AND kind = :k"
    ), {"m": municipio_id, "a": ano_key, "k": kind})).first()
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
    ), {"m": municipio_id, "a": ano_key, "k": kind, "t": texto, "h": input_hash})
    await db.commit()
    return {"texto": texto, "kind": kind, "cache": False, "disponivel": True}


def _money_br(v) -> str:
    v = float(v or 0)
    if abs(v) >= 1_000_000:
        return ("R$ %.1f mi" % (v / 1_000_000)).replace(".", ",")
    if abs(v) >= 1_000:
        return "R$ %.0f mil" % (v / 1_000)
    return "R$ %.0f" % v


async def _gerar_narrativa(dados: dict, kind: str, api_key: str) -> str:
    """Uma chamada Haiku (sem tools/thinking) que traduz os numeros em 2-4 frases
    de linguagem leiga para o prefeito. NAO reusa o tool-loop pesado do ai.py."""
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)
    total = (dados["estadual"] or 0) + (dados["federal"] or 0)
    top_txt = "; ".join(f'{t["n"]} ({_money_br(t["v"])})' for t in dados["top"]) or "sem registro"
    ano_txt = str(dados["ano"]) if dados["ano"] else "todos os anos"
    cauc_txt = "em dia, sem pendencias" if dados["cauc_regular"] else f'{dados["cauc_pend"]} pendencia(s)'
    system = (
        "Voce explica dados de captacao de recursos publicos para um PREFEITO leigo, em "
        "portugues do Brasil. Linguagem simples e direta, tom institucional, positivo mas "
        "honesto. Sem jargao tecnico. Responda em 2 a 4 frases curtas. Nao invente numeros "
        "alem dos fornecidos."
    )
    prompt = (
        f"Municipio: {dados['municipio']}. Periodo: {ano_txt}.\n"
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


# ---- Token de quiosque (TV liga sem senha) — emissao ADMIN ----

class KioskIn(BaseModel):
    municipio_id: int
    dias: int = 365


@router.post("/kiosk-tokens")
async def criar_kiosk_token(
    body: KioskIn,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Emite um token de longa duracao pra TV do municipio ligar sem login.
    Cria/reusa um usuario 'viewer' escopado ao municipio e devolve o token (a TV
    grava em localStorage.pactha_token). Somente admin."""
    if current.role != "admin":
        raise HTTPException(status_code=403, detail="Apenas admin emite token de quiosque")
    mrow = (await db.execute(text(
        "SELECT nome FROM municipios WHERE id = :m AND active = true"
    ), {"m": body.municipio_id})).first()
    if not mrow:
        raise HTTPException(status_code=404, detail="Municipio nao encontrado")

    email = f"kiosk-{body.municipio_id}@painel.local"
    urow = (await db.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email})).first()
    if urow:
        uid = urow[0]
        await db.execute(text("UPDATE users SET active = true, role = 'viewer' WHERE id = :u"), {"u": uid})
    else:
        ph = hash_password(secrets.token_urlsafe(24))
        r = (await db.execute(text(
            "INSERT INTO users (email, name, password_hash, role, active, must_change_password) "
            "VALUES (:e, :n, :p, 'viewer', true, false) RETURNING id"
        ), {"e": email, "n": f"Quiosque {mrow[0]}", "p": ph})).first()
        uid = r[0]

    await db.execute(text(
        "INSERT INTO user_municipios (user_id, municipio_id) VALUES (:u, :m) ON CONFLICT DO NOTHING"
    ), {"u": uid, "m": body.municipio_id})
    await db.commit()

    token = create_kiosk_token(uid, body.dias)
    return {
        "token": token,
        "municipio_id": body.municipio_id,
        "municipio": mrow[0],
        "dias": body.dias,
        "user_email": email,
        "instrucoes": "Na TV, abra /tv e cole este token em localStorage.pactha_token, ou acesse /tv?kiosk=<token>.",
    }


# ---- Push web + preferencias (prefeito) ----

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
    ensure_municipio_access(current, body.municipio_id)
    await db.execute(text(
        "INSERT INTO painel_push_subscriptions (user_id, municipio_id, endpoint, p256dh, auth, ua) "
        "VALUES (:u, :m, :e, :p, :a, :ua) "
        "ON CONFLICT (endpoint) DO UPDATE SET p256dh = :p, auth = :a, ua = :ua, "
        "municipio_id = :m, user_id = :u, last_ok_at = NULL"
    ), {"u": current.id, "m": body.municipio_id, "e": body.endpoint, "p": body.p256dh, "a": body.auth, "ua": body.ua})
    await db.commit()
    return {"ok": True}


@router.delete("/push/subscribe")
async def push_unsubscribe(
    endpoint: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    await db.execute(text("DELETE FROM painel_push_subscriptions WHERE endpoint = :e"), {"e": endpoint})
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
        return {"cauc_vencendo": True, "nova_emenda": True, "prazo_prestacao": True, "mudanca_status": True, "vigencia_60d": True}
    return {"cauc_vencendo": row[0], "nova_emenda": row[1], "prazo_prestacao": row[2], "mudanca_status": row[3], "vigencia_60d": row[4]}


@router.put("/preferencias")
async def put_preferencias(
    body: PrefsIn,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    await db.execute(text(
        "INSERT INTO painel_preferencias (user_id, cauc_vencendo, nova_emenda, prazo_prestacao, mudanca_status, vigencia_60d, updated_at) "
        "VALUES (:u, :a, :b, :c, :d, :e, NOW()) "
        "ON CONFLICT (user_id) DO UPDATE SET cauc_vencendo = :a, nova_emenda = :b, prazo_prestacao = :c, "
        "mudanca_status = :d, vigencia_60d = :e, updated_at = NOW()"
    ), {"u": current.id, "a": body.cauc_vencendo, "b": body.nova_emenda, "c": body.prazo_prestacao,
        "d": body.mudanca_status, "e": body.vigencia_60d})
    await db.commit()
    return {"ok": True}
