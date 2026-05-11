"""
DOU - Diario Oficial da Uniao (via INLABS).
Inserts/atualizacoes de uma publicacao.
"""
from sqlalchemy import Column, Integer, String, Date, DateTime, Text, Index
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB
from database import Base


class DouPublicacao(Base):
    __tablename__ = "dou_publicacoes"

    id = Column(Integer, primary_key=True, index=True)
    id_oficio = Column(String(50), unique=True, index=True)  # id INLABS
    secao = Column(String(20))  # 1, 2, 3, 1e, 2e, 3e
    dt_publicacao = Column(Date, index=True)
    orgao = Column(String(300))
    titulo = Column(String(1000))
    texto = Column(Text)
    autoridade = Column(String(300))
    materia = Column(String(200))  # Portaria, Decreto, Lei, Resolucao
    valor = Column(String(50))  # quando aplicavel
    edicao = Column(String(50))
    pagina = Column(String(20))
    url_pdf = Column(String(500))
    raw_xml = Column(Text)
    keywords_match = Column(JSONB)  # palavras-chave que casaram
    municipio_match = Column(String(300))  # quando texto cita municipio do client
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_dou_dt_secao", "dt_publicacao", "secao"),
    )
