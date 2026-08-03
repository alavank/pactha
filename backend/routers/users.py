"""Gerenciamento de usuarios (admin-only).

Telas: listar, criar, resetar senha, ativar/desativar, mudar role.
Senhas nunca sao retornadas (hash bcrypt). Reset gera senha temporaria
aleatoria que o admin repassa; usuario troca no proximo login.
"""
import secrets
import string
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from pydantic import BaseModel

from database import get_db
from models.user import User
from schemas.auth import UserResponse
from services.auth import (
    hash_password, get_current_user, is_super_admin, eh_somente_leitura,
    READONLY_ROLES,
)
from services.audit import registrar, registrar_critico

router = APIRouter(prefix="/api/users", tags=["users"])

ALPHABET = string.ascii_letters + string.digits + "!@#$%&*"


def _gen_senha(n: int = 14) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


def _require_admin(user: User):
    """Gate de ACAO desta tela — continua olhando o PAPEL, de proposito.

    `role` deixou de CONCEDER escopo (ver `services/auth.py::load_user_scopes`),
    mas quem pode dar e tirar permissao dos outros ainda e decidido aqui pelo
    rotulo. Trocar isto por permissao individual e o Incremento 5 (permissao por
    ACAO); fazer junto significaria mudar QUEM tem escopo e ONDE se checa no
    mesmo deploy, e a primeira mudanca ja e a que arrisca trancar o cliente
    fora. Ate la, `admin` deixou de ser deus mas continua sendo o zelador.
    """
    if user.role != "admin":
        raise HTTPException(403, "Apenas administradores podem gerenciar usuarios")


# Contas donas do sistema: a lista vive em services/auth.py (uma so, para as
# copias nao divergirem). Sem a guarda abaixo, qualquer admin reseta a senha do
# dono para a padrao "1234" e entra no lugar dele.
_is_super = is_super_admin


def _guard_target(current: User, target: User):
    """Protege contas sensiveis contra quem nao pode altera-las."""
    if _is_super(target) and not _is_super(current):
        raise HTTPException(403, "Somente o administrador principal pode alterar essa conta")
    if target.role == "admin" and current.role != "admin":
        raise HTTPException(403, "Apenas administradores podem alterar contas admin")


# ⚠️ `super_admin` NAO entra nestes payloads, e a ausencia e a decisao: e a chave
# da PLATAFORMA (Alavank), nao do cliente. Aceita-lo aqui deixaria qualquer admin
# do tenant se promover a dono num PATCH e alcancar Sessoes, Service Tokens e as
# contas dos outros donos — escalada de privilegio pela porta da frente. Trocar
# quem manda ja nao exige mais deploy (virou coluna), mas exige acesso ao BANCO,
# que e outro nivel de confianca.
#
# `somente_leitura` ENTRA, e a diferenca e proposital. Ela nao promove ninguem —
# so restringe —, e sem ela este incremento AFROUXAVA a unica trava de acao do
# sistema: `READONLY_ROLES = {"prefeito","viewer"}` barrava escrita pelo PAPEL,
# entao marcar alguem como "Prefeito" nesta tela produzia, ate ontem, uma conta
# que nao escreve. Com o guard lendo a FLAG e a flag so alcancavel por migration,
# todo prefeito criado DEPOIS do deploy nasceria com escrita liberada em tudo o
# que tivesse tela — e sem caminho nenhum, fora do banco, para conte-lo. Era
# trocar "prefeito nao escreve" por "prefeito escreve", calado.
class CreateUserRequest(BaseModel):
    email: str
    name: str
    # Default deixou de ser "admin". Enquanto `role == "admin"` zerava os limites
    # em `load_user_scopes`, este default fazia um POST que ESQUECESSE o campo
    # criar um usuario sem limite nenhum — o campo mais poderoso do sistema era o
    # campo omitido. Hoje o papel e so rotulo, mas o default continua sendo o
    # rotulo mais modesto: um cadastro incompleto nao pode sair com o rotulo de
    # zelador, que ainda e o que abre esta tela de Usuarios (`_require_admin`).
    # "user" e o mesmo default que a tela de Usuarios passou a marcar neste
    # incremento — duas portas de criacao com defaults diferentes divergem em
    # silencio. A tela sempre manda o campo; quem herda este default e cliente de
    # API. (O canal do Console, em `routers/control.py`, usa "analyst"; os dois
    # sao byte-identicos no codigo — nenhuma checagem testa nenhum dos dois.)
    role: str = "user"
    municipio_ids: Optional[list[int]] = None  # municipios que o usuario pode acessar
    telas: Optional[list[str]] = None  # telas/modulos que o usuario pode acessar
    # `None` = "nao opinei", e NAO `False`. Omitido, o default e semeado do
    # rotulo — a MESMA regra que a migration usou para semear as contas que ja
    # existiam (`role IN ('prefeito','viewer')`). E semente de nascimento, nao
    # regra de execucao: no minuto seguinte o administrador liga e desliga a flag
    # nesta mesma tela, individualmente, que e o que o dono pediu.
    #
    # A licao vem do proprio `role: str = "admin"` que este incremento matou: o
    # campo OMITIDO nao pode ser o campo mais permissivo. Quem esquece de mandar
    # `somente_leitura` ao cadastrar um prefeito recebe o comportamento de
    # ontem — restritivo —, e nao escrita liberada em silencio.
    somente_leitura: Optional[bool] = None


