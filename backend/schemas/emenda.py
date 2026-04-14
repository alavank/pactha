from pydantic import BaseModel
from typing import Optional


class EmendaResponse(BaseModel):
    id: int
    nr_emenda: Optional[str] = None
    parlamentar_nome: Optional[str] = None
    parlamentar_partido: Optional[str] = None
    municipio_id: int
    valor: Optional[float] = None
    ano: Optional[int] = None
    tipo: Optional[str] = None
    esfera: Optional[str] = None
    funcao: Optional[str] = None

    class Config:
        from_attributes = True
