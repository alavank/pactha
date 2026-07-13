"""
Superficie de CONTROL-PLANE que a instancia expoe ao Console Alavank.
Tudo sob /api/control/*, autenticado por X-Control-Token (kind='control', scope control:*).
Enderecamento por CHAVE ESTAVEL (ibge_code), nunca pelo id autoincrement interno.

Municipio NAO tem delecao (decisao do usuario) — no maximo desativar via PATCH.
"""
import os
import base64
import json as _json
import secrets as pysecrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from database import get_db
from models import Municipio
from models.user import User
from models.cofre import CofreSenha
from models.audit import AuditLog
from models.service_token import ServiceToken
from services.control_auth import require_control_scope, ControlPrincipal
from services.auth import hash_password, create_sso_token
from services.service_auth import hash_token
from services import users_admin, crypto
from services.telas_catalog import TELAS_CATALOG
from services.audit import log_event

router = APIRouter(prefix="/api/control", tags=["control"])


def _mun(m: Municipio) -> dict:
    return {"ibge_code": m.ibge_code, "nome": m.nome, "uf": m.uf,
            "active": bool(m.active), "fns_code": m.fns_code}


class MunicipioIn(BaseModel):
    ibge_code: str
    nome: str
    uf: str | None = "MG"
    fns_code: str | None = None


class MunicipioPatch(BaseModel):
    nome: str | None = None
    uf: str | None = None
    active: bool | None = None
    fns_code: str | None = None


# --- Municipios ---
@router.get("/municipios")
async def list_municipios(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:municipios:read")),
):
    """Lista TODOS os municipios, inclusive inativos (difere do GET de usuario)."""
    rows = (await db.execute(select(Municipio).order_by(Municipio.nome))).scalars().all()
    return [_mun(m) for m in rows]


@router.post("/municipios")
async def upsert_municipio(
    body: MunicipioIn, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:municipios:write")),
):
    """Upsert por ibge_code (reativa se estiver inativo)."""
    ibge = (body.ibge_code or "").strip()
    nome = (body.nome or "").strip()
    uf = (body.uf or "MG").strip().upper()[:2]
    if len(ibge) != 7 or not ibge.isdigit():
        raise HTTPException(status_code=400, detail="ibge_code deve ter 7 digitos")
    if not nome:
        raise HTTPException(status_code=400, detail="nome obrigatorio")

    fns = None
    if body.fns_code is not None:
        fns = "".join(ch for ch in body.fns_code if ch.isdigit())[:6] or None
    m = (await db.execute(select(Municipio).where(Municipio.ibge_code == ibge))).scalar_one_or_none()
    created = m is None
    if m is None:
        m = Municipio(nome=nome, ibge_code=ibge, uf=uf, active=True, fns_code=fns)
        db.add(m)
    else:
        m.nome = nome
        m.uf = uf
        m.active = True
        if body.fns_code is not None:
            m.fns_code = fns
    await db.commit()
    await db.refresh(m)
    await log_event(db, action="control.municipio.upsert", request=request,
                    target_type="municipio", target_id=ibge,
                    details={"nome": nome, "uf": uf, "created": created, "token": p.name})
    return _mun(m)


@router.patch("/municipios/{ibge_code}")
async def patch_municipio(
    ibge_code: str, body: MunicipioPatch, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:municipios:write")),
):
    """Renomear / mudar UF / ativar-desativar. Municipio NAO deleta (sem DELETE)."""
    m = (await db.execute(select(Municipio).where(Municipio.ibge_code == ibge_code))).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Municipio nao encontrado")
    changed = []
    if body.nome is not None and body.nome.strip():
        m.nome = body.nome.strip(); changed.append("nome")
    if body.uf is not None and body.uf.strip():
        m.uf = body.uf.strip().upper()[:2]; changed.append("uf")
    if body.active is not None:
        m.active = bool(body.active); changed.append("active")
    if body.fns_code is not None:
        m.fns_code = "".join(ch for ch in body.fns_code if ch.isdigit())[:6] or None
        changed.append("fns_code")
    await db.commit()
    await db.refresh(m)
    await log_event(db, action="control.municipio.patch", request=request,
                    target_type="municipio", target_id=ibge_code,
                    details={"changed": changed, "active": m.active, "token": p.name})
    return _mun(m)


