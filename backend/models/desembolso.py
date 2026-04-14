from sqlalchemy import Column, Integer, String, Numeric, Date, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from database import Base


class Desembolso(Base):
    __tablename__ = "desembolsos"

    id = Column(Integer, primary_key=True, index=True)
    convenio_federal_id = Column(Integer, ForeignKey("convenios_federal.id"), index=True)
    data_desembolso = Column(Date)
    valor = Column(Numeric(18, 2))
    nr_ordem_bancaria = Column(String(100))
    raw_data = Column(JSONB)
