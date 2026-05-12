"""
Endpoints INTERNOS - acessados apenas por scrapers/workers via Service Token.
NUNCA expor publicamente, NUNCA usar JWT de usuario aqui.
"""
from datetime import datetime
import re
import unicodedata
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from pydantic import BaseModel


def _norm_parl_name(s: str | None) -> str:
    if not s:
        return ""
    s = str(s).strip().upper()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

from database import get_db
from models.cofre import CofreSenha
from models.service_token import ServiceToken
from models.convenio import ConvenioFederal
from services.service_auth import get_service_token, require_scope
from services import crypto
from services.audit import log_event

router = APIRouter(prefix="/api/internal", tags=["internal"])


class UpsertItem(BaseModel):
    municipio_id: int
    nr_proposta: str | None = None
    objeto: str | None = None
    programa: str | None = None
    tipo_programa: str | None = None
    valor: float = 0
    situacao: str | None = None
    ano: int | None = None
    fonte: str
    orgao_concedente: str | None = None
    # Vinculo com parlamentar (opcional). Quando informado, o endpoint cria
    # ou atualiza um registro em `emendas` ligado ao convenio inserido.
    parlamentar_nome: str | None = None
    nr_emenda: str | None = None


class UpsertRequest(BaseModel):
    items: list[UpsertItem]


@router.get("/secrets/{automation_key}")
async def get_secret_for_automation(
    automation_key: str,
    municipio_id: int | None = None,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    token: ServiceToken = Depends(get_service_token),
):
    """Retorna credenciais cadastradas no Cofre marcadas com automation_key.

    Scraper precisa de scope `secret:read:<automation_key>` ou `secret:read:*`.
    Cada chamada e auditada com IP, IP do scraper, automation_key, municipio.
    """
    require_scope(token, f"secret:read:{automation_key}")

    q = select(CofreSenha).where(CofreSenha.automation_key == automation_key)
    if municipio_id:
        q = q.where(CofreSenha.municipio_id == municipio_id)
    result = await db.execute(q)
    items = result.scalars().all()

    # Para resolver nome/UF do municipio, faz join leve
    from models import Municipio
    mun_ids = {it.municipio_id for it in items if it.municipio_id}
    mun_meta = {}
    if mun_ids:
        mres = await db.execute(select(Municipio).where(Municipio.id.in_(mun_ids)))
        for m in mres.scalars().all():
            mun_meta[m.id] = (m.nome, m.uf)

    out = []
    for it in items:
        nome, uf = mun_meta.get(it.municipio_id, (None, None))
        # Tenta decrypt; tolera senhas legadas em texto puro
        try:
            senha = crypto.decrypt(it.senha_encrypted) if it.senha_encrypted else ""
        except Exception:
            senha = it.senha_encrypted or ""
        out.append({
            "id": it.id,
            "municipio_id": it.municipio_id,
            "municipio_nome": nome,
            "municipio_uf": uf,
            "sistema": it.sistema,
            "url": it.url,
            "usuario": it.usuario,
            "senha": senha,
        })

    # Auditoria
    await log_event(
        db, action="secret.read",
        request=request,
        target_type="automation",
        target_id=automation_key,
        details={
            "service_token": token.name,
            "token_prefix": token.token_prefix,
            "municipio_id": municipio_id,
            "n_secrets": len(out),
        },
    )
    return {"secrets": out}


