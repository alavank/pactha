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
    # EMENDA vinculada (direcao reversa de #3): casada pelo nr_indicacao capturado
    # no convenio (raw_data->>'nr_indicacao' / raw_data->'indicacoes'). Vazio ate o
    # scraper popular a indicacao. Ver routers/convenios.list_convenios.
    emenda_nr: Optional[str] = None
    emenda_objeto: Optional[str] = None
    # ULTIMA ALTERACAO do convenio estadual (SIGCON). A situacao real do momento
    # vive aqui — `situacao` sozinha e generica. Vazio ate o scraper capturar.
    alteracao_situacao: Optional[str] = None
    alteracao_tipo: Optional[str] = None
    alteracao_data: Optional[str] = None
    alteracao_titulo: Optional[str] = None

    class Config:
        from_attributes = True


class ConvenioListResponse(BaseModel):
    items: List[ConvenioResponse]
    total: int
    page: int
    per_page: int
    pages: int
    # Frescor da coleta SIGCON do municipio filtrado (None sem municipio_id,
    # sem rastreio ou com coleta falhando). coleta_falhas > 0 = login/portal
    # falhando ha N rodadas: a tela avisa em vez de exibir um "atualizado em"
    # que na verdade seria a hora do ultimo ERRO (pos-#159 o carimbo tambem
    # acontece na falha, para o rodizio nao sofrer starvation).
    coleta_em: Optional[str] = None
    coleta_falhas: int = 0


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
    # QUAL municipio — sem isto o consumidor nao sabe de quem e o convenio (o
    # modal de vigencias do Painel mostrava "—" e nao conseguia nem agrupar nem
    # filtrar). `municipio_nome` vem junto para a tela nao precisar cruzar.
    municipio_id: Optional[int] = None
    municipio_nome: Optional[str] = None
    nr_convenio: Optional[str] = None
    nr_sigcon: Optional[str] = None
    objeto: Optional[str] = None
    orgao_concedente: Optional[str] = None
    dt_fim_vigencia: Optional[date] = None
    dias_restantes: int
    valor_total: Optional[float] = None
    situacao: Optional[str] = None
