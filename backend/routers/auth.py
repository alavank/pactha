import time
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from database import get_db
from models.user import User
from schemas.auth import (
    LoginRequest, LoginResponse, UserResponse,
    RegisterRequest, ChangePasswordRequest,
)
from services.auth import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, generate_csrf_token,
    decode_refresh, revoke_jti, decode_sso,
    set_auth_cookies, clear_auth_cookies, decode_access,
    get_current_user, COOKIE_NAME_REFRESH, COOKIE_NAME_ACCESS,
    load_user_scopes,
)
from services.audit import registrar
from services.registro_rotas import exige

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_resp(user) -> UserResponse:
    """UserResponse com escopos (telas/municipios). None = acesso total.

    `de_usuario` e nao `model_validate`: as flags `super_admin`/`somente_leitura`
    saem CALCULADAS (coluna + reforco do codigo), do mesmo jeito que em
    `GET /users`. Ler a coluna crua aqui faria a sidebar discordar do backend.
    """
    resp = UserResponse.de_usuario(user)
    at = getattr(user, "allowed_telas", None)
    am = getattr(user, "allowed_municipio_ids", None)
    resp.telas = None if at is None else sorted(at)
    resp.municipio_ids = None if am is None else sorted(am)
    return resp

# Rate limit in-memory: 5 tentativas/(IP+email)/60s
_LOGIN_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
_RATE_WINDOW = 60.0
_RATE_MAX = 5


def _rate_limit_check(key: str):
    now = time.time()
    arr = [t for t in _LOGIN_ATTEMPTS[key] if now - t < _RATE_WINDOW]
    if len(arr) >= _RATE_MAX:
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde 1 minuto.")
    arr.append(now)
    _LOGIN_ATTEMPTS[key] = arr