# --- Status/identidade (o Console confirma que fala com o tenant certo) ---
@router.get("/status")
async def control_status(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:status:read")),
):
    async def _count(sql: str):
        try:
            return (await db.execute(text(sql))).scalar()
        except Exception:
            await db.rollback()
            return None

    return {
        "instance_slug": os.getenv("INSTANCE_SLUG", ""),
        "env": os.getenv("ENV", ""),
        "db_ok": True,
        "counts": {
            "municipios": await _count("SELECT COUNT(*) FROM municipios"),
            "municipios_ativos": await _count("SELECT COUNT(*) FROM municipios WHERE active = true"),
            "users": await _count("SELECT COUNT(*) FROM users"),
            "cofre_senhas": await _count("SELECT COUNT(*) FROM cofre_senhas"),
            # fontes de dados
            "convenios_estadual": await _count("SELECT COUNT(*) FROM convenios_estadual"),
            "transferegov_propostas": await _count("SELECT COUNT(*) FROM transferegov_propostas"),
            "emendas_estaduais": await _count("SELECT COUNT(*) FROM emendas_estaduais"),
            "cauc_situacao": await _count("SELECT COUNT(*) FROM cauc_situacao"),
            "acordofes_credor": await _count("SELECT COUNT(*) FROM acordofes_credor"),
            "siconv_federal": await _count("SELECT COUNT(*) FROM siconv_federal"),
        },
        "control_token": p.name,
    }


# --- Ingestao por fonte (ingestion_log) — a Central monitora a carga de cada fonte ---
@router.get("/ingestion")
async def control_ingestion(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:data:read")),
):
    """Ultimas execucoes por fonte (source, status, registros, quando). Isto e o
    historico real de ingestao — cada script grava aqui."""
    try:
        rows = (await db.execute(text(
            "SELECT source, status, records_inserted, "
            "to_char(finished_at, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS finished_at "
            "FROM ingestion_log ORDER BY id DESC LIMIT 40"
        ))).mappings().all()
        return {"log": [dict(r) for r in rows]}
    except Exception:
        await db.rollback()
        return {"log": [], "error": "tabela ingestion_log indisponivel"}


# --- Ingestao de dados (povoar/testar pela Central) ---
class RefreshIn(BaseModel):
    source: str = "sigcon"


@router.post("/refresh")
async def control_refresh(
    body: RefreshIn, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:data:write")),
):
    """Enfileira um job de scraping (mesma fila do refresh on-demand da UI). Dedup:
    nao enfileira se ja houver pending/running do mesmo tipo. Consumido pelo Worker
    (Scheduled Task -> ingestion/run_queue_sigcon.py). Hoje: 'sigcon' (dados abertos,
    sem credencial)."""
    source = (body.source or "sigcon").strip().lower()
    if source != "sigcon":
        raise HTTPException(status_code=400, detail="fonte nao suportada (use: sigcon)")
    row = (await db.execute(text(
        "INSERT INTO scraper_jobs (tipo, status) "
        "SELECT :t, 'pending' "
        "WHERE NOT EXISTS (SELECT 1 FROM scraper_jobs WHERE tipo = :t AND status IN ('pending','running')) "
        "RETURNING id"
    ), {"t": source})).first()
    await db.commit()
    await log_event(db, action="control.refresh", request=request,
                    target_type="scraper", target_id=source,
                    details={"queued": row is not None, "token": p.name})
    if row is None:
        return {"status": "already_queued", "source": source,
                "message": "Ja existe uma atualizacao na fila ou em execucao."}
    return {"status": "triggered", "source": source, "job_id": row[0],
            "message": "Job enfileirado. O Worker processa em ~1-2min."}


@router.get("/jobs")
async def control_jobs(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:data:read")),
):
    """Ultimos jobs de scraping (status pending|running|done|error) p/ a Central
    acompanhar a ingestao."""
    try:
        rows = (await db.execute(text(
            "SELECT id, tipo, status, "
            "to_char(requested_at, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS requested_at, "
            "to_char(started_at,   'YYYY-MM-DD\"T\"HH24:MI:SS') AS started_at, "
            "to_char(finished_at,  'YYYY-MM-DD\"T\"HH24:MI:SS') AS finished_at, "
            "error "
            "FROM scraper_jobs ORDER BY id DESC LIMIT 15"
        ))).mappings().all()
        return {"jobs": [dict(r) for r in rows]}
    except Exception:
        await db.rollback()
        return {"jobs": [], "error": "tabela scraper_jobs indisponivel"}


