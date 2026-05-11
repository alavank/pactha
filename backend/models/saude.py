"""
Modelos para dados de saude:
- EstabelecimentoCNES: estabelecimentos CNES por municipio (UBS, hospitais).
  Util para enriquecer convenios de saude e gerar relatorios.
"""
from sqlalchemy import Column, Integer, String, Date, DateTime, Text, ForeignKey, Index
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB
from database import Base


class EstabelecimentoCNES(Base):
    __tablename__ = "estabelecimentos_cnes"

    id = Column(Integer, primary_key=True, index=True)
    cnes = Column(String(15), unique=True, index=True)
    cnpj = Column(String(20), index=True)
    nome_fantasia = Column(String(500))
    razao_social = Column(String(500))
    municipio_id = Column(Integer, ForeignKey("municipios.id"), nullable=True, index=True)
    codigo_ibge = Column(String(10), index=True)
    natureza_juridica = Column(String(200))
    tipo_estabelecimento = Column(String(200))
    subtipo = Column(String(200))
    endereco = Column(String(500))
    bairro = Column(String(200))
    cep = Column(String(10))
    telefone = Column(String(50))
    email = Column(String(200))
    raw_data = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
