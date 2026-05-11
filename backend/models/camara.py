"""
Modelos para dados da Camara dos Deputados (e Senado).
- CamaraDespesa: cota parlamentar (CEAP) - gastos do deputado
- CamaraVotacao: como o deputado votou em cada proposicao
- CamaraProposicao: PLs/PECs autoradas pelo deputado
- EmendaCamara: emendas federais via API Camara (autor + valor + situacao)
              complementa siconv_emenda.csv com cobertura diaria
"""
from sqlalchemy import Column, Integer, String, Numeric, Date, DateTime, Text, ForeignKey, Boolean, Index
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB
from database import Base


class CamaraDespesa(Base):
    """Cota Parlamentar (CEAP) - despesas do deputado."""
    __tablename__ = "camara_despesas"

    id = Column(Integer, primary_key=True, index=True)
    parlamentar_id = Column(Integer, ForeignKey("parlamentares.id"), index=True)
    id_camara = Column(Integer, index=True)  # id deputado na API Camara
    ano = Column(Integer, index=True)
    mes = Column(Integer)
    tipo_despesa = Column(String(200))  # combustivel, passagens, etc
    fornecedor = Column(String(300))
    cnpj_cpf = Column(String(20))
    valor_documento = Column(Numeric(18, 2))
    valor_liquido = Column(Numeric(18, 2))
    dt_documento = Column(Date)
    url_documento = Column(String(500))
    nr_documento = Column(String(50))
    raw_data = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CamaraProposicao(Base):
    """Proposicoes (PL, PEC, PLN, etc) autoradas pelo deputado."""
    __tablename__ = "camara_proposicoes"

    id = Column(Integer, primary_key=True, index=True)
    id_camara = Column(Integer, unique=True, index=True)
    sigla_tipo = Column(String(20))  # PL, PEC, PLN, PRC
    numero = Column(Integer)
    ano = Column(Integer, index=True)
    ementa = Column(Text)
    descricao_tipo = Column(String(200))
    autor_id_camara = Column(Integer, index=True)
    autor_nome = Column(String(300))
    autor_partido = Column(String(20))
    autor_uf = Column(String(2))
    situacao = Column(String(200))
    dt_apresentacao = Column(Date)
    url = Column(String(500))
    raw_data = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CamaraVotacao(Base):
    """Votacao do deputado em uma proposicao."""
    __tablename__ = "camara_votacoes"

    id = Column(Integer, primary_key=True, index=True)
    id_votacao = Column(String(50), index=True)  # id votacao Camara
    proposicao_id_camara = Column(Integer, index=True)
    dt_votacao = Column(Date, index=True)
    descricao = Column(Text)
    resultado = Column(String(100))  # Aprovada/Rejeitada
    parlamentar_id = Column(Integer, ForeignKey("parlamentares.id"), index=True)
    id_camara_dep = Column(Integer, index=True)
    voto = Column(String(20))  # Sim/Nao/Abstencao/Obstrucao
    raw_data = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class EmendaCamara(Base):
    """Emendas federais via API Camara (PIX/RP9 individuais e coletivas).
    Complementa siconv_emenda.csv com cobertura diaria por ID_PROPOSTA + autor."""
    __tablename__ = "emendas_camara"

    id = Column(Integer, primary_key=True, index=True)
    cd_emenda = Column(String(20), unique=True, index=True)  # codigo emenda RP9/PIX
    ano = Column(Integer, index=True)
    autor_id_camara = Column(Integer, index=True)
    autor_nome = Column(String(300), index=True)
    tipo = Column(String(50))  # Individual, Bancada, Comissao, Relator
    funcao = Column(String(100))
    subfuncao = Column(String(100))
    valor_indicado = Column(Numeric(18, 2))
    valor_empenhado = Column(Numeric(18, 2))
    valor_pago = Column(Numeric(18, 2))
    objeto = Column(Text)
    municipio_id = Column(Integer, ForeignKey("municipios.id"), nullable=True, index=True)
    codigo_ibge = Column(String(10), index=True)  # bate com municipios.ibge_code
    parlamentar_id = Column(Integer, ForeignKey("parlamentares.id"), nullable=True, index=True)
    raw_data = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
