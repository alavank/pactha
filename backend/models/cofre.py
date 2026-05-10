from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from database import Base


class CofreSenha(Base):
    __tablename__ = "cofre_senhas"

    id = Column(Integer, primary_key=True, index=True)
    municipio_id = Column(Integer, ForeignKey("municipios.id"), index=True)
    sistema = Column(String(200), nullable=False)  # ex: "TransfereGov", "SIGCON-MG", "FNS"
    url = Column(Text)
    usuario = Column(String(200))
    senha_encrypted = Column("senha_hash", Text)  # AES-GCM encrypted via services.crypto
    observacao = Column(Text)
    categoria = Column(String(100))  # ex: "Federal", "Estadual", "Saude", "Educacao"
    atualizado_por_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
