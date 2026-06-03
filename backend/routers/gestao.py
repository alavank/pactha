"""Modulo Gestao Interna - anotacoes paralelas (sem alterar dados oficiais).

Permite ao usuario:
- Marcar status personalizado por item de convenio/proposta
  (ex: "Prestacao de Contas enviada fisicamente")
- Anotar protocolo + data + observacoes
- Anexar PDFs/imagens (base64 no JSONB)
- Listar todas anotacoes do municipio com filtros

Endpoints:
  GET    /api/gestao/status-opcoes      -> lista de status pre-definidos
  GET    /api/gestao/anotacoes          -> lista (filtros: municipio_id, fonte, status)
  GET    /api/gestao/anotacoes/item     -> anotacoes de um item especifico (fonte+ref)
  POST   /api/gestao/anotacoes          -> cria
  PUT    /api/gestao/anotacoes/{id}     -> atualiza
  DELETE /api/gestao/anotacoes/{id}     -> remove
"""
from __future__ import annotations
import json
from datetime import date
from typing import Optional, Any
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from services.auth import get_current_user

router = APIRouter(prefix="/api/gestao", tags=["gestao"])

# Opcoes de status pre-definidas (usuario pode escolher "Outro" para texto livre).
# Validadas no payload mas o frontend tambem deve mostrar essas opcoes.
STATUS_OPCOES = [
    "Prestação de contas enviada fisicamente",
    "Prestação de contas em elaboração",
    "Aguardando documentação do beneficiário",
    "Aguardando assinatura do prefeito",
    "Aguardando resposta do órgão",
    "Em análise interna",
    "Pendente de licitação",
    "Pendente de execução",
    "Concluído internamente",
    "Outro",
]

# Fontes validas (mesma lista que o RM builder usa)
FONTES_VALIDAS = {"sigcon", "voluntaria", "plano_acao", "fns", "simec", "emenda", "rm"}

# Limite de tamanho por anexo (base64 expandido = ~33% maior que binario)
MAX_ANEXO_BYTES = 2 * 1024 * 1024  # 2MB base64 ~= 1.5MB binario


class Anexo(BaseModel):
    nome: str = Field(..., max_length=200)
    mime: str = Field(..., max_length=100)
    dados_b64: str  # base64 do conteudo
    tamanho: Optional[int] = None  # bytes (binario, antes do base64)


class AnotacaoCreate(BaseModel):
    municipio_id: int
    fonte: str = Field(..., description="sigcon | voluntaria | plano_acao | fns | simec | emenda | rm")
    fonte_ref: str = Field(..., max_length=200)
    numero_referencia: Optional[str] = Field(None, max_length=200)
    status_interno: Optional[str] = None
    status_custom: Optional[str] = None
    protocolo: Optional[str] = Field(None, max_length=200)
    data_protocolo: Optional[date] = None
    observacoes: Optional[str] = None
    anexos: list[Anexo] = Field(default_factory=list)


class AnotacaoUpdate(BaseModel):
    status_interno: Optional[str] = None
    status_custom: Optional[str] = None
    protocolo: Optional[str] = None
    data_protocolo: Optional[date] = None
    observacoes: Optional[str] = None
    anexos: Optional[list[Anexo]] = None
    numero_referencia: Optional[str] = None


def _validate_payload(body: AnotacaoCreate | AnotacaoUpdate):
    if hasattr(body, "fonte") and body.fonte not in FONTES_VALIDAS:
        raise HTTPException(400, f"Fonte invalida. Use uma de: {sorted(FONTES_VALIDAS)}")
    if body.status_interno and body.status_interno not in STATUS_OPCOES:
        # Permite custom no banco mas avisa
        pass
    if body.status_interno == "Outro" and not (body.status_custom or "").strip():
        raise HTTPException(400, "Status 'Outro' exige status_custom preenchido.")
    if body.anexos:
        for a in body.anexos:
            # checa tamanho do base64 (string)
            if len(a.dados_b64) > MAX_ANEXO_BYTES:
                raise HTTPException(413, f"Anexo '{a.nome}' excede o limite de {MAX_ANEXO_BYTES//1024}KB (base64).")


def _row_to_dict(row, *, with_anexos: bool = True) -> dict:
    anexos = row[10] or []
    if not with_anexos:
        # Lista sem os dados_b64 para economizar payload
        anexos = [{k: v for k, v in a.items() if k != "dados_b64"} for a in anexos]
    return {
        "id": row[0],
        "municipio_id": row[1],
        "fonte": row[2],
        "fonte_ref": row[3],
        "numero_referencia": row[4],
        "status_interno": row[5],
        "status_custom": row[6],
        "protocolo": row[7],
        "data_protocolo": row[8].isoformat() if row[8] else None,
        "observacoes": row[9],
        "anexos": anexos,
        "criado_por": row[11],
        "created_at": row[12].isoformat() if row[12] else None,
        "updated_at": row[13].isoformat() if row[13] else None,
    }


_SELECT = """
SELECT id, municipio_id, fonte, fonte_ref, numero_referencia,
       status_interno, status_custom, protocolo, data_protocolo, observacoes,
       anexos, criado_por, created_at, updated_at
FROM gestao_anotacoes
"""


