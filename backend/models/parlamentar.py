from sqlalchemy import Column, Integer, String, UniqueConstraint
from database import Base


class Parlamentar(Base):
    __tablename__ = "parlamentares"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(300), nullable=False)
    partido = Column(String(50))
    uf = Column(String(2))
    esfera = Column(String(20))  # federal, estadual
    legislatura = Column(String(20))
    external_id = Column(String(100))

    __table_args__ = (
        UniqueConstraint("nome", "partido", "esfera", name="uq_parlamentar"),
    )
