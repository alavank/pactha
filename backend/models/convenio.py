from sqlalchemy import Column, Integer, String, Numeric, Date, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from database import Base


class ConvenioFederal(Base):
    __tablename__ = "convenios_federal"

    id = Column(Integer, primary_key=True, index=True)
    nr_convenio = Column(String(50), unique=True, nullable=False, index=True)
    municipio_id = Column(Integer, ForeignKey("municipios.id"), index=True)
    proponente_nome = Column(String(500))
    orgao_concedente = Column(String(500))
    objeto = Column(Text)
    situacao = Column(String(200), index=True)
    valor_global = Column(Numeric(18, 2))
    valor_repasse = Column(Numeric(18, 2))
    valor_contrapartida = Column(Numeric(18, 2))
    valor_empenhado = Column(Numeric(18, 2))
    valor_desembolsado = Column(Numeric(18, 2))
    dt_inicio = Column(Date)
    dt_fim = Column(Date)
    dt_fim_vigencia = Column(Date, index=True)
    ano = Column(Integer)
    programa = Column(String(500))
    modalidade = Column(String(200))
    fonte = Column(String(50), default="TransfereGov")  # TransfereGov, FNS, SIMEC, SISMOB, SUAS, Upload
    raw_data = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ConvenioEstadual(Base):
    __tablename__ = "convenios_estadual"

    id = Column(Integer, primary_key=True, index=True)
    nr_sigcon = Column(String(50), index=True)
    nr_siafi = Column(String(50))
    municipio_id = Column(Integer, ForeignKey("municipios.id"), index=True)
    convenente_nome = Column(String(500))
    orgao_concedente = Column(String(500))
    objeto = Column(Text)
    objetivo = Column(Text)
    situacao = Column(String(200), index=True)
    tp_instrumento = Column(String(100))
    valor_concedente = Column(Numeric(18, 2))
    valor_emenda_parlamentar = Column(Numeric(18, 2))
    valor_contrapartida = Column(Numeric(18, 2))
    valor_total = Column(Numeric(18, 2))
    valor_repassado = Column(Numeric(18, 2))
    dt_publicacao = Column(Date)
    dt_vigencia_inicial = Column(Date)
    dt_vigencia_final = Column(Date)
    dt_vigencia_atual = Column(Date, index=True)
    ano = Column(Integer)
    etapa_sigcon = Column(String(200))
    etapa_sigcon_nr = Column(Integer)
    fonte = Column(String(50), default="SIGCON-MG")
    raw_data = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