@router.post("/upsert/{automation_key}")
async def upsert_from_scraper(
    automation_key: str,
    payload: UpsertRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: ServiceToken = Depends(get_service_token),
):
    """Recebe items coletados pelo scraper e faz upsert em convenios_federal.

    Scope necessario: write:<automation_key> (ex: write:fns).
    """
    require_scope(token, f"write:{automation_key}")

    inserted = 0
    skipped = 0
    emendas_linked = 0
    for it in payload.items:
        # Gerar nr_convenio uniforme
        nr = (it.nr_proposta or "").strip()
        if not nr:
            nr = f"{automation_key.upper()}-{it.municipio_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{inserted}"
        nr = nr[:50]
        try:
            res = await db.execute(text("""
                INSERT INTO convenios_federal (
                    nr_convenio, municipio_id, orgao_concedente, objeto,
                    situacao, valor_repasse, ano, programa, tipo_programa,
                    fonte, raw_data, updated_at
                ) VALUES (
                    :nr, :mun, :orgao, :obj, :sit, :val, :ano, :prog, :tipo,
                    :fonte, :raw, NOW()
                )
                ON CONFLICT (nr_convenio) DO UPDATE SET
                    valor_repasse = EXCLUDED.valor_repasse,
                    situacao = EXCLUDED.situacao,
                    raw_data = EXCLUDED.raw_data,
                    updated_at = NOW()
                RETURNING id
            """), {
                "nr": nr,
                "mun": it.municipio_id,
                "orgao": it.orgao_concedente or it.fonte,
                "obj": (it.objeto or it.programa or "")[:1000],
                "sit": (it.situacao or "")[:200],
                "val": float(it.valor or 0),
                "ano": it.ano,
                "prog": it.programa,
                "tipo": it.tipo_programa,
                "fonte": it.fonte,
                "raw": "{}",
            })
            convenio_id = res.scalar()
            inserted += 1

            # Cria/atualiza emenda quando o scraper informa parlamentar
            if it.parlamentar_nome and convenio_id:
                parl_id = await _upsert_parlamentar(db, it.parlamentar_nome)
                if parl_id:
                    await db.execute(text("""
                        INSERT INTO emendas (
                            nr_emenda, parlamentar_id, municipio_id, convenio_federal_id,
                            valor, tipo, esfera, ano
                        ) VALUES (:ne, :p, :m, :cf, :v, 'Indicacao Parlamentar', 'federal', :a)
                        ON CONFLICT DO NOTHING
                    """), {
                        "ne": (it.nr_emenda or "")[:100] or None,
                        "p": parl_id, "m": it.municipio_id, "cf": convenio_id,
                        "v": float(it.valor or 0), "a": it.ano,
                    })
                    emendas_linked += 1
        except Exception:
            skipped += 1
            continue
    await db.commit()

    await log_event(
        db, action="scraper.upsert", request=request,
        target_type="automation", target_id=automation_key,
        details={
            "service_token": token.name,
            "n_items": len(payload.items),
            "inserted": inserted,
            "skipped": skipped,
            "emendas_linked": emendas_linked,
        },
    )
    return {
        "inserted": inserted, "skipped": skipped,
        "emendas_linked": emendas_linked, "total": len(payload.items),
    }


async def _upsert_parlamentar(db: AsyncSession, nome: str) -> int | None:
    """Busca parlamentar por nome normalizado; cria se nao existir.

    Detecta automaticamente se o nome e institucional (Comissao/Bancada/Bloco/
    Programa/etc) e padroniza para UPPER sem acentos. Para individuais,
    mantem capitalizacao original.

    Usado por scrapers (FNS/SIMEC/SUAS/PortalTransparencia/CODEVASF) para
    linkar uma indicacao a um deputado/senador OU rotulo institucional.
    """
    from services.institucional import is_institucional, normalize_institucional
    norm = _norm_parl_name(nome)
    if not norm or len(norm) < 3:
        return None

    # Match por nome normalizado em Python
    r = await db.execute(text("SELECT id, nome FROM parlamentares"))
    for pid, pnome in r.fetchall():
        if _norm_parl_name(pnome) == norm:
            return pid

    # Cadastra novo - se for institucional, normaliza UPPER sem acentos
    inst = is_institucional(nome)
    nome_db = normalize_institucional(nome) if inst else nome.strip()[:300]
    esfera = "federal"
    uf = "BR" if inst and any(k in norm for k in ["BANCADA", "COMISS", "BLOCO", "RELATOR"]) else "MG"

    # ON CONFLICT DO NOTHING usa o UNIQUE INDEX ix_parlamentares_nome_unaccent
    # para evitar duplicatas em race conditions (varios scrapers paralelos)
    res = await db.execute(text("""
        INSERT INTO parlamentares (nome, esfera, uf)
        VALUES (:n, :e, :u)
        ON CONFLICT (upper(translate(nome,
            'ÁÉÍÓÚÀÂÊÔÃÕÇáéíóúàâêôãõç',
            'AEIOUAAEOAOCAEIOUAAEOAOC'))) DO NOTHING
        RETURNING id
    """), {"n": nome_db, "e": esfera, "u": uf})
    new_id = res.scalar()
    if new_id:
        return new_id

    # Conflito (alguem inseriu antes) - re-buscar
    r2 = await db.execute(text("""
        SELECT id FROM parlamentares
        WHERE upper(translate(nome,
            'ÁÉÍÓÚÀÂÊÔÃÕÇáéíóúàâêôãõç',
            'AEIOUAAEOAOCAEIOUAAEOAOC'))
            = upper(translate(:n,
            'ÁÉÍÓÚÀÂÊÔÃÕÇáéíóúàâêôãõç',
            'AEIOUAAEOAOCAEIOUAAEOAOC'))
        LIMIT 1
    """), {"n": nome_db})
    return r2.scalar()
