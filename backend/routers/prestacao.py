from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from database import get_db
from models import PrestacaoContas, PrestacaoDocumento, ConvenioEstadual, ConvenioFederal
from schemas.prestacao import PrestacaoResponse, PrestacaoUpdate, DocumentoCreate, DocumentoUpdate, DocumentoResponse
from services.auth import get_current_user

router = APIRouter(prefix="/api/prestacao", tags=["prestacao"])

SIGCON_STAGES = {
    1: "Indicacao da Emenda",
    2: "Cadastro Proposta",
    3: "Analise Tecnica",
    4: "Diligencias",
    5: "Aprovacao",
    6: "Celebracao",
    7: "Execucao",
    8: "Prorrogacao",
    9: "Reprogramacao",
    10: "Conclusao",
    11: "Prest. Contas - Envio",
    12: "Prest. Contas - Analise",
    13: "Prest. Contas - Diligencia",
    14: "Prest. Contas - Aprovacao",
    15: "Prest. Contas - Recurso",
    16: "Encerramento",
}


@router.get("", response_model=list[PrestacaoResponse])
async def list_prestacoes(
    municipio_id: Optional[int] = None,
    status: Optional[str] = None,
    ano: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    q = select(PrestacaoContas)
    if municipio_id:
        q = q.where(PrestacaoContas.municipio_id == municipio_id)
    if status:
        q = q.where(PrestacaoContas.status == status)
    if ano:
        # Filter by convenio ano (join)
        q = q.join(
            ConvenioEstadual, ConvenioEstadual.id == PrestacaoContas.convenio_estadual_id,
            isouter=True,
        ).where(ConvenioEstadual.ano == ano)
    q = q.order_by(PrestacaoContas.etapa_atual.asc())
    result = await db.execute(q)
    prestacoes = result.scalars().all()

    responses = []
    for p in prestacoes:
        docs_result = await db.execute(
            select(PrestacaoDocumento).where(PrestacaoDocumento.prestacao_id == p.id)
        )
        docs = [DocumentoResponse.model_validate(d) for d in docs_result.scalars().all()]

        # Load full convenio info
        from datetime import date as ddate
        nr = objeto = orgao = esfera = situacao = None
        valor_total = None
        dt_inicio = dt_fim = None
        ano = None

        if p.convenio_estadual_id:
            ce = await db.get(ConvenioEstadual, p.convenio_estadual_id)
            if ce:
                nr = ce.nr_sigcon
                objeto = ce.objeto
                orgao = ce.orgao_concedente
                esfera = "estadual"
                situacao = ce.situacao
                valor_total = float(ce.valor_total) if ce.valor_total else None
                dt_inicio = ce.dt_vigencia_inicial
                dt_fim = ce.dt_vigencia_atual or ce.dt_vigencia_final
                ano = ce.ano
        elif p.convenio_federal_id:
            cf = await db.get(ConvenioFederal, p.convenio_federal_id)
            if cf:
                nr = cf.nr_convenio
                objeto = cf.objeto
                orgao = cf.orgao_concedente
                esfera = "federal"
                situacao = cf.situacao
                valor_total = float(cf.valor_global) if cf.valor_global else None
                dt_inicio = cf.dt_inicio
                dt_fim = cf.dt_fim_vigencia
                ano = cf.ano

        dias_rest = (dt_fim - ddate.today()).days if dt_fim else None

        resp = PrestacaoResponse(
            id=p.id,
            convenio_estadual_id=p.convenio_estadual_id,
            convenio_federal_id=p.convenio_federal_id,
            municipio_id=p.municipio_id,
            etapa_atual=p.etapa_atual,
            etapa_nome=p.etapa_nome or SIGCON_STAGES.get(p.etapa_atual, ""),
            responsavel_id=p.responsavel_id,
            status=p.status,
            observacoes=p.observacoes,
            documentos=docs,
            nr_convenio=nr,
            objeto=objeto,
            esfera=esfera,
            orgao_concedente=orgao,
            valor_total=valor_total,
            dt_inicio=dt_inicio,
            dt_fim_vigencia=dt_fim,
            dias_restantes=dias_rest,
            ano=ano,
            situacao=situacao,
        )
        responses.append(resp)
    return responses


@router.put("/{prestacao_id}", response_model=PrestacaoResponse)
async def update_prestacao(
    prestacao_id: int,
    data: PrestacaoUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    p = await db.get(PrestacaoContas, prestacao_id)
    if not p:
        raise HTTPException(status_code=404, detail="Prestacao nao encontrada")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(p, field, value)
    if data.etapa_atual and not data.etapa_nome:
        p.etapa_nome = SIGCON_STAGES.get(data.etapa_atual, "")

    await db.commit()
    await db.refresh(p)

    docs_result = await db.execute(
        select(PrestacaoDocumento).where(PrestacaoDocumento.prestacao_id == p.id)
    )
    docs = [DocumentoResponse.model_validate(d) for d in docs_result.scalars().all()]

    return PrestacaoResponse(
        id=p.id,
        convenio_estadual_id=p.convenio_estadual_id,
        convenio_federal_id=p.convenio_federal_id,
        municipio_id=p.municipio_id,
        etapa_atual=p.etapa_atual,
        etapa_nome=p.etapa_nome,
        responsavel_id=p.responsavel_id,
        status=p.status,
        observacoes=p.observacoes,
        documentos=docs,
    )


@router.post("/{prestacao_id}/documentos", response_model=DocumentoResponse)
async def add_documento(
    prestacao_id: int,
    data: DocumentoCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    p = await db.get(PrestacaoContas, prestacao_id)
    if not p:
        raise HTTPException(status_code=404, detail="Prestacao nao encontrada")

    doc = PrestacaoDocumento(
        prestacao_id=prestacao_id,
        documento_nome=data.documento_nome,
        responsavel_id=data.responsavel_id,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return DocumentoResponse.model_validate(doc)


@router.put("/documentos/{doc_id}", response_model=DocumentoResponse)
async def update_documento(
    doc_id: int,
    data: DocumentoUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    doc = await db.get(PrestacaoDocumento, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Documento nao encontrado")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(doc, field, value)
    await db.commit()
    await db.refresh(doc)
    return DocumentoResponse.model_validate(doc)
