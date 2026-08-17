"""Relatorio de Monitoramento (RM) - CRUD + auto-popular + PDF.

Endpoints:
  GET    /api/rm?municipio_id=         lista RMs
  POST   /api/rm                       cria novo (com option auto_popular)
  GET    /api/rm/{id}                  detalhe completo
  PUT    /api/rm/{id}                  atualiza meta + conteudo
  POST   /api/rm/{id}/auto-popular     repreenche conteudo com dados atuais do DB
  DELETE /api/rm/{id}                  remove
  GET    /api/rm/{id}/pdf              gera o PDF/Excel (4 variantes: completo,
                                       resumido, totalizado pdf, totalizado xlsx)

PERMISSAO (ver services/authz.py)
---------------------------------
Ate aqui so o LISTAR checava alguma coisa. Criar, detalhe, PUT, auto-popular,
DELETE e o PDF aceitavam QUALQUER sessao valida: um usuario criado com zero
telas e zero municipios apagava o Relatorio de Monitoramento de qualquer
prefeitura chamando a API direto, ou baixava o PDF dela.

Agora todo endpoint daqui exige a tela `rm`, e cada um que recebe `{rid}`
confere ainda o municipio DA LINHA (`authz.ensure_dono`) — permissao de tela diz
que a pessoa mexe em RM, nao diz nada sobre o RM de OUTRO municipio, e `{rid}` e
so um numero que qualquer um chuta. Sem essa segunda conferencia, quem tem a
tela tem a tela do tenant inteiro.

⚠️ Com AUTHZ_MODO=aviso (o DEFAULT) nada disto NEGA: registra na trilha "eu teria
negado isto, para este usuario, por este motivo" e DEIXA PASSAR. O comportamento
em producao segue identico ao de hoje ate o dono corrigir as permissoes de quem
precisa e so entao ligar AUTHZ_MODO=bloqueio. Ver o docstring de services/authz.py.

PERMISSAO POR ACAO (`exige`, ver services/registro_rotas.py)
------------------------------------------------------------
Cada rota declara o VERBO que ela executa — e e a declaracao que separa quem so
CONSULTA de quem ESCREVE, coisa que a tela `rm` sozinha nunca soube fazer (quem
via, apagava). A tela continua dizendo se a pessoa trabalha com RM, o municipio
diz onde, e a permissao diz o que ela faz la.

ALCANCE POR LINHA (Incremento 6 — `authz.exigir_dono_da_linha`)
---------------------------------------------------------------
Um usuario pode ser configurado, POR MODULO, como "somente os que ele criou":
ai ele so ALTERA e APAGA o RM que ele mesmo cadastrou. Continua VENDO e
EXPORTANDO o municipio inteiro — decisao do dono, e o motivo e operacional:
dois servidores do mesmo setor deixariam de ver o trabalho um do outro, e o
registro de quem saiu da prefeitura sumiria da tela.

Por isso o gate mora em `_exigir_escrita` (PUT, auto-popular e DELETE) e NAO no
detalhe nem no PDF. A lista passa a devolver `pode_editar`/`pode_excluir` por
item, para o botao sumir — mas botao escondido NAO e permissao: quem barra
continua sendo o servidor.

⚠️ E O `POST ""` TAMBEM E ESCRITA EM LINHA ALHEIA, ao contrario do POST dos
outros dois modulos: aqui ele e um UPSERT (`ON CONFLICT DO UPDATE`), entao o
mesmo POST sobrescreve o RM que ja existe naquela data. Ele leva o gate de
alcance quando a linha JA EXISTE — ver o comentario dentro de `criar`. Sem isso,
"nao pode editar o RM do colega" seria uma frase que so valia no PUT.
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
from services import authz
from services.registro_rotas import exige
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
    # SELECAO de anos do relatorio. O RM e UM so, com o escopo escolhido:
    #   []           -> TODOS os anos (o "completo")
    #   [2026]       -> so 2026
    #   [2024,2025]  -> esses anos juntos, num unico relatorio
    # A identidade do RM e (municipio_id, anos) — ver migrations/add_rm_anos.sql e
    # services/rm_builder.montar_conteudo(anos=...). Sempre 4 partes (padrao Freitas).
    anos: list[int] = []


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


async def _exigir_escrita(db: AsyncSession, rid: int, user) -> None:
    """Os TRES recortes de todo endpoint que ALTERA um RM.

    A tela (o modulo), o municipio da linha (o territorio) e — desde o
    Incremento 6 — o ALCANCE por linha: quem esta configurado como "somente os
    que ele criou" so mexe no proprio relatorio.

    So nos endpoints de ESCRITA (PUT, auto-popular e DELETE), e nao no detalhe
    nem no PDF: a decisao do dono e que o alcance vale so para escrita — quem
    esta restrito continua VENDO e EXPORTANDO o RM do municipio inteiro.

    Custo para quem NAO foi restringido: zero consulta a mais — `escopo_de`
    volta `todos` antes de tocar no banco."""
    authz.exigir_tela(user, "rm")
    await authz.ensure_dono(db, "rm_relatorios", "id", rid, user)
    await authz.exigir_dono_da_linha(db, "rm", rid, user)


def _row_to_dict(row, usuario) -> dict:
    """⭐ `usuario` e OBRIGATORIO desde o Incremento 6 — ver o mesmo helper em
    routers/gestao.py: a resposta passa a dizer, POR ITEM, se quem pediu pode
    alterar aquele relatorio. Botao escondido NAO e permissao; quem barra
    continua sendo `_exigir_escrita` nos endpoints de escrita."""
    criado_por = row[8]
    return {
        "id": row[0], "municipio_id": row[1], "data_referencia": row[2].isoformat() if row[2] else None,
        "cidade_emissao": row[3], "titulo": row[4], "rodape": row[5],
        "status": row[6], "conteudo": row[7] or {"partes": []},
        "criado_por": criado_por,
        "created_at": row[9].isoformat() if row[9] else None,
        "updated_at": row[10].isoformat() if row[10] else None,
        # 'anual' (legado) | 'completo' (todos) | 'parcial' (recorte de anos).
        "escopo": row[11],
        # SELECAO de anos do relatorio ([] = todos = completo). A lista mostra o escopo.
        "anos": list(row[12]) if row[12] is not None else [],
        "pode_editar": authz.pode_editar_item(usuario, "rm", "editar", criado_por),
        "pode_excluir": authz.pode_editar_item(usuario, "rm", "excluir", criado_por),
    }


@router.get("", dependencies=[exige("rm.ver")])
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
               r.created_at, r.updated_at, r.escopo, r.anos, m.nome AS municipio_nome
        FROM rm_relatorios r LEFT JOIN municipios m ON m.id = r.municipio_id
        {('WHERE ' + ' AND '.join(where)) if where else ''}
        ORDER BY cardinality(r.anos) = 0 DESC, r.anos DESC, r.id DESC
    """
    rs = (await db.execute(text(sql), params)).fetchall()
    items = []
    for row in rs:
        d = _row_to_dict(row, current)
        d["municipio_nome"] = row[13]
        items.append(d)
    return {"items": items, "total": len(items)}


