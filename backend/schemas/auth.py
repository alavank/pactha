from pydantic import BaseModel, Field
from typing import Optional


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    # ROTULO de organizacao interna do cliente. Vem para a tela desenhar o
    # cadastro — NAO para ela decidir o que mostrar. Ver `models/user.py`.
    role: str
    active: bool
    must_change_password: Optional[bool] = False
    # None = acesso TOTAL (super-admin). Lista = o escopo daquela pessoa.
    # Ate o incremento "o papel vira rotulo", `None` chegava tambem para todo
    # `role == "admin"`; hoje o admin do cliente recebe a lista dele.
    telas: Optional[list[str]] = None
    municipio_ids: Optional[list[int]] = None
    # As duas condicoes que NAO se leem do papel. Vao CALCULADAS pelos helpers
    # (`is_super_admin` / `eh_somente_leitura`), como em `GET /users`, e nunca
    # cruas da coluna: quem esta na semente da Alavank manda no sistema mesmo com
    # a coluna em `false`, e mandar `false` ali seria a resposta mentindo sobre
    # quem tem a chave.
    #
    # ⚠️ Sem estes dois campos, `GET /auth/me` e `GET /users` DISCORDAVAM: o
    # backend ja aceitava um dono promovido por UPDATE na coluna, mas a sidebar
    # (que le /auth/me) continuava escondendo Sessoes e Service Tokens dele,
    # porque so lhe restava a allowlist de e-mails. Promover sem deploy e o que o
    # incremento entregou — a tela precisa enxergar isso.
    #
    # Somente LEITURA: nao ha rota que aceite nenhum dos dois de volta neste
    # schema (`RegisterRequest`/`UpdateUserRequest` sao outros modelos).
    super_admin: bool = False
    somente_leitura: bool = False

    class Config:
        from_attributes = True

    @classmethod
    def de_usuario(cls, user) -> "UserResponse":
        """A UNICA porta de saida de um `User` para a API.

        Existe para os tres pontos que respondiam um usuario (`/auth/me`,
        `/auth/register`, `PATCH /users/{id}`) nao calcularem cada um o seu:
        `model_validate` sozinho copia a COLUNA crua, e coluna crua nao e a
        resposta certa para nenhuma das duas flags — `is_super_admin` e
        `eh_somente_leitura` somam a coluna com o reforco do codigo, e e a soma
        que vale em tempo de execucao.

        Import tardio de proposito: `services.auth` puxa `database` e `config` na
        importacao, e este modulo e carregado por `schemas/__init__.py` bem cedo.
        """
        from services.auth import is_super_admin, eh_somente_leitura
        resp = cls.model_validate(user)
        resp.super_admin = is_super_admin(user)
        resp.somente_leitura = eh_somente_leitura(user)
        return resp


class LoginResponse(BaseModel):
    access_token: str  # tambem setado em cookie httpOnly
    token_type: str = "bearer"
    must_change_password: bool = False
    user: UserResponse


class RegisterRequest(BaseModel):
    email: str
    name: str
    password: str = Field(min_length=8)
    role: str = "analyst"


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)
