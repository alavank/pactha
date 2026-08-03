"""Módulo "Geração de Documentos".

CRUD de documentos preenchidos na plataforma + exportação DOCX/PDF.
O formulário é dirigido pelo schema (services/documentos_schema.py), então o
frontend renderiza dinamicamente e os renders (docx/pdf) iteram o mesmo schema.
"""
from __future__ import annotations
import io
import json
from typing import Optional, Any

from fastapi import APIRouter, Depends, Query, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Municipio
from services.auth import get_current_user, ensure_municipio_access, ensure_tela
from models.user import User
from services.audit import registrar
from services.documentos_schema import get_schema, listar_tipos
from services.documento_docx import gerar_docx
from services.documento_pdf import gerar_pdf

router = APIRouter(prefix="/api/documentos", tags=["documentos"])


async def _doc_contexto(db: AsyncSession, doc_id: int) -> dict:
    """Municipio, tipo e titulo do documento, para a trilha.

    Igual ao RM: os endpoints de alteracao so conhecem o id, e sem esta leitura o
    registro sairia sem `municipio_id` e sem nada que um leigo reconheca. Nao
    levanta 404 — quem decide isso e o endpoint."""
    r = (await db.execute(text(
        "SELECT municipio_id, tipo, titulo, status FROM documentos_gerados WHERE id = :id"
    ), {"id": doc_id})).first()
    if not r:
        return {"municipio_id": None, "tipo": None, "titulo": None, "status": None}
    return {"municipio_id": r[0], "tipo": r[1], "titulo": r[2], "status": r[3]}


class DocCreate(BaseModel):
    municipio_id: Optional[int] = None
    tipo: str = "plano_sustentabilidade"
    titulo: Optional[str] = None
    dados: dict[str, Any] = {}
    status: Optional[str] = "rascunho"


class DocUpdate(BaseModel):
    titulo: Optional[str] = None
    dados: Optional[dict[str, Any]] = None
    status: Optional[str] = None


def _row_to_dict(r) -> dict:
    return {
        "id": r[0], "municipio_id": r[1], "tipo": r[2], "titulo": r[3],
        "dados": r[4] if isinstance(r[4], dict) else (json.loads(r[4]) if r[4] else {}),
        "status": r[5], "criado_por": r[6],
        "created_at": r[7].isoformat() if r[7] else None,
        "updated_at": r[8].isoformat() if r[8] else None,
    }


@router.get("/schemas")
async def schemas(_=Depends(get_current_user)):
    """Tipos de documento disponíveis (p/ o menu 'Novo documento')."""
    return {"items": listar_tipos()}


@router.get("/schema/{tipo}")
async def schema_de(tipo: str, _=Depends(get_current_user)):
    s = get_schema(tipo)
    if not s:
        raise HTTPException(404, f"Tipo de documento desconhecido: {tipo}")
    return s


@router.get("")
async def listar(
    municipio_id: Optional[int] = Query(None),
    tipo: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "documentos")
    where, params = [], {}
    if municipio_id:
        where.append("municipio_id = :m"); params["m"] = municipio_id
    if tipo:
        where.append("tipo = :t"); params["t"] = tipo
    sql = ("SELECT id, municipio_id, tipo, titulo, dados, status, criado_por, created_at, updated_at "
           "FROM documentos_gerados")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC"
    rows = (await db.execute(text(sql), params)).fetchall()
    return {"items": [_row_to_dict(r) for r in rows], "total": len(rows)}


