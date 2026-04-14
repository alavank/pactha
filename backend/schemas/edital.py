from pydantic import BaseModel
from typing import Optional
from datetime import date


class EditalCreate(BaseModel):
    titulo: str
    orgao: Optional[str] = None
    area: Optional[str] = None
    esfera: Optional[str] = None
    url: Optional[str] = None
    dt_publicacao: Optional[date] = None
    dt_encerramento: Optional[date] = None
    valor_total: Optional[float] = None
    resumo: Optional[str] = None


class EditalResponse(BaseModel):
    id: int
    titulo: str
    orgao: Optional[str] = None
    area: Optional[str] = None
    esfera: Optional[str] = None
    url: Optional[str] = None
    dt_publicacao: Optional[date] = None
    dt_encerramento: Optional[date] = None
    valor_total: Optional[float] = None
    resumo: Optional[str] = None
    status: str
    acompanhando: bool = False

    class Config:
        from_attributes = True


class AcompanhamentoCreate(BaseModel):
    municipio_id: int
    notas: Optional[str] = None


class AcompanhamentoResponse(BaseModel):
    id: int
    edital: EditalResponse
    municipio_id: int
    status: str
    notas: Optional[str] = None

    class Config:
        from_attributes = True