# --- Auditoria (audit_log) — a Central LE o que foi feito nesta instancia ---
def _audit_out(a: AuditLog) -> dict:
    return {
        "id": a.id,
        "user_email": a.user_email,
        "action": a.action,
        "target_type": a.target_type,
        "target_id": a.target_id,
        "ip": a.ip,
        "user_agent": a.user_agent,
        "details": a.details,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.get("/audit")
async def control_audit(
    action: str | None = None,
    user_email: str | None = None,
    target_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:audit:read")),
):
    """Eventos do audit_log desta instancia p/ a aba Auditoria da Central. SOMENTE
    LEITURA — o audit_log ja e gravado por varias acoes (login, cofre, user, etc.),
    aqui so lemos. Filtros opcionais: action (prefixo), user_email (substring),
    target_type (exato). Ordena por id DESC (mais recentes primeiro). Sem escopo novo:
    o control token e control:* — control:audit:read ja passa."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    stmt = select(AuditLog)
    if action and action.strip():
        stmt = stmt.where(AuditLog.action.ilike(action.strip() + "%"))
    if user_email and user_email.strip():
        stmt = stmt.where(AuditLog.user_email.ilike("%" + user_email.strip() + "%"))
    if target_type and target_type.strip():
        stmt = stmt.where(AuditLog.target_type == target_type.strip())
    stmt = stmt.order_by(AuditLog.id.desc()).limit(limit).offset(offset)
    try:
        rows = (await db.execute(stmt)).scalars().all()
    except Exception:
        await db.rollback()
        return []
    return [_audit_out(a) for a in rows]


# --- Cofre de credenciais (gerido pela Central; o scraper le localmente) ---
class CofreIn(BaseModel):
    municipio_ibge: str | None = None       # escopo (opcional; None = instancia)
    sistema: str
    url: str | None = None
    usuario: str | None = None
    senha: str | None = None                # texto claro -> cifrado no tenant
    automation_key: str | None = None       # ex: fns, govbr, simec...
    categoria: str | None = None
    observacao: str | None = None


class CofrePatch(BaseModel):
    municipio_ibge: str | None = None
    sistema: str | None = None
    url: str | None = None
    usuario: str | None = None
    senha: str | None = None
    automation_key: str | None = None
    categoria: str | None = None
    observacao: str | None = None


async def _mun_id_by_ibge(db, ibge: str | None):
    if not ibge:
        return None
    return (await db.execute(select(Municipio.id).where(Municipio.ibge_code == ibge))).scalar_one_or_none()


async def _ibge_by_mun_id(db, mid):
    if not mid:
        return None
    return (await db.execute(select(Municipio.ibge_code).where(Municipio.id == mid))).scalar_one_or_none()


def _cofre_mask(clear: str) -> str:
    if not clear:
        return ""
    s = clear.strip()
    if s.startswith("{") and '"cookies"' in s:   # blob de sessao capturada (extensao)
        return "[sessao capturada]"
    n = len(clear)
    return "*" * n if n <= 4 else clear[0] + "*" * (n - 2) + clear[-1]


async def _cofre_out(db, it: CofreSenha) -> dict:
    clear = crypto.decrypt(it.senha_encrypted) if it.senha_encrypted else ""
    return {
        "id": it.id,
        "municipio_ibge": await _ibge_by_mun_id(db, it.municipio_id),
        "sistema": it.sistema, "url": it.url, "usuario": it.usuario,
        "senha_mascarada": _cofre_mask(clear), "tem_senha": bool(it.senha_encrypted),
        "automation_key": it.automation_key, "categoria": it.categoria,
        "observacao": it.observacao,
        "updated_at": it.updated_at.isoformat() if it.updated_at else None,
    }


@router.get("/cofre")
async def list_cofre(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:cofre:read")),
):
    rows = (await db.execute(
        select(CofreSenha).order_by(CofreSenha.categoria, CofreSenha.sistema))).scalars().all()
    return [await _cofre_out(db, i) for i in rows]


@router.post("/cofre")
async def create_cofre(
    body: CofreIn, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:cofre:write")),
):
    sistema = (body.sistema or "").strip()
    if not sistema:
        raise HTTPException(status_code=400, detail="sistema obrigatorio")
    mun_id = await _mun_id_by_ibge(db, body.municipio_ibge)
    if body.municipio_ibge and mun_id is None:
        raise HTTPException(status_code=400, detail="municipio (ibge) nao encontrado")
    it = CofreSenha(
        municipio_id=mun_id, sistema=sistema, url=body.url, usuario=body.usuario,
        senha_encrypted=crypto.encrypt(body.senha) if body.senha else None,
        automation_key=(body.automation_key or None), categoria=body.categoria,
        observacao=body.observacao,
    )
    db.add(it)
    await db.commit()
    await db.refresh(it)
    await log_event(db, action="control.cofre.create", request=request,
                    target_type="cofre_senha", target_id=it.id,
                    details={"sistema": sistema, "token": p.name})
    return await _cofre_out(db, it)


@router.patch("/cofre/{item_id}")
async def patch_cofre(
    item_id: int, body: CofrePatch, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:cofre:write")),
):
    it = await db.get(CofreSenha, item_id)
    if not it:
        raise HTTPException(status_code=404, detail="entrada nao encontrada")
    fields = body.model_dump(exclude_unset=True)
    if "municipio_ibge" in fields:
        ibge = fields.pop("municipio_ibge")
        mid = await _mun_id_by_ibge(db, ibge) if ibge else None
        if ibge and mid is None:   # nao rebaixa p/ escopo geral por typo de IBGE
            raise HTTPException(status_code=400, detail="municipio (ibge) nao encontrado")
        it.municipio_id = mid
    if "senha" in fields:                       # so re-cifra se veio senha
        senha = fields.pop("senha")
        it.senha_encrypted = crypto.encrypt(senha) if senha else None
    for k, v in fields.items():
        setattr(it, k, v)
    await db.commit()
    await db.refresh(it)
    await log_event(db, action="control.cofre.patch", request=request,
                    target_type="cofre_senha", target_id=it.id,
                    details={"sistema": it.sistema, "token": p.name})
    return await _cofre_out(db, it)


@router.get("/cofre/{item_id}/reveal")
async def reveal_cofre(
    item_id: int, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:cofre:read")),
):
    it = await db.get(CofreSenha, item_id)
    if not it:
        raise HTTPException(status_code=404, detail="entrada nao encontrada")
    await log_event(db, action="control.cofre.reveal", request=request,
                    target_type="cofre_senha", target_id=it.id,
                    details={"sistema": it.sistema, "token": p.name})
    return {"senha": crypto.decrypt(it.senha_encrypted) if it.senha_encrypted else ""}


@router.delete("/cofre/{item_id}")
async def delete_cofre(
    item_id: int, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:cofre:write")),
):
    it = await db.get(CofreSenha, item_id)
    if not it:
        raise HTTPException(status_code=404, detail="entrada nao encontrada")
    sistema = it.sistema
    await db.delete(it)
    await db.commit()
    await log_event(db, action="control.cofre.delete", request=request,
                    target_type="cofre_senha", target_id=item_id,
                    details={"sistema": sistema, "token": p.name})
    return {"status": "deleted"}


# --- Sessao gov.br + token da extensao de captura ---
@router.get("/session/status")
async def control_session_status(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:session:read")),
):
    """Status REAL da sessao gov.br capturada (do Cofre): valida/expirada + minutos
    restantes (decodifica o exp do JWT user-id). Insumo p/ FNS/TransfereGov. A captura
    em si e manual (extensao) — o Console so monitora."""
    row = (await db.execute(text("""
        SELECT id, municipio_id, updated_at, observacao, senha_hash
        FROM cofre_senhas
        WHERE automation_key='govbr' AND length(senha_hash) > 1000
        ORDER BY updated_at DESC LIMIT 1
    """))).first()
    if not row:
        return {"has_session": False, "message": "Nenhuma sessao gov.br capturada"}
    age_h = (datetime.now(timezone.utc) - row[2]).total_seconds() / 3600 if row[2] else None
    base: dict = {"has_session": True, "municipio_id": row[1],
                  "updated_at": row[2].isoformat() if row[2] else None,
                  "age_hours": round(age_h, 2) if age_h is not None else None,
                  "observacao": row[3]}
    try:
        data = _json.loads(crypto.decrypt(row[4]) or "")
        uid = next((c for c in data.get("cookies", []) if c.get("name") == "user-id"), None)
        if uid:
            parts = (uid.get("value") or "").split(".")
            if len(parts) >= 2:
                pb = parts[1] + "=" * (-len(parts[1]) % 4)
                payload = _json.loads(base64.urlsafe_b64decode(pb))
                exp_ts = payload.get("exp")
                if exp_ts:
                    mins = (exp_ts - datetime.now(timezone.utc).timestamp()) / 60
                    base["exp_minutes"] = round(mins, 1)
                    base["expired"] = mins <= 0
                    base["expira_em"] = datetime.fromtimestamp(exp_ts, tz=timezone.utc).isoformat()
                    return base
    except Exception as e:
        base["decode_error"] = str(e)[:80]
    base["expired"] = (age_h or 1) > 0.33   # fallback pela idade da captura (~20min)
    return base


@router.post("/session/token")
async def control_session_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:session:write")),
):
    """Emite (ou rotaciona) o service token da EXTENSAO de captura (scope session:write,
    kind scraper). Mostrado UMA vez; o operador configura na extensao do navegador."""
    name = "extensao-captura"
    raw = "pactha_st_" + pysecrets.token_urlsafe(40)
    existing = (await db.execute(
        select(ServiceToken).where(ServiceToken.name == name))).scalar_one_or_none()
    if existing:
        existing.token_hash = hash_token(raw)
        existing.token_prefix = raw[:12]
        existing.scopes = ["session:write"]
        existing.kind = "scraper"
        existing.active = True
        existing.last_used_at = None
        existing.last_used_ip = None
        tok, action = existing, "control.session_token.rotate"
    else:
        tok = ServiceToken(name=name, token_hash=hash_token(raw), token_prefix=raw[:12],
                           scopes=["session:write"], kind="scraper", active=True)
        db.add(tok)
        action = "control.session_token.create"
    await db.commit()
    await db.refresh(tok)
    await log_event(db, action=action, request=request, target_type="service_token",
                    target_id=tok.id, details={"name": name, "token": p.name})
    return {"token": raw, "name": name, "scopes": ["session:write"], "prefix": tok.token_prefix,
            "warning": "Anote agora — nao sera mostrado de novo. Configure na extensao de captura."}


# --- SSO tecnico: a Central pede uma sessao de suporte p/ um tecnico Alavank ---
class SsoIn(BaseModel):
    tech_email: str
    tech_name: str | None = None


@router.post("/sso")
async def control_sso(
    body: SsoIn, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:sso:write")),
):
    """Cria/atualiza um usuario de SUPORTE (Alavank) e devolve um token de uso unico
    (2 min) que o aceitador /api/auth/sso-login troca por uma sessao. A senha do
    tecnico nunca sai da Central — o usuario local so serve p/ carregar a sessao."""
    email = (body.tech_email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="email invalido")
    # Email NAMESPACED: nunca colide com um usuario real do tenant. Antes, casar pelo
    # email cru permitia sequestrar (e reativar) a conta de um usuario legitimo que
    # tivesse o mesmo email. O prefixo "alavank-sso." garante identidade de suporte
    # separada e estavel (o mesmo tecnico reusa sempre o mesmo usuario de suporte).
    local, _, domain = email.partition("@")
    support_email = f"alavank-sso.{local}@{domain}"
    u = (await db.execute(select(User).where(User.email == support_email))).scalar_one_or_none()
    if u is None:
        u = User(email=support_email, name=("[Suporte Alavank] " + (body.tech_name or email))[:200],
                 password_hash=hash_password(pysecrets.token_urlsafe(24)),
                 role="admin", active=True, must_change_password=False)
        db.add(u)
        await db.commit()
        await db.refresh(u)
    elif not u.active:
        u.active = True
        await db.commit()
    token = create_sso_token(u.id)
    await log_event(db, action="control.sso.mint", request=request,
                    target_type="user", target_id=email,
                    details={"tech": email, "token": p.name})
    return {"sso_token": token, "path": "/api/auth/sso-login"}


# --- Usuarios do cliente (users do tenant), geridos pela Central via canal ---
class ControlUserIn(BaseModel):
    email: str
    name: str
    role: str = "analyst"                  # default analyst (nao admin/"deus")
    telas: list[str] | None = None         # keys de telas/modulos
    municipios: list[str] | None = None    # ibge_codes do escopo


class ControlUserPatch(BaseModel):
    name: str | None = None
    role: str | None = None
    active: bool | None = None
    telas: list[str] | None = None
    municipios: list[str] | None = None


async def _user_out(db, u: User) -> dict:
    return {
        "email": u.email, "name": u.name, "role": u.role, "active": bool(u.active),
        "must_change_password": bool(u.must_change_password),
        "telas": await users_admin.get_user_telas(db, u.id),
        "municipios": await users_admin.get_user_ibges(db, u.id),
    }


async def _active_admin_count(db) -> int:
    return (await db.execute(text(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = true"))).scalar() or 0


@router.get("/telas-catalog")
async def telas_catalog(p: ControlPrincipal = Depends(require_control_scope("control:users:read"))):
    return {"telas": TELAS_CATALOG}


@router.get("/users")
async def list_control_users(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:users:read")),
):
    rows = (await db.execute(select(User).order_by(User.name))).scalars().all()
    return [await _user_out(db, u) for u in rows]


@router.post("/users")
async def create_control_user(
    body: ControlUserIn, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:users:write")),
):
    email = (body.email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Email invalido")
    if body.role not in users_admin.ROLES:
        raise HTTPException(status_code=400, detail="Role invalida (admin|analyst|user)")
    dup = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=400, detail="Email ja cadastrado")
    senha = users_admin.gen_senha()
    u = User(email=email, name=(body.name or "").strip(), password_hash=hash_password(senha),
             role=body.role, active=True, must_change_password=True)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    if body.telas is not None:
        await users_admin.set_user_telas(db, u.id, body.telas)
    if body.municipios is not None:
        await users_admin.set_user_municipios_by_ibge(db, u.id, body.municipios)
    await db.commit()
    await log_event(db, action="control.user.create", request=request,
                    target_type="user", target_id=email,
                    details={"role": body.role, "token": p.name})
    out = await _user_out(db, u)
    out["senha_temporaria"] = senha
    return out


@router.patch("/users/{email}")
async def patch_control_user(
    email: str, body: ControlUserPatch, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:users:write")),
):
    u = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    if body.role is not None and body.role not in users_admin.ROLES:
        raise HTTPException(status_code=400, detail="Role invalida")
    # Nao deixar o cliente sem NENHUM admin
    demoting = body.role is not None and body.role != "admin" and u.role == "admin"
    deactivating = body.active is False and u.active and u.role == "admin"
    if (demoting or deactivating) and await _active_admin_count(db) <= 1:
        raise HTTPException(status_code=409, detail="Nao e possivel deixar o cliente sem administrador")

    if body.name is not None:
        u.name = body.name.strip()
    if body.role is not None:
        u.role = body.role
    if body.active is not None:
        u.active = body.active
    if body.telas is not None:
        await users_admin.set_user_telas(db, u.id, body.telas)
    if body.municipios is not None:
        await users_admin.set_user_municipios_by_ibge(db, u.id, body.municipios)
    await db.commit()
    await db.refresh(u)
    await log_event(db, action="control.user.patch", request=request,
                    target_type="user", target_id=email, details={"token": p.name})
    return await _user_out(db, u)


@router.post("/users/{email}/reset-password")
async def reset_control_user_password(
    email: str, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:users:write")),
):
    u = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    senha = users_admin.gen_senha()
    u.password_hash = hash_password(senha)
    u.must_change_password = True
    await db.commit()
    await log_event(db, action="control.user.reset_password", request=request,
                    target_type="user", target_id=email, details={"token": p.name})
    return {"email": u.email, "senha_temporaria": senha}
