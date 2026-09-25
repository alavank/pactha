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
    session_capture, emendas_estaduais, dou_mg, dou_es, dou_go, dou_to, dou_rs,
    dou_federal, fns, transferegov, emendas_federais, emendas_parlamentares, export_pdf,
    users, simec, rm, ai, gestao, parlamentares, status_changes,
    documentos, cauc, cagec, siconfi, negativos, acordofes, control, freshness, painel, bi,
    sismob, obrasgov, parcerias, faf_planos, investsus, auditoria, permissoes,
    repasses,
    contas_irregulares,
    cofinanciamento, parametros, monitoramento, consulta_popular, programas_rs,
    conteudo_rs, programas_captacao, agendamentos,
    uso, mcp_tokens, consolidado, tce_pr, cgu_convenios, cgu_transferencias,
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
    (cold start do container gerava 'email ou senha incorretos' fantasma
    porque o connect demorava mais que o timeout do frontend)."""
    # print() para garantir que aparece nos logs do Coolify mesmo se logging falhar
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

    # ⭐ Servidor MCP (Streamable HTTP). O app montado NÃO tem seu lifespan rodado
    # pelo pai automaticamente; sem isto o gerenciador de sessão do transporte não
    # sobe e toda chamada MCP trava/500. Rodamos o lifespan dele AQUI, em volta do
    # yield, para viver o mesmo tempo que a API. `registro_rotas` acima ignora o
    # Mount (só enxerga APIRoute), então a montagem não passa pelo portão de
    # permissão — o /api/mcp autentica pelo próprio token (services/mcp_auth.py).
    from mcp_app import mcp_starlette
    async with mcp_starlette.router.lifespan_context(mcp_starlette):
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
app.include_router(dou_rs.router)
# DOU federal: COLETADO (ingestion/dou_federal.py), nao busca em tempo real como
# os diarios estaduais acima — os atos que citam cada municipio da carteira.
app.include_router(dou_federal.router)
app.include_router(repasses.router)
app.include_router(contas_irregulares.router)
app.include_router(cofinanciamento.router)
# Monitoramento mensal de convenios (Decreto RS 56.939/2023) — gate `convenios.ver`
app.include_router(monitoramento.router)
# Consulta Popular / COREDEs (RS) — a porta de entrada do convenio estadual gaucho
app.include_router(consulta_popular.router)
# Catalogo dos programas estaduais gauchos — conteudo curado, sem coleta
app.include_router(programas_rs.router)
# RADAR DE CAPTACAO — a unica tela federal que olha para FRENTE (prazo aberto).
# Gate `convenios.ver`: e o funil de onde nasce o convenio, mesma razao da
# Consulta Popular. Nao cria concessao nova.
app.include_router(programas_captacao.router)
# FUNRIGS, emendas estaduais e TCE-RS — conteudo curado onde a coleta nao alcanca
app.include_router(conteudo_rs.router)
# /api/pr/tce: o que o municipio do PR declarou ao TCE (SIM-AM), pelo PIT —
# dado coletado por `ingestion/tce_pr.py`, nao curadoria.
app.include_router(tce_pr.router)
# /api/cgu-convenios: o dinheiro federal fora do TransfereGov (Defesa Civil),
# pela planilha da CGU — `ingestion/cgu_convenios.py`.
app.include_router(cgu_convenios.router)
# /api/cgu-transferencias: os recursos recebidos por pasta (FPM, FUNDEB, fundo a
# fundo...), mês a mês — `ingestion/cgu_transferencias.py`.
app.include_router(cgu_transferencias.router)
app.include_router(cofre.router)
app.include_router(session_capture.router)
app.include_router(service_tokens.router)
app.include_router(transferegov.router)
# Emendas parlamentares FEDERAIS — a nona tela do grupo FEDERAIS (06/09/2026).
# Fica junto do transferegov de proposito: as duas sao do mesmo grupo do menu
# e a emenda federal aparecia ate aqui embutida nas telas dele.
app.include_router(emendas_federais.router)
# Emendas parlamentares numa tela so (17/09/2026): Federais | Estaduais |
# Parlamentares. Cada aba cobra a chave que ja existia — nao ha tela nova no
# catalogo. Ver o cabecalho de routers/emendas_parlamentares.py.
app.include_router(emendas_parlamentares.router)
app.include_router(export_pdf.router)
app.include_router(users.router)
app.include_router(simec.router)
app.include_router(rm.router)
app.include_router(ai.router)
app.include_router(gestao.router)
# AGENDAMENTOS — a agenda de trabalho da equipe. Fica ao lado da Gestao Interna
# porque sao os dois unicos modulos em que a equipe ESCREVE; todo o resto do
# sistema mostra dado que veio de fora.
app.include_router(agendamentos.router)
app.include_router(parlamentares.router)
# CONSOLIDADO (18/09/2026): a carteira inteira lado a lado, com escopo pelo
# `resolve_scope` e permissao propria. Nao depende do BI_MODULE: so reusa
# `services/bi.py`, que nao e gateado.
app.include_router(consolidado.router)
# TELEGRAM REMOVIDO em 05/09/2026 (decisão do dono). Ficou desativado atrás de
# `TELEGRAM_MODULE` desde 09/08/2026 e a flag nunca foi ligada em tenant nenhum;
# o canal de avisos será WhatsApp com a API oficial da Meta, e quando existir
# nasce com router e permissões próprias.
# A lição do #168 fica escrita, porque vale para QUALQUER módulo atrás de flag:
# o import também precisa ficar atrás dela, não só o `include_router` — o
# decorator das rotas chama `exige(...)` NO IMPORT, e o `exige()` valida
# fail-closed contra o catálogo. Importar um router cuja chave não está no
# catálogo DERRUBA O BOOT da API inteira.
app.include_router(status_changes.router)
app.include_router(documentos.router)
app.include_router(cauc.router)
app.include_router(cagec.router)
# Terceira coluna da MESMA tela de regularidade (chave `cauc.ver`,
# tela `cauc`): contas entregues ao Tesouro e nota CAPAG.
app.include_router(siconfi.router)
# QUARTA coluna da mesma tela: os cadastros NEGATIVOS (CADIN-MG, CADIN/RS,
# CFIL/RS). Pergunta diferente das outras tres — nao "esta em dia?", e sim
# "existe pendencia inscrita contra ele?" —, e que trava sozinha: a unica
# inscricao real da carteira em 07/09/2026 era de um fundo municipal que nem
# cadastro estadual tem.
app.include_router(negativos.router)
app.include_router(sismob.router)   # /api/sismob/* (obras de saude do MS)
# /api/obrasgov/* (CIPI): as obras federais de TODAS as areas — o que o SISMOB
# (saude) e o SIMEC (educacao) nao cobrem. Repete de proposito a obra que ja
# aparece naquelas duas; ver o cabecalho do router.
app.include_router(obrasgov.router)
# /api/parcerias/*: a Gestao de Parcerias do Transferegov, onde as
# transferencias passaram a ser processadas de 2024 em diante — e onde mora a
# emenda de saude do municipio. NAO substitui as Voluntarias: aquela mostra o
# convenio discricionario do SICONV, que segue vindo dos dumps CSV.
app.include_router(parcerias.router)
# /api/faf-planos/*: o PLANO DE ACAO por tras do repasse fundo a fundo. O
# ConsultaFNS (`fns`) ja conta o dinheiro que entra; so aqui se sabe QUANTO
# daquele repasse veio de emenda, e o que o municipio se comprometeu a fazer
# com ele. E nao e so saude: os 4 planos de Nova Palma sao do MinC.
app.include_router(faf_planos.router)
app.include_router(investsus.router)  # /api/investsus/* (repasses fundo a fundo)
app.include_router(acordofes.router)
app.include_router(control.router)  # /api/control/* (Console Alavank)
app.include_router(auditoria.router)  # /api/auditoria/* (trilha, so leitura)
app.include_router(uso.router)
app.include_router(permissoes.router)  # /api/permissoes/* (catalogo de permissoes)
app.include_router(parametros.router)  # /api/parametros/* (listas do proprio cliente)
# ⚠️ `modelos_permissao.router` (/api/permissoes/modelos/*) SAIU em 05/09/2026
# com o subsistema de moldes. Ver a nota no topo de `routers/permissoes.py`.
app.include_router(freshness.router)  # /api/admin/freshness (monitor de frescor)
# Servidor MCP de LEITURA (Claude/ChatGPT). Duas peças: o router administra os
# tokens (por usuário), e o transporte Streamable HTTP é montado como sub-app
# ASGI — seu lifespan roda no `lifespan()` acima. Ver mcp_app.py / services/mcp_auth.py.
app.include_router(mcp_tokens.router)   # /api/mcp-tokens/* (gerência de tokens)
from mcp_app import mcp_asgi            # noqa: E402  (mount precisa do app pronto)
app.mount("/api/mcp", mcp_asgi)         # /api/mcp — gate de Bearer + Streamable HTTP
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
