"""Relatorio de Monitoramento (RM) - CRUD + auto-popular + PDF.

Endpoints:
  GET    /api/rm?municipio_id=         lista RMs
  POST   /api/rm                       cria novo (com option auto_popular)
  GET    /api/rm/{id}                  detalhe completo
  PUT    /api/rm/{id}                  atualiza meta + conteudo
  POST   /api/rm/{id}/auto-popular     repreenche conteudo com dados atuais do DB
  DELETE /api/rm/{id}                  remove
  GET    /api/rm/{id}/pdf              gera o PDF (download)
"""
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import json
from config import get_settings
from database import get_db
from models import Municipio
from services.auth import get_current_user, ensure_municipio_access, ensure_tela
from models.user import User
from services.audit import registrar
from services.rm_builder import montar_conteudo
from services.rm_pdf import gerar_pdf
from services.rm_export import (
    gerar_totalizado_xlsx, gerar_totalizado_pdf, gerar_resumido_pdf,
)

router = APIRouter(prefix="/api/rm", tags=["rm"])


async def _rm_contexto(db: AsyncSession, rid: int) -> dict:
    """Municipio e titulo do RM, para a trilha.

    Os endpoints de alteracao trabalham so com o id; sem esta leitura o registro
    sairia sem `municipio_id` (impossivel recortar a auditoria por prefeitura) e
    sem um rotulo que um leigo reconheca. Nao levanta 404 de proposito: quem
    decide o que fazer com RM inexistente e o endpoint, nao a auditoria — a
    trilha nao pode mudar o comportamento de nenhuma rota."""
    row = (await db.execute(text(
        "SELECT municipio_id, titulo, data_referencia, status FROM rm_relatorios WHERE id = :id"
    ), {"id": rid})).first()
    if not row:
        return {"municipio_id": None, "titulo": None, "data_referencia": None, "status": None}
    return {"municipio_id": row[0], "titulo": row[1],
            "data_referencia": row[2].isoformat() if row[2] else None,
            "status": row[3]}


class RmCreate(BaseModel):
    municipio_id: int
    data_referencia: date
    # Sem default fixo: quem nao mandar cidade recebe a do PROPRIO municipio
    # do RM (ver `criar`). Estava "Brasília/DF" — a cidade da consultoria que
    # originou o modulo — e carimbava relatorio de municipio de Minas.
    cidade_emissao: Optional[str] = None
    titulo: Optional[str] = None
    auto_popular: bool = True


class RmUpdate(BaseModel):
    data_referencia: Optional[date] = None
    cidade_emissao: Optional[str] = None
    titulo: Optional[str] = None
    rodape: Optional[str] = None
    status: Optional[str] = None
    conteudo: Optional[dict] = None


async def _get_municipio(db: AsyncSession, municipio_id: int) -> Municipio:
    from sqlalchemy import select
    m = (await db.execute(select(Municipio).where(Municipio.id == municipio_id))).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Município não encontrado")
    return m


def _row_to_dict(row) -> dict:
    return {
        "id": row[0], "municipio_id": row[1], "data_referencia": row[2].isoformat() if row[2] else None,
        "cidade_emissao": row[3], "titulo": row[4], "rodape": row[5],
        "status": row[6], "conteudo": row[7] or {"partes": []},
        "criado_por": row[8],
        "created_at": row[9].isoformat() if row[9] else None,
        "updated_at": row[10].isoformat() if row[10] else None,
    }


@router.get("")
async def listar(
    municipio_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "rm")
    where = []
    params: dict = {}
    if municipio_id:
        where.append("r.municipio_id = :m"); params["m"] = municipio_id
    sql = f"""
        SELECT r.id, r.municipio_id, r.data_referencia, r.cidade_emissao,
               r.titulo, r.rodape, r.status, NULL, r.criado_por,
               r.created_at, r.updated_at, m.nome AS municipio_nome
        FROM rm_relatorios r LEFT JOIN municipios m ON m.id = r.municipio_id
        {('WHERE ' + ' AND '.join(where)) if where else ''}
        ORDER BY r.data_referencia DESC, r.id DESC
    """
    rs = (await db.execute(text(sql), params)).fetchall()
    items = []
    for row in rs:
        d = _row_to_dict(row)
        d["municipio_nome"] = row[11]
        items.append(d)
    return {"items": items, "total": len(items)}


