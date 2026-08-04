"""
Endpoint para o bookmarklet enviar cookie de sessao do portal governamental.

Fluxo:
1. Cliente loga manualmente no portal (FNS/SIMEC/etc)
2. Clica no bookmarklet PACTHA na barra de favoritos
3. JavaScript captura document.cookie + URL atual
4. POST aqui com X-Service-Token (do bookmarklet) ou JWT (logado em PACTHA)
5. Backend criptografa e salva no Cofre como observacao da credencial
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel

from database import get_db
from models import CofreSenha, User
from services import authz
from services.auth import get_current_user, decode_access, COOKIE_NAME_ACCESS
from services.registro_rotas import declarado, exige
from services.service_auth import hash_token, require_scope
from models.service_token import ServiceToken
from services import crypto
from services.audit import log_event

router = APIRouter(prefix="/api/session-capture", tags=["session"])


class _CapturePrincipal:
    """Resultado da autenticacao flexivel: JWT de usuario OU service token.
    Expoe .user_id (None se service token) e .label para auditoria."""
    def __init__(self, user_id: Optional[int], label: str, via: str):
        self.user_id = user_id
        self.label = label
        self.via = via  # 'jwt' | 'service_token'


async def get_capture_principal(
    request: Request,
    x_service_token: Optional[str] = Header(None, alias="X-Service-Token"),
    db: AsyncSession = Depends(get_db),
) -> _CapturePrincipal:
    """Aceita DOIS modos de auth para captura de sessao:

    1. X-Service-Token (extensao Chrome) — token LONGEVO com scope
       'session:write'. Resolve o problema do JWT de 60min que fazia a
       auto-captura da extensao morrer silenciosamente apos 1h.
    2. Authorization Bearer / cookie JWT (usuario logado no PACTHA web).

    Tenta service token primeiro; se ausente, cai pro JWT.
    """
    # Modo 1: service token (preferido pela extensao — nao expira em 60min)
    if x_service_token and len(x_service_token) >= 32:
        th = hash_token(x_service_token)
        res = await db.execute(select(ServiceToken).where(ServiceToken.token_hash == th))
        tok = res.scalar_one_or_none()
        if not tok or not tok.active:
            raise HTTPException(401, "Service token inválido ou revogado")
        if tok.expires_at and tok.expires_at < datetime.now(timezone.utc):
            raise HTTPException(401, "Service token expirado")
        require_scope(tok, "session:write")
        tok.last_used_at = datetime.now(timezone.utc)
        if request.client:
            tok.last_used_ip = request.client.host
        await db.commit()
        return _CapturePrincipal(user_id=None, label=f"service:{tok.name}", via="service_token")

    # Modo 2: JWT de usuario (web app) — aceita Bearer header OU cookie
    token = None
    auth_h = request.headers.get("Authorization") or ""
    if auth_h.lower().startswith("bearer "):
        token = auth_h[7:].strip()
    if not token:
        token = request.cookies.get(COOKIE_NAME_ACCESS)
    if not token:
        raise HTTPException(401, "Não autenticado (sem service token nem JWT)")
    try:
        payload = decode_access(token)
        uid = int(payload.get("sub"))
    except Exception:
        raise HTTPException(401, "JWT inválido ou expirado")
    res = await db.execute(select(User).where(User.id == uid))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(401, "Usuário não encontrado")
    # Esta rota decodifica o JWT na mao e NAO passa por `get_current_user`, entao
    # NENHUM guard central roda aqui — nem o de somente-leitura, nem o de
    # quiosque. As duas checagens abaixo tem de existir NESTE arquivo.
    #
    # `active` faltava: revogar um link de TV desativa o usuario de quiosque
    # (`bi.py::revogar_tela_link`), e sem esta linha o token revogado continuava
    # escrevendo no Cofre pelos 365 dias do JWT. O mesmo vale para funcionario
    # desligado cuja conta foi desativada.
    if not user.active:
        raise HTTPException(401, "Usuário inativo")
    # E conta de quiosque nao captura sessao. O que esta rota faz e cifrar e
    # gravar credencial no Cofre (e disparar o scraper): e a operacao mais
    # sensivel do sistema, e o link publico de TV nao tem o que fazer aqui.
    if getattr(user, "kiosk", False):
        raise HTTPException(403, "Conta de quiosque não captura sessão")
    # ⭐ E, no caminho do USUARIO, a permissao. Ela so existe aqui: o caminho do
    # service token nao tem `User` de quem cobrar, e nao precisa — a autoridade
    # dele e o scope `session:write`, ja conferido acima por `require_scope`.
    #
    # Por que isto faltava: a rota nasceu descrita como "a rota da extensao", e
    # com essa leitura ela foi para a allowlist de rotas livres. Mas o Modo 2
    # aqui aceita o cookie de QUALQUER conta ativa — e o que ela faz e cifrar
    # credencial de portal do governo dentro do Cofre e disparar o scraper. Sem
    # esta linha, `sessoes.capturar` era uma caixinha do catalogo que nenhuma
    # rota consultava: o administrador a marcava e nada mudava.
    authz.exigir(user, "sessoes.capturar")
    return _CapturePrincipal(user_id=user.id, label=f"user:{user.email}", via="jwt")


class CookieFull(BaseModel):
    name: str
    value: str
    domain: Optional[str] = None
    path: Optional[str] = None
    httpOnly: Optional[bool] = False
    secure: Optional[bool] = False
    sameSite: Optional[str] = None
    expirationDate: Optional[float] = None


class CapturedSession(BaseModel):
    automation_key: str   # ex: "fns", "govbr", "simec"
    municipio_id: Optional[int] = None   # None/0 = sessao da instancia (nao por municipio)
    cookie: str  # formato Cookie header: "name=val; name2=val2"
    cookies_full: Optional[list[CookieFull]] = None  # estrutura completa (extension)
    url_atual: Optional[str] = None
    user_agent: Optional[str] = None
    domain_capturado: Optional[str] = None


# `declarado` e nao `exige`: a permissao vale para UM dos dois modos de
# autenticacao (o do usuario) e quem sabe qual modo entrou e
# `get_capture_principal`, que a cobra la dentro. `exige()` aqui exigiria
# `get_current_user`, que esta rota deliberadamente nao usa — e mataria a
# extensao do Chrome, que nao manda cookie de sessao nenhum.
@router.post("", dependencies=[declarado("sessoes.capturar")])
async def capture_session(
    payload: CapturedSession,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: _CapturePrincipal = Depends(get_capture_principal),
):
    """Salva cookie de sessao capturado pelo bookmarklet/extensao no Cofre.
    Auth: service token longevo (extensao) OU JWT de usuario (web)."""
    if not payload.cookie or len(payload.cookie) < 10:
        raise HTTPException(status_code=400, detail="Cookie vazio ou inválido")

    # Limita tamanho
    cookie_clean = payload.cookie[:8000]

    # Se temos cookies_full (da extension), usa esse formato JSON cifrado
    # Senao, fallback para Cookie header simples
    import json
    if payload.cookies_full:
        # Usa formato estruturado (preserva httpOnly, expiry, etc)
        storage_payload = json.dumps({
            "format": "cookies_full",
            "cookies": [c.dict() for c in payload.cookies_full],
            "url": payload.url_atual,
            "domain": payload.domain_capturado,
        })[:64000]  # limit razoavel
    else:
        storage_payload = cookie_clean

    # municipio_id opcional: None/0 => sessao da instancia (nao amarrada a municipio).
    mid = payload.municipio_id or None
    # Encontra credencial existente para esse automation_key + municipio
    q = select(CofreSenha).where(CofreSenha.automation_key == payload.automation_key)
    q = q.where(CofreSenha.municipio_id.is_(None) if mid is None else CofreSenha.municipio_id == mid)
    res = await db.execute(q)
    item = res.scalar_one_or_none()

    captured_at = datetime.now(timezone.utc).isoformat()
    n_cookies = len(payload.cookies_full) if payload.cookies_full else len(cookie_clean.split(";"))
    n_httponly = sum(1 for c in (payload.cookies_full or []) if c.httpOnly)
    obs = (
        f"[SESSION] capturado em {captured_at} | "
        f"cookies={n_cookies} httpOnly={n_httponly} | "
        f"url={(payload.url_atual or '?')[:100]} | "
        f"ua={(payload.user_agent or '?')[:60]}"
    )

    if item:
        # Atualiza observacao + senha (com cookie cifrado)
        item.senha_encrypted = crypto.encrypt(storage_payload)
        item.observacao = obs
        item.atualizado_por_id = principal.user_id
        await db.commit()
        action = "session.update"
    else:
        # Cria nova
        item = CofreSenha(
            municipio_id=mid,
            sistema=f"Sessao {payload.automation_key.upper()}",
            url=payload.url_atual,
            usuario="(cookie)",
            senha_encrypted=crypto.encrypt(storage_payload),
            observacao=obs,
            categoria="Sessao",
            automation_key=payload.automation_key,
            atualizado_por_id=principal.user_id,
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)
        action = "session.create"

    await log_event(
        db, action=action, user=None, request=request,
        target_type="cofre_session", target_id=item.id,
        details={
            "automation_key": payload.automation_key,
            "municipio_id": payload.municipio_id,
            "cookie_size": len(cookie_clean),
            "auth_via": principal.via,
            "principal": principal.label,
        },
    )

    # AUTO-DISPATCH: se for gov.br OU siconv_legado, dispara scraper TransfereGov
    # em background imediatamente. A janela do JWT user-id (parcerias) e ~20min,
    # JSESSIONID do siconv_legado tambem expira rapido por inatividade.
    # captura+scrape automatico maximiza o aproveitamento.
    auto_scrape = False
    if payload.automation_key in ("govbr", "siconv_legado"):
        try:
            import asyncio as _aio
            from ingestion.transferegov_voluntarias import run as _run_tg

            async def _bg_scrape():
                try:
                    await _run_tg()
                except Exception as ex:
                    import logging
                    logging.getLogger("auto-scrape").exception(f"erro: {ex}")

            _aio.create_task(_bg_scrape())
            auto_scrape = True
        except Exception as e:
            import logging
            logging.getLogger("auto-scrape").warning(f"nao disparou: {e}")

    return {
        "status": "ok",
        "id": item.id,
        "automation_key": payload.automation_key,
        "auto_scrape_started": auto_scrape,
        "message": (
            "Sessão capturada + scraper TransfereGov iniciado em background "
            "(janela 20min). Acompanhe via /dashboard/sessoes."
            if auto_scrape else "Sessão capturada."
        ),
    }


# So o GET declara. O POST acima autentica por SERVICE TOKEN (a extensao do
# Chrome), onde nao ha usuario com permissao a checar — ele esta em ROTAS_LIVRES
# com esse motivo. Aqui ha `get_current_user`, entao ha o que exigir.
@router.get("/status/{automation_key}", dependencies=[exige("sessoes.ver")])
async def session_status(
    automation_key: str,
    municipio_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Verifica se ha sessao ativa cadastrada para esse portal/municipio.

    Distingue cookies de sessao (JSON, capturado via bookmarklet) de credencial
    cadastrada (senha em texto, util como referencia mas NAO permite scraping)."""
    q = select(CofreSenha).where(
        CofreSenha.automation_key == automation_key,
    ).order_by(CofreSenha.updated_at.desc())
    items = (await db.execute(q)).scalars().all()

    def _is_cookies(it: CofreSenha) -> bool:
        if not it or not it.senha_encrypted:
            return False
        dec = crypto.decrypt(it.senha_encrypted) or ""
        return dec.startswith("{") and '"cookies"' in dec

    # Prefere cookies do MESMO municipio; senao, cookies de qualquer mun
    # (sessao SSO gov.br serve cross-mun)
    cookies_item = next((it for it in items
                         if _is_cookies(it) and it.municipio_id == municipio_id), None)
    if not cookies_item:
        cookies_item = next((it for it in items if _is_cookies(it)), None)
    senha_item = next((it for it in items
                       if it.municipio_id == municipio_id and not _is_cookies(it)), None)

    if not cookies_item and not senha_item:
        return {"has_session": False, "tipo": None}

    pick = cookies_item or senha_item
    return {
        "has_session": True,
        "tipo": "cookies" if cookies_item else "senha_apenas",
        "has_cookies": cookies_item is not None,
        "id": pick.id,
        "municipio_id": pick.municipio_id,
        "atualizado_em": pick.updated_at.isoformat() if pick.updated_at else None,
        "observacao": pick.observacao,
    }