class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None
    municipio_ids: Optional[list[int]] = None
    telas: Optional[list[str]] = None
    # `None` = nao mexe. Trocar o ROTULO nao arrasta a flag junto: um prefeito
    # que ganhou escrita continua com escrita se for reetiquetado, e e isso que
    # separa as duas coisas de vez.
    somente_leitura: Optional[bool] = None


def _trava_inicial(role: str, pedido: Optional[bool]) -> bool:
    """A trava de escrita com que a conta NASCE.

    O que o administrador marcou na tela; e, quando ele nao disse nada, o que o
    sistema fazia com esse rotulo ate a vespera deste incremento
    (`READONLY_ROLES`). Isso e SEMENTE de nascimento, nao regra de execucao —
    quem autoriza em runtime e a coluna, e ela se edita usuario a usuario. Um
    prefeito pode receber escrita no minuto seguinte sem deixar de ser prefeito.

    ⚠️ O campo OMITIDO nao pode ser o mais permissivo — e a licao do
    `role: str = "admin"` que este mesmo incremento matou. Sem esta semente, um
    POST sem `somente_leitura` criaria prefeito com escrita liberada em tudo o
    que tivesse tela, calado, onde ontem sairia uma conta que nao escreve.
    """
    return pedido if pedido is not None else role in READONLY_ROLES


async def _set_user_municipios(db: AsyncSession, user_id: int, ids) -> None:
    """Substitui o conjunto de municipios permitidos do usuario."""
    await db.execute(text("DELETE FROM user_municipios WHERE user_id = :u"), {"u": user_id})
    for mid in (ids or []):
        await db.execute(
            text("INSERT INTO user_municipios (user_id, municipio_id) VALUES (:u, :m) "
                 "ON CONFLICT DO NOTHING"),
            {"u": user_id, "m": int(mid)},
        )


async def _set_user_telas(db: AsyncSession, user_id: int, telas) -> None:
    """Substitui o conjunto de telas/modulos permitidos do usuario."""
    await db.execute(text("DELETE FROM user_telas WHERE user_id = :u"), {"u": user_id})
    for tela in (telas or []):
        t = str(tela).strip()
        if not t:
            continue
        await db.execute(
            text("INSERT INTO user_telas (user_id, tela) VALUES (:u, :t) "
                 "ON CONFLICT DO NOTHING"),
            {"u": user_id, "t": t},
        )


