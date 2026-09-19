from pydantic import BaseModel


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
    total_convenios_estadual: int = 0
    total_voluntarias: int = 0      # voluntárias CELEBRADAS (services/fases_voluntaria)
    valor_total_estadual: float = 0
    valor_total_federal: float = 0  # soma valor_global/repasse das CELEBRADAS
    # {celebrada|analise|rejeitada: {n, valor}} — o que não é celebrado fica AO LADO
    voluntarias_fases: dict = {}
    alertas_vigencia: int = 0       # vencendo em ate 120 dias (estadual + voluntarias)
    alertas_vigencia_60d: int = 0   # vencendo em ate 60 dias (critico)
    alertas_prestacao_contas: int = 0  # vencidos ha +90 dias (total estadual + federal)
    alertas_prestacao_contas_estadual: int = 0  # SIGCON vencidos ha +90 dias
    alertas_prestacao_contas_federal: int = 0   # Voluntarias vencidas ha +90 dias
