from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from database import Base


class PrestacaoContas(Base):
    __tablename__ = "prestacao_contas"

    id = Column(Integer, primary_key=True, index=True)
    convenio_estadual_id = Column(Integer, ForeignKey("convenios_estadual.id"), nullable=True)
    convenio_federal_id = Column(Integer, ForeignKey("convenios_federal.id"), nullable=True)
    municipio_id = Column(Integer, ForeignKey("municipios.id"), index=True)
    etapa_atual = Column(Integer, default=1)
    etapa_nome = Column(String(200))
    responsavel_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(100), default="pendente")
    observacoes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PrestacaoDocumento(Base):
    __tablename__ = "prestacao_documentos"

    id = Column(Integer, primary_key=True, index=True)
    prestacao_id = Column(Integer, ForeignKey("prestacao_contas.id"), index=True)
    documento_nome = Column(String(500), nullable=False)
    enviado = Column(Boolean, default=False)
    dt_envio = Column(Date, nullable=True)
    responsavel_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    observacao = Column(Text)
