from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, Text, ForeignKey, Numeric
from sqlalchemy.sql import func
from database import Base


class PrestacaoContas(Base):
    __tablename__ = "prestacao_contas"

    id = Column(Integer, primary_key=True, index=True)
    convenio_estadual_id = Column(Integer, ForeignKey("convenios_estadual.id"), nullable=True)
    convenio_federal_id = Column(Integer, ForeignKey("convenios_federal.id"), nullable=True)
    municipio_id = Column(Integer, ForeignKey("municipios.id"), index=True)
    etapa_atual = Column(Integer, default=1)
    etapa_nome = Column(String(200))
    responsavel_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(100), default="pendente")
    observacoes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PrestacaoDocumento(Base):
    __tablename__ = "prestacao_documentos"

    id = Column(Integer, primary_key=True, index=True)
    prestacao_id = Column(Integer, ForeignKey("prestacao_contas.id"), index=True)
    documento_nome = Column(String(500), nullable=False)
    enviado = Column(Boolean, default=False)
    dt_envio = Column(Date, nullable=True)
    responsavel_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    observacao = Column(Text)


class PlanoTrabalho(Base):
    """Itens do plano de trabalho aprovado (orcamento por categoria/meta)."""
    __tablename__ = "plano_trabalho"

    id = Column(Integer, primary_key=True, index=True)
    prestacao_id = Column(Integer, ForeignKey("prestacao_contas.id"), index=True, nullable=False)
    item = Column(String(500), nullable=False)  # ex: "Aquisicao de UBS Movel"
    categoria = Column(String(100))  # ex: "Material Permanente", "Servico Terceiros"
    quantidade = Column(Numeric(12, 2))
    valor_unitario = Column(Numeric(18, 2))
    valor_planejado = Column(Numeric(18, 2), nullable=False)
    observacao = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class NotaFiscal(Base):
    """Notas fiscais entregues pelo cliente para a prestacao de contas."""
    __tablename__ = "notas_fiscais"

    id = Column(Integer, primary_key=True, index=True)
    prestacao_id = Column(Integer, ForeignKey("prestacao_contas.id"), index=True, nullable=False)
    plano_item_id = Column(Integer, ForeignKey("plano_trabalho.id"), nullable=True, index=True)
    nf_numero = Column(String(50))
    nf_serie = Column(String(20))
    fornecedor_nome = Column(String(300))
    fornecedor_cnpj = Column(String(20))
    descricao = Column(Text)
    valor = Column(Numeric(18, 2), nullable=False)
    dt_emissao = Column(Date)
    dt_pagamento = Column(Date)
    arquivo_path = Column(String(500))
    validada = Column(Boolean, default=False)
    obs_validacao = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