@router.get("/sso-login")
async def sso_login(t: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Aceitador do SSO da Central: valida o token de uso único (2 min) mintado pelo
    canal de controle e abre uma sessão de SUPORTE (marcada nos logs). Nunca expõe senha."""
    try:
        payload = decode_sso(t)
    except HTTPException:
        return RedirectResponse(url="/login?sso=invalido", status_code=302)
    # Uso único REAL: grava o jti; a UNIQUE do Postgres impede replay mesmo entre
    # workers (o revoke_jti in-memory nao era compartilhado -> permitia replay).
    jti = payload.get("jti", "")
    try:
        await db.execute(text("INSERT INTO sso_used_jti (jti) VALUES (:j)"), {"j": jti})
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return RedirectResponse(url="/login?sso=usado", status_code=302)
    revoke_jti(jti)   # camada extra (best-effort, mesmo worker)
    u = await db.get(User, int(payload.get("sub", 0) or 0))
    if not u or not u.active:
        return RedirectResponse(url="/login?sso=invalido", status_code=302)
    access = create_access_token({"sub": u.id, "role": u.role})
    refresh = create_refresh_token(u.id)
    csrf = generate_csrf_token()
    resp = RedirectResponse(url="/dashboard", status_code=302)
    set_auth_cookies(resp, access, refresh, csrf)
    u.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await registrar(db, action="sso.login", user=u, request=request,
                    target_type="user", target_id=u.email, details={"via": "console-sso"})
    return resp


@router.post("/login", response_model=LoginResponse)
async def login(
    req: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    ip = request.client.host if request.client else "?"
    _rate_limit_check(f"{ip}:{req.email}")

    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        await registrar(
            db, action="login.fail", request=request,
            # O e-mail TENTADO vai no campo indexado `user_email`, nao so em
            # `details`. Tentativa de invasao chega como "tentaram entrar na conta
            # do fulano" e a busca natural e por e-mail; enquanto isso ficou so
            # dentro do JSONB, o filtro nao achava nada e a trilha jurava que
            # ninguem tinha tentado. Nao ha `user=` aqui de proposito: em ataque
            # o e-mail costuma nem existir, entao user_id continua nulo.
            user_email=(req.email or "").strip().lower()[:255],
            details={
                "email_tentado": req.email,
                # Distinguir os dois casos e o que separa "usuario errou a senha"
                # de "alguem esta varrendo e-mails". Fica so na trilha interna —
                # a resposta ao cliente continua generica ("Email ou senha
                # incorretos"), para nao virar oraculo de contas existentes.
                "motivo": "senha incorreta" if user else "usuário inexistente",
            },
            commit=True,
        )
        raise HTTPException(status_code=401, detail="Email ou senha incorretos")
    if not user.active:
        await registrar(db, action="login.disabled_user", user=user, request=request)
        raise HTTPException(status_code=403, detail="Usuário desativado")

    # Atualiza last_login
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    access = create_access_token({"sub": user.id, "role": user.role})
    refresh = create_refresh_token(user.id)
    csrf = generate_csrf_token()
    set_auth_cookies(response, access, refresh, csrf)

    await registrar(db, action="login.success", user=user, request=request)

    await load_user_scopes(db, user)
    return LoginResponse(
        access_token=access,
        must_change_password=bool(user.must_change_password),
        user=_user_resp(user),
    )


@router.post("/refresh")
async def refresh_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Rota refresh - le refresh_token do cookie, emite novo access."""
    rt = request.cookies.get(COOKIE_NAME_REFRESH)
    if not rt:
        raise HTTPException(status_code=401, detail="Refresh token ausente")

    payload = decode_refresh(rt)
    user_id = int(payload["sub"])
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="Usuário inválido")

    # rotate: revoga refresh antigo + emite novos
    revoke_jti(payload["jti"])
    new_access = create_access_token({"sub": user.id, "role": user.role})
    new_refresh = create_refresh_token(user.id)
    csrf = generate_csrf_token()
    set_auth_cookies(response, new_access, new_refresh, csrf)

    return {"access_token": new_access}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Revoga tokens atuais e limpa cookies."""
    # Revoga access
    access = request.cookies.get(COOKIE_NAME_ACCESS) or (
        request.headers.get("Authorization", "").replace("Bearer ", "") or None
    )
    if access:
        try:
            p = decode_access(access)
            revoke_jti(p["jti"])
        except Exception:
            pass
    # Revoga refresh
    refresh = request.cookies.get(COOKIE_NAME_REFRESH)
    if refresh:
        try:
            p = decode_refresh(refresh)
            revoke_jti(p["jti"])
        except Exception:
            pass

    clear_auth_cookies(response)
    await registrar(db, action="logout", user=user, request=request)
    return {"status": "ok"}


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return _user_resp(user)


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Permite o usuario trocar a propria senha. Usado tambem no 1o login forcado."""
    if not verify_password(req.current_password, user.password_hash):
        await registrar(db, action="user.password_change.fail", user=user, request=request)
        raise HTTPException(status_code=401, detail="Senha atual incorreta")

    # Politicas minimas
    if req.new_password == req.current_password:
        raise HTTPException(status_code=400, detail="Nova senha deve ser diferente da atual")
    if len(req.new_password) < 10:
        raise HTTPException(status_code=400, detail="Senha deve ter no mínimo 10 caracteres")

    user.password_hash = hash_password(req.new_password)
    user.must_change_password = False
    await db.commit()
    await registrar(db, action="user.password_change.success", user=user, request=request)
    return {"status": "ok"}


# ⚠️ A UNICA rota de /api/auth/* que NAO e rota de sessao. Todas as outras
# (login, refresh, logout, me, change-password) tratam da sessao de quem ja
# chegou e estao em ROTAS_LIVRES, uma a uma; esta CRIA GENTE, entao vale a mesma
# permissao de `POST /api/users`. Uma entrada `/api/auth/*` na allowlist teria
# levado o cadastro de usuarios junto sem ninguem perceber.
@router.post("/register", response_model=UserResponse,
             dependencies=[exige("usuarios.criar")])
async def register(
    req: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Apenas admins podem registrar usuários")

    # Normaliza o email (case/espacos): sem isso "Admin@Pactha.com.br" nao colide
    # com a conta principal e cria uma segunda conta que se passa por ela.
    # Mesmo tratamento que create_user (routers/users.py) ja faz.
    email = (req.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Email inválido")
    if req.role not in ("admin", "usuario", "analyst", "user"):
        raise HTTPException(status_code=400, detail="Role inválida")

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email já cadastrado")

    user = User(
        email=email,
        name=req.name,
        password_hash=hash_password(req.password),
        role=req.role,
        must_change_password=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await registrar(
        db, action="user.create", user=current_user, request=request,
        target_type="user", target_id=user.id,
        details={"new_email": email, "role": req.role},
    )
    return UserResponse.de_usuario(user)
