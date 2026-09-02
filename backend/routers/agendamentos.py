"""AGENDAMENTOS — a agenda de trabalho da equipe, por município.

Todo o resto da plataforma mostra dado que vem de fora. Este é o único módulo em
que a equipe ESCREVE: o compromisso marcado, quem é o responsável, o que foi
feito e o documento que sobrou daquilo.

⭐ TRÊS VISUALIZAÇÕES, UMA CONSULTA SÓ. Lista, calendário e kanban leem as mesmas
linhas com os mesmos filtros — o que muda é o desenho na tela, não o recorte. Por
isso não existe endpoint "de calendário" nem "de kanban": eles pediriam três
consultas para manter em sincronia, e a primeira a divergir mostraria um
agendamento que as outras duas escondem.

⚠️ A EXPORTAÇÃO USA A MESMA FUNÇÃO DE FILTRO DA LISTA, e é o motivo de ela morar
aqui e não em `routers/export_pdf.py` com as outras seis. O dono pediu "exportar
a relação conforme o filtro": se a exportação montasse a própria consulta, um
ajuste no filtro da tela deixaria o arquivo desalinhado com o que a pessoa está
vendo — e um relatório que não bate com a tela é pior que nenhum, porque ninguém
descobre pela tela qual dos dois está certo.

⚠️ ANEXO TEM PERMISSÃO PRÓPRIA (`agendamentos.anexo_baixar`), pela mesma razão do
módulo de Gestão: a lista mostra QUE existe um anexo, esta caixinha entrega o
ARQUIVO — que pode ser ofício, contrato ou documento pessoal. Ver que existe não
é ver o conteúdo.

⚠️ E O `dados_b64` NUNCA SAI NA LISTAGEM. Uma agenda de mês com trinta cartões,
cada um com um PDF em base64, viraria um payload de dezenas de megabytes para
desenhar uma grade de calendário. A lista manda só o metadado; o arquivo sai
pela rota de download, uma requisição por vez, e com a permissão própria.
"""
from __future__ import annotations

import base64
import json
from datetime import date
from io import BytesIO
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services import authz
from services.audit import registrar
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.registro_rotas import exige

router = APIRouter(prefix="/api/agendamentos", tags=["agendamentos"])

# ⚠️ MESMO TETO DO MÓDULO DE GESTÃO, e o número é do base64 (que é ~33% maior
# que o binário). Dois módulos com limites diferentes para o mesmo tipo de
# arquivo fariam a pessoa aprender o limite errado num e ser recusada no outro.
MAX_ANEXO_BYTES = 2 * 1024 * 1024  # 2MB base64 ≈ 1,5MB de arquivo

# As três colunas do kanban. A ordem É a do quadro, da esquerda para a direita.
# ⚠️ Tem de bater com o CHECK da migration `add_agendamentos.sql`: um valor aqui
# que o banco recuse vira 500 na cara do usuário; um valor no banco que não
# esteja aqui some do quadro sem erro nenhum.
STATUS = ("a_fazer", "em_andamento", "realizado")
STATUS_ROTULO = {"a_fazer": "A fazer", "em_andamento": "Em andamento",
                 "realizado": "Realizado"}


class Anexo(BaseModel):
    nome: str = Field(..., max_length=255)
    mime: str = Field(..., max_length=100)
    dados_b64: str
    tamanho: Optional[int] = None  # bytes do binário, antes do base64


class AgendamentoCreate(BaseModel):
    municipio_id: int
    titulo: str = Field(..., min_length=1, max_length=200)
    data: date
    relato: Optional[str] = None
    responsavel_id: Optional[int] = None
    status: str = "a_fazer"
    anexos: list[Anexo] = Field(default_factory=list)


class AgendamentoUpdate(BaseModel):
    titulo: Optional[str] = Field(None, min_length=1, max_length=200)
    data: Optional[date] = None
    relato: Optional[str] = None
    responsavel_id: Optional[int] = None
    status: Optional[str] = None
    anexos: Optional[list[Anexo]] = None


