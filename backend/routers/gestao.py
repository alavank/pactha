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

PERMISSAO (o que este modulo exige, e por que sao DUAS coisas)
--------------------------------------------------------------
So `GET /anotacoes` (a lista) checava alguma coisa. Todo o resto — inclusive
`GET /anotacoes/{id}/anexo/{idx}`, que devolve o ARQUIVO anexado (oficio,
comprovante, foto) direto do banco — bastava estar logado. Quem tivesse
qualquer conta baixava o anexo de qualquer anotacao de qualquer prefeitura.

Cada endpoint passa a exigir os dois recortes, que respondem a perguntas
diferentes:

  `authz.exigir_tela(user, "gestao")`  -> a pessoa trabalha com este MODULO?
  `authz.ensure_dono(...)`       -> ESTA anotacao e de um municipio que ela
                                    alcanca? Ter a tela nao diz nada sobre a
                                    linha.

⚠️ NADA DISSO BARRA HOJE. `AUTHZ_MODO=aviso` (o default) apenas REGISTRA "eu
teria negado isto" e deixa passar — comportamento identico ao de antes. So
`AUTHZ_MODO=bloqueio` levanta 403. Ver services/authz.py.

⚠️ O QUE VAI APARECER NA SEMANA DE OBSERVACAO, e nao e defeito: tres endpoints
daqui (`/status-opcoes`, `/anotacoes/item` e `/anotacoes/contagens`) sao usados
pelo BOTAO DE ANOTACAO que aparece DENTRO de outras telas — Convenios e
TransfereGov (frontend/src/components/AnotacaoButton.tsx e AnotacaoModal.tsx).
Entao quem tem "convenios" mas nao tem "gestao" vai gerar linha `authz.negaria`
sem nunca ter aberto a Gestao Interna. E a decisao certa (anotar E o modulo de
Gestao Interna), mas quem for ligar o bloqueio precisa saber que essas contas
perdem o botao — conceder a tela `gestao` a elas e a correcao.

