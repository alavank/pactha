from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    password_hash = Column(String(255), nullable=False)
    # ROTULO de organizacao interna do cliente ("prefeito", "usuario", "admin"),
    # nao concessao. Quem decide o que a pessoa alcanca sao as permissoes dela,
    # uma a uma: user_telas, user_municipios e as duas flags abaixo. Ver
    # migrations/add_role_vira_rotulo.sql.
    role = Column(String(50), default="usuario")
    active = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=True)
    # Dono da PLATAFORMA (Alavank), nao "mais um admin do cliente". Era a
    # allowlist SUPER_ADMIN_EMAILS no CODIGO, copiada em tres arquivos: trocar
    # quem manda exigia deploy. Virou dado; a lista do codigo continua como
    # semente e reforco, para nunca se perder o acesso por erro de migracao.
    # `server_default` alem do `default`: ha INSERT em `users` escrito a mao
    # (routers/bi.py cria a conta de quiosque por SQL cru, sem citar estas
    # colunas). Sem default NO BANCO, um NOT NULL sem valor viraria erro de
    # insercao em vez de FALSE.
    super_admin = Column(Boolean, default=False, nullable=False, server_default="false")
    # Trava de ACAO por USUARIO. Antes vinha do papel (READONLY_ROLES =
    # {'prefeito','viewer'} em services/auth.py), e por isso marcar alguem como
    # prefeito decidia o acesso dele. Separada do rotulo, da para ter dois
    # prefeitos com acessos diferentes — e um deles podendo escrever.
    somente_leitura = Column(Boolean, default=False, nullable=False, server_default="false")
    # Conta de QUIOSQUE (TV/celular publicados por link). Marca no USUARIO e nao
    # no token: o refresh nao repassa claim, entao claim nao sobrevive a um 401.
    # Ver migrations/add_users_kiosk.sql.
    kiosk = Column(Boolean, default=False, nullable=False)
    last_login_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
