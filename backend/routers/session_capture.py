"""
Endpoint para o bookmarklet enviar cookie de sessao do portal governamental.

Fluxo:
1. Cliente loga manualmente no portal (FNS/SIMEC/etc)
2. Clica no bookmarklet PACTHA na barra de favoritos
3. JavaScript captura document.cookie + URL atual
4. POST aqui com X-Service-Token (do bookmarklet) ou JWT (logado em PACTHA)
5. Backend criptografa e salva no Cofre como observacao da credencial
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, update
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

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/session-capture", tags=["session"])


def conteudo_e_sessao(claro: str | None) -> bool:
    """O conteudo decifrado de uma linha do Cofre e uma SESSAO (e nao uma senha)?

    ⚠️ MESMO CRITERIO DE `govbr_renew._load_govbr`, e os dois precisam concordar:
    la, `dec.startswith("{")` e o que decide se a linha serve como sessao. Se
    este teste ficar mais frouxo que aquele, a captura considera credencial o que
    o renovador considera sessao (ou o contrario), e a divergencia so aparece
    como "recapturei e continua sem sessao".

    Senha de verdade nao comeca com "{"; o payload da extensao e um JSON.

    Sem `strip()` DE PROPOSITO: `_load_govbr` nao faz, e um criterio "mais
    esperto" aqui reintroduz a divergencia que este docstring existe para evitar.
    """
    return (claro or "").startswith("{")


# =====================================================================
# SESSAO VIVA NAO E SOBRESCRITA — a captura vira CANDIDATA
# =====================================================================
#
# ⚠️ POR QUE ISTO EXISTE (21/09/2026). A sessao gov.br morreu nos SEIS tenants
# ao mesmo tempo tres vezes em duas semanas (09/09, 14/09, 17/09), com tempos de
# vida de 11h a 79h — variavel demais para ser teto do SSO. O mecanismo estava
# aqui: a extensao espelha o jar do Chrome do dono para os seis Cofres em TODA
# navegacao em gov.br (inclusive www.gov.br e a propria tela de login) e a cada
# 12 minutos, sem saber se o Chrome esta logado; e este endpoint gravava por
# cima da sessao viva conferindo so `len(cookie) >= 10`. Chrome fechado (cookie
# de sessao some), "Sair" no portal ou gov.br aberto deslogado => jar MORTO por
# cima da sessao BOA, nos seis de uma vez.
#
# ⚠️ A GUARDA NAO OLHA NOME DE COOKIE. Seria o jeito barato ("tem
# Session_Gov_Br_Prod?"), mas o nome e o dominio do cookie de SSO nunca foram
# medidos em producao, e uma guarda por nome errado recusaria a captura BOA —
# o defeito oposto, e pior. Quem sabe se um jar esta logado e quem o USA: o
# worker (govbr_renew.processa_candidata) navega com ele e so promove se
# autenticar. Aqui so se decide ONDE guardar:
#   sessao atual VIVA  -> linha `govbr_candidata`; a viva nao e tocada.
#   sessao atual MORTA (ou nunca medida) -> grava direto, como sempre. E o
#       caminho da RECAPTURA, que tem de valer na hora.
#
# "Viva" = a ultima linha de `govbr_sso` (o renew horario do worker) e success
# e tem menos de SESSAO_VIVA_MIN. 180 = tres renews perdidos, o mesmo prazo do
# vigia (watchdog_coleta._sessao_govbr_caida). Sem linha nenhuma, ou se a
# consulta falhar, NAO esta viva: o lado seguro e o comportamento antigo, que
# nunca impede uma recaptura.
CHAVE_GOVBR = "govbr"
CHAVE_CANDIDATA = "govbr_candidata"
SOURCE_SSO = "govbr_sso"          # o mesmo nome de govbr_renew.SOURCE_SSO
# A regua de "viva" mora em services/sessao_govbr.py — o vigia (sync, sem
# Playwright) usa a MESMA para o aviso de vencimento; duas copias divergiriam.
from services.sessao_govbr import SESSAO_VIVA_MIN, sessao_esta_viva  # noqa: E402,F401


async def _ultima_medicao(db: AsyncSession, source: str) -> tuple:
    """(status, idade em minutos, mensagem) da ultima linha da fonte no
    ingestion_log, ou (None, None, None). Best-effort: falha vira 'nao sei'."""
    try:
        # ⚠️ EM SAVEPOINT. No Postgres uma query que falha ABORTA a transacao, e o
        # `except` sozinho nao a conserta: o commit da captura, logo depois na
        # MESMA sessao, levantaria InFailedSQLTransaction e a recaptura viraria
        # 500 — por causa de uma consulta que se diz "best-effort".
        async with db.begin_nested():
            row = (await db.execute(text(
                "SELECT status, EXTRACT(EPOCH FROM (NOW() - finished_at)) / 60, error_message "
                "FROM ingestion_log WHERE source = :s ORDER BY id DESC LIMIT 1"
            ), {"s": source})).first()
        if not row:
            return None, None, None
        return row[0], (float(row[1]) if row[1] is not None else None), row[2]
    except Exception as e:  # tabela ausente, banco ocupado: nao impede a captura
        log.info("session-capture: ultima medicao de %s indisponivel (%s)", source, str(e)[:80])
        return None, None, None


# Estado do auto-scrape DESTE processo (ver o bloco AUTO-DISPATCH no POST).
_AUTO_SCRAPE = {"rodando": False, "ultimo": 0.0}
AUTO_SCRAPE_INTERVALO_S = 6 * 3600


def _agora_s() -> float:
    import time
    return time.monotonic()


def pode_auto_scrape(agora: float | None = None) -> bool:
    """O POST de captura pode disparar o scraper dentro da API?

    So com `SESSION_CAPTURE_AUTO_SCRAPE=1` (default DESLIGADO), sem outro rodando
    neste processo e com o ultimo disparo ha mais de AUTO_SCRAPE_INTERVALO_S. A
    env e lida a cada chamada: liga e desliga por tenant sem deploy."""
    import os
    if (os.getenv("SESSION_CAPTURE_AUTO_SCRAPE", "0") or "0").strip() not in ("1", "true", "yes"):
        return False
    if _AUTO_SCRAPE["rodando"]:
        return False
    agora = _agora_s() if agora is None else agora
    ult = _AUTO_SCRAPE["ultimo"]
    return not ult or (agora - ult) >= AUTO_SCRAPE_INTERVALO_S


class _CapturePrincipal:
    """Resultado da autenticacao flexivel: JWT de usuario OU service token.
    Expoe .user_id (None se service token) e .label para auditoria."""
    def __init__(self, user_id: Optional[int], label: str, via: str):
        self.user_id = user_id
        self.label = label
        self.via = via  # 'jwt' | 'service_token'


async def get_capture_principal_leitura(
    request: Request,
    x_service_token: Optional[str] = Header(None, alias="X-Service-Token"),
    db: AsyncSession = Depends(get_db),
) -> "_CapturePrincipal":
    """A MESMA autenticacao de `get_capture_principal`, sem carimbar o uso do token.

    `last_used_at` do token `extensao-captura` e o diagnostico de "este tenant
    esta RECEBENDO captura" (foi assim que se achou o BGK sem token em 09/09). A
    consulta de saude roda de 12 em 12 minutos nos seis: se ela carimbasse, o
    campo passaria a dizer "em uso" com nenhuma captura chegando."""
    return await _resolve_principal(request, x_service_token, db, marcar_uso=False)


async def get_capture_principal(
    request: Request,
    x_service_token: Optional[str] = Header(None, alias="X-Service-Token"),
    db: AsyncSession = Depends(get_db),
) -> _CapturePrincipal:
    return await _resolve_principal(request, x_service_token, db, marcar_uso=True)


# ⚠️ FUNCAO COMUM, e nao um parametro a mais na dependencia: todo parametro
# simples de uma dependencia do FastAPI vira QUERY PARAM publico — `marcar_uso`
# apareceria como `?marcar_uso=false` na rota de captura.
async def _resolve_principal(
    request: Request,
    x_service_token: Optional[str],
    db: AsyncSession,
    marcar_uso: bool,
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
        if marcar_uso:
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
    # ⚠️ A MAIS RECENTE, e nao `scalar_one_or_none()`: nao ha indice unico em
    # (automation_key, municipio_id), e com duas linhas aquele metodo LEVANTA — a
    # captura passaria a responder 500 naquele tenant ate alguem limpar o banco a
    # mao. E a mesma linha que `govbr_renew._load_govbr_v` escolhe (ORDER BY
    # updated_at DESC), entao captura e renovador continuam falando da mesma.
    res = await db.execute(q.order_by(CofreSenha.updated_at.desc()))
    item = res.scalars().first()

    # ⚠️ NUNCA GRAVA SESSAO POR CIMA DE UMA CREDENCIAL. Isto ja aconteceu em
    # producao: a extensao antiga mandava `municipio_id`, o casamento por
    # (automation_key, municipio_id) achou a credencial gov.br da prefeitura e o
    # blob de cookies substituiu a SENHA. Em 02/09 havia duas assim (freitas
    # IBGE 3103900 e montesiao IBGE 3143401, mesmo CPF) — a senha nao volta.
    #
    # O teste e o mesmo que `govbr_renew._load_govbr` usa para decidir se uma
    # linha e sessao: o conteudo decifrado comeca com "{". Se a linha achada NAO
    # e sessao, ela e credencial de verdade — preserva-se, e a sessao vai para
    # uma linha nova.
    #
    # So vale para captura COM municipio (cliente antigo/bookmarklet): a
    # extensao atual manda sempre escopo de instancia, onde credencial nao mora.
    if item is not None and mid is not None:
        try:
            atual = crypto.decrypt(item.senha_encrypted) or ""
        except Exception:
            # Nao decifra => nao da para provar que e sessao => trata como
            # credencial e preserva. O lado seguro aqui e NAO sobrescrever.
            atual = ""
        if not conteudo_e_sessao(atual):
            log.warning(
                "session-capture: linha %s do Cofre e credencial (municipio_id=%s), "
                "nao sessao — preservada; a sessao vai para uma linha nova",
                item.id, mid,
            )
            item = None

    captured_at = datetime.now(timezone.utc).isoformat()
    n_cookies = len(payload.cookies_full) if payload.cookies_full else len(cookie_clean.split(";"))
    n_httponly = sum(1 for c in (payload.cookies_full or []) if c.httpOnly)
    obs = (
        f"[SESSION] capturado em {captured_at} | "
        f"cookies={n_cookies} httpOnly={n_httponly} | "
        f"url={(payload.url_atual or '?')[:100]} | "
        f"ua={(payload.user_agent or '?')[:60]}"
    )

    # ⭐ SESSAO gov.br VIVA NAO E SOBRESCRITA: a captura vira CANDIDATA e o worker
    # so a promove se ela AUTENTICAR. Ver o bloco "SESSAO VIVA NAO E SOBRESCRITA"
    # no topo. So vale para a sessao de instancia do gov.br e so quando ja existe
    # uma sessao gravada — primeira captura e recaptura de sessao morta seguem
    # direto, como sempre.
    if payload.automation_key == CHAVE_GOVBR and mid is None and item is not None:
        st, idade, _msg = await _ultima_medicao(db, SOURCE_SSO)
        if sessao_esta_viva(st, idade):
            cand = (await db.execute(
                select(CofreSenha).where(CofreSenha.automation_key == CHAVE_CANDIDATA)
                .where(CofreSenha.municipio_id.is_(None))
                # a MAIS NOVA, como o worker le (`_load_candidata`): dois POSTs
                # simultaneos podem ter criado duas linhas; o worker limpa as velhas.
                .order_by(CofreSenha.updated_at.desc())
            )).scalars().first()
            if cand:
                cand.senha_encrypted = crypto.encrypt(storage_payload)
                cand.observacao = obs
                cand.atualizado_por_id = principal.user_id
                await db.commit()
            else:
                cand = CofreSenha(
                    municipio_id=None,
                    sistema="Sessao GOVBR — candidata (aguardando validacao do worker)",
                    url=payload.url_atual,
                    usuario="(cookie)",
                    senha_encrypted=crypto.encrypt(storage_payload),
                    observacao=obs,
                    categoria="Sessao",
                    automation_key=CHAVE_CANDIDATA,
                    atualizado_por_id=principal.user_id,
                )
                db.add(cand)
                await db.commit()
                await db.refresh(cand)
            await log_event(
                db, action="session.candidata", user=None, request=request,
                target_type="cofre_session", target_id=cand.id,
                details={
                    "automation_key": payload.automation_key,
                    "municipio_id": payload.municipio_id,
                    "cookie_size": len(cookie_clean),
                    "auth_via": principal.via,
                    "principal": principal.label,
                },
            )
            # ⚠️ SEM auto-scrape: nada mudou na sessao em uso, e o scraper rodar a
            # cada navegacao do dono era carga sem proposito.
            return {
                "status": "candidata",
                "id": cand.id,
                "automation_key": payload.automation_key,
                "auto_scrape_started": False,
                "message": (
                    "A sessão gov.br do servidor está VIVA e não foi tocada. Esta "
                    "captura ficou como candidata: o worker a testa em até ~10 min "
                    "e só a promove se ela autenticar."
                ),
            }

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

    # AUTO-DISPATCH do scraper TransfereGov — ⛔ DESLIGADO POR PADRAO (21/09/2026).
    #
    # ISTO DERRUBOU A PRODUCAO. Cada captura disparava `transferegov_voluntarias
    # .run()` DENTRO DO PROCESSO DA API — e uma recaptura nao e uma captura: a
    # extensao manda uma por navegacao e por cookie trocado, para os SEIS
    # tenants. Medido em 21/09/2026, na recaptura do dono pelas 4 portas: ~20
    # rodadas do scraper por tenant em uma hora (o normal e 1 a 3), o event loop
    # das seis APIs travou, o healthcheck falhou e o proxy respondeu **503 nos
    # seis clientes** por varios minutos. E o `run()` de hoje nao e o de quando
    # isto foi escrito: desde 15/09 ele monta a arvore dos dumps (~12 min por
    # tenant). Pior: com a API fora, as capturas das portas seguintes da MESMA
    # recaptura voltavam 503 e se perdiam.
    #
    # Nao se perde coleta: o worker roda o TransfereGov toda noite (task
    # `transferegov` + `transferegov_lote`), com trava e orcamento proprios, e o
    # keepalive segura a sessao ate la. `SESSION_CAPTURE_AUTO_SCRAPE=1` religa
    # por tenant, sem deploy — e mesmo ligado roda UM por vez, com intervalo
    # minimo (`pode_auto_scrape`).
    auto_scrape = False
    if payload.automation_key in ("govbr", "siconv_legado") and pode_auto_scrape():
        try:
            import asyncio as _aio
            from ingestion.transferegov_voluntarias import run as _run_tg

            _AUTO_SCRAPE["rodando"] = True
            _AUTO_SCRAPE["ultimo"] = _agora_s()

            async def _bg_scrape():
                try:
                    await _run_tg()
                except Exception as ex:
                    import logging
                    logging.getLogger("auto-scrape").exception(f"erro: {ex}")
                finally:
                    _AUTO_SCRAPE["rodando"] = False

            _aio.create_task(_bg_scrape())
            auto_scrape = True
        except Exception as e:
            _AUTO_SCRAPE["rodando"] = False
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
            if auto_scrape else
            "Sessão capturada. O servidor a confirma em até ~10 min (keepalive); "
            "a coleta do TransfereGov roda na janela noturna do worker."
        ),
    }


def resumo_saude(sso: tuple, sps: tuple, tem_candidata: bool,
                 login_em=None, agora=None) -> dict:
    """O que a extensao mostra ao dono, NO CHROME, que e onde ele resolve.

    Funcao pura sobre as duas ultimas medicoes `(status, idade_min, mensagem)`.
    Sem valor de cookie, sem observacao do Cofre — so estado e horario.

    `precisa_recapturar` so e True com MEDICAO dizendo que o login caiu: tenant
    que nunca mediu (`status None`) nao cobra recaptura de ninguem, a mesma
    disciplina do vigia (`FRASE_SEM_SESSAO`)."""
    st, idade, msg = sso
    sp_st, sp_idade, sp_msg = sps
    viva = sessao_esta_viva(st, idade)
    nunca_capturou = bool(msg) and "nenhuma sessao" in str(msg).lower()
    caiu = (st is not None) and (st != "success") and not nunca_capturou
    # Hora do login e vencimento PREVISTO (padrao medido: ~24h) — e o que faz o
    # selo da extensao avisar ANTES de cair, em vez de so depois.
    from services.sessao_govbr import vencimento
    venc = vencimento(login_em, agora)
    return {
        "login": "vivo" if viva else ("caiu" if caiu else "sem_medicao"),
        "login_medido_ha_min": round(idade) if idade is not None else None,
        "modulos": sp_msg if sp_st and sp_st != "success" else ("private=vivo, execucao=vivo, prestacao=vivo" if sp_st == "success" else None),
        "modulos_medidos_ha_min": round(sp_idade) if sp_idade is not None else None,
        "candidata_pendente": bool(tem_candidata),
        "precisa_recapturar": bool(caiu),
        "login_em": venc["login_em"],
        "login_ha_h": venc["login_ha_h"],
        "vence_previsto_em": venc["vence_previsto_em"],
        "vence_em_h": venc["vence_em_h"],
        # so avisa vencimento de login VIVO: caido, quem fala e `precisa_recapturar`
        "vencendo": bool(venc["vencendo"] and viva),
    }


# `declarado`, como o POST: o token da extensao nao tem usuario de quem cobrar
# permissao, e o caminho do JWT a cobra dentro de `get_capture_principal`.
# Devolve SO estado e horario — nada do Cofre — para a extensao pintar o aviso
# no Chrome do dono. O vigia ja avisa no Telegram desde 16/09; a sessao ficou
# morta mais quatro dias mesmo assim. O aviso tem de chegar onde se resolve.
@router.get("/saude", dependencies=[declarado("sessoes.capturar")])
async def saude_da_sessao(
    db: AsyncSession = Depends(get_db),
    _principal: _CapturePrincipal = Depends(get_capture_principal_leitura),
):
    sso = await _ultima_medicao(db, SOURCE_SSO)
    sps = await _ultima_medicao(db, "govbr_sessao")
    try:
        tem = (await db.execute(
            select(CofreSenha.id).where(CofreSenha.automation_key == CHAVE_CANDIDATA)
            .where(CofreSenha.municipio_id.is_(None))
        )).first() is not None
    except Exception:
        tem = False
    login_em = None
    try:
        from services.sessao_govbr import login_em_da_observacao
        obs = (await db.execute(
            select(CofreSenha.observacao).where(CofreSenha.automation_key == CHAVE_GOVBR)
            .where(CofreSenha.municipio_id.is_(None))
            .order_by(CofreSenha.updated_at.desc())
        )).scalars().first()
        login_em = login_em_da_observacao(obs)
    except Exception:
        login_em = None
    return resumo_saude(sso, sps, tem, login_em=login_em)


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