PERMISSAO POR ACAO (`exige`, ver services/registro_rotas.py)
------------------------------------------------------------
Cada rota declara o verbo que executa. Duas escolhas nao sao obvias e estao
comentadas onde acontecem: `POST /anotacoes/contagens` declara `gestao.ver`
(e um GROUP BY — o POST e por causa do corpo, nao porque escreva) e o download
de anexo declara `gestao.anexo_baixar`, a caixinha propria do catalogo.
"""
from __future__ import annotations
import json
from datetime import date
from typing import Optional, Any
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from services.auth import get_current_user, ensure_municipio_access, ensure_tela
from services import authz
from services.registro_rotas import exige
from services.audit import registrar
from models.user import User

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


def _rotulo_anexos(anexos) -> list:
    """Metadado dos anexos para a trilha — NUNCA o `dados_b64`.

    O conteudo do arquivo mora em base64 no JSONB da anotacao; copia-lo para o
    audit_log duplicaria megabytes numa tabela que, por decisao do dono, nao se
    apaga. Nome, tipo e tamanho bastam para provar o que foi anexado."""
    return [{"nome": a.get("nome"), "mime": a.get("mime"), "tamanho": a.get("tamanho")}
            for a in (anexos or [])]


async def _exigir_acesso(db: AsyncSession, anot_id: int, user) -> None:
    """Os dois recortes de todo endpoint que fala de UMA anotacao.

    Num lugar so porque sao quatro (ler, editar, apagar, baixar o anexo) e
    porque o nome da tabela vira literal de SQL la dentro: uma copia divergente
    e uma porta que continua aberta sem ninguem notar.

    Em `AUTHZ_MODO=aviso` nenhuma das duas levanta — registram e voltam."""
    authz.exigir_tela(user, "gestao")
    # Devolve o municipio da linha; nao usamos o retorno — quem decide o 404
    # continua sendo o endpoint, com a consulta dele.
    await authz.ensure_dono(db, "gestao_anotacoes", "id", anot_id, user)


async def _anotacao_contexto(db: AsyncSession, anot_id: int) -> dict:
    """Municipio e a que item a anotacao se refere. Sem isto o registro nao teria
    `municipio_id` (a auditoria nao recorta por prefeitura) nem diria sobre QUAL
    convenio a anotacao fala. Nao levanta 404: quem decide isso e o endpoint."""
    r = (await db.execute(text(
        "SELECT municipio_id, fonte, fonte_ref, numero_referencia, status_interno "
        "FROM gestao_anotacoes WHERE id = :id"), {"id": anot_id})).first()
    if not r:
        return {"municipio_id": None, "fonte": None, "fonte_ref": None,
                "numero_referencia": None, "status_interno": None}
    return {"municipio_id": r[0], "fonte": r[1], "fonte_ref": r[2],
            "numero_referencia": r[3], "status_interno": r[4]}


@router.get("/status-opcoes", dependencies=[exige("gestao.ver")])
async def status_opcoes(current: User = Depends(get_current_user)):
    # Constantes deste arquivo, sem dado de prefeitura nenhuma — mas e o
    # vocabulario do modulo, e o formulario de anotacao nao existe sem ele. So a
    # tela: nao ha municipio a julgar aqui.
    authz.exigir_tela(current, "gestao")
    return {"opcoes": STATUS_OPCOES, "fontes_validas": sorted(FONTES_VALIDAS)}


@router.get("/anotacoes", dependencies=[exige("gestao.ver")])
async def listar(
    municipio_id: Optional[int] = Query(None),
    fonte: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="Filtra por status_interno"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "gestao")
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


@router.get("/anotacoes/item", dependencies=[exige("gestao.ver")])
async def listar_item(
    fonte: str = Query(...),
    fonte_ref: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Anotacoes de um item especifico (com anexos completos)."""
    authz.exigir_tela(current, "gestao")
    rows = (await db.execute(
        text(_SELECT + " WHERE fonte = :f AND fonte_ref = :r ORDER BY updated_at DESC"),
        {"f": fonte, "r": fonte_ref},
    )).fetchall()
    # O pedido nao traz `municipio_id` (a busca e por fonte+fonte_ref), entao o
    # recorte so pode sair das LINHAS que a consulta devolveu.
    #
    # ⚠️ Por que julgar depois em vez de filtrar a consulta: filtrar mudaria a
    # RESPOSTA, e em modo aviso a resposta tem de ser byte a byte a de hoje —
    # uma anotacao a menos aparecendo na tela e exatamente o apagao silencioso
    # que este incremento existe para evitar. Julgando, em aviso vira linha na
    # trilha e em bloqueio vira o 403 de sempre.
    #
    # `municipio_id` e a 2a coluna de `_SELECT`. O `is not None` protege de um
    # dia a coluna deixar de ser NOT NULL: `authz.exigir_municipio(user, None)`
    # levanta 403 nos DOIS modos (pedido malformado, ver services/authz.py) e
    # isso seria um 403 NOVO em modo aviso.
    for mid in sorted({r[1] for r in rows if r[1] is not None}):
        authz.exigir_municipio(current, mid)
    return {"items": [_row_to_dict(r, with_anexos=True) for r in rows], "total": len(rows)}


class ContagensIn(BaseModel):
    fonte: str
    refs: list[str]


