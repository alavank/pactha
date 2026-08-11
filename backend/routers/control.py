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
from services.telas_catalog import TELAS_CATALOG, TELAS_TODAS
from services.audit import registrar, registrar_critico

router = APIRouter(prefix="/api/control", tags=["control"])


# Cabecalhos com que o Console identifica a PESSOA por tras da chamada. Ficam em
# ordem de preferencia; o primeiro que parecer e-mail vale.
_HEADERS_ATOR = ("x-control-actor", "x-operator-email", "x-actor-email")

# NOTA sobre a chave `integracao` nos `details` daqui: ela guarda `p.name`, o
# nome do control token (ex.: "console-alavank"), e ANTES se chamava "token".
# O sanitizador de `services/audit.py` redige por SUBSTRING qualquer chave que
# contenha "token" — corretamente, porque em 99% dos casos ali dentro estaria um
# segredo. Com o nome antigo, a unica identificacao da origem virava "[oculto]".


def _ator(request: Request, p: ControlPrincipal) -> str:
    """Quem, do lado da Alavank, esta agindo — para o campo indexado `user_email`.

    Todo evento `control.*` gravava `user_email` NULO: sobrava o nome do token em
    `details`, que identifica a INTEGRACAO, nao a pessoa. "Quem da Alavank revelou
    a senha do gov.br desta prefeitura" simplesmente nao existia como pergunta
    respondivel, e e exatamente o tipo de acesso que a LGPD manda rastrear.

    O Console envia o tecnico logado num destes cabecalhos. Quando nao envia (ou
    e uma automacao sem gente na frente), o responsavel possivel e o TOKEN — e ai
    grava-se `control-token:<nome>`.

    ⚠️ OS DOIS VALORES SAO SEMPRE PREFIXADOS, e o prefixo nao e enfeite. O
    cabecalho e uma AFIRMACAO de quem detem o control token: nada aqui prova que
    o tecnico e aquele. Gravado como e-mail cru, um Console comprometido (ou com
    bug) escreveria `admin@montesiao.mg.gov.br` no campo indexado e a trilha
    apontaria o servidor da prefeitura como autor de um ato que so o canal da
    Alavank consegue praticar — envenenar a prova justamente no incidente em que
    ela serve. Com `control:` na frente, um evento do canal externo nunca se
    confunde com o login de uma pessoa do tenant, e continua achavel na busca por
    e-mail (que e `ilike '%termo%'`, nao igualdade). O ator VERIFICADO — o token
    autenticado — vai em `details.integracao` nas 13 chamadas, sempre."""
    for h in _HEADERS_ATOR:
        v = (request.headers.get(h) or "").strip().lower()
        if v and "@" in v and len(v) <= 200:
            return f"control:{v}"
    return f"control-token:{p.name}"[:255]


def _mun(m: Municipio) -> dict:
    return {"ibge_code": m.ibge_code, "nome": m.nome, "uf": m.uf,
            "active": bool(m.active), "fns_code": m.fns_code}


