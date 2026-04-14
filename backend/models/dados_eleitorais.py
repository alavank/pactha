from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, UniqueConstraint
from database import Base


class DadosEleitorais(Base):
    __tablename__ = "dados_eleitorais"

    id = Column(Integer, primary_key=True, index=True)
    parlamentar_id = Column(Integer, ForeignKey("parlamentares.id"), index=True)
    municipio_id = Column(Integer, ForeignKey("municipios.id"), index=True)
    ano_eleicao = Column(Integer)
    votos = Column(Integer)
    cargo = Column(String(100))
    eleito = Column(Boolean)

    __table_args__ = (
        UniqueConstraint("parlamentar_id", "municipio_id", "ano_eleicao", "cargo", name="uq_eleicao"),
    )