@router.get("/status-opcoes")
async def status_opcoes(_=Depends(get_current_user)):
    return {"opcoes": STATUS_OPCOES, "fontes_validas": sorted(FONTES_VALIDAS)}


@router.get("/anotacoes")
async def listar(
    municipio_id: Optional[int] = Query(None),
    fonte: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="Filtra por status_interno"),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    where = []
    params: dict = {}
    if municipio_id:
        where.append("municipio_id = :m"); params["m"] = municipio_id
    if fonte:
        where.append("fonte = :f"); params["f"] = fonte
    if status:
        where.append("status_interno = :s"); params["s"] = status
    sql = _SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY updated_at DESC"
    rows = (await db.execute(text(sql), params)).fetchall()
    # Lista sem dados_b64 dos anexos (apenas metadata) para economizar payload
    return {"items": [_row_to_dict(r, with_anexos=False) for r in rows], "total": len(rows)}


@router.get("/anotacoes/item")
async def listar_item(
    fonte: str = Query(...),
    fonte_ref: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Anotacoes de um item especifico (com anexos completos)."""
    rows = (await db.execute(
        text(_SELECT + " WHERE fonte = :f AND fonte_ref = :r ORDER BY updated_at DESC"),
        {"f": fonte, "r": fonte_ref},
    )).fetchall()
    return {"items": [_row_to_dict(r, with_anexos=True) for r in rows], "total": len(rows)}


@router.get("/anotacoes/{anot_id}")
async def detalhe(
    anot_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    row = (await db.execute(text(_SELECT + " WHERE id = :id"), {"id": anot_id})).first()
    if not row:
        raise HTTPException(404, "Anotacao nao encontrada")
    return _row_to_dict(row, with_anexos=True)


@router.post("/anotacoes")
async def criar(
    body: AnotacaoCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    _validate_payload(body)
    anex_json = json.dumps([a.model_dump() for a in body.anexos], ensure_ascii=False)
    rid = (await db.execute(text("""
        INSERT INTO gestao_anotacoes
            (municipio_id, fonte, fonte_ref, numero_referencia,
             status_interno, status_custom, protocolo, data_protocolo,
             observacoes, anexos, criado_por)
        VALUES (:m, :f, :r, :nr, :si, :sc, :p, :dp, :o, CAST(:a AS JSONB), :u)
        RETURNING id
    """), {
        "m": body.municipio_id, "f": body.fonte, "r": body.fonte_ref,
        "nr": body.numero_referencia, "si": body.status_interno,
        "sc": body.status_custom, "p": body.protocolo,
        "dp": body.data_protocolo, "o": body.observacoes,
        "a": anex_json, "u": getattr(user, "id", None),
    })).scalar()
    await db.commit()
    return {"id": rid, "created": True}


@router.put("/anotacoes/{anot_id}")
async def atualizar(
    anot_id: int,
    body: AnotacaoUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    _validate_payload(body)
    sets = []
    params: dict = {"id": anot_id}
    if body.status_interno is not None:
        sets.append("status_interno = :si"); params["si"] = body.status_interno
    if body.status_custom is not None:
        sets.append("status_custom = :sc"); params["sc"] = body.status_custom
    if body.protocolo is not None:
        sets.append("protocolo = :p"); params["p"] = body.protocolo
    if body.data_protocolo is not None:
        sets.append("data_protocolo = :dp"); params["dp"] = body.data_protocolo
    if body.observacoes is not None:
        sets.append("observacoes = :o"); params["o"] = body.observacoes
    if body.anexos is not None:
        sets.append("anexos = CAST(:a AS JSONB)")
        params["a"] = json.dumps([a.model_dump() for a in body.anexos], ensure_ascii=False)
    if body.numero_referencia is not None:
        sets.append("numero_referencia = :nr"); params["nr"] = body.numero_referencia
    if not sets:
        return {"updated": False, "reason": "nada para atualizar"}
    sets.append("updated_at = NOW()")
    await db.execute(text(f"UPDATE gestao_anotacoes SET {', '.join(sets)} WHERE id = :id"), params)
    await db.commit()
    return {"updated": True}


@router.delete("/anotacoes/{anot_id}")
async def remover(
    anot_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    r = await db.execute(text("DELETE FROM gestao_anotacoes WHERE id = :id"), {"id": anot_id})
    await db.commit()
    if r.rowcount == 0:
        raise HTTPException(404, "Anotacao nao encontrada")
    return {"deleted": True}


@router.get("/anotacoes/{anot_id}/anexo/{idx}")
async def download_anexo(
    anot_id: int,
    idx: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Download de um anexo especifico (decodifica base64)."""
    from fastapi.responses import Response
    import base64
    row = (await db.execute(text("SELECT anexos FROM gestao_anotacoes WHERE id = :id"), {"id": anot_id})).first()
    if not row:
        raise HTTPException(404, "Anotacao nao encontrada")
    anexos = row[0] or []
    if idx < 0 or idx >= len(anexos):
        raise HTTPException(404, "Anexo nao encontrado")
    a = anexos[idx]
    try:
        data = base64.b64decode(a["dados_b64"])
    except Exception:
        raise HTTPException(500, "Anexo corrompido")
    return Response(
        content=data, media_type=a.get("mime") or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{a.get("nome", "anexo")}"'},
    )