class MunicipioIn(BaseModel):
    ibge_code: str
    nome: str
    # ⚠️ SEM default. Municipio criado sem UF nascia "MG" e todo filtro por
    # estado passava a mentir — Minas e mais um estado, nao o padrao.
    uf: str
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
    uf = (body.uf or "").strip().upper()[:2]
    if len(ibge) != 7 or not ibge.isdigit():
        raise HTTPException(status_code=400, detail="ibge_code deve ter 7 dígitos")
    if not nome:
        raise HTTPException(status_code=400, detail="nome obrigatório")
    if len(uf) != 2 or not uf.isalpha():
        raise HTTPException(status_code=400, detail="uf obrigatória (sigla de 2 letras)")

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
    if created:
        # MUNICIPIO NOVO PRECISA CHEGAR A ALGUEM — senao ele nasce invisivel.
        #
        # Ate este incremento nao havia o que fazer aqui: `role == "admin"`
        # zerava `allowed_municipio_ids`, entao a cidade recem-cadastrada ja
        # aparecia para os administradores do cliente no primeiro F5. Com o papel
        # virado rotulo, quem nao tem LINHA em `user_municipios` leva
        # "Voce nao tem acesso a este municipio" — e o municipio novo nao tem
        # linha para ninguem. A assessoria assinaria a cidade nova pelo Console e
        # o cliente nao a veria, sem erro nenhum que explicasse.
        #
        # O criterio NAO e o papel (ele nao concede mais nada): e COBERTURA. Quem
        # ja tinha TODOS os outros municipios continua com todos — o admin de uma
        # prefeitura, o gestor da assessoria que cuida da carteira inteira. Quem
        # estava limitado a 2 de 5 segue limitado a 2 de 6, que e o ponto do
        # incremento: ninguem ganha alcance por efeito colateral de cadastro.
        #
        # Fora do alcance, explicitamente:
        #  · quem nao tem municipio NENHUM — sem isto, "tem todos os outros"
        #    seria verdade VAZIA para uma conta sem acesso, e ela ganharia a
        #    cidade nova sem nunca ter tido nada;
        #  · as contas de QUIOSQUE (links publicos de TV). Elas espelham o dono
        #    na emissao e nao podem crescer sozinhas depois — um link colado numa
        #    TV passaria a mostrar uma cidade que nao existia quando foi gerado.
        await db.execute(text("""
            INSERT INTO user_municipios (user_id, municipio_id)
            SELECT u.id, :novo
              FROM users u
             WHERE u.active
               AND NOT u.kiosk
               AND u.email NOT LIKE '%@painel.local'
               AND EXISTS (SELECT 1 FROM user_municipios um WHERE um.user_id = u.id)
               AND NOT EXISTS (
                     SELECT 1 FROM municipios m2
                      WHERE m2.id <> :novo
                        AND NOT EXISTS (
                              SELECT 1 FROM user_municipios um2
                               WHERE um2.user_id = u.id AND um2.municipio_id = m2.id))
            ON CONFLICT DO NOTHING
        """), {"novo": m.id})
        await db.commit()
    await registrar(db, action="control.municipio.upsert", request=request,
                    user_email=_ator(request, p), municipio_id=m.id,
                    target_type="municipio", target_id=ibge, alvo_nome=f"{nome}/{uf}",
                    details={"nome": nome, "uf": uf, "created": created, "integracao": p.name})
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
        raise HTTPException(status_code=404, detail="Município não encontrado")
    changed = []
    if body.nome is not None and body.nome.strip():
        m.nome = body.nome.strip(); changed.append("nome")
    if body.uf is not None and body.uf.strip():
        uf_nova = body.uf.strip().upper()[:2]
        # Mesma regra do POST: uf agora dirige coletor (CAGEC, Acordo FES) e
        # filtro de tela — "MI" truncado de "Minas" desligaria tudo em silencio.
        if len(uf_nova) != 2 or not uf_nova.isalpha():
            raise HTTPException(status_code=400, detail="uf inválida (sigla de 2 letras)")
        m.uf = uf_nova; changed.append("uf")
    if body.active is not None:
        m.active = bool(body.active); changed.append("active")
    if body.fns_code is not None:
        m.fns_code = "".join(ch for ch in body.fns_code if ch.isdigit())[:6] or None
        changed.append("fns_code")
    await db.commit()
    await db.refresh(m)
    await registrar(db, action="control.municipio.patch", request=request,
                    user_email=_ator(request, p), municipio_id=m.id,
                    target_type="municipio", target_id=ibge_code, alvo_nome=f"{m.nome}/{m.uf}",
                    details={"changed": changed, "active": m.active, "integracao": p.name})
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
            # inserted+updated na MESMA chave que a Central ja le: o sigcon
            # passou a gravar as duas colunas separadas, e em regime estavel
            # (quase tudo update) o inserted cru viraria 0 e pareceria coleta
            # quebrada no console. LIMIT 80: o lote horario adiciona 24
            # linhas/dia e com 40 o historico encolhia para ~1 dia.
            "SELECT source, status, "
            "records_inserted + coalesce(records_updated, 0) AS records_inserted, "
            "to_char(finished_at, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS finished_at "
            "FROM ingestion_log ORDER BY id DESC LIMIT 80"
        ))).mappings().all()
        return {"log": [dict(r) for r in rows]}
    except Exception:
        await db.rollback()
        return {"log": [], "error": "tabela ingestion_log indisponível"}