# LIMITE DECLARADO: o INSERT abaixo e um UPSERT, entao `rm.criar` tambem alcanca
# o relatorio que JA existe naquela data (ver `ja_existia`). Nao exigimos
# `rm.editar` junto porque `exige()` cobra TODAS as chaves — quem so pode criar
# perderia a criacao. A trilha ja separa os dois casos (`rm.create`/`rm.update`).
@router.post("", dependencies=[exige("rm.criar")])
async def criar(
    body: RmCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    # Gate ANTES de `_get_municipio`: nao ha por que confirmar que o municipio
    # existe para quem nao pode escrever nele — e, em modo bloqueio, checar
    # depois transformaria "nao e seu" em 404 ou 403 conforme o municipio
    # existisse, o que e um oraculo de existencia de graca.
    authz.exigir_tela(user, "rm")
    # Aqui o municipio vem do CORPO (o RM ainda nao existe, entao nao ha linha
    # de onde tirar dono). `municipio_id` e obrigatorio no schema, entao isto
    # nunca cai no ramo de "pedido malformado" de ensure_municipio_access.
    authz.exigir_municipio(user, body.municipio_id)
    mun = await _get_municipio(db, body.municipio_id)
    # ⚠️⚠️ ESTE ENDPOINT E UM UPSERT, E POR ISSO ELE TAMBEM E ESCRITA EM LINHA
    # ALHEIA. Ele nao cria so: `ON CONFLICT (municipio_id, data_referencia) DO
    # UPDATE` faz o mesmo POST sobrescrever o RM que JA existe naquela data —
    # titulo, cidade de emissao, rodape e, com `auto_popular`, o CONTEUDO
    # inteiro. Sem esta leitura, quem esta configurado como "somente os que ele
    # criou" levava 403 no PUT do RM do colega e apagava o mesmo relatorio pelo
    # POST, com o mesmo corpo e sem nenhuma trava no caminho — a porta dos
    # fundos exata que o alcance por linha existe para fechar.
    #
    # A leitura ja acontecia (era o `ja_existia`, que separa "criou" de
    # "substituiu" na trilha); so passou a trazer o `id`, que e o que a checagem
    # precisa. Zero consulta a mais, para todo mundo.
    #
    # RM que ainda NAO existe nao passa por aqui: nao ha linha anterior de quem
    # julgar o dono, e o registro nasce de quem esta postando.
    # SELECAO de anos: normaliza (ordenada, sem repetir, sem zero). Vazio = TODOS
    # (o completo). A identidade do RM e (municipio_id, anos). `escopo` fica so como
    # rotulo derivado ('completo' quando vazio, 'parcial' quando ha recorte) — usado
    # pelo cabecalho do PDF (padrao Freitas em ambos).
    _anos = sorted({int(a) for a in (body.anos or []) if a})
    _escopo = "completo" if not _anos else "parcial"
    # asyncpg exige uma LISTA Python p/ param INT[] (o CAST informa o tipo do
    # elemento e cobre a lista vazia = completo). Passar string '{2026}' quebra.
    anterior = (await db.execute(text(
        "SELECT id FROM rm_relatorios WHERE municipio_id = :m AND anos = CAST(:a AS INT[])"
    ), {"m": body.municipio_id, "a": _anos})).first()
    ja_existia = anterior is not None
    if ja_existia:
        # Antes de `montar_conteudo`, que e a parte cara: em modo bloqueio nao ha
        # por que remontar o relatorio inteiro para descartar tudo no 403.
        await authz.exigir_dono_da_linha(db, "rm", anterior[0], user)
    # RM sempre no padrao Freitas (4 partes por estagio), recortado pelos anos
    # selecionados. ano_emissao = ano corrente (contexto de emissao: rotula
    # "REPASSES DE {ano}" e a Parte 4 de voluntarias do ano).
    # ANO DE REFERENCIA do padrao: e o MAIOR ano do escopo escolhido — nao o ano
    # corrente. Ele rotula o bloco "REPASSES DE {ano}" e o texto da Parte 4; um RM
    # gerado para [2024] saia dizendo "REPASSES DE 2026". Sem selecao (completo),
    # a referencia e o ano corrente.
    _ano_ref = max(_anos) if _anos else date.today().year
    conteudo = (await montar_conteudo(db, body.municipio_id, _ano_ref,
                                      completo=True, anos=_anos)
                if body.auto_popular else {"partes": []})
    titulo = body.titulo or f"RELATÓRIO DE MONITORAMENTO – {mun.nome.upper()}/{mun.uf}"
    # `ja_existia` (lido acima, junto do gate de alcance) separa "criou" de
    # "substituiu" na trilha: registrar tudo como "criou" faria o registro mentir
    # justamente no caso que interessa — o relatorio que ja existia e foi trocado.
    # ON CONFLICT: se ja existe RM nessa data, atualiza conteudo
    sql = text("""
        INSERT INTO rm_relatorios
            (municipio_id, data_referencia, escopo, anos, cidade_emissao, titulo, conteudo, criado_por, rodape)
        VALUES (:mun, :dt, :escopo, CAST(:anos AS INT[]), :cidade, :titulo, CAST(:cont AS JSONB), :usr, :rodape)
        ON CONFLICT (municipio_id, anos) DO UPDATE SET
            titulo = EXCLUDED.titulo,
            cidade_emissao = EXCLUDED.cidade_emissao,
            rodape = EXCLUDED.rodape,
            data_referencia = EXCLUDED.data_referencia,
            escopo = EXCLUDED.escopo,
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
        "mun": body.municipio_id, "dt": body.data_referencia, "escopo": _escopo,
        "anos": _anos,
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
                 "anos": (_anos or "todos"),
                 "cidade_emissao": cidade, "auto_popular": body.auto_popular,
                 "via": "upsert", "conteudo_substituido": ja_existia and body.auto_popular},
    )
    return {"id": rid, "created": True}


@router.get("/{rid}", dependencies=[exige("rm.ver")])
async def detalhe(
    rid: int,
    db: AsyncSession = Depends(get_db),
    # Era `_=Depends(...)`: a sessao ja era exigida, mas o usuario era descartado
    # e por isso nenhuma permissao podia ser conferida. A dependencia e a mesma —
    # so o nome mudou, para haver quem julgar.
    current: User = Depends(get_current_user),
):
    authz.exigir_tela(current, "rm")
    # O detalhe traz o RM inteiro (conteudo completo do relatorio). `ensure_dono`
    # confere o municipio DA LINHA; RM inexistente devolve None sem levantar, e
    # cai no 404 do proprio endpoint logo abaixo — quem decide o 404 e ele.
    await authz.ensure_dono(db, "rm_relatorios", "id", rid, current)
    row = (await db.execute(text("""
        SELECT r.id, r.municipio_id, r.data_referencia, r.cidade_emissao,
               r.titulo, r.rodape, r.status, r.conteudo, r.criado_por,
               r.created_at, r.updated_at, r.escopo, r.anos, m.nome AS municipio_nome, m.uf
        FROM rm_relatorios r LEFT JOIN municipios m ON m.id = r.municipio_id
        WHERE r.id = :id
    """), {"id": rid})).first()
    if not row:
        raise HTTPException(404, "RM não encontrado")
    d = _row_to_dict(row, current)
    d["municipio_nome"] = row[13]
    d["uf"] = row[14]
    return d


@router.put("/{rid}", dependencies=[exige("rm.editar")])
async def atualizar(
    rid: int,
    body: RmUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # Gate no TOPO, antes de montar o UPDATE: o que nao pode acontecer e a
    # escrita, entao a conferencia vem antes de qualquer preparo dela.
    await _exigir_escrita(db, rid, current)
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


# `rm.editar` e nao `rm.excluir`: a linha continua existindo — o que este endpoint
# faz e SOBRESCREVER o conteudo dela (a redacao manual vai embora). Exigir
# `excluir` cobraria a permissao de apagar de quem so precisa reprocessar.
@router.post("/{rid}/auto-popular", dependencies=[exige("rm.editar")])
async def repopular(
    rid: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Substitui conteudo pelo gerado automaticamente a partir do DB atual."""
    # Este endpoint DESCARTA a redacao manual do relatorio — e destrutivo como o
    # DELETE, so que sem apagar a linha. Mesmo gate.
    await _exigir_escrita(db, rid, current)
    row = (await db.execute(text(
        "SELECT municipio_id, data_referencia, titulo, escopo, anos FROM rm_relatorios WHERE id = :id"
    ), {"id": rid})).first()
    if not row:
        raise HTTPException(404, "RM não encontrado")
    # Regenera no MESMO escopo de anos do relatorio (row[4] = anos; vazio = todos).
    _anos = [int(a) for a in (row[4] or [])]
    # Mesmo ano de referencia da criacao: o maior ano do escopo (ver `criar`).
    _ano_ref = max(_anos) if _anos else date.today().year
    conteudo = await montar_conteudo(db, row[0], _ano_ref, completo=True, anos=_anos)
    # O `escopo` acompanha o que foi REGENERADO. Sem isto um RM legado ('anual')
    # era reescrito no padrao de 4 partes mas mantinha o rotulo antigo, e o PDF
    # saia com o cabecalho de exercicio ("Relatório referente ao exercício de X")
    # num documento que ja nao e anual.
    _escopo = "completo" if not _anos else "parcial"
    await db.execute(text(
        "UPDATE rm_relatorios SET conteudo = CAST(:c AS JSONB), escopo = :e, updated_at = NOW() WHERE id = :id"
    ), {"c": json.dumps(conteudo), "e": _escopo, "id": rid})
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
                 "efeito": "conteúdo anterior substituído pelos dados atuais"},
    )
    return {"ok": True, "partes": n_partes, "itens": n_itens}


