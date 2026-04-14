from sqlalchemy import Column, Integer, String, Numeric, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from database import Base


class Emenda(Base):
    __tablename__ = "emendas"

    id = Column(Integer, primary_key=True, index=True)
    nr_emenda = Column(String(100))
    parlamentar_id = Column(Integer, ForeignKey("parlamentares.id"), index=True)
    municipio_id = Column(Integer, ForeignKey("municipios.id"), index=True)
    convenio_federal_id = Column(Integer, ForeignKey("convenios_federal.id"), nullable=True)
    convenio_estadual_id = Column(Integer, ForeignKey("convenios_estadual.id"), nullable=True)
    valor = Column(Numeric(18, 2))
    ano = Column(Integer)
    tipo = Column(String(100))
    esfera = Column(String(20))
    funcao = Column(String(200))
    subfuncao = Column(String(200))
    raw_data = Column(JSONB)
