"""
Audit log - trilha de auditoria (LGPD / ISO 27001).

Uma linha = um ato. Grava-se tudo que MUDA dado, a navegacao (deduplicada) e
toda exportacao; consulta individual nao entra, por decisao do dono.

⚠️ Espelha `migrations/add_auditoria_detalhada.sql`. Os dois criam o mesmo
schema por caminhos diferentes: em banco NOVO quem cria a tabela e o
`Base.metadata.create_all` do boot (a partir DESTE arquivo), em banco EXISTENTE
quem acrescenta as colunas e a migration. Mexeu aqui, mexa la — senao o tenant
novo nasce com um schema e o antigo fica com outro, em silencio.

As colunas de imutabilidade (hash encadeado) sao o Incremento 3 e ainda nao
existem; nada aqui atrapalha a entrada delas depois.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)

    # --- Quem ---
    # user_id e ZERADO quando a conta e excluida (routers/control.py::delete_user
    # faz _null_fk em audit_log). Por isso o e-mail e o nome ficam congelados em
    # coluna propria: a trilha continua dizendo quem foi depois da conta sumir.
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    user_email = Column(String(255), index=True)
    usuario_nome = Column(String(200))

    # --- O que ---
    action = Column(String(100), nullable=False, index=True)
    # Ex: "login.success", "login.fail", "cofre.reveal", "cofre.create",
    #     "cofre.delete", "user.create", "user.password_change", "export.pdf",
    #     "nav.tela"
    target_type = Column(String(50))  # ex: "cofre_senha", "user", "convenio"
    target_id = Column(String(100))
    # Nome legivel do alvo no instante do ato. "excluiu o usuario 47" nao explica
    # nada; "excluiu Maria Souza (id 47)" explica — e continua explicando depois
    # que a linha 47 deixa de existir.
    alvo_nome = Column(String(300))

    # sucesso | negado | erro. Tentativa BARRADA e evento tao relevante quanto
    # ato concluido; sem esta coluna os dois ficam iguais na tela.
    resultado = Column(String(16))

    # --- Onde / com que recorte ---
    # Sem FK (ver a migration) e sem index=True: os indices das colunas novas sao
    # COMPOSTOS com created_at e nascem na migration, que roda tambem em banco
    # novo — declarar index=True aqui criaria um segundo indice, redundante.
    municipio_id = Column(Integer)
    ip = Column(String(64))
    user_agent = Column(String(500))   # cru; dispositivo/navegador sao derivados na leitura
    http_metodo = Column(String(10))
    http_path = Column(String(300))    # sem query string (minimizacao LGPD)

    # --- Sessao ---
    sessao_id = Column(String(64))
    sessao_inicio = Column(DateTime(timezone=True))

    # --- Detalhe ---
    details = Column(JSONB)        # contexto livre, sanitizado
    valor_antes = Column(JSONB)    # so os campos que mudaram, sanitizados
    valor_depois = Column(JSONB)   # so os campos que mudaram, sanitizados

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