# ---------------------------------------------------------------------------
# Trilha de PERMISSAO — o que a auditoria precisa saber sobre quem pode o que
#
# "Quem deu essa permissao a essa pessoa, e quando" nao tinha resposta: o
# registro de edicao de usuario guardava so {name, role, active}. Telas e
# municipios — que sao a permissao de verdade — mudavam sem deixar rastro, e sem
# valor-antes/valor-depois nem daria para dizer se a edicao concedeu ou retirou.
# ---------------------------------------------------------------------------
async def _snapshot_acessos(db: AsyncSession, user_id: int) -> dict:
    """Telas e municipios que o usuario tem NESTE instante.

    Le pelo mesmo AsyncSession das escritas de proposito: chamado depois de
    `_set_user_telas`/`_set_user_municipios` e ANTES do commit, enxerga o estado
    novo dentro da propria transacao — e assim o "depois" e o que de fato ficou
    gravado, nao o que o payload pediu."""
    t = (await db.execute(
        text("SELECT tela FROM user_telas WHERE user_id = :u"), {"u": user_id})).fetchall()
    m = (await db.execute(
        text("SELECT municipio_id FROM user_municipios WHERE user_id = :u"), {"u": user_id})).fetchall()
    return {"telas": sorted(r[0] for r in t), "municipios": sorted(r[0] for r in m)}


async def _nomes_municipios(db: AsyncSession, ids) -> dict:
    """id -> "Nome/UF" para a trilha nao virar uma lista de numeros.

    Guarda o nome VIGENTE no momento do ato: se o municipio for renomeado depois,
    o registro continua descrevendo o que o administrador tinha na tela. Trilha
    de 5 anos precisa ser legivel sozinha, sem depender de join com uma tabela
    que mudou nesse meio-tempo."""
    ids = sorted({int(i) for i in (ids or [])})
    if not ids:
        return {}
    rows = (await db.execute(
        text("SELECT id, nome, uf FROM municipios WHERE id = ANY(:ids)"), {"ids": ids})).fetchall()
    return {str(r[0]): f"{r[1]}/{r[2]}" for r in rows}


def _concessoes(antes: dict, depois: dict) -> dict:
    """A mudanca de permissao em linguagem de CONCESSAO e RETIRADA.

    As colunas `valor_antes`/`valor_depois` do audit_log ja guardam o par
    completo, e `services/audit.py` reduz sozinho aos campos que mudaram — mas
    so como "de esta lista, para aquela lista". Para o campo do RBAC a pergunta
    e outra, e e a do dono: o que essa pessoa GANHOU e o que PERDEU. Comparar
    duas listas de cabeca e justamente o que a tela didatica nao pode exigir."""
    out: dict = {}
    for campo in ("telas", "municipios"):
        a, d = set(antes.get(campo) or []), set(depois.get(campo) or [])
        if a != d:
            out[campo] = {"concedidos": sorted(d - a), "retirados": sorted(a - d)}
    return out


class SenhaResetResponse(BaseModel):
    id: int
    email: str
    name: str
    senha_temporaria: str


