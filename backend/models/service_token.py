"""
Service Token - autenticacao para scrapers/workers (separada de Users).

Caracteristicas:
- Token guardado HASHED no banco (nunca em claro)
- Escopo restrito (ex: "secret:read" apenas)
- Pode ser revogado/rotacionado a qualquer momento
- Cada uso registra audit_log
- Pode ter expiracao opcional
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from database import Base


class ServiceToken(Base):
    __tablename__ = "service_tokens"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)  # "fns_scraper", "simec_scraper"
    # Discrimina o tipo: 'scraper' (default) | 'control' (token do Console Alavank)
    kind = Column(String(20), server_default="scraper", default="scraper")
    token_hash = Column(String(255), nullable=False, index=True)  # SHA-256 do token raw
    token_prefix = Column(String(12))  # primeiros 12 chars (para identificacao em logs)
    scopes = Column(JSONB, default=list)  # ["secret:read:fns", "secret:read:simec"]
    description = Column(Text)
    active = Column(Boolean, default=True)
    last_used_at = Column(DateTime(timezone=True))
    last_used_ip = Column(String(64))
    expires_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by_user_id = Column(Integer)