@router.delete("/{rid}", dependencies=[exige("rm.excluir")])
async def remover(
    rid: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # Gate ANTES do DELETE, obviamente: em modo bloqueio a linha nao pode ter
    # sido apagada antes de a negativa sair.
    await _exigir_escrita(db, rid, current)
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


# As 4 variantes (completo, resumido, totalizado PDF e XLSX) saem por aqui, e
# todas geram ARQUIVO que anda sozinho: `exportar`, nao `ver`.
@router.get("/{rid}/pdf", dependencies=[exige("rm.exportar")])
async def pdf(
    rid: int,
    request: Request,
    tipo: str = Query("completo", description="completo | resumido | totalizado"),
    formato: str = Query("pdf", description="pdf | xlsx (xlsx só p/ totalizado)"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # As 4 variantes (completo, resumido, totalizado em PDF e totalizado em
    # Excel) saem todas por aqui, entao o gate no topo cobre as quatro. E o
    # endpoint que mais precisa dele: o arquivo sai da plataforma e anda
    # sozinho — e ate agora bastava a URL e uma sessao qualquer para baixar o
    # relatorio de qualquer prefeitura.
    authz.exigir_tela(current, "rm")
    await authz.ensure_dono(db, "rm_relatorios", "id", rid, current)
    row = (await db.execute(text("""
        SELECT r.data_referencia, r.cidade_emissao, r.titulo, r.rodape, r.conteudo, m.nome, m.uf,
               r.municipio_id, r.escopo
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
        # 'completo' troca o cabecalho (local + data por extenso, sem "exercicio").
        "escopo": row[8],
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