class StatusUpdate(BaseModel):
    """⚠️ ROTA PRÓPRIA PARA O KANBAN, e não o PUT inteiro.

    Arrastar um cartão de coluna muda UMA coisa. Mandar o objeto completo faria
    o front reenviar `anexos` a cada arrastada — os mesmos megabytes de base64,
    de ida e de volta —, e um cartão arrastado a partir de uma tela carregada há
    dez minutos sobrescreveria com dado velho o relato que outra pessoa acabou
    de editar. Um PATCH de um campo não tem como fazer isso."""
    status: str


def _valida(body: AgendamentoCreate | AgendamentoUpdate | StatusUpdate) -> None:
    st = getattr(body, "status", None)
    if st is not None and st not in STATUS:
        raise HTTPException(422, f"Status inválido: {st!r}. Use um de {list(STATUS)}.")
    for a in (getattr(body, "anexos", None) or []):
        if len(a.dados_b64) > MAX_ANEXO_BYTES:
            raise HTTPException(
                413, f"Anexo '{a.nome}' excede o limite de "
                     f"{MAX_ANEXO_BYTES // 1024}KB (base64).")


def _rotulo_anexos(anexos) -> list:
    """Metadado dos anexos para a trilha — NUNCA o `dados_b64`.

    Copiar o base64 para o `audit_log` duplicaria megabytes numa tabela que, por
    decisão do dono, não se apaga. Mesma regra do módulo de Gestão."""
    return [{"nome": a.get("nome"), "mime": a.get("mime"),
             "tamanho": a.get("tamanho")} for a in (anexos or [])]


# ⚠️ A ORDEM DAS COLUNAS AQUI É LIDA POR ÍNDICE em `_row_to_dict`. Coluna nova
# entra no FIM — é a regra da casa, e o defeito que ela evita (todo campo depois
# do inserido passa a ler o vizinho) não levanta erro: só troca os valores de
# lugar na tela.
_SELECT = """
    -- ⚠️ `users.name`, E NAO `users.nome`. As duas tabelas usam vocabulario
    -- diferente e isso ja custou um erro em producao: `municipios` tem `nome`
    -- (portugues) e `users` tem `name` (ingles). O `pglast` valida a GRAMATICA
    -- do SQL e nao o ESQUEMA, entao `ur.nome` passou por toda a suite e so
    -- apareceu como ProgrammingError na tela do cliente. Ver
    -- `test_agendamentos.py::test_o_select_so_usa_coluna_que_existe_no_modelo`.
    SELECT a.id, a.municipio_id, m.nome, a.responsavel_id, ur.name,
           a.titulo, a.relato, a.data, a.status, a.anexos,
           a.criado_por, uc.name, a.created_at, a.updated_at
      FROM agendamentos a
      JOIN municipios m ON m.id = a.municipio_id
      LEFT JOIN users ur ON ur.id = a.responsavel_id
      LEFT JOIN users uc ON uc.id = a.criado_por
"""


def _row_to_dict(row, *, with_anexos: bool = False) -> dict:
    """⚠️ O PADRAO E `False` — o lado SEGURO. Quem esquecer o argumento omite o
    `dados_b64` em vez de vaza-lo, e vazar aqui anula a permissao
    `agendamentos.anexo_baixar`: quem tem so `ver` ja teria recebido o arquivo.
    Hoje NENHUMA chamada pede `True`; o parametro existe para que um dia pedir
    seja uma decisao escrita, e nao um descuido."""
    anexos = row[9] or []
    if not with_anexos:
        anexos = [{k: v for k, v in a.items() if k != "dados_b64"} for a in anexos]
    return {
        "id": row[0],
        "municipio_id": row[1],
        "municipio": row[2],
        "responsavel_id": row[3],
        "responsavel": row[4],
        "titulo": row[5],
        "relato": row[6],
        "data": row[7].isoformat() if row[7] else None,
        "status": row[8],
        "status_rotulo": STATUS_ROTULO.get(row[8], row[8]),
        "anexos": anexos,
        "criado_por": row[10],
        "criado_por_nome": row[11],
        "created_at": row[12].isoformat() if row[12] else None,
        "updated_at": row[13].isoformat() if row[13] else None,
    }


