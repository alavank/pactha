import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text as _sql_text
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from routers import (
    auth, municipios, convenios, cofre, service_tokens,
    session_capture, emendas_estaduais, dou_mg, dou_es, dou_go, dou_to, fns, transferegov, export_pdf,
    users, simec, rm, ai, gestao, parlamentares, status_changes,
    documentos, cauc, cagec, acordofes, control, freshness, painel, bi,
    sismob, auditoria, permissoes, modelos_permissao, repasses, contas_irregulares,
    cofinanciamento, parametros,
    uso,
)
from config import get_settings
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
    print("=== PACTHA boot - rodando migrations ===", flush=True)
    logging.getLogger("startup").warning("=== PACTHA boot - rodando migrations ===")
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
    # Retencao do historico da IA: a tela promete "apagadas apos 30 dias", entao
    # o expurgo roda no boot alem de rodar quando alguem abre o painel.
    try:
        from database import async_session
        from routers.ai import _expurgar_antigas
        async with async_session() as _s:
            n = await _expurgar_antigas(_s, forcar=True)
        print(f"[STARTUP] expurgo do historico da IA: {n} conversa(s)", flush=True)
    except Exception as e:
        print(f"[STARTUP] expurgo do historico da IA falhou: {e}", flush=True)

    # ⭐ O REGISTRO QUE FALHA FECHADO (Incremento 5). Varre `app.routes` e
    # compara com (1) as rotas que declararam permissao via `exige(...)` e (2) a
    # allowlist explicita de rotas publicas/auto-escopadas. O que nao esta em
    # nenhuma das duas e PENDENTE.
    #
    # ⚠️ SEM try/except, e e a linha mais deliberada deste arquivo. Em modo
    # ESTRITO (desenvolvimento) a excecao TEM de subir e derrubar o boot — e o
    # unico momento em que "esqueci de declarar permissao" custa uma linha em vez
    # de custar um endpoint aberto por seis meses. Envolver isto no try/except
    # generoso das linhas acima transformaria o registro inteiro em decoracao.
    #
    # Em producao o modo e `bloqueio`: sobe, registra CRITICO e devolve 403 so
    # NAQUELA rota — derrubar a API de uma prefeitura por uma rota nova esquecida
    # e trocar um risco por um dano garantido. Ver services/registro_rotas.py.
    from services.registro_rotas import aplicar as aplicar_registro
    aplicar_registro(app)

    yield


app = FastAPI(
    title="PACTHA API",
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
# FRONTEND_URL: domain principal (Coolify/custom). Pode ser CSV.
frontend_urls = os.getenv("FRONTEND_URL", "")
for url in frontend_urls.split(","):
    url = url.strip()
    if url:
        allowed_origins.append(url)

# Regex opcional p/ dominios extras (ex.: previews). Sem fallback: em producao o
# FRONTEND_URL cobre o dominio, e no deploy subpath (front + API no MESMO host) o
# CORS e inocuo por ser same-origin.
allow_regex = os.getenv("CORS_ORIGIN_REGEX") or None

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=allow_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    # X-Service-Token: header proprio da API (services/service_auth.py), usado pela
    # extensao de captura de sessao. Sem ele na lista, o preflight do navegador
    # falha e o POST nunca sai — o erro aparece como "Failed to fetch" no cliente
    # e NADA e registrado no servidor, o que torna o diagnostico bem dificil.
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-CSRF-Token",
                   "X-Service-Token"],
    # Cabecalhos que o JAVASCRIPT precisa LER na resposta. Por padrao o navegador
    # entrega ao script so um punhado de cabecalhos simples e esconde o resto —
    # mesmo estando todos na resposta. Sem esta lista, num deploy em que o front
    # fale com a API em outra origem, a exportacao da auditoria baixa com nome
    # generico (Content-Disposition invisivel) e, pior, o aviso de recorte
    # TRUNCADO (X-Auditoria-Truncado) nunca aparece: o usuario recebe um CSV
    # cortado achando que e a trilha inteira.
    expose_headers=["Content-Disposition", "X-Auditoria-Linhas", "X-Auditoria-Truncado"],
)
app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(Exception)
async def _erro_nao_tratado(request, exc):
    """Sem isto, uma excecao nao tratada vira `Internal Server Error` em TEXTO
    PURO (default do Starlette). O frontend le `data.detail`, acha `undefined` e
    mostra so "HTTP 500" — indistinguivel do 500 do proxy do Next, e sem pista
    nenhuma pra quem for depurar. Aqui devolvemos JSON com detail + uma
    referencia curta que tambem vai pro log da API."""
    import logging as _logging
    import uuid as _uuid
    from fastapi.responses import JSONResponse
    ref = _uuid.uuid4().hex[:8]
    _logging.getLogger("pactha").exception(
        "Erro nao tratado [%s] em %s %s", ref, request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Erro interno ({type(exc).__name__}). Referencia: {ref}"},
    )


