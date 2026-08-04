"""Módulo "Geração de Documentos".

CRUD de documentos preenchidos na plataforma + exportação DOCX/PDF.
O formulário é dirigido pelo schema (services/documentos_schema.py), então o
frontend renderiza dinamicamente e os renders (docx/pdf) iteram o mesmo schema.

PERMISSÃO (o que este módulo exige, e por quê são DUAS coisas)
--------------------------------------------------------------
Até agora só `GET /api/documentos` (a lista) checava alguma coisa: criar, ler,
editar, apagar e EXPORTAR um documento bastava estar logado. Um usuário criado
com zero telas e zero municípios apagava o documento de qualquer prefeitura
chamando a API direto.

Cada endpoint passa a exigir os dois recortes, que respondem a perguntas
diferentes:

  `authz.exigir_tela(user, "documentos")`  -> a pessoa trabalha com este MÓDULO?
  `authz.ensure_dono(...)`           -> ESTE documento é de um município que
                                        ela alcança? Ter a tela não diz nada
                                        sobre a linha: sem a segunda checagem,
                                        quem tem "documentos" tem os documentos
                                        do tenant inteiro.

⚠️ NADA DISSO BARRA HOJE. `AUTHZ_MODO=aviso` (o default) apenas REGISTRA "eu
teria negado isto" na trilha e deixa passar — o comportamento é idêntico ao de
antes. Só `AUTHZ_MODO=bloqueio` levanta 403. Ver services/authz.py.

E há uma TERCEIRA pergunta, declarada em cada rota com `exige(...)`:

  `documentos.ver` / `criar` / `editar` / `excluir` / `exportar`
                                     -> o que ela FAZ neste módulo? Ter a tela
                                        `documentos` sempre significou poder
                                        apagar o documento de quem quer que
                                        fosse; a declaração é o que passa a
                                        separar consultar de escrever.

ALCANCE POR LINHA (Incremento 6 — `authz.exigir_dono_da_linha`)
---------------------------------------------------------------
Um usuário pode ser configurado, POR MÓDULO, como "somente os que ele criou":
aí ele só ALTERA e APAGA o documento que ele mesmo criou. Continua VENDO e
EXPORTANDO os do município inteiro — decisão do dono. O gate mora em
`_exigir_escrita` (PUT e DELETE); a lista devolve `pode_editar`/`pode_excluir`
por item, para o botão sumir.
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
from services import authz
from services.registro_rotas import exige
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


async def _exigir_acesso(db: AsyncSession, doc_id: int, user) -> None:
    """Os dois recortes de todo endpoint que fala de UM documento.

    Num lugar só porque são quatro (ler, editar, apagar, exportar) e porque o
    nome da tabela vira literal de SQL lá dentro: uma cópia divergente é uma
    porta que continua aberta sem ninguém notar.

    Em `AUTHZ_MODO=aviso` nenhuma das duas levanta — registram e voltam. E a
    ordem importa pouco na prática, mas é deliberada: a tela é a pergunta mais
    barata (não toca o banco) e a mais provável de faltar."""
    authz.exigir_tela(user, "documentos")
    # Devolve o município da linha; aqui não usamos o retorno — quem decide o
    # 404 continua sendo o endpoint, com a consulta dele.
    await authz.ensure_dono(db, "documentos_gerados", "id", doc_id, user)


async def _exigir_escrita(db: AsyncSession, doc_id: int, user) -> None:
    """O acesso ao documento MAIS o alcance por linha (Incremento 6).

    Só nos DOIS endpoints de escrita (editar e apagar). Ler e EXPORTAR seguem
    com `_exigir_acesso` puro: a decisão do dono é que o alcance vale só para
    escrita — quem está em "somente os que ele criou" continua vendo e baixando
    o Word de todo o município.

    Custo para quem NÃO foi restringido: zero consulta a mais — `escopo_de`
    volta `todos` antes de tocar no banco."""
    await _exigir_acesso(db, doc_id, user)
    await authz.exigir_dono_da_linha(db, "documentos", doc_id, user)


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


def _row_to_dict(r, usuario) -> dict:
    """⭐ `usuario` é OBRIGATÓRIO desde o Incremento 6 — ver o mesmo helper em
    routers/gestao.py: a resposta passa a dizer, POR ITEM, se quem pediu pode
    alterar aquela linha. Botão escondido NÃO é permissão; quem barra continua
    sendo `authz.exigir_dono_da_linha` no endpoint de escrita."""
    criado_por = r[6]
    return {
        "id": r[0], "municipio_id": r[1], "tipo": r[2], "titulo": r[3],
        "dados": r[4] if isinstance(r[4], dict) else (json.loads(r[4]) if r[4] else {}),
        "status": r[5], "criado_por": criado_por,
        "created_at": r[7].isoformat() if r[7] else None,
        "updated_at": r[8].isoformat() if r[8] else None,
        "pode_editar": authz.pode_editar_item(usuario, "documentos", "editar", criado_por),
        "pode_excluir": authz.pode_editar_item(usuario, "documentos", "excluir", criado_por),
    }


@router.get("/schemas", dependencies=[exige("documentos.ver")])
async def schemas(current: User = Depends(get_current_user)):
    """Tipos de documento disponíveis (p/ o menu 'Novo documento')."""
    # Catálogo estático, sem dado de prefeitura nenhuma — mas é a porta do menu
    # "Novo documento". Só a tela: não há município a julgar aqui.
    authz.exigir_tela(current, "documentos")
    return {"items": listar_tipos()}


@router.get("/schema/{tipo}", dependencies=[exige("documentos.ver")])
async def schema_de(tipo: str, current: User = Depends(get_current_user)):
    # `tipo` é chave de um dicionário em código (services/documentos_schema.py),
    # não id de linha: não há dono a checar, só a tela do módulo.
    authz.exigir_tela(current, "documentos")
    s = get_schema(tipo)
    if not s:
        raise HTTPException(404, f"Tipo de documento desconhecido: {tipo}")
    return s


@router.get("", dependencies=[exige("documentos.ver")])
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
    return {"items": [_row_to_dict(r, current) for r in rows], "total": len(rows)}


@router.post("", dependencies=[exige("documentos.criar")])
async def criar(
    body: DocCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    authz.exigir_tela(user, "documentos")
    # ⚠️ SÓ julga o município quando HÁ município no pedido, e a guarda não é
    # zelo: `documentos_gerados.municipio_id` é NULL-able e o editor manda
    # `municipio_id: null` quando nenhuma prefeitura está selecionada
    # (frontend .../dashboard/documentos/editor/page.tsx). Município ausente é
    # PEDIDO MALFORMADO para `ensure_municipio_access`, que o nega nos DOIS
    # modos (ver services/authz.py) — chamar sem esta guarda criaria um 403 NOVO
    # já em modo aviso, que é o único defeito que este incremento não pode ter.
    # O documento órfão que nasce daí não fica invisível: qualquer endpoint que
    # o abra depois registra `authz.sem_dono`.
    if body.municipio_id is not None:
        authz.exigir_municipio(user, body.municipio_id)
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


@router.get("/{doc_id}", dependencies=[exige("documentos.ver")])
async def detalhe(doc_id: int, db: AsyncSession = Depends(get_db),
                  current: User = Depends(get_current_user)):
    await _exigir_acesso(db, doc_id, current)
    r = (await db.execute(text(
        "SELECT id, municipio_id, tipo, titulo, dados, status, criado_por, created_at, updated_at "
        "FROM documentos_gerados WHERE id = :id"
    ), {"id": doc_id})).first()
    if not r:
        raise HTTPException(404, "Documento não encontrado")
    return _row_to_dict(r, current)


@router.put("/{doc_id}", dependencies=[exige("documentos.editar")])
async def atualizar(doc_id: int, body: DocUpdate, request: Request,
                    db: AsyncSession = Depends(get_db),
                    current: User = Depends(get_current_user)):
    await _exigir_escrita(db, doc_id, current)
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


@router.delete("/{doc_id}", dependencies=[exige("documentos.excluir")])
async def remover(doc_id: int, request: Request,
                  db: AsyncSession = Depends(get_db),
                  current: User = Depends(get_current_user)):
    await _exigir_escrita(db, doc_id, current)
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


@router.get("/{doc_id}/export", dependencies=[exige("documentos.exportar")])
async def exportar(
    doc_id: int,
    request: Request,
    formato: str = Query("pdf", description="pdf | docx"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # A exportação é a porta por onde o documento SAI da plataforma (protocolo,
    # e-mail, órgão). Mesmo gate das outras: ler o Word de outra prefeitura não
    # é menos grave por ser leitura.
    await _exigir_acesso(db, doc_id, current)
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