@router.post("")
async def criar(
    body: RmCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    mun = await _get_municipio(db, body.municipio_id)
    # ano de emissão = ano da data de referência (janela do relatório por ANO)
    _ano = None
    try:
        _dr = body.data_referencia
        _ano = _dr.year if hasattr(_dr, "year") else int(str(_dr)[:4])
    except (ValueError, TypeError):
        _ano = None
    conteudo = await montar_conteudo(db, body.municipio_id, _ano) if body.auto_popular else {"partes": []}
    titulo = body.titulo or f"RELATÓRIO DE MONITORAMENTO – {mun.nome.upper()}/{mun.uf}"
    # O INSERT abaixo e um UPSERT (ON CONFLICT em municipio+data): a mesma chamada
    # cria OU sobrescreve. Registrar tudo como "criou" faria a trilha mentir
    # justamente no caso que interessa — o relatorio que ja existia e foi
    # substituido. Uma leitura barata antes resolve, sem mexer na escrita.
    ja_existia = (await db.execute(text(
        "SELECT 1 FROM rm_relatorios WHERE municipio_id = :m AND data_referencia = :d"
    ), {"m": body.municipio_id, "d": body.data_referencia})).first() is not None
    # ON CONFLICT: se ja existe RM nessa data, atualiza conteudo
    sql = text("""
        INSERT INTO rm_relatorios
            (municipio_id, data_referencia, cidade_emissao, titulo, conteudo, criado_por, rodape)
        VALUES (:mun, :dt, :cidade, :titulo, CAST(:cont AS JSONB), :usr, :rodape)
        ON CONFLICT (municipio_id, data_referencia) DO UPDATE SET
            titulo = EXCLUDED.titulo,
            cidade_emissao = EXCLUDED.cidade_emissao,
            rodape = EXCLUDED.rodape,
            conteudo = CASE WHEN :overwrite THEN EXCLUDED.conteudo
                            ELSE rm_relatorios.conteudo END,
            updated_at = NOW()
        RETURNING id
    """)
    # A cidade de emissao e a do PROPRIO municipio do relatorio. `mun` ja esta
    # carregado aqui, entao nao custa consulta nenhuma — e e a unica fonte que
    # nao pode estar errada. So um valor explicito do usuario sobrepoe.
    cidade = (body.cidade_emissao or "").strip() or f"{mun.nome}/{mun.uf}"
    rid = (await db.execute(sql, {
        "mun": body.municipio_id, "dt": body.data_referencia,
        "cidade": cidade, "titulo": titulo, "rodape": get_settings().RM_RODAPE,
        "cont": json.dumps(conteudo), "usr": getattr(user, "id", None),
        "overwrite": body.auto_popular,
    })).scalar()
    await db.commit()
    await registrar(
        db, action=("rm.update" if ja_existia else "rm.create"),
        user=user, request=request,
        target_type="rm", target_id=rid, municipio_id=body.municipio_id,
        alvo_nome=titulo,
        details={"titulo": titulo, "municipio": f"{mun.nome}/{mun.uf}",
                 "data_referencia": str(body.data_referencia),
                 "cidade_emissao": cidade, "auto_popular": body.auto_popular,
                 "via": "upsert", "conteudo_substituido": ja_existia and body.auto_popular},
    )
    return {"id": rid, "created": True}


@router.get("/{rid}")
async def detalhe(
    rid: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    row = (await db.execute(text("""
        SELECT r.id, r.municipio_id, r.data_referencia, r.cidade_emissao,
               r.titulo, r.rodape, r.status, r.conteudo, r.criado_por,
               r.created_at, r.updated_at, m.nome AS municipio_nome, m.uf
        FROM rm_relatorios r LEFT JOIN municipios m ON m.id = r.municipio_id
        WHERE r.id = :id
    """), {"id": rid})).first()
    if not row:
        raise HTTPException(404, "RM não encontrado")
    d = _row_to_dict(row)
    d["municipio_nome"] = row[11]
    d["uf"] = row[12]
    return d


@router.put("/{rid}")
async def atualizar(
    rid: int,
    body: RmUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    sets = []
    params: dict = {"id": rid}
    if body.data_referencia is not None:
        sets.append("data_referencia = :dt"); params["dt"] = body.data_referencia
    if body.cidade_emissao is not None:
        sets.append("cidade_emissao = :cid"); params["cid"] = body.cidade_emissao
    if body.titulo is not None:
        sets.append("titulo = :tit"); params["tit"] = body.titulo
    if body.rodape is not None:
        sets.append("rodape = :rod"); params["rod"] = body.rodape
    if body.status is not None:
        sets.append("status = :sta"); params["sta"] = body.status
    if body.conteudo is not None:
        sets.append("conteudo = CAST(:cont AS JSONB)"); params["cont"] = json.dumps(body.conteudo)
    if not sets:
        return {"updated": False, "reason": "nada para atualizar"}
    ctx = await _rm_contexto(db, rid)
    sets.append("updated_at = NOW()")
    sql = text(f"UPDATE rm_relatorios SET {', '.join(sets)} WHERE id = :id")
    await db.execute(sql, params)
    await db.commit()
    # `campos` e a lista do que o usuario tocou. O conteudo do relatorio NAO vai
    # para a trilha: sao dezenas de KB de JSON por edicao, e a auditoria e sobre o
    # ATO ("editou o RM de julho de Monte Siao"), nao sobre versionar documento.
    await registrar(
        db, action="rm.update", user=current, request=request,
        target_type="rm", target_id=rid, municipio_id=ctx["municipio_id"],
        alvo_nome=body.titulo or ctx["titulo"],
        details={"titulo": body.titulo or ctx["titulo"],
                 "data_referencia": ctx["data_referencia"],
                 "campos": sorted(body.model_dump(exclude_unset=True).keys())},
        # Status e o unico campo cujo VALOR interessa a auditoria (rascunho ->
        # emitido muda o peso do documento). Snapshot completo dos dois lados,
        # como o audit pede — nao o corpo do PATCH.
        valor_antes={"status": ctx["status"]},
        valor_depois={"status": body.status if body.status is not None else ctx["status"]},
    )
    return {"updated": True}


@router.post("/{rid}/auto-popular")
async def repopular(
    rid: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Substitui conteudo pelo gerado automaticamente a partir do DB atual."""
    row = (await db.execute(text(
        "SELECT municipio_id, data_referencia, titulo FROM rm_relatorios WHERE id = :id"
    ), {"id": rid})).first()
    if not row:
        raise HTTPException(404, "RM não encontrado")
    _ano = row[1].year if row[1] and hasattr(row[1], "year") else None
    conteudo = await montar_conteudo(db, row[0], _ano)
    await db.execute(text(
        "UPDATE rm_relatorios SET conteudo = CAST(:c AS JSONB), updated_at = NOW() WHERE id = :id"
    ), {"c": json.dumps(conteudo), "id": rid})
    await db.commit()
    n_partes = len(conteudo.get("partes", []))
    n_itens = sum(len(it.get("itens", []))
                  for p in conteudo.get("partes", [])
                  for s in p.get("secoes", [])
                  for it in s.get("grupos", []))
    # Repopular DESCARTA a redacao manual do relatorio. Fica como evento proprio
    # (nao como "rm.update") porque a pergunta que aparece depois e sempre a
    # mesma: "quem apagou o que eu tinha escrito, e quando".
    await registrar(
        db, action="rm.auto_popular", user=current, request=request,
        target_type="rm", target_id=rid, municipio_id=row[0], alvo_nome=row[2],
        details={"partes": n_partes, "itens": n_itens,
                 "data_referencia": row[1].isoformat() if row[1] else None,
                 "efeito": "conteudo anterior substituido pelos dados atuais"},
    )
    return {"ok": True, "partes": n_partes, "itens": n_itens}


@router.delete("/{rid}")
async def remover(
    rid: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # Contexto lido ANTES do DELETE: depois a linha nao existe mais e o registro
    # sairia como "apagou o RM 47" — um numero que nao diz nada a ninguem.
    ctx = await _rm_contexto(db, rid)
    r = await db.execute(text("DELETE FROM rm_relatorios WHERE id = :id"), {"id": rid})
    await db.commit()
    if r.rowcount == 0:
        raise HTTPException(404, "RM não encontrado")
    await registrar(
        db, action="rm.delete", user=current, request=request,
        target_type="rm", target_id=rid, municipio_id=ctx["municipio_id"],
        alvo_nome=ctx["titulo"],
        details={"titulo": ctx["titulo"], "data_referencia": ctx["data_referencia"]},
    )
    return {"deleted": True}


@router.get("/{rid}/pdf")
async def pdf(
    rid: int,
    request: Request,
    tipo: str = Query("completo", description="completo | resumido | totalizado"),
    formato: str = Query("pdf", description="pdf | xlsx (xlsx só p/ totalizado)"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    row = (await db.execute(text("""
        SELECT r.data_referencia, r.cidade_emissao, r.titulo, r.rodape, r.conteudo, m.nome, m.uf,
               r.municipio_id
        FROM rm_relatorios r JOIN municipios m ON m.id = r.municipio_id
        WHERE r.id = :id
    """), {"id": rid})).first()
    if not row:
        raise HTTPException(404, "RM não encontrado")
    meta = {
        "data_referencia": row[0],
        "cidade_emissao": row[1],
        "titulo": row[2],
        "rodape": row[3],
    }
    conteudo = row[4] or {"partes": []}
    municipio = f"{row[5]}/{row[6]}"
    dt_str = row[0].strftime("%d-%m-%Y") if row[0] else "sem-data"
    tipo = (tipo or "completo").lower()
    formato = (formato or "pdf").lower()

    async def _registrar_export(nome_arquivo: str, fmt: str, variante: str):
        """Toda saida deste endpoint passa por aqui.

        Exportacao e o momento em que o dado deixa a tela e vira arquivo que anda
        sozinho — e, para a LGPD, o evento mais importante de rastrear. Fica sob o
        prefixo `export.` de proposito: um filtro so ("action comeca com export.")
        lista tudo o que ja saiu do sistema, venha de onde vier.

        `registrar` e nao `registrar_critico`: o PDF e leitura de dado que o
        usuario ja tem na tela — derrubar o download por falha de trilha nao
        impede exfiltracao nenhuma (ele fotografa a tela), so quebra o trabalho de
        quem nao fez nada de errado. O que nao pode acontecer em silencio e
        CONCEDER PODER; ver o que ja se ve, nao."""
        await registrar(
            db, action="export.rm", user=current, request=request,
            target_type="rm", target_id=rid, municipio_id=row[7],
            details={"formato": fmt, "variante": variante, "arquivo": nome_arquivo,
                     "titulo": row[2], "municipio": municipio,
                     "data_referencia": row[0].isoformat() if row[0] else None},
        )

    # Totalizado em Excel
    if tipo == "totalizado" and formato == "xlsx":
        conteudo_bytes = gerar_totalizado_xlsx(meta, conteudo, municipio)
        nome = f"RM-Totalizado-{row[5]}-{dt_str}.xlsx".replace(" ", "_")
        await _registrar_export(nome, "xlsx", "totalizado")
        return Response(
            content=conteudo_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{nome}"'},
        )

    if tipo == "totalizado":
        pdf_bytes = gerar_totalizado_pdf(meta, conteudo, municipio)
        rotulo = "Totalizado"
    elif tipo == "resumido":
        pdf_bytes = gerar_resumido_pdf(meta, conteudo, municipio)
        rotulo = "Resumido"
    else:
        pdf_bytes = gerar_pdf(meta, conteudo, municipio)
        rotulo = "Completo"

    nome = f"RM-{rotulo}-{row[5]}-{dt_str}.pdf".replace(" ", "_")
    await _registrar_export(nome, "pdf", rotulo.lower())
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nome}"'},
    )