# Catalogo de fontes p/ o Monitor da Central: tabela contada (escopada por municipio
# ativo = o que o cliente REALMENTE ve) + nomes que cada scraper grava no ingestion_log.
_FONTES_MONITOR = [
    {"key": "convenios_estadual", "sources": ["sigcon_scraper", "sigcon_ckan_backfill"]},
    {"key": "transferegov_propostas", "sources": ["transferegov_voluntarias", "transferegov_lote"]},
    {"key": "emendas_estaduais", "sources": ["emendas_estaduais"]},
    {"key": "cauc_situacao", "sources": ["cauc"]},
    {"key": "acordofes_credor", "sources": ["acordofes"]},
    {"key": "siconv_federal", "sources": ["siconv_federal", "siconv_convenio_backfill", "siconv_emenda_backfill"]},
]


@router.get("/fontes")
async def control_fontes(
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:data:read")),
):
    """Saude por fonte p/ o Monitor: contagem ESCOPADA pelos municipios ATIVOS (o que o
    cliente realmente ve, ao contrario do /status que conta a tabela crua) + a ultima
    execucao (ingestion_log). So leitura. Fail-safe: cada consulta cai em None."""
    async def _scoped_count(table: str):
        # 1) so o que pertence a municipio ATIVO; 2) fallback contagem crua (tabela sem
        # municipio_id); None se a tabela nao existir. Retorna (n, escopado?).
        scoped_sql = (f"SELECT COUNT(*) FROM {table} t "
                      f"JOIN municipios m ON m.id = t.municipio_id WHERE m.active = true")
        try:
            return (await db.execute(text(scoped_sql))).scalar(), True
        except Exception:
            await db.rollback()
        try:
            return (await db.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar(), False
        except Exception:
            await db.rollback()
            return None, False

    async def _last_run(sources: list):
        if not sources:
            return None, None
        names = {f"s{i}": s for i, s in enumerate(sources)}
        inclause = ", ".join(f":{k}" for k in names)
        try:
            row = (await db.execute(text(
                f"SELECT status, to_char(finished_at, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS finished_at "
                f"FROM ingestion_log WHERE source IN ({inclause}) ORDER BY id DESC LIMIT 1"
            ), names)).mappings().first()
            return (row["status"], row["finished_at"]) if row else (None, None)
        except Exception:
            await db.rollback()
            return None, None

    out = []
    for f in _FONTES_MONITOR:
        registros, escopado = await _scoped_count(f["key"])
        status, finished_at = await _last_run(f["sources"])
        out.append({
            "key": f["key"], "registros": registros, "escopo_ativo": escopado,
            "ultimo_status": status, "ultima_coleta": finished_at,
        })
    return {"fontes": out, "instance_slug": os.getenv("INSTANCE_SLUG", "")}


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
    await registrar(db, action="control.refresh", request=request,
                    user_email=_ator(request, p),
                    target_type="scraper", target_id=source, alvo_nome="SIGCON-MG",
                    details={"queued": row is not None, "integracao": p.name,
                             "job_id": row[0] if row else None})
    if row is None:
        return {"status": "already_queued", "source": source,
                "message": "Já existe uma atualização na fila ou em execução."}
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
        return {"jobs": [], "error": "tabela scraper_jobs indisponível"}


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
        return "[sessão capturada]"
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
        raise HTTPException(status_code=400, detail="sistema obrigatório")
    mun_id = await _mun_id_by_ibge(db, body.municipio_ibge)
    if body.municipio_ibge and mun_id is None:
        raise HTTPException(status_code=400, detail="município (ibge) não encontrado")
    it = CofreSenha(
        municipio_id=mun_id, sistema=sistema, url=body.url, usuario=body.usuario,
        senha_encrypted=crypto.encrypt(body.senha) if body.senha else None,
        automation_key=(body.automation_key or None), categoria=body.categoria,
        observacao=body.observacao,
    )
    db.add(it)
    await db.commit()
    await db.refresh(it)
    await registrar(db, action="control.cofre.create", request=request,
                    user_email=_ator(request, p), municipio_id=it.municipio_id,
                    target_type="cofre_senha", target_id=it.id, alvo_nome=sistema,
                    details={"sistema": sistema, "integracao": p.name,
                             "automation_key": it.automation_key})
    return await _cofre_out(db, it)


@router.patch("/cofre/{item_id}")
async def patch_cofre(
    item_id: int, body: CofrePatch, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:cofre:write")),
):
    it = await db.get(CofreSenha, item_id)
    if not it:
        raise HTTPException(status_code=404, detail="entrada não encontrada")
    fields = body.model_dump(exclude_unset=True)
    if "municipio_ibge" in fields:
        ibge = fields.pop("municipio_ibge")
        mid = await _mun_id_by_ibge(db, ibge) if ibge else None
        if ibge and mid is None:   # nao rebaixa p/ escopo geral por typo de IBGE
            raise HTTPException(status_code=400, detail="município (ibge) não encontrado")
        it.municipio_id = mid
    if "senha" in fields:                       # so re-cifra se veio senha
        senha = fields.pop("senha")
        it.senha_encrypted = crypto.encrypt(senha) if senha else None
    for k, v in fields.items():
        setattr(it, k, v)
    await db.commit()
    await db.refresh(it)
    await registrar(db, action="control.cofre.patch", request=request,
                    user_email=_ator(request, p), municipio_id=it.municipio_id,
                    target_type="cofre_senha", target_id=it.id,
                    alvo_nome=it.sistema,
                    # Quais campos foram tocados (NUNCA o valor: da senha fica so
                    # a marca de que houve troca). `exclude_unset` ja separa
                    # "mandou vazio" de "nem mandou". `senha_changed` e o nome
                    # exato que o sanitizador do audit reconhece como METRICA e
                    # deixa passar — qualquer outro nome com "senha" viraria
                    # "[oculto]" e a marca se perderia.
                    details={"sistema": it.sistema, "integracao": p.name,
                             "campos": sorted(body.model_dump(exclude_unset=True).keys()),
                             "senha_changed": "senha" in body.model_fields_set})
    return await _cofre_out(db, it)


@router.get("/cofre/{item_id}/reveal")
async def reveal_cofre(
    item_id: int, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:cofre:read")),
):
    it = await db.get(CofreSenha, item_id)
    if not it:
        raise HTTPException(status_code=404, detail="entrada não encontrada")
    # Registro ANTES da revelacao: se a trilha nao gravar, a senha nao sai. Nos
    # outros endpoints deste arquivo falhar o registro depois do commit so
    # mentiria sobre um ato ja consumado; neste, falhar de proposito EVITA a
    # divulgacao — a unica ordem em que "critico" e honesto. Revelar credencial
    # de prefeitura sem deixar quem e quando e o pior evento desta superficie.
    # (`services/audit.py` ja promoveria `*.reveal` a critico mesmo por
    # `registrar`; a chamada explicita aqui e para nao depender disso.)
    await registrar_critico(db, action="control.cofre.reveal", request=request,
                            user_email=_ator(request, p), municipio_id=it.municipio_id,
                            target_type="cofre_senha", target_id=it.id,
                            alvo_nome=it.sistema,
                            # `it.usuario` (o LOGIN do portal) fica de fora: no
                            # gov.br ele E o CPF de um servidor. A trilha nao se
                            # apaga por 5 anos e sai do sistema em PDF/Excel —
                            # copiar o CPF para ca multiplicaria dado pessoal
                            # sem responder nada que `sistema` + `target_id` +
                            # `automation_key` ja nao respondam (qual entrada do
                            # cofre foi exposta). E o mesmo recorte que o reveal
                            # do lado do cliente ja usa (routers/cofre.py):
                            # dois eventos do MESMO ato guardando conjuntos
                            # diferentes de dado pessoal seria incoerencia
                            # dificil de defender numa auditoria de LGPD.
                            details={"sistema": it.sistema,
                                     "automation_key": it.automation_key, "integracao": p.name})
    return {"senha": crypto.decrypt(it.senha_encrypted) if it.senha_encrypted else ""}


@router.delete("/cofre/{item_id}")
async def delete_cofre(
    item_id: int, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:cofre:write")),
):
    it = await db.get(CofreSenha, item_id)
    if not it:
        raise HTTPException(status_code=404, detail="entrada não encontrada")
    sistema = it.sistema
    mun_id = it.municipio_id       # some junto com a linha; copiado antes do delete
    await db.delete(it)
    await db.commit()
    await registrar(db, action="control.cofre.delete", request=request,
                    user_email=_ator(request, p), municipio_id=mun_id,
                    target_type="cofre_senha", target_id=item_id, alvo_nome=sistema,
                    details={"sistema": sistema, "integracao": p.name})
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
    await registrar(db, action=action, request=request, user_email=_ator(request, p),
                    target_type="service_token", target_id=tok.id, alvo_nome=name,
                    details={"name": name, "integracao": p.name, "prefix": tok.token_prefix})
    return {"token": raw, "name": name, "scopes": ["session:write"], "prefix": tok.token_prefix,
            "warning": "Anote agora — não será mostrado de novo. Configure na extensão de captura."}


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
        raise HTTPException(status_code=400, detail="email inválido")
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
    # ⚠️ O ESCOPO DO SUPORTE, ESCRITO — e não herdado do papel.
    #
    # Esta conta nascia só com `role="admin"`, e isso bastava: `load_user_scopes`
    # zerava os dois limites de todo admin. Não zera mais (o papel virou rótulo),
    # e a conta de suporte NÃO é super-admin — o e-mail é `alavank-sso.<local>@…`,
    # que não está em `SUPER_ADMIN_EMAILS` nem foi semeado na coluna. Sem estas
    # duas concessões, o técnico da Alavank entraria pelo SSO num tenant e veria
    # menu vazio e 403 em tudo: o backfill da migration só alcançou as contas de
    # suporte que JÁ EXISTIAM no dia do deploy, e cada técnico novo (ou cada
    # tenant novo) cria a sua depois.
    #
    # A CADA emissão, e não só na criação: é o mesmo motivo de `_ensure_kiosk_user`
    # reescrever o escopo do quiosque — conta sintética não tem dono humano para
    # ajustar permissão, então nada aqui desfaz decisão de ninguém. E é o que
    # cura sozinho o município cadastrado DEPOIS da última sessão de suporte.
    #
    # Não vira `super_admin = TRUE` de propósito: isso daria ao suporte mais do
    # que ele tinha ontem (Sessões, Service Tokens, poder sobre as contas donas).
    # Aqui só se repõe, como dado, o que o papel concedia por desvio.
    for _tela in TELAS_TODAS:
        await db.execute(text(
            "INSERT INTO user_telas (user_id, tela) VALUES (:u, :t) ON CONFLICT DO NOTHING"
        ), {"u": u.id, "t": _tela})
    await db.execute(text(
        "INSERT INTO user_municipios (user_id, municipio_id) "
        "SELECT :u, id FROM municipios ON CONFLICT DO NOTHING"
    ), {"u": u.id})
    await db.commit()
    token = create_sso_token(u.id)
    # Aqui o proprio corpo diz quem e o tecnico que vai entrar no sistema do
    # cliente — melhor identificacao que qualquer cabecalho. Se o Console mandar
    # o ator, ele vence (pode ser um coordenador abrindo sessao para outro); o
    # e-mail do tecnico fica sempre em `details` para os dois casos casarem.
    ator = _ator(request, p)
    await registrar(db, action="control.sso.mint", request=request,
                    # Mesmo prefixo de `_ator` no fallback: o e-mail do corpo
                    # tambem e afirmacao de quem tem o token, e um ato do canal
                    # externo nao pode aparecer no filtro como login local.
                    user_email=(ator if "@" in ator else f"control:{email}"[:255]),
                    target_type="user", target_id=email,
                    alvo_nome=(body.tech_name or email),
                    details={"tech": email, "tech_nome": body.tech_name,
                             "usuario_suporte": support_email, "integracao": p.name})
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
    _ll = getattr(u, "last_login_at", None)
    _cr = getattr(u, "created_at", None)
    return {
        "email": u.email, "name": u.name, "role": u.role, "active": bool(u.active),
        "must_change_password": bool(u.must_change_password),
        "last_login_at": _ll.isoformat() if _ll else None,
        "created_at": _cr.isoformat() if _cr else None,
        "telas": await users_admin.get_user_telas(db, u.id),
        "municipios": await users_admin.get_user_ibges(db, u.id),
    }


async def _active_admin_count(db) -> int:
    # Exclui usuarios de SUPORTE da Alavank (alavank-sso.*): a senha deles nunca sai da
    # Central (o cliente nao autentica como eles), entao NAO contam como "o cliente ainda
    # tem admin". Sem isso, a trava de "unico admin" (do PATCH e do DELETE) era burlavel.
    return (await db.execute(text(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = true "
        "AND email NOT LIKE 'alavank-sso.%'"))).scalar() or 0


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
        raise HTTPException(status_code=400, detail="Email inválido")
    if body.role not in users_admin.ROLES:
        raise HTTPException(status_code=400, detail="Role inválida (admin|analyst|user)")
    dup = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=400, detail="Email já cadastrado")
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
    await registrar(db, action="control.user.create", request=request,
                    user_email=_ator(request, p),
                    target_type="user", target_id=email, alvo_nome=u.name,
                    details={"role": body.role, "integracao": p.name,
                             "telas": sorted(body.telas or []),
                             "municipios": sorted(body.municipios or [])})
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
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    if body.role is not None and body.role not in users_admin.ROLES:
        raise HTTPException(status_code=400, detail="Role inválida")
    # Nao deixar o cliente sem NENHUM admin
    demoting = body.role is not None and body.role != "admin" and u.role == "admin"
    deactivating = body.active is False and u.active and u.role == "admin"
    if (demoting or deactivating) and await _active_admin_count(db) <= 1:
        raise HTTPException(status_code=409, detail="Não é possível deixar o cliente sem administrador")

    # Mesmo "antes/depois" do PATCH da tela de usuarios: este canal tambem concede
    # e retira acesso, e ate agora gravava apenas o nome do token — ou seja, que
    # ALGO foi editado, sem dizer o que. Escopo aqui vem por ibge_code (chave
    # estavel do canal), nao por id interno.
    antes = {"name": u.name, "role": u.role, "active": bool(u.active),
             "telas": await users_admin.get_user_telas(db, u.id),
             "municipios": await users_admin.get_user_ibges(db, u.id)}
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
    depois = {"name": u.name, "role": u.role, "active": bool(u.active),
              "telas": await users_admin.get_user_telas(db, u.id),
              "municipios": await users_admin.get_user_ibges(db, u.id)}
    permissao = {}
    for campo in ("telas", "municipios"):
        a, d = set(antes[campo]), set(depois[campo])
        if a != d:
            permissao[campo] = {"concedidos": sorted(d - a), "retirados": sorted(a - d)}
    await registrar(db, action="control.user.patch", request=request,
                    user_email=_ator(request, p),
                    target_type="user", target_id=email, alvo_nome=u.name,
                    # Snapshots completos: o audit reduz sozinho ao que mudou.
                    valor_antes=antes, valor_depois=depois,
                    details={"permissao": permissao or None, "integracao": p.name})
    return await _user_out(db, u)


