"""
Audit log - registra acoes sensiveis para conformidade LGPD.
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    user_email = Column(String(255), index=True)
    action = Column(String(100), nullable=False, index=True)
    # Ex: "login.success", "login.fail", "cofre.reveal", "cofre.create",
    #     "cofre.delete", "user.create", "user.password_change", "export.pdf"
    target_type = Column(String(50))  # ex: "cofre_senha", "user", "convenio"
    target_id = Column(String(100))
    ip = Column(String(64))
    user_agent = Column(String(500))
    details = Column(JSONB)  # dados adicionais opcionais
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
