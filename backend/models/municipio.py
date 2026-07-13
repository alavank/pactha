from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from database import Base


class Municipio(Base):
    __tablename__ = "municipios"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(200), nullable=False)
    ibge_code = Column(String(7), unique=True, nullable=False, index=True)
    uf = Column(String(2), default="MG")
    # Código FNS (6 díg.) p/ o scraper do Fundo Nacional de Saúde — antes hardcoded.
    fns_code = Column(String(6))
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