@router.post("/users/{email}/reset-password")
async def reset_control_user_password(
    email: str, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:users:write")),
):
    u = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    senha = users_admin.gen_senha()
    u.password_hash = hash_password(senha)
    u.must_change_password = True
    await db.commit()
    await registrar(db, action="control.user.reset_password", request=request,
                    user_email=_ator(request, p),
                    target_type="user", target_id=email, alvo_nome=u.name,
                    details={"integracao": p.name})
    return {"email": u.email, "senha_temporaria": senha}


@router.delete("/users/{email}")
async def delete_control_user(
    email: str, request: Request,
    db: AsyncSession = Depends(get_db),
    p: ControlPrincipal = Depends(require_control_scope("control:users:write")),
):
    """Remove DEFINITIVAMENTE um usuario do tenant (limpeza de entulho de seed).
    Trava: nao remove o UNICO admin ativo. A trilha fica INTACTA: audit_log nao e
    tocada (nao tem mais FK para users e e append-only desde o Incremento 3) — as
    linhas continuam com user_id, user_email e usuario_nome do instante do ato.
    Zera as FKs sem ON DELETE (cofre_senhas, edital_acompanhamento,
    prestacao_contas/documentos); user_telas/user_municipios/telegram_* somem por
    ON DELETE CASCADE. Falha de forma atomica (rollback)."""
    u = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    # Usuario de SUPORTE da Alavank (alavank-sso.*) nao e removivel por aqui: e sintetico,
    # o SSO o recria, e deletar no meio de uma sessao derruba o tecnico (401). Some so via SSO.
    if (u.email or "").startswith("alavank-sso."):
        raise HTTPException(status_code=409, detail="Usuário de suporte Alavank não é removível por este canal")
    if u.role == "admin" and u.active and await _active_admin_count(db) <= 1:
        raise HTTPException(status_code=409, detail="Não é possível remover o único administrador ativo")
    uid, uname, urole = u.id, u.name, u.role
    # user_telas/user_municipios somem por ON DELETE CASCADE: se nao forem
    # copiados AGORA, "que acessos essa conta tinha quando foi removida" fica sem
    # resposta para sempre. E a pergunta que uma auditoria faz primeiro.
    utelas = await users_admin.get_user_telas(db, uid)
    umuns = await users_admin.get_user_ibges(db, uid)

    # ⭐ A LIMPEZA DE FKs MUDOU DE ENDEREÇO: mora em
    # services/users_admin.py::limpar_fks_do_usuario, compartilhada com o canal
    # do produto (routers/users.py::delete_user, criado em 11/08/2026). As duas
    # listas viviam separadas e divergiram uma vez — as tabelas do Painel
    # chegaram depois desta rotina e ninguem veio somar aqui; o sintoma foi 409
    # sem remedio. A historia toda (audit_log fora da lista de proposito, o que
    # zera vs o que apaga) esta documentada la, num lugar so.
    await users_admin.limpar_fks_do_usuario(db, uid)
    try:
        await db.delete(u)
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=409,
                            detail=f"Não foi possível remover (referências pendentes: {type(e).__name__})")
    await registrar(db, action="control.user.delete", request=request,
                    user_email=_ator(request, p),
                    target_type="user", target_id=email, alvo_nome=uname,
                    details={"name": uname, "role": urole, "integracao": p.name,
                             "telas": utelas, "municipios": umuns})
    return {"status": "deleted", "email": email}