@router.get("")
async def list_users(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _require_admin(current)
    # Fora da lista os usuarios sinteticos de quiosque (@painel.local): eles nao
    # sao PESSOAS, sao credencial de um link de TV. Cada link publicado cria um,
    # entao deixa-los aqui encheria a tela de "Quiosque de Fulano" e daria a
    # impressao de que a prefeitura tem 40 usuarios. Quem os administra e o
    # proprio painel (Ajustes -> Link publico da TV, com copiar e revogar).
    r = await db.execute(
        select(User).where(User.email.notlike("%@painel.local")).order_by(User.id)
    )
    users = r.scalars().all()
    mr = await db.execute(text("SELECT user_id, municipio_id FROM user_municipios"))
    by_user: dict[int, list[int]] = {}
    for uid, mid in mr.fetchall():
        by_user.setdefault(uid, []).append(mid)
    tr = await db.execute(text("SELECT user_id, tela FROM user_telas"))
    telas_by_user: dict[int, list[str]] = {}
    for uid, tela in tr.fetchall():
        telas_by_user.setdefault(uid, []).append(tela)
    # `super_admin` e `somente_leitura` saem CALCULADOS pelos mesmos helpers que
    # o guard usa (flag OU reforco), e nao lidos crus da coluna: a tela precisa
    # mostrar o que de fato vale em tempo de execucao. Um usuario cuja coluna
    # esta `false` mas cujo e-mail esta na semente da Alavank manda no sistema —
    # exibir "false" ali seria a tela mentindo sobre quem tem a chave.
    #
    # Somente LEITURA: nenhum dos dois e aceito de volta em POST/PATCH (ver a
    # nota em `CreateUserRequest`).
    return [{
        "id": u.id, "email": u.email, "name": u.name, "role": u.role,
        "active": u.active, "must_change_password": u.must_change_password,
        "municipio_ids": by_user.get(u.id, []),
        "telas": sorted(telas_by_user.get(u.id, [])),
        "super_admin": is_super_admin(u),
        "somente_leitura": eh_somente_leitura(u),
    } for u in users]


@router.post("", response_model=SenhaResetResponse)
async def create_user(
    req: CreateUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _require_admin(current)
    email = req.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "Email invalido")
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Email ja cadastrado")
    if req.role not in ("admin", "usuario", "analyst", "user", "prefeito"):
        raise HTTPException(400, "Role invalida")

    senha = _gen_senha()
    somente_leitura = _trava_inicial(req.role, req.somente_leitura)
    user = User(
        email=email,
        name=req.name.strip(),
        password_hash=hash_password(senha),
        role=req.role,
        active=True,
        must_change_password=True,
        somente_leitura=somente_leitura,
    )
    db.add(user)
    # `flush` e NAO `commit`: manda o INSERT (e recebe o `user.id`, necessario
    # para as tabelas de escopo) sem fechar a transacao. Commitar aqui quebrava a
    # promessa escrita logo abaixo — o registro critico da concessao roda depois,
    # e se ele falhasse a conta ja estaria gravada: sobraria um usuario orfao, com
    # uma senha temporaria que ninguem chegou a ver (a resposta virou 500) e sem
    # permissao nenhuma, e a repeticao da operacao esbarraria em "Email ja
    # cadastrado". Com o flush, ou nasce tudo — conta, escopo e trilha — ou nada.
    await db.flush()
    if req.municipio_ids is not None:
        await _set_user_municipios(db, user.id, req.municipio_ids)
    if req.telas is not None:
        await _set_user_telas(db, user.id, req.telas)
    depois = await _snapshot_acessos(db, user.id)
    # `registrar_critico` com `commit=False`: a trilha entra na MESMA transacao da
    # concessao de acesso. Ou as duas coisas gravam, ou nenhuma — e "permissao
    # concedida sem ninguem saber por quem" e justamente o buraco que este
    # incremento fecha. Os dois commits que existiam aqui viraram este unico
    # commit final; o estado final e identico (e agora telas e municipios entram
    # juntos, em vez de meio a meio se o processo morresse no meio).
    await registrar_critico(
        db, action="user.create", user=current, request=request,
        target_type="user", target_id=user.id, alvo_nome=user.name,
        details={
            "alvo_email": email, "role": req.role,
            "somente_leitura": somente_leitura,
            "telas": depois["telas"],
            "municipios": depois["municipios"],
            "municipios_nomes": await _nomes_municipios(db, depois["municipios"]),
        },
        commit=False,
    )
    await db.commit()
    return SenhaResetResponse(id=user.id, email=user.email, name=user.name, senha_temporaria=senha)


@router.post("/{user_id}/reset-password", response_model=SenhaResetResponse)
async def reset_password(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _require_admin(current)
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not u:
        raise HTTPException(404, "Usuario nao encontrado")
    _guard_target(current, u)
    # Senha padrao "1234" - o usuario sera obrigado a troca-la no primeiro login
    senha = "1234"
    u.password_hash = hash_password(senha)
    u.must_change_password = True
    await db.commit()
    # `registrar` (nao critico): a senha ja foi trocada e devolvida ao admin. Se
    # a trilha falhasse aqui, derrubar a resposta faria o admin acreditar que o
    # reset nao aconteceu — quando aconteceu. Melhor devolver a senha e gritar no
    # log da aplicacao do que mentir sobre o estado do sistema.
    await registrar(
        db, action="user.reset_password", user=current, request=request,
        target_type="user", target_id=u.id, alvo_nome=u.name,
        details={"alvo_email": u.email},
    )
    return SenhaResetResponse(id=u.id, email=u.email, name=u.name, senha_temporaria=senha)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    req: UpdateUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _require_admin(current)
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not u:
        raise HTTPException(404, "Usuario nao encontrado")
    _guard_target(current, u)
    # Protecao: nao deixar o admin se auto-desativar nem se auto-rebaixar
    if req.active is False and u.id == current.id:
        raise HTTPException(400, "Voce nao pode desativar a si mesmo")
    if req.role and req.role != "admin" and u.id == current.id and current.role == "admin":
        raise HTTPException(400, "Voce nao pode rebaixar o proprio perfil de administrador (evita se trancar pra fora)")
    if req.role and req.role not in ("admin", "usuario", "analyst", "user", "prefeito"):
        raise HTTPException(400, "Role invalida")
    # Auto-trancamento: pôr a SI MESMO em somente-leitura e uma porta que fecha
    # por fora. O guard de `get_current_user` barra todo POST/PUT/PATCH/DELETE
    # fora do Painel — e este endpoint e um PATCH. A pessoa perderia, no mesmo
    # ato, a escrita e o unico caminho de desfaze-la: so voltaria por outro admin
    # ou pelo banco. Mesma familia das duas protecoes acima.
    if req.somente_leitura is True and u.id == current.id:
        raise HTTPException(400, "Voce nao pode se colocar em somente leitura (evita se trancar pra fora)")
    # Foto do ANTES tirada antes de qualquer atribuicao: `u` e o objeto vivo da
    # sessao, entao ler `u.name` depois do `u.name = ...` ja devolveria o valor
    # novo e o "de -> para" sairia dizendo que nada mudou.
    #
    # `somente_leitura` entra no retrato porque conceder ou tirar ESCRITA e a
    # mudanca de poder mais forte que esta tela faz — sem ela na trilha, "quem
    # liberou o prefeito para editar, e quando" ficaria sem resposta.
    antes = {"name": u.name, "role": u.role, "active": bool(u.active),
             "somente_leitura": bool(u.somente_leitura)}
    antes.update(await _snapshot_acessos(db, u.id))
    if req.name is not None:
        u.name = req.name.strip()
    if req.role is not None:
        u.role = req.role
    if req.active is not None:
        u.active = req.active
    if req.somente_leitura is not None:
        u.somente_leitura = req.somente_leitura
    if req.municipio_ids is not None:
        await _set_user_municipios(db, u.id, req.municipio_ids)
    if req.telas is not None:
        await _set_user_telas(db, u.id, req.telas)
    depois = {"name": u.name, "role": u.role, "active": bool(u.active),
              "somente_leitura": bool(u.somente_leitura)}
    depois.update(await _snapshot_acessos(db, u.id))
    # Critico e ANTES do commit, pelo mesmo motivo do create: conceder acesso e
    # registrar quem concedeu tem de ser um ato so. Aqui a regra e mais forte
    # ainda — este e o endpoint que da e tira poder dentro do sistema, e e sobre
    # ele que o RBAC granular vai se apoiar.
    await registrar_critico(
        db, action="user.update", user=current, request=request,
        target_type="user", target_id=u.id, alvo_nome=depois["name"],
        # Snapshots COMPLETOS dos dois lados: `services/audit.py` reduz sozinho
        # aos campos que mudaram (`campos_alterados`). Mandar aqui o corpo do
        # PATCH em vez do estado inteiro faria os campos nao enviados aparecerem
        # como apagados.
        valor_antes=antes, valor_depois=depois,
        details={
            "alvo_email": u.email,
            "permissao": _concessoes(antes, depois) or None,
            # Nomes de TODOS os municipios envolvidos (antes ou depois), para o
            # modal explicar a mudanca sem consultar outra tabela.
            "municipios_nomes": await _nomes_municipios(
                db, set(antes["municipios"]) | set(depois["municipios"])),
        },
        commit=False,
    )
    await db.commit()
    await db.refresh(u)
    # `de_usuario` e nao `model_validate`: a tela reaplica esta resposta na linha
    # editada, e a coluna crua diria "somente_leitura: false" para uma conta de
    # quiosque — que o codigo barra pelo papel. Ver `schemas/auth.py`.
    return UserResponse.de_usuario(u)