def _filtros(municipio_id, de, ate, status, responsavel_id,
             municipios_permitidos=None) -> tuple[str, dict]:
    """O WHERE compartilhado pela lista E pela exportação.

    ⚠️ FUNÇÃO ÚNICA DE PROPÓSITO. É o que garante que o arquivo exportado tenha
    exatamente as linhas que a tela mostra. Duas montagens de filtro divergem no
    primeiro ajuste, e a divergência aparece como "o relatório veio com um
    agendamento a mais" — sem nada para culpar.

    ⚠️ `municipios_permitidos` É O RECORTE DO PEDIDO "TODOS", e ele existe
    porque a primeira versão deste módulo mentia sobre ele. O comentário da tela
    dizia que, sem `municipio_id`, "o backend devolve o que o alcance da pessoa
    permite" — e não devolvia: não havia recorte nenhum aqui, e o que impedia o
    tenant inteiro de sair era o 403 de `ensure_municipio_access(user, None)`.
    Ou seja, a opção «Todos os meus municípios» respondia 403 para TODO usuário
    que não fosse o super-admin da Alavank, que é o único com carteira `None`.

    Agora o pedido "todos" significa **todos OS MEUS**, com o mesmo desenho do
    `routers/convenios.py` (que já resolvia isto): carteira restrita vira um
    `IN`, carteira `None` (super-admin) não filtra, e carteira VAZIA devolve
    lista vazia — nunca o tenant inteiro.
    """
    where, params = [], {}
    if municipio_id:
        where.append("a.municipio_id = :m"); params["m"] = municipio_id
    elif municipios_permitidos is not None:
        # ⚠️ `= ANY(:mids)` e não `IN :mids`: o SQLAlchemy só expande `IN` com
        # `expanding=True`, e sem isso a lista chega como um parâmetro só.
        where.append("a.municipio_id = ANY(:mids)")
        params["mids"] = list(municipios_permitidos)
    if de:
        where.append("a.data >= :de"); params["de"] = de
    if ate:
        where.append("a.data <= :ate"); params["ate"] = ate
    if status:
        where.append("a.status = :s"); params["s"] = status
    if responsavel_id:
        where.append("a.responsavel_id = :r"); params["r"] = responsavel_id
    return (" WHERE " + " AND ".join(where) if where else ""), params


def _carteira(current, municipio_id):
    """O recorte de município de um pedido de LEITURA em lote.

    Devolve `(permitidos, vazia)`:
      - `municipio_id` presente  -> (None, False): o filtro é ele, e quem valida
        o acesso é `ensure_municipio_access`, chamado pelo endpoint.
      - ausente, carteira restrita -> (a carteira, False): "todos os MEUS".
      - ausente, super-admin       -> (None, False): sem filtro, é o alcance dele.
      - ausente, carteira VAZIA    -> (None, True): não há o que listar. Devolver
        sem filtro aqui seria entregar o tenant inteiro a quem não alcança
        município nenhum.
    """
    if municipio_id:
        return None, False
    permitidos = getattr(current, "allowed_municipio_ids", None)
    if permitidos is None:
        return None, False
    if not permitidos:
        return None, True
    return list(permitidos), False


async def _exigir_acesso(db: AsyncSession, aid: int, user) -> None:
    """Os dois recortes de todo endpoint que fala de UM agendamento.

    Num lugar só porque são quatro (ler, editar, apagar, baixar anexo) e porque o
    nome da tabela vira literal de SQL lá dentro: uma cópia divergente é uma
    porta que continua aberta sem ninguém notar. Mesmo desenho do `gestao`."""
    authz.exigir_tela(user, "agendamentos")
    await authz.ensure_dono(db, "agendamentos", "id", aid, user)


async def _contexto(db: AsyncSession, aid: int) -> dict:
    """Município e título da linha, para a trilha de auditoria dizer SOBRE QUAL."""
    row = (await db.execute(text(
        "SELECT municipio_id, titulo, data FROM agendamentos WHERE id = :id"
    ), {"id": aid})).first()
    if not row:
        return {}
    return {"municipio_id": row[0], "titulo": row[1],
            "data": row[2].isoformat() if row[2] else None}


# ---------------------------------------------------------------- leitura ---

