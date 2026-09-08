"""MCP Token — a credencial de LEITURA que um assistente de IA (Claude, ChatGPT)
usa para consultar os dados do município pela API MCP.

⚠️ DIFERENTE do `ServiceToken` DE PROPÓSITO. O ServiceToken é uma chave-mestra:
super-admin, com `scopes` PRÓPRIOS, sem dono cujo alcance herdar. Este é o
oposto — é um USUÁRIO: pertence a uma pessoa (`user_id`) e herda EXATAMENTE o
escopo de município dela, lido em tempo de verificação. Não há coluna de escopo
aqui, para não existir uma segunda fonte de permissão que divergiria da conta.
Ver `services/mcp_auth.py` e `migrations/add_mcp_tokens.sql`.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from database import Base


class McpToken(Base):
    __tablename__ = "mcp_tokens"

    id = Column(Integer, primary_key=True, index=True)
    # O DONO. O token vale exatamente o que a conta dele vale, hoje — inclusive
    # "conta desativada = token morto" (a verificação recusa dono inativo).
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    name = Column(String(100), nullable=False)      # "Claude do gabinete"
    token_prefix = Column(String(16))               # primeiros chars, p/ identificar
    token_hash = Column(String(64), nullable=False, index=True)  # SHA-256 hex
    active = Column(Boolean, nullable=False, default=True)
    last_used_at = Column(DateTime(timezone=True))  # NULL = nunca usado
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    revoked_at = Column(DateTime(timezone=True))    # revogar não apaga a linha