app.include_router(auth.router)
app.include_router(municipios.router)
app.include_router(convenios.router)
app.include_router(emendas_estaduais.router)
app.include_router(fns.router)
app.include_router(dou_mg.router)
app.include_router(dou_es.router)
app.include_router(dou_go.router)
app.include_router(dou_to.router)
app.include_router(repasses.router)
app.include_router(contas_irregulares.router)
app.include_router(cofinanciamento.router)
app.include_router(cofre.router)
app.include_router(session_capture.router)
app.include_router(service_tokens.router)
app.include_router(transferegov.router)
app.include_router(export_pdf.router)
app.include_router(users.router)
app.include_router(simec.router)
app.include_router(rm.router)
app.include_router(ai.router)
app.include_router(gestao.router)
app.include_router(parlamentares.router)
# TELEGRAM DESATIVADO ATÉ SEGUNDA ORDEM (decisão do dono, 09/08/2026): o canal
# de avisos será WhatsApp com API oficial; Telegram só sob demanda rara. Sem a
# flag, as rotas nem existem (404 — webhook incluso) e o catálogo de permissões
# não oferece as chaves (services/permissoes.py). Religar = TELEGRAM_MODULE=1
# aqui + NEXT_PUBLIC_TELEGRAM_MODULE=1 no build do frontend.
# ⚠️ O IMPORT também fica atrás da flag — não só o include_router. O decorator
# das rotas chama exige("telegram.vincular") NO IMPORT, e o exige() valida
# fail-closed contra o catálogo (que sem a flag não tem as chaves): importar
# com o módulo desligado DERRUBA O BOOT da API inteira. Foi exatamente o que
# aconteceu no 1º deploy do #168 — o guardião de rotas fez o papel dele e o
# rolling deploy segurou a versão antiga; que este comentário poupe o próximo.
if os.getenv("TELEGRAM_MODULE") == "1":
    from routers import telegram
    app.include_router(telegram.router)
app.include_router(status_changes.router)
app.include_router(documentos.router)
app.include_router(cauc.router)
app.include_router(cagec.router)
app.include_router(sismob.router)   # /api/sismob/* (obras de saude do MS)
app.include_router(acordofes.router)
app.include_router(control.router)  # /api/control/* (Console Alavank)
app.include_router(auditoria.router)  # /api/auditoria/* (trilha, so leitura)
app.include_router(uso.router)
app.include_router(permissoes.router)  # /api/permissoes/* (catalogo de permissoes)
app.include_router(parametros.router)  # /api/parametros/* (listas do proprio cliente)
# /api/permissoes/modelos/* — os MOLDES (Incremento 7). Registrado DEPOIS de
# `permissoes.router` so por leitura: os caminhos nao se sobrepoem (o outro
# router nao tem rota com parametro na raiz), entao a ordem nao muda nada.
app.include_router(modelos_permissao.router)
app.include_router(freshness.router)  # /api/admin/freshness (monitor de frescor)
app.include_router(painel.router)   # /api/painel/* (Painel Executivo do prefeito)
if get_settings().BI_MODULE:
    app.include_router(bi.router)   # /api/bi/* (Painel de Indicadores - BI, flag-gated)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "PACTHA API"}


@app.get("/api/status/ingestao")
async def status_ingestao(db: AsyncSession = Depends(get_db)):
    """Snapshot de populacao do banco: contagens + ingestion_log + fila scraper_jobs.
    Aberto (so agregados, sem dados sensiveis) p/ monitorar a carga inicial dos dados."""
    async def _count(tbl: str):
        try:
            r = await db.execute(_sql_text(f"SELECT count(*) FROM {tbl}"))
            return int(r.scalar() or 0)
        except Exception:
            await db.rollback()  # evita cascata: query falha aborta a transacao
            return "n/a (tabela ausente)"

    out: dict = {"counts": {}}
    for tbl in ("municipios", "users", "cofre_senhas", "convenios_estadual",
                "transferegov_propostas", "emendas_estaduais",
                "cauc_situacao", "acordofes_credor", "siconv_federal"):
        out["counts"][tbl] = await _count(tbl)
    try:
        rows = (await db.execute(_sql_text(
            "SELECT source, status, records_inserted, finished_at "
            "FROM ingestion_log ORDER BY id DESC LIMIT 25"))).fetchall()
        out["ingestion_log"] = [
            {"source": r[0], "status": r[1], "records": r[2],
             "finished_at": r[3].isoformat() if r[3] else None} for r in rows]
    except Exception as e:
        await db.rollback()
        out["ingestion_log"] = f"n/a ({str(e)[:40]})"
    try:
        rows = (await db.execute(_sql_text(
            "SELECT id, tipo, status, started_at, finished_at, error "
            "FROM scraper_jobs ORDER BY id DESC LIMIT 10"))).fetchall()
        out["scraper_jobs"] = [
            {"id": r[0], "tipo": r[1], "status": r[2],
             "started_at": r[3].isoformat() if r[3] else None,
             "finished_at": r[4].isoformat() if r[4] else None,
             "error": r[5]} for r in rows]
    except Exception as e:
        out["scraper_jobs"] = f"n/a ({str(e)[:40]})"
    return out
