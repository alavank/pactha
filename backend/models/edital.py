from sqlalchemy import Column, Integer, String, Numeric, Date, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from database import Base


class Edital(Base):
    __tablename__ = "editais"

    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String(1000), nullable=False)
    orgao = Column(String(500))
    area = Column(String(100), index=True)
    esfera = Column(String(20))
    url = Column(Text)
    dt_publicacao = Column(Date)
    dt_encerramento = Column(Date, index=True)
    valor_total = Column(Numeric(18, 2))
    resumo = Column(Text)
    status = Column(String(50), default="aberto", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class EditalAcompanhamento(Base):
    __tablename__ = "edital_acompanhamento"

    id = Column(Integer, primary_key=True, index=True)
    edital_id = Column(Integer, ForeignKey("editais.id"), index=True)
    municipio_id = Column(Integer, ForeignKey("municipios.id"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    notas = Column(Text)
    status = Column(String(50), default="acompanhando")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("edital_id", "municipio_id", name="uq_edital_municipio"),
    )
