"""
Compliance: CEIS (Cadastro de Empresas Inidoneas e Suspensas) + CNEP (Empresas Punidas).
Fonte: Portal Transparencia bulk CSV.
"""
from sqlalchemy import Column, Integer, String, Date, DateTime, Text, Numeric
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB
from database import Base


class SancaoCEIS(Base):
    """Cadastro de Empresas Inidoneas e Suspensas - sancoes administrativas."""
    __tablename__ = "sancoes_ceis"

    id = Column(Integer, primary_key=True, index=True)
    cpf_cnpj = Column(String(20), index=True)
    razao_social = Column(String(500))
    nome_fantasia = Column(String(500))
    tipo_pessoa = Column(String(20))  # PJ/PF
    tipo_sancao = Column(String(200))
    fundamentacao = Column(Text)
    dt_inicio_sancao = Column(Date, index=True)
    dt_fim_sancao = Column(Date, index=True)
    dt_publicacao = Column(Date)
    orgao_sancionador = Column(String(300))
    uf_sancionador = Column(String(2))
    raw_data = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ProgramaFederal(Base):
    """Catalogo de programas federais ativos (oportunidades) - SICONV."""
    __tablename__ = "programas_federais"

    id = Column(Integer, primary_key=True, index=True)
    id_programa = Column(Integer, unique=True, index=True)
    nome_programa = Column(String(500))
    orgao = Column(String(300))
    objetivo = Column(Text)
    publico_alvo = Column(String(500))
    valor_minimo = Column(Numeric(18, 2))
    valor_maximo = Column(Numeric(18, 2))
    dt_inicio_inscricao = Column(Date, index=True)
    dt_fim_inscricao = Column(Date, index=True)
    contrapartida_min_pct = Column(Numeric(5, 2))
    modalidade = Column(String(200))
    natureza = Column(String(100))
    situacao = Column(String(100), index=True)  # Aberto, Fechado
    url = Column(String(500))
    raw_data = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
