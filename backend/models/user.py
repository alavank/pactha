from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), default="analyst")
    active = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=True)
    # Conta de QUIOSQUE (TV/celular publicados por link). Marca no USUARIO e nao
    # no token: o refresh nao repassa claim, entao claim nao sobrevive a um 401.
    # Ver migrations/add_users_kiosk.sql.
    kiosk = Column(Boolean, default=False, nullable=False)
    last_login_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
