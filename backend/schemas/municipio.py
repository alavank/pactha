from pydantic import BaseModel
from typing import Optional


class MunicipioResponse(BaseModel):
    id: int
    nome: str
    ibge_code: str
    uf: str
    active: bool

    class Config:
        from_attributes = True


class MunicipioSummary(BaseModel):
    municipio: MunicipioResponse
    total_convenios_federal: int = 0
    total_convenios_estadual: int = 0
    valor_total_federal: float = 0
    valor_total_estadual: float = 0
    alertas_vigencia: int = 0
    editais_acompanhados: int = 0
