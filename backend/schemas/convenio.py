from pydantic import BaseModel
from typing import Optional, List
from datetime import date
from decimal import Decimal


class ConvenioResponse(BaseModel):
    id: int
    esfera: str  # federal ou estadual
    nr_convenio: Optional[str] = None
    nr_sigcon: Optional[str] = None
    municipio_id: int
    orgao_concedente: Optional[str] = None
    objeto: Optional[str] = None
    situacao: Optional[str] = None
    valor_total: Optional[float] = None
    valor_repasse: Optional[float] = None
    valor_empenhado: Optional[float] = None
    valor_desembolsado: Optional[float] = None
    valor_contrapartida: Optional[float] = None
    dt_inicio: Optional[date] = None
    dt_fim_vigencia: Optional[date] = None
    dias_restantes: Optional[int] = None
    ano: Optional[int] = None
    programa: Optional[str] = None
    etapa_sigcon: Optional[str] = None
    etapa_sigcon_nr: Optional[int] = None
    # Campos extras (PDF Freitas / RM Word)
    fonte: Optional[str] = None
    tipo_programa: Optional[str] = None
    banco: Optional[str] = None
    agencia: Optional[str] = None
    conta_corrente: Optional[str] = None
    saldo_bancario: Optional[float] = None
    dt_saldo: Optional[date] = None
    nr_sei: Optional[str] = None
    dt_empenho: Optional[date] = None
    dt_desembolso: Optional[date] = None
    # SIGCON: numeros de tracking (Pesquisa Unificada)
    nr_proposta: Optional[str] = None
    nr_plano_trabalho: Optional[str] = None
    nr_instrumento: Optional[str] = None
    nr_siafi: Optional[str] = None

    class Config:
        from_attributes = True


class ConvenioListResponse(BaseModel):
    items: List[ConvenioResponse]
    total: int
    page: int
    per_page: int
    pages: int


class ConvenioStats(BaseModel):
    total_convenios: int = 0
    total_ativos: int = 0
    valor_total: float = 0
    valor_empenhado: float = 0
    valor_desembolsado: float = 0
    por_situacao: dict = {}
    por_esfera: dict = {}


class AlertaVigencia(BaseModel):
    id: int
    esfera: str
    nr_convenio: Optional[str] = None
    nr_sigcon: Optional[str] = None
    objeto: Optional[str] = None
    orgao_concedente: Optional[str] = None
    dt_fim_vigencia: Optional[date] = None
    dias_restantes: int
    valor_total: Optional[float] = None
    situacao: Optional[str] = None
