import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import auth, municipios, convenios, editais, prestacao, politica, export, cofre, fontes, upload, relatorio_monitoramento, levantamento_parlamentar, internal, service_tokens, prestacao_avancada, session_capture, export_relatorios
from services.security_headers import SecurityHeadersMiddleware

app = FastAPI(
    title="PACTA API",
    description="Sistema de Monitoramento de Convenios e Transferencias Governamentais",
    version="1.0.0",
    redirect_slashes=False,
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
app.include_router(editais.router)
app.include_router(prestacao.router)
app.include_router(politica.router)
app.include_router(export.router)
app.include_router(cofre.router)
app.include_router(fontes.router)
app.include_router(upload.router)
app.include_router(relatorio_monitoramento.router)
app.include_router(levantamento_parlamentar.router)
app.include_router(internal.router)
app.include_router(service_tokens.router)
app.include_router(prestacao_avancada.router)
app.include_router(session_capture.router)
app.include_router(export_relatorios.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "PACTA API"}
