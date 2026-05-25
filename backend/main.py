import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import (
    auth, municipios, convenios, cofre, service_tokens,
    session_capture, emendas_estaduais, dou_mg, fns, transferegov, export_pdf,
    users,
)
from services.security_headers import SecurityHeadersMiddleware
from services.startup import run_migrations

# force=True: uvicorn ja configurou o root logger, basicConfig sem force seria no-op
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    force=True,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Roda migrations idempotentes no boot (ANTES das rotas atenderem).
    Garante que seed institucional + tabelas estao sempre atualizadas.

    Tambem aquece o pool asyncpg pra evitar primeira request travada
    (cold start no Railway gerava 'email ou senha incorretos' fantasma
    porque o connect demorava mais que o timeout do frontend)."""
    # print() para garantir que aparece nos logs do Railway mesmo se logging falhar
    print("=== PACTA boot - rodando migrations ===", flush=True)
    logging.getLogger("startup").warning("=== PACTA boot - rodando migrations ===")
    try:
        run_migrations()
    except Exception as e:
        print(f"[STARTUP] run_migrations falhou: {e}", flush=True)
    # Warmup do pool asyncpg: faz SELECT 1 ANTES de yield pra primeira request
    # nao pagar o custo de criar conexao.
    try:
        from database import engine
        from sqlalchemy import text
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        print("[STARTUP] DB pool warmup OK", flush=True)
    except Exception as e:
        print(f"[STARTUP] DB pool warmup falhou: {e}", flush=True)
    yield


app = FastAPI(
    title="PACTA API",
    description="Sistema de Monitoramento de Convenios e Transferencias Governamentais",
    version="1.0.0",
    redirect_slashes=False,
    lifespan=lifespan,
)

# CORS: localhost + production frontend URL (whitelist explicita)
allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
# FRONTEND_URL: domain principal (railway, custom). Pode ser CSV.
frontend_urls = os.getenv("FRONTEND_URL", "")
for url in frontend_urls.split(","):
    url = url.strip()
    if url:
        allowed_origins.append(url)

# Regex restrito: apenas domains do projeto PACTA (railway/custom)
allow_regex = os.getenv("CORS_ORIGIN_REGEX") or r"^https://(pacta|.*\.pacta).*\.(up\.railway\.app|railway\.app)$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=allow_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-CSRF-Token"],
)
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(auth.router)
app.include_router(municipios.router)
app.include_router(convenios.router)
app.include_router(emendas_estaduais.router)
app.include_router(fns.router)
app.include_router(dou_mg.router)
app.include_router(cofre.router)
app.include_router(session_capture.router)
app.include_router(service_tokens.router)
app.include_router(transferegov.router)
app.include_router(export_pdf.router)
app.include_router(users.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "PACTA API"}