@router.get("/status-opcoes", dependencies=[exige("agendamentos.ver")])
async def status_opcoes(current: User = Depends(get_current_user)):
    """As colunas do kanban, na ordem, com o rótulo que a tela mostra.

    Vem do backend para a tela não ter uma segunda lista de status: duas listas
    divergem, e a divergência esconde cartão."""
    ensure_tela(current, "agendamentos")
    return {"opcoes": [{"valor": s, "rotulo": STATUS_ROTULO[s]} for s in STATUS]}


@router.get("", dependencies=[exige("agendamentos.ver")])
async def listar(
    municipio_id: Optional[int] = Query(None),
    de: Optional[date] = Query(None, description="data inicial (inclusive)"),
    ate: Optional[date] = Query(None, description="data final (inclusive)"),
    status: Optional[str] = Query(None),
    responsavel_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """A relação filtrada. Alimenta as TRÊS visualizações."""
    # ⚠️ `ensure_municipio_access` SÓ COM MUNICÍPIO ESCOLHIDO. Chamada com None
    # ela levanta 403 ("Selecione um municipio permitido") para todo usuário de
    # carteira restrita — o que matava a opção «Todos os meus municípios».
    # Quando não há município, quem faz o recorte é `_carteira`, abaixo.
    if municipio_id:
        ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "agendamentos")
    if status and status not in STATUS:
        raise HTTPException(422, f"Status inválido: {status!r}")
    permitidos, vazia = _carteira(current, municipio_id)
    if vazia:
        return {"items": [], "total": 0}
    onde, params = _filtros(municipio_id, de, ate, status, responsavel_id,
                            permitidos)
    # ⚠️ ORDEM CRESCENTE de data. A lista é uma AGENDA: o que vem primeiro é o
    # que acontece primeiro. As outras telas do repo ordenam por `updated_at
    # DESC` porque mostram histórico — aqui isso poria o mês que vem no topo.
    sql = _SELECT + onde + " ORDER BY a.data ASC, a.id ASC"
    rows = (await db.execute(text(sql), params)).fetchall()
    return {"items": [_row_to_dict(r) for r in rows],
            "total": len(rows)}


