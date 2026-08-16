from sqlalchemy import Boolean, Column, Date, DateTime, Integer, String, Text
from sqlalchemy.sql import func
from database import Base


class Municipio(Base):
    __tablename__ = "municipios"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(200), nullable=False)
    ibge_code = Column(String(7), unique=True, nullable=False, index=True)
    # ⚠️ SEM default. Nascia "MG" e todo filtro por estado passava a mentir: o
    # coletor do CAGEC ganhava alvo falso, o Acordo FES casava dívida por nome e
    # o FNS consultava a UF errada. O default do BANCO caiu em
    # `uf_sem_default_mg.sql`; este aqui era o resíduo do lado do ORM.
    uf = Column(String(2))
    # Código FNS (6 díg.) p/ o scraper do Fundo Nacional de Saúde — antes hardcoded.
    fns_code = Column(String(6))
    # ⭐ CNPJ (14 dígitos, sem máscara). Antes era INFERIDO de dado coletado
    # (`emendas_estaduais`, `transferegov_pac`) — o que só funciona onde já houve
    # coleta estadual, ou seja, em MG. O coletor do cadastro estadual gaúcho
    # (CHE) precisa dele no dia 1, então ele passa a ter origem própria.
    cnpj = Column(String(14))
    # Conselho Regional de Desenvolvimento (os 28 do RS) — recorte da Consulta
    # Popular e dos programas regionais gaúchos.
    corede = Column(String(60))
    # Código do órgão no tribunal de contas estadual: é a chave das URLs de dado
    # aberto do TCE-RS. ⚠️ A Câmara Municipal tem código próprio e não é o cliente.
    tce_orgao_codigo = Column(String(10))
    # Fundo Municipal de Reconstrução — exigência do fundo a fundo do FUNRIGS.
    fundo_reconstrucao = Column(Boolean)
    fundo_reconstrucao_obs = Column(Text)
    # Até quando vale a exceção de calamidade (prazo de 120 dias em vez do dia 15
    # no monitoramento do Decreto 56.939/2023). Sem ela, o alerta acusa atraso de
    # quem está legalmente em dia.
    calamidade_ate = Column(Date)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
