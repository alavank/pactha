import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import auth, municipios, convenios, editais, prestacao, politica, export, cofre

app = FastAPI(
    title="PACTA API",
    description="Sistema de Monitoramento de Convenios e Transferencias Governamentais",
    version="1.0.0",
    redirect_slashes=False,
)

# CORS: localhost + production frontend URL
allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
frontend_url = os.getenv("FRONTEND_URL")
if frontend_url:
    allowed_origins.append(frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(municipios.router)
app.include_router(convenios.router)
app.include_router(editais.router)
app.include_router(prestacao.router)
app.include_router(politica.router)
app.include_router(export.router)
app.include_router(cofre.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "PACTA API"}