@router.get("/{aid}", dependencies=[exige("agendamentos.ver")])
async def detalhe(
    aid: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    await _exigir_acesso(db, aid, current)
    row = (await db.execute(text(_SELECT + " WHERE a.id = :id"), {"id": aid})).first()
    if not row:
        raise HTTPException(404, "Agendamento não encontrado")
    return _row_to_dict(row)


# ----------------------------------------------------------------- escrita ---

@router.post("", dependencies=[exige("agendamentos.criar")])
async def criar(
    body: AgendamentoCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    authz.exigir_tela(current, "agendamentos")
    authz.exigir_municipio(current, body.municipio_id)
    _valida(body)
    anex = json.dumps([a.model_dump() for a in body.anexos], ensure_ascii=False)
    rid = (await db.execute(text("""
        INSERT INTO agendamentos
            (municipio_id, responsavel_id, titulo, relato, data, status,
             anexos, criado_por)
        VALUES (:m, :r, :t, :rel, :d, :s, CAST(:a AS JSONB), :u)
        RETURNING id
    """), {
        "m": body.municipio_id, "r": body.responsavel_id, "t": body.titulo,
        "rel": body.relato, "d": body.data, "s": body.status, "a": anex,
        "u": getattr(current, "id", None),
    })).scalar()
    await db.commit()
    await registrar(
        db, action="agendamentos.create", user=current, request=request,
        target_type="agendamento", target_id=rid, municipio_id=body.municipio_id,
        alvo_nome=body.titulo,
        details={"titulo": body.titulo, "data": str(body.data),
                 "status": body.status, "responsavel_id": body.responsavel_id,
                 "anexos": _rotulo_anexos([a.model_dump() for a in body.anexos])},
    )
    return {"id": rid, "created": True}


@router.put("/{aid}", dependencies=[exige("agendamentos.editar")])
async def atualizar(
    aid: int,
    body: AgendamentoUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    await _exigir_acesso(db, aid, current)
    await authz.exigir_dono_da_linha(db, "agendamentos", aid, current)
    _valida(body)
    antes = await _contexto(db, aid)
    if not antes:
        raise HTTPException(404, "Agendamento não encontrado")

    campos, params = [], {"id": aid}
    for coluna, valor in (("titulo", body.titulo), ("relato", body.relato),
                          ("data", body.data), ("status", body.status),
                          ("responsavel_id", body.responsavel_id)):
        # ⚠️ `is not None` E NÃO "if valor": limpar o relato (mandar "") e tirar
        # o responsável (mandar null) são edições legítimas, e um teste de
        # verdade descartaria as duas em silêncio — a pessoa apagaria o texto,
        # salvaria, e o texto voltaria.
        if valor is not None:
            campos.append(f"{coluna} = :{coluna}"); params[coluna] = valor
    if body.anexos is not None:
        campos.append("anexos = CAST(:anexos AS JSONB)")
        params["anexos"] = json.dumps([a.model_dump() for a in body.anexos],
                                      ensure_ascii=False)
    if not campos:
        return {"id": aid, "updated": False}
    campos.append("updated_at = NOW()")
    await db.execute(text(
        f"UPDATE agendamentos SET {', '.join(campos)} WHERE id = :id"), params)
    await db.commit()

    mudou = {k: (str(v) if isinstance(v, date) else v)
             for k, v in params.items() if k not in ("id", "anexos")}
    if body.anexos is not None:
        mudou["anexos"] = _rotulo_anexos([a.model_dump() for a in body.anexos])
    await registrar(
        db, action="agendamentos.update", user=current, request=request,
        target_type="agendamento", target_id=aid,
        municipio_id=antes.get("municipio_id"), alvo_nome=antes.get("titulo"),
        details=mudou,
    )
    return {"id": aid, "updated": True}


@router.patch("/{aid}/status", dependencies=[exige("agendamentos.editar")])
async def mudar_status(
    aid: int,
    body: StatusUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Mover o cartão de coluna no kanban. Ver o porquê em `StatusUpdate`."""
    await _exigir_acesso(db, aid, current)
    await authz.exigir_dono_da_linha(db, "agendamentos", aid, current)
    _valida(body)
    antes = await _contexto(db, aid)
    if not antes:
        raise HTTPException(404, "Agendamento não encontrado")
    await db.execute(text(
        "UPDATE agendamentos SET status = :s, updated_at = NOW() WHERE id = :id"),
        {"s": body.status, "id": aid})
    await db.commit()
    await registrar(
        db, action="agendamentos.status", user=current, request=request,
        target_type="agendamento", target_id=aid,
        municipio_id=antes.get("municipio_id"), alvo_nome=antes.get("titulo"),
        details={"status": body.status, "rotulo": STATUS_ROTULO.get(body.status)},
    )
    return {"id": aid, "status": body.status}


@router.delete("/{aid}", dependencies=[exige("agendamentos.excluir")])
async def remover(
    aid: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    await _exigir_acesso(db, aid, current)
    await authz.exigir_dono_da_linha(db, "agendamentos", aid, current)
    antes = await _contexto(db, aid)
    if not antes:
        raise HTTPException(404, "Agendamento não encontrado")
    await db.execute(text("DELETE FROM agendamentos WHERE id = :id"), {"id": aid})
    await db.commit()
    await registrar(
        db, action="agendamentos.delete", user=current, request=request,
        target_type="agendamento", target_id=aid,
        municipio_id=antes.get("municipio_id"), alvo_nome=antes.get("titulo"),
        details=antes,
    )
    return {"id": aid, "deleted": True}


# ------------------------------------------------------------------ anexo ---

@router.get("/{aid}/anexo/{idx}", dependencies=[exige("agendamentos.anexo_baixar")])
async def baixar_anexo(
    aid: int,
    idx: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """O ARQUIVO em si — ofício, comprovante, foto — decodificado do base64."""
    await _exigir_acesso(db, aid, current)
    row = (await db.execute(text(
        "SELECT anexos, municipio_id, titulo FROM agendamentos WHERE id = :id"
    ), {"id": aid})).first()
    if not row:
        raise HTTPException(404, "Agendamento não encontrado")
    anexos = row[0] or []
    if idx < 0 or idx >= len(anexos):
        raise HTTPException(404, "Anexo não encontrado")
    a = anexos[idx]
    try:
        dados = base64.b64decode(a["dados_b64"])
    except Exception:
        raise HTTPException(500, "Anexo corrompido")
    # Baixar anexo É exportação: o documento sai da plataforma. Entra sob
    # `export.` pela mesma razão dos PDFs — ver `routers/gestao.py`.
    await registrar(
        db, action="export.agendamento_anexo", user=current, request=request,
        target_type="agendamento", target_id=aid, municipio_id=row[1],
        alvo_nome=a.get("nome"),
        details={"agendamento": row[2], "indice": idx, "arquivo": a.get("nome"),
                 "mime": a.get("mime"), "tamanho_bytes": len(dados)},
    )
    return Response(
        content=dados, media_type=a.get("mime") or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{a.get("nome", "anexo")}"'},
    )


# ------------------------------------------------------------- exportacao ---

# ⚠️ TETO DE LINHAS. Sem ele, um filtro largo (sem município e sem data) monta
# um PDF de milhares de páginas na memória do container — e o host tem 2 vCPU
# compartilhados por 43 containers. O teto é alto o bastante para qualquer
# recorte real e devolve 413 com instrução, em vez de derrubar o worker.
MAX_EXPORT = 5000


@router.get("/exportar/relacao", dependencies=[exige("agendamentos.exportar")])
async def exportar(
    request: Request,
    formato: str = Query("xlsx", pattern="^(xlsx|pdf)$"),
    municipio_id: Optional[int] = Query(None),
    de: Optional[date] = Query(None),
    ate: Optional[date] = Query(None),
    status: Optional[str] = Query(None),
    responsavel_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """A relação filtrada, em Excel ou PDF — com os MESMOS filtros da tela."""
    # Mesma regra da lista — ver o comentário lá. O arquivo tem de trazer
    # exatamente as linhas da tela, e isso inclui o recorte da carteira.
    if municipio_id:
        ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "agendamentos")
    if status and status not in STATUS:
        raise HTTPException(422, f"Status inválido: {status!r}")

    permitidos, vazia = _carteira(current, municipio_id)
    if vazia:
        raise HTTPException(403, "Sua conta não alcança nenhum município.")
    onde, params = _filtros(municipio_id, de, ate, status, responsavel_id,
                            permitidos)
    sql = _SELECT + onde + " ORDER BY a.data ASC, a.id ASC"
    rows = (await db.execute(text(sql), params)).fetchall()
    if len(rows) > MAX_EXPORT:
        raise HTTPException(
            413, f"O filtro alcançou {len(rows)} agendamentos e o limite de "
                 f"exportação é {MAX_EXPORT}. Estreite o período ou escolha um "
                 f"município.")
    itens = [_row_to_dict(r) for r in rows]

    from services import agendamentos_export as ax
    hoje = date.today().strftime("%Y-%m-%d")
    if formato == "xlsx":
        conteudo = ax.gerar_xlsx(itens)
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        nome = f"agendamentos_{hoje}.xlsx"
    else:
        conteudo = ax.gerar_pdf(itens, de=de, ate=ate)
        mime = "application/pdf"
        nome = f"agendamentos_{hoje}.pdf"

    await registrar(
        db, action="export.agendamentos", user=current, request=request,
        target_type="export", target_id="agendamentos", alvo_nome=nome,
        municipio_id=municipio_id,
        details={
            # ⚠️ O `formato` vai nos FILTROS, e não solto. É a convenção que o
            # `_registrar_export` do `export_pdf.py` já usa para as Vigências,
            # que também exportam nos dois formatos.
            "registros": len(itens), "arquivo": nome,
            "filtros": {k: v for k, v in {
                "formato": formato, "municipio_id": municipio_id,
                "de": str(de) if de else None, "ate": str(ate) if ate else None,
                "status": status, "responsavel_id": responsavel_id,
            }.items() if v not in (None, "", [])} or None,
        },
    )
    return StreamingResponse(
        BytesIO(conteudo), media_type=mime,
        headers={"Content-Disposition": f"attachment; filename={nome}"})