# `gestao.ver` mesmo sendo POST: o verbo tem de casar com o que o endpoint FAZ, e
# aqui ele so conta (GROUP BY). O metodo e POST porque a lista de `refs` nao cabe
# em query string — declarar `criar` aqui cobraria escrita de quem so consulta.
@router.post("/anotacoes/contagens", dependencies=[exige("gestao.ver")])
async def contagens(
    body: ContagensIn,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Quantas anotacoes cada item tem — UMA consulta para a lista inteira.

    Existe porque contar custava caro: o botaozinho de anotacao de cada linha
    chamava `GET /anotacoes/item`, que devolve as anotacoes COM OS ANEXOS EM
    BASE64. Numa tela de 20 linhas eram 20 requisicoes, cada uma podendo
    carregar megabytes de arquivo — para exibir um numero.

    Aqui e um GROUP BY, sem tocar na coluna `anexos`. Itens sem anotacao nao
    voltam na resposta; quem chama trata ausencia como zero.

    GATE: so a tela. LIMITE DECLARADO — a resposta nao carrega `municipio_id`
    (e um numero por `fonte_ref`), e por-lo la exigiria mexer no GROUP BY, ou
    seja alterar o endpoint que este incremento so deveria proteger. Fica assim
    de proposito: o que vaza sem o recorte de municipio e a EXISTENCIA de
    anotacoes num item cujo numero quem pergunta ja conhece — nunca conteudo,
    nunca anexo. Todo caminho que devolve conteudo (`/anotacoes`,
    `/anotacoes/item`, `/anotacoes/{id}`, `/anexo/{idx}`) e recortado por
    municipio.
    """
    authz.exigir_tela(current, "gestao")
    if not body.refs:
        return {}
    rows = (await db.execute(text("""
        SELECT fonte_ref, COUNT(*) FROM gestao_anotacoes
        WHERE fonte = :f AND fonte_ref = ANY(:refs)
        GROUP BY fonte_ref
    """), {"f": body.fonte, "refs": list(dict.fromkeys(body.refs))})).fetchall()
    return {r[0]: r[1] for r in rows}


@router.get("/anotacoes/{anot_id}", dependencies=[exige("gestao.ver")])
async def detalhe(
    anot_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    await _exigir_acesso(db, anot_id, current)
    row = (await db.execute(text(_SELECT + " WHERE id = :id"), {"id": anot_id})).first()
    if not row:
        raise HTTPException(404, "Anotacao nao encontrada")
    return _row_to_dict(row, with_anexos=True)


@router.post("/anotacoes", dependencies=[exige("gestao.criar")])
async def criar(
    body: AnotacaoCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    authz.exigir_tela(user, "gestao")
    # Aqui o municipio vem no corpo e e OBRIGATORIO no modelo (`municipio_id:
    # int`), entao nao ha o caso "ausente" que teria de ser desviado: pedido sem
    # municipio nem chega neste ponto (422 do pydantic, como sempre foi).
    authz.exigir_municipio(user, body.municipio_id)
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
    await registrar(
        db, action="gestao.anotacao.create", user=user, request=request,
        target_type="gestao_anotacao", target_id=rid, municipio_id=body.municipio_id,
        alvo_nome=(body.numero_referencia or body.fonte_ref),
        details={"fonte": body.fonte, "fonte_ref": body.fonte_ref,
                 "numero_referencia": body.numero_referencia,
                 "status_interno": body.status_custom or body.status_interno,
                 "protocolo": body.protocolo,
                 "data_protocolo": str(body.data_protocolo) if body.data_protocolo else None,
                 "anexos": _rotulo_anexos([a.model_dump() for a in body.anexos])},
    )
    return {"id": rid, "created": True}


@router.put("/anotacoes/{anot_id}", dependencies=[exige("gestao.editar")])
async def atualizar(
    anot_id: int,
    body: AnotacaoUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    await _exigir_acesso(db, anot_id, current)
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
    ctx = await _anotacao_contexto(db, anot_id)
    sets.append("updated_at = NOW()")
    await db.execute(text(f"UPDATE gestao_anotacoes SET {', '.join(sets)} WHERE id = :id"), params)
    await db.commit()
    await registrar(
        db, action="gestao.anotacao.update", user=current, request=request,
        target_type="gestao_anotacao", target_id=anot_id, municipio_id=ctx["municipio_id"],
        alvo_nome=(body.numero_referencia or ctx["numero_referencia"] or ctx["fonte_ref"]),
        details={"fonte": ctx["fonte"], "fonte_ref": ctx["fonte_ref"],
                 "numero_referencia": ctx["numero_referencia"],
                 "campos": sorted(body.model_dump(exclude_unset=True).keys()),
                 "anexos": (_rotulo_anexos([a.model_dump() for a in body.anexos])
                            if body.anexos is not None else None)},
        # O status interno e a razao de existir do modulo ("prestacao enviada
        # fisicamente", "aguardando assinatura"): o valor ANTES e DEPOIS e o que
        # o gestor vai querer conferir. Snapshot completo dos dois lados — o
        # audit reduz sozinho se nao mudou.
        valor_antes={"status_interno": ctx["status_interno"]},
        valor_depois={"status_interno": (body.status_custom or body.status_interno
                                         or ctx["status_interno"])},
    )
    return {"updated": True}


@router.delete("/anotacoes/{anot_id}", dependencies=[exige("gestao.excluir")])
async def remover(
    anot_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    await _exigir_acesso(db, anot_id, current)
    ctx = await _anotacao_contexto(db, anot_id)   # depois do DELETE nao ha contexto
    r = await db.execute(text("DELETE FROM gestao_anotacoes WHERE id = :id"), {"id": anot_id})
    await db.commit()
    if r.rowcount == 0:
        raise HTTPException(404, "Anotacao nao encontrada")
    await registrar(
        db, action="gestao.anotacao.delete", user=current, request=request,
        target_type="gestao_anotacao", target_id=anot_id, municipio_id=ctx["municipio_id"],
        alvo_nome=(ctx["numero_referencia"] or ctx["fonte_ref"]),
        details={"fonte": ctx["fonte"], "fonte_ref": ctx["fonte_ref"],
                 "numero_referencia": ctx["numero_referencia"],
                 "status_interno": ctx["status_interno"]},
    )
    return {"deleted": True}


# `gestao.anexo_baixar` e nao `gestao.ver`: e a caixinha propria do catalogo — a
# lista mostra que HA anexo, esta rota entrega o arquivo digitalizado.
#
# ⚠️ LIMITE DECLARADO, para ninguem ler a caixinha como uma promessa maior do que
# ela e hoje: `GET /anotacoes/item` e `GET /anotacoes/{id}` devolvem os anexos com
# `dados_b64` embutido (`with_anexos=True`), entao `gestao.ver` sozinho ja alcanca
# o conteudo por aqueles dois caminhos. Fechar isso e retirar o base64 daquelas
# duas respostas — o que MUDA a resposta de producao e nao cabe neste incremento.
@router.get("/anotacoes/{anot_id}/anexo/{idx}",
            dependencies=[exige("gestao.anexo_baixar")])
async def download_anexo(
    anot_id: int,
    idx: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Download de um anexo especifico (decodifica base64)."""
    from fastapi.responses import Response
    import base64
    # O ARQUIVO em si sai por aqui (oficio, comprovante, foto), em base64 direto
    # do banco. Era a porta mais aberta do modulo: qualquer conta logada baixava
    # o anexo de qualquer anotacao de qualquer prefeitura.
    await _exigir_acesso(db, anot_id, current)
    row = (await db.execute(text(
        "SELECT anexos, municipio_id, fonte, fonte_ref FROM gestao_anotacoes WHERE id = :id"
    ), {"id": anot_id})).first()
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
    # Baixar anexo E exportacao: o arquivo (oficio, comprovante, foto) sai da
    # plataforma. Entra sob `export.` pelo mesmo motivo dos PDFs — o dono pediu
    # "toda exportacao", e o que sai daqui e justamente documento digitalizado.
    await registrar(
        db, action="export.gestao_anexo", user=current, request=request,
        target_type="gestao_anotacao", target_id=anot_id, municipio_id=row[1],
        alvo_nome=a.get("nome"),
        details={"fonte": row[2], "fonte_ref": row[3], "indice": idx,
                 "arquivo": a.get("nome"), "mime": a.get("mime"),
                 "tamanho_bytes": len(data)},
    )
    return Response(
        content=data, media_type=a.get("mime") or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{a.get("nome", "anexo")}"'},
    )
