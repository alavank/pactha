from pydantic import BaseModel
from typing import Optional


class EmendaPorDeputado(BaseModel):
    parlamentar_id: int
    parlamentar_nome: str
    partido: Optional[str] = None
    total_valor: float
    total_emendas: int
    esfera: Optional[str] = None


class BenchmarkMunicipio(BaseModel):
    municipio_id: int
    municipio_nome: str
    total_emendas: float
    total_convenios: int
    total_valor_convenios: float


class TopDeputado(BaseModel):
    parlamentar_id: int
    parlamentar_nome: str
    partido: Optional[str] = None
    votos: int
    cargo: Optional[str] = None
    eleito: bool = False
    total_emendas_valor: Optional[float] = None
    status: Optional[str] = None  # "completo", "sem_tse", "sem_emendas", "coletivo"