@router.post("")
async def criar(
    body: DocCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    if not get_schema(body.tipo):
        raise HTTPException(400, f"Tipo de documento desconhecido: {body.tipo}")
    titulo = body.titulo or (body.dados or {}).get("convenio_proposta") or get_schema(body.tipo)["titulo"]
    rid = (await db.execute(text("""
        INSERT INTO documentos_gerados (municipio_id, tipo, titulo, dados, status, criado_por)
        VALUES (:mun, :tipo, :tit, CAST(:dados AS JSONB), :st, :usr)
        RETURNING id
    """), {
        "mun": body.municipio_id, "tipo": body.tipo, "tit": titulo,
        "dados": json.dumps(body.dados or {}, ensure_ascii=False),
        "st": body.status or "rascunho", "usr": getattr(user, "id", None),
    })).scalar()
    await db.commit()
    # `dados` fica de fora: e o documento inteiro (dezenas de campos livres, com
    # nome de pessoa e CPF em varios modelos). A trilha guarda o ATO e o rotulo;
    # replicar o conteudo aqui so multiplicaria dado pessoal numa tabela que
    # ninguem pode apagar por 5 anos — o contrario de minimizacao (LGPD art. 6 III).
    await registrar(
        db, action="documento.create", user=user, request=request,
        target_type="documento", target_id=rid, municipio_id=body.municipio_id,
        alvo_nome=titulo,
        details={"tipo": body.tipo, "titulo": titulo, "status": body.status or "rascunho"},
    )
    return {"id": rid, "created": True}


@router.get("/{doc_id}")
async def detalhe(doc_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    r = (await db.execute(text(
        "SELECT id, municipio_id, tipo, titulo, dados, status, criado_por, created_at, updated_at "
        "FROM documentos_gerados WHERE id = :id"
    ), {"id": doc_id})).first()
    if not r:
        raise HTTPException(404, "Documento não encontrado")
    return _row_to_dict(r)


@router.put("/{doc_id}")
async def atualizar(doc_id: int, body: DocUpdate, request: Request,
                    db: AsyncSession = Depends(get_db),
                    current: User = Depends(get_current_user)):
    sets, params = [], {"id": doc_id}
    if body.titulo is not None:
        sets.append("titulo = :tit"); params["tit"] = body.titulo
    if body.dados is not None:
        sets.append("dados = CAST(:dados AS JSONB)"); params["dados"] = json.dumps(body.dados, ensure_ascii=False)
    if body.status is not None:
        sets.append("status = :st"); params["st"] = body.status
    if not sets:
        return {"updated": False, "reason": "nada para atualizar"}
    ctx = await _doc_contexto(db, doc_id)
    sets.append("updated_at = NOW()")
    res = await db.execute(text(
        f"UPDATE documentos_gerados SET {', '.join(sets)} WHERE id = :id"
    ), params)
    await db.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "Documento não encontrado")
    await registrar(
        db, action="documento.update", user=current, request=request,
        target_type="documento", target_id=doc_id, municipio_id=ctx["municipio_id"],
        alvo_nome=body.titulo or ctx["titulo"],
        details={"tipo": ctx["tipo"], "titulo": body.titulo or ctx["titulo"],
                 "campos": sorted(body.model_dump(exclude_unset=True).keys())},
        # Titulo e status sao os campos cujo VALOR a auditoria precisa: rascunho
        # -> emitido muda o peso do documento. Snapshot completo dos dois lados
        # (o audit reduz ao que mudou); o corpo do PATCH nao serviria.
        valor_antes={"titulo": ctx["titulo"], "status": ctx["status"]},
        valor_depois={"titulo": body.titulo if body.titulo is not None else ctx["titulo"],
                      "status": body.status if body.status is not None else ctx["status"]},
    )
    return {"updated": True}


@router.delete("/{doc_id}")
async def remover(doc_id: int, request: Request,
                  db: AsyncSession = Depends(get_db),
                  current: User = Depends(get_current_user)):
    ctx = await _doc_contexto(db, doc_id)   # depois do DELETE nao ha mais rotulo
    res = await db.execute(text("DELETE FROM documentos_gerados WHERE id = :id"), {"id": doc_id})
    await db.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "Documento não encontrado")
    await registrar(
        db, action="documento.delete", user=current, request=request,
        target_type="documento", target_id=doc_id, municipio_id=ctx["municipio_id"],
        alvo_nome=ctx["titulo"],
        details={"tipo": ctx["tipo"], "titulo": ctx["titulo"], "status": ctx["status"]},
    )
    return {"deleted": True}


@router.get("/{doc_id}/export")
async def exportar(
    doc_id: int,
    request: Request,
    formato: str = Query("pdf", description="pdf | docx"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    r = (await db.execute(text(
        "SELECT id, municipio_id, tipo, titulo, dados FROM documentos_gerados WHERE id = :id"
    ), {"id": doc_id})).first()
    if not r:
        raise HTTPException(404, "Documento não encontrado")
    schema = get_schema(r[2])
    if not schema:
        raise HTTPException(400, "Tipo de documento sem schema")
    dados = r[4] if isinstance(r[4], dict) else (json.loads(r[4]) if r[4] else {})
    mun_nome = mun_uf = ""
    if r[1]:
        mun = (await db.execute(select(Municipio).where(Municipio.id == r[1]))).scalar_one_or_none()
        if mun:
            mun_nome, mun_uf = mun.nome, mun.uf
    base_nome = (r[3] or schema["titulo"]).replace(" ", "_").replace("/", "-")[:60]
    if formato == "docx":
        data = gerar_docx(schema, dados, mun_nome, mun_uf)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        fname = f"{base_nome}.docx"
    else:
        data = gerar_pdf(schema, dados, mun_nome, mun_uf)
        media = "application/pdf"
        fname = f"{base_nome}.pdf"
    # O Word e o PDF do modulo de Documentos saem daqui — e o documento gerado
    # circula fora da plataforma (protocolo, e-mail, orgao). `export.*` para cair
    # no mesmo filtro de "tudo que ja saiu do sistema".
    await registrar(
        db, action="export.documento", user=current, request=request,
        target_type="documento", target_id=doc_id, municipio_id=r[1], alvo_nome=fname,
        details={"formato": "docx" if formato == "docx" else "pdf",
                 "tipo": r[2], "titulo": r[3], "arquivo": fname,
                 "municipio": f"{mun_nome}/{mun_uf}".strip("/") or None,
                 "tamanho_bytes": len(data)},
    )
    return StreamingResponse(io.BytesIO(data), media_type=media,
        headers={"Content-Disposition": f"attachment; filename={fname}"})
