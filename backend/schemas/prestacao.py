from pydantic import BaseModel
from typing import Optional, List
from datetime import date


class DocumentoResponse(BaseModel):
    id: int
    documento_nome: str
    enviado: bool
    dt_envio: Optional[date] = None
    responsavel_id: Optional[int] = None
    observacao: Optional[str] = None

    class Config:
        from_attributes = True


class PrestacaoResponse(BaseModel):
    id: int
    convenio_estadual_id: Optional[int] = None
    convenio_federal_id: Optional[int] = None
    municipio_id: int
    etapa_atual: int
    etapa_nome: Optional[str] = None
    responsavel_id: Optional[int] = None
    status: str
    observacoes: Optional[str] = None
    documentos: List[DocumentoResponse] = []
    nr_convenio: Optional[str] = None
    objeto: Optional[str] = None
    esfera: Optional[str] = None
    orgao_concedente: Optional[str] = None
    valor_total: Optional[float] = None
    dt_inicio: Optional[date] = None
    dt_fim_vigencia: Optional[date] = None
    dias_restantes: Optional[int] = None
    ano: Optional[int] = None
    situacao: Optional[str] = None

    class Config:
        from_attributes = True


class PrestacaoUpdate(BaseModel):
    etapa_atual: Optional[int] = None
    etapa_nome: Optional[str] = None
    responsavel_id: Optional[int] = None
    status: Optional[str] = None
    observacoes: Optional[str] = None


class DocumentoCreate(BaseModel):
    documento_nome: str
    responsavel_id: Optional[int] = None


class DocumentoUpdate(BaseModel):
    enviado: Optional[bool] = None
    dt_envio: Optional[date] = None
    responsavel_id: Optional[int] = None
    observacao: Optional[str] = None
