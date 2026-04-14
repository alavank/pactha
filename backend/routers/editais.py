from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from database import get_db
from models import Edital, EditalAcompanhamento
from schemas.edital import EditalCreate, EditalResponse, AcompanhamentoCreate, AcompanhamentoResponse
from services.auth import get_current_user
from models.user import User

router = APIRouter(prefix="/api/editais", tags=["editais"])


@router.get("", response_model=list[EditalResponse])
async def list_editais(
    area: Optional[str] = None,
    esfera: Optional[str] = None,
    status: Optional[str] = None,
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(Edital)
    if area:
        q = q.where(Edital.area == area)
    if esfera:
        q = q.where(Edital.esfera == esfera)
    if status:
        q = q.where(Edital.status == status)
    q = q.order_by(Edital.dt_encerramento.asc().nullslast())
    result = await db.execute(q)
    editais = result.scalars().all()

    responses = []
    for e in editais:
        resp = EditalResponse.model_validate(e)
        if municipio_id:
            acomp = await db.execute(
                select(EditalAcompanhamento).where(
                    EditalAcompanhamento.edital_id == e.id,
                    EditalAcompanhamento.municipio_id == municipio_id,
                )
            )
            resp.acompanhando = acomp.scalar_one_or_none() is not None
        responses.append(resp)
    return responses


@router.post("", response_model=EditalResponse)
async def create_edital(
    data: EditalCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    edital = Edital(**data.model_dump())
    db.add(edital)
    await db.commit()
    await db.refresh(edital)
    return EditalResponse.model_validate(edital)


@router.post("/{edital_id}/acompanhar", response_model=AcompanhamentoResponse)
async def acompanhar_edital(
    edital_id: int,
    data: AcompanhamentoCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    edital = await db.get(Edital, edital_id)
    if not edital:
        raise HTTPException(status_code=404, detail="Edital nao encontrado")

    acomp = EditalAcompanhamento(
        edital_id=edital_id,
        municipio_id=data.municipio_id,
        user_id=user.id,
        notas=data.notas,
    )
    db.add(acomp)
    await db.commit()
    await db.refresh(acomp)
    return AcompanhamentoResponse(
        id=acomp.id,
        edital=EditalResponse.model_validate(edital),
        municipio_id=acomp.municipio_id,
        status=acomp.status,
        notas=acomp.notas,
    )


@router.get("/acompanhados", response_model=list[AcompanhamentoResponse])
async def list_acompanhados(
    municipio_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    q = select(EditalAcompanhamento).where(
        EditalAcompanhamento.municipio_id == municipio_id
    )
    result = await db.execute(q)
    acomps = result.scalars().all()

    responses = []
    for a in acomps:
        edital = await db.get(Edital, a.edital_id)
        responses.append(AcompanhamentoResponse(
            id=a.id,
            edital=EditalResponse.model_validate(edital),
            municipio_id=a.municipio_id,
            status=a.status,
            notas=a.notas,
        ))
    return responses
