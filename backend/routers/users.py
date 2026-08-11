"""Gerenciamento de usuarios (admin-only).

Telas: listar, criar, resetar senha, ativar/desativar, mudar role.
Senhas nunca sao retornadas (hash bcrypt). Reset gera senha temporaria
aleatoria que o admin repassa; usuario troca no proximo login.

PERMISSAO POR ACAO (`exige`, ver services/registro_rotas.py)
------------------------------------------------------------
O `_require_admin` por PAPEL abaixo CONTINUA valendo, e a declaracao soma a ele.
O que o rotulo `admin` juntava num poder so passa a ser caixinha separada:

    usuarios.ver           abrir a lista de pessoas
    usuarios.criar         cadastrar gente (⚠️ a resposta traz a senha temporaria)
    usuarios.editar        corrigir nome, papel, ativo
    usuarios.conceder      decidir o que a pessoa ALCANCA (telas, municipios,
                           trava de escrita) — cobrada dentro do PATCH, porque a
                           mesma rota faz as duas coisas
    usuarios.resetar_senha gerar senha temporaria de OUTRA pessoa (quem faz isso
                           entra como ela ate a troca obrigatoria)
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
from services import authz
from services.auth import (
    hash_password, get_current_user, is_super_admin, eh_somente_leitura,
    READONLY_ROLES,
)
from services.audit import registrar, registrar_critico
from services.registro_rotas import exige

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
        raise HTTPException(403, "Apenas administradores podem gerenciar usuários")


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
    # ⚠️ E-MAIL É IDENTIDADE, não rótulo — e por isso o PATCH o trata com as
    # mesmas guardas de uma promoção. `services/auth.py::is_super_admin` decide
    # quem é dono da plataforma POR E-MAIL (allowlist SUPER_ADMIN_EMAILS): sem
    # a guarda de `_validar_email_novo`, renomear o próprio e-mail para um da
    # lista seria escalada a dono pela porta da frente, e renomear o e-mail de
    # OUTRO poderia sequestrar a conta do dono. A sessão sobrevive à troca (o
    # JWT usa `sub = user.id`, nunca o e-mail — auth.py:346).
    email: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None
    municipio_ids: Optional[list[int]] = None
    telas: Optional[list[str]] = None
    # `None` = nao mexe. Trocar o ROTULO nao arrasta a flag junto: um prefeito
    # que ganhou escrita continua com escrita se for reetiquetado, e e isso que
    # separa as duas coisas de vez.
    somente_leitura: Optional[bool] = None


async def _validar_role(db: AsyncSession, role: str) -> str:
    """⭐ O PERFIL AGORA VEM DA TABELA DO CLIENTE (`parametros`, tipo
    `perfil_usuario`) — antes era uma tupla fixa aqui dentro, repetida em mais
    tres lugares do backend.

    ⚠️ ACEITA O INATIVO de proposito. `ativo` governa o que o SELETOR oferece;
    recusar aqui um rotulo desativado quebraria o PATCH de uma conta que ja o
    tem (a tela reenvia o papel atual ao salvar outra coisa) e a integracao do
    Console, que ainda cria com `analyst`.

    ⚠️ FALHA ABERTO se a tabela ainda nao existe (tenant com migration atrasada
    entre o deploy da API e o boot que roda o SQL): cai na lista historica. Um
    cadastro de usuario nao pode virar 500 por causa da ordem de duas coisas que
    sobem juntas — e a lista antiga e restritiva, nao permissiva.
    """
    r = (role or "").strip()
    if not r:
        raise HTTPException(400, "Perfil inválido")
    try:
        existe = (await db.execute(
            text("SELECT 1 FROM parametros WHERE tipo = 'perfil_usuario' AND valor = :v"),
            {"v": r})).first()
    except Exception:
        await db.rollback()
        return r if r in ("admin", "usuario", "analyst", "user", "prefeito", "viewer") \
            else _erro_role()
    if not existe:
        _erro_role()
    return r


def _erro_role():
    raise HTTPException(400, "Perfil inválido — cadastre-o em Configurações › Parâmetros")


async def _validar_email_novo(db: AsyncSession, alvo: User, bruto: str) -> str:
    """Normaliza e recusa os e-mails que não podem ser assumidos por ninguém.

    Três recusas, e nenhuma é decorativa:
      · da allowlist de DONOS (`SUPER_ADMIN_EMAILS`) — quem manda no sistema é
        decidido por e-mail, então um PATCH que o adotasse seria promoção a dono;
      · `@painel.local` — sufixo das contas sintéticas de quiosque, que a lista
        de usuários esconde: adotá-lo faria a conta sumir da própria tela;
      · prefixo `alavank-sso.` — contas de suporte que o SSO recria sozinho.
    """
    from services.auth import SUPER_ADMIN_EMAILS
    email = (bruto or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "Email inválido")
    if email in {e.lower() for e in SUPER_ADMIN_EMAILS}:
        raise HTTPException(403, "Este e-mail é reservado ao administrador principal")
    if email.endswith("@painel.local") or email.startswith("alavank-sso."):
        raise HTTPException(400, "Este e-mail é reservado pelo sistema")
    if email != (alvo.email or "").lower():
        existe = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existe:
            raise HTTPException(400, "Email já cadastrado")
    return email


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


@router.get("", dependencies=[exige("usuarios.ver")])
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


@router.post("", response_model=SenhaResetResponse,
             dependencies=[exige("usuarios.criar")])
async def create_user(
    req: CreateUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _require_admin(current)
    email = req.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "Email inválido")
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Email já cadastrado")
    await _validar_role(db, req.role)

    # ⚠️ CRIAR COM ESCOPO JA E CONCEDER — e sem esta linha era um DESVIO da
    # permissao de conceder.
    #
    # A resposta deste endpoint devolve a SENHA TEMPORARIA no corpo (e o unico
    # jeito de entregar a conta a pessoa). Entao quem tivesse apenas
    # `usuarios.criar` podia: criar uma conta ja com todas as telas e todos os
    # municipios, ler a senha na propria resposta, e entrar como ela. O caminho
    # legitimo — PATCH — cobra `usuarios.conceder`; este cobrava so `criar`.
    # Resultado liquido: `usuarios.conceder` seria contornavel por qualquer um
    # que pudesse criar usuario, e a caixinha da tela mentiria.
    #
    # Conta SEM escopo nenhum continua exigindo so `usuarios.criar`: ela nao
    # alcanca nada ate alguem conceder, e e o fluxo comum de cadastrar a pessoa
    # primeiro e ajustar o acesso depois.
    if req.telas or req.municipio_ids:
        authz.exigir(current, "usuarios.conceder")

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


@router.post("/{user_id}/reset-password", response_model=SenhaResetResponse,
             dependencies=[exige("usuarios.resetar_senha")])
async def reset_password(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _require_admin(current)
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not u:
        raise HTTPException(404, "Usuário não encontrado")
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


@router.patch("/{user_id}", response_model=UserResponse,
              dependencies=[exige("usuarios.editar")])
async def update_user(
    user_id: int,
    req: UpdateUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _require_admin(current)
    # ⭐ `usuarios.conceder` e SEPARADA de `usuarios.editar`, e as duas entram
    # pelo mesmo PATCH: corrigir o nome de alguem e uma coisa, decidir o que essa
    # pessoa alcanca e outra. Por isso a rota declara o denominador comum
    # (`editar`) e a segunda so e cobrada quando o pedido mexe em ACESSO.
    #
    # `somente_leitura` entra na conta com telas e municipios porque conceder ou
    # tirar ESCRITA e a mudanca de poder mais forte que esta tela faz — e o que a
    # nota de `UpdateUserRequest` ja dizia por outras palavras.
    #
    # `authz.exigir` e nao `exige(...)` no decorador: gate NOVO respeita
    # `AUTHZ_MODO`, entao hoje isto so registra "eu teria negado". A tela de
    # Usuarios chama esta rota de tres jeitos e so um deles manda estes campos
    # (frontend .../dashboard/usuarios/page.tsx: acesso, ativar/desativar, papel).
    if (req.telas is not None or req.municipio_ids is not None
            or req.somente_leitura is not None):
        authz.exigir(current, "usuarios.conceder")
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not u:
        raise HTTPException(404, "Usuário não encontrado")
    _guard_target(current, u)
    # Protecao: nao deixar o admin se auto-desativar nem se auto-rebaixar
    if req.active is False and u.id == current.id:
        raise HTTPException(400, "Você não pode desativar a si mesmo")
    if req.role and req.role != "admin" and u.id == current.id and current.role == "admin":
        raise HTTPException(400, "Você não pode rebaixar o próprio perfil de administrador (evita se trancar pra fora)")
    if req.role:
        await _validar_role(db, req.role)
    # Auto-trancamento: pôr a SI MESMO em somente-leitura e uma porta que fecha
    # por fora. O guard de `get_current_user` barra todo POST/PUT/PATCH/DELETE
    # fora do Painel — e este endpoint e um PATCH. A pessoa perderia, no mesmo
    # ato, a escrita e o unico caminho de desfaze-la: so voltaria por outro admin
    # ou pelo banco. Mesma familia das duas protecoes acima.
    if req.somente_leitura is True and u.id == current.id:
        raise HTTPException(400, "Você não pode se colocar em somente leitura (evita se trancar pra fora)")
    # Foto do ANTES tirada antes de qualquer atribuicao: `u` e o objeto vivo da
    # sessao, entao ler `u.name` depois do `u.name = ...` ja devolveria o valor
    # novo e o "de -> para" sairia dizendo que nada mudou.
    #
    # `somente_leitura` entra no retrato porque conceder ou tirar ESCRITA e a
    # mudanca de poder mais forte que esta tela faz — sem ela na trilha, "quem
    # liberou o prefeito para editar, e quando" ficaria sem resposta.
    antes = {"name": u.name, "email": u.email, "role": u.role,
             "active": bool(u.active),
             "somente_leitura": bool(u.somente_leitura)}
    antes.update(await _snapshot_acessos(db, u.id))
    if req.name is not None:
        u.name = req.name.strip()
    if req.email is not None:
        # Guardas de identidade em `_validar_email_novo` — e alvo super-admin já
        # foi barrado por `_guard_target` (o e-mail DELE é a própria chave).
        u.email = await _validar_email_novo(db, u, req.email)
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
    depois = {"name": u.name, "email": u.email, "role": u.role,
              "active": bool(u.active),
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


async def _active_admin_count(db: AsyncSession) -> int:
    """Quantos zeladores ativos o tenant tem. Exclui as contas de suporte da
    Alavank (alavank-sso.%): elas sao sinteticas e o SSO as recria — contar com
    elas deixaria remover o ultimo admin REAL do cliente achando que sobra um."""
    return int((await db.execute(text(
        "SELECT count(*) FROM users WHERE role = 'admin' AND active "
        "AND email NOT LIKE 'alavank-sso.%'"))).scalar() or 0)


@router.delete("/{user_id}", dependencies=[exige("usuarios.excluir")])
async def delete_user(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """⭐ EXCLUSAO DEFINITIVA (decisao do dono, 11/08/2026): o usuario some do
    sistema; fica SO o log. O que ele criou (RM, documentos, anotacoes, senhas
    do cofre) e PATRIMONIO DO CLIENTE e permanece, com a autoria zerada —
    "usuario removido". A trilha de auditoria nao e tocada: nome e e-mail do
    autor estao CONGELADOS em cada linha dela por desenho (add_auditoria_
    imutavel.sql), entao a historia continua legivel depois que a conta morre.

    A limpeza de FKs mora em services/users_admin.py::limpar_fks_do_usuario —
    UMA fonte para este canal e o do Console (routers/control.py), porque as
    duas listas ja divergiram uma vez e o sintoma foi 409 sem remedio."""
    _require_admin(current)
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not u:
        raise HTTPException(404, "Usuário não encontrado")
    _guard_target(current, u)
    if u.id == current.id:
        raise HTTPException(400, "Você não pode excluir a si mesmo")
    if _is_super(u):
        raise HTTPException(403, "A conta do administrador principal não pode ser excluída")
    email = (u.email or "")
    if email.endswith("@painel.local"):
        raise HTTPException(400, "Conta de quiosque não se exclui aqui — revogue o link da TV no Painel")
    if email.startswith("alavank-sso."):
        raise HTTPException(409, "Usuário de suporte Alavank não é removível por este canal")
    if u.role == "admin" and u.active and await _active_admin_count(db) <= 1:
        raise HTTPException(409, "Não é possível excluir o único administrador ativo")

    # O RETRATO COMPLETO antes do CASCADE apagar as provas: "que acessos essa
    # conta tinha quando foi removida" e a primeira pergunta de uma auditoria,
    # e depois do delete nao ha mais onde responder.
    retrato = {"alvo_email": u.email, "role": u.role,
               "somente_leitura": bool(u.somente_leitura)}
    retrato.update(await _snapshot_acessos(db, u.id))
    retrato["municipios_nomes"] = await _nomes_municipios(db, retrato["municipios"])
    perms = (await db.execute(
        text("SELECT permissao FROM user_permissoes WHERE user_id = :u"),
        {"u": u.id})).fetchall()
    retrato["permissoes"] = sorted(r[0] for r in perms)

    from services import users_admin
    await users_admin.limpar_fks_do_usuario(db, u.id)
    alvo_nome = u.name
    await db.delete(u)
    # Critico e NA MESMA transacao do delete (commit=False): ou a conta morre
    # com a linha "quem excluiu, quando, e o que ela tinha" gravada, ou nada
    # acontece. E a versao mais forte do canal do Console (la o registro e
    # melhor-esforco pos-commit).
    await registrar_critico(
        db, action="user.excluir", user=current, request=request,
        target_type="user", target_id=user_id, alvo_nome=alvo_nome,
        details=retrato, commit=False,
    )
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(409,
                            f"Não foi possível excluir (referências pendentes: {type(e).__name__})")
    return {"excluido": True, "id": user_id, "nome": alvo_nome}


class CopiarPermissoesRequest(BaseModel):
    origem_id: int
    # Escopo de municipios e parte do "perfil" as vezes sim, as vezes nao (o
    # mesmo analista com outra carteira) — por isso e uma caixinha no modal, e
    # nao uma regra fixa.
    incluir_municipios: bool = True


@router.post("/{user_id}/copiar-permissoes",
             dependencies=[exige("usuarios.conceder")])
async def copiar_permissoes(
    user_id: int,
    req: CopiarPermissoesRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """⭐ COPIA O PERFIL DE ACESSO de um usuario para outro (pedido do dono,
    11/08/2026): telas, permissoes por acao, alcance por modulo, trava de
    leitura — e, opcionalmente, o escopo de municipios. SUBSTITUI o que o alvo
    tinha (espelho, nao mescla): "ja fica com as permissoes ajustadas como a do
    outro".

    E o mesmo ato de conceder do PUT /api/permissoes/usuario/{id}, com a mesma
    ordem de guardas — quem pode mexer (papel), em quem (_guard_target), o que
    pode conceder (anti-escalonamento: ninguem copia para os outros o que nao
    tem). POST e nao GET pelo mesmo motivo do /aplicar dos modelos: a resposta
    descreve o acesso de pessoas nomeadas."""
    from routers.permissoes import (
        _barrar_escalonamento, _barrar_escalonamento_escopo,
        _concedidas, _escopos_atuais, _gravar_concessao, _gravar_escopos,
    )
    from services import permissoes as permissoes_svc

    _require_admin(current)
    if req.origem_id == user_id:
        raise HTTPException(400, "Origem e destino são o mesmo usuário")
    alvo = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    origem = (await db.execute(select(User).where(User.id == req.origem_id))).scalar_one_or_none()
    if not alvo or not origem:
        raise HTTPException(404, "Usuário não encontrado")
    _guard_target(current, alvo)
    for conta in (alvo, origem):
        if (conta.email or "").endswith("@painel.local"):
            raise HTTPException(400, "Conta de quiosque não participa de cópia de permissões")

    # O PERFIL DA ORIGEM, lido dentro da transacao.
    telas_origem = sorted(r[0] for r in (await db.execute(
        text("SELECT tela FROM user_telas WHERE user_id = :u"), {"u": origem.id})).fetchall())
    antes_p = {c for c in await _concedidas(db, alvo.id) if permissoes_svc.existe(c)}
    depois_p = {c for c in await _concedidas(db, origem.id) if permissoes_svc.existe(c)}
    _barrar_escalonamento(current, antes_p, depois_p)
    escopos_antes = await _escopos_atuais(db, alvo.id)
    escopos_depois = await _escopos_atuais(db, origem.id)
    _barrar_escalonamento_escopo(current, escopos_antes, escopos_depois)

    antes = {"somente_leitura": bool(alvo.somente_leitura)}
    antes.update(await _snapshot_acessos(db, alvo.id))

    # A COPIA: telas + permissoes + alcance + trava de leitura; municipios so
    # com a caixinha marcada.
    await _set_user_telas(db, alvo.id, telas_origem)
    await _gravar_concessao(db, alvo.id, antes_p, depois_p, getattr(current, "id", None))
    await _gravar_escopos(db, alvo.id, escopos_antes, escopos_depois,
                          getattr(current, "id", None))
    alvo.somente_leitura = bool(origem.somente_leitura)
    if req.incluir_municipios:
        ids_origem = [r[0] for r in (await db.execute(
            text("SELECT municipio_id FROM user_municipios WHERE user_id = :u"),
            {"u": origem.id})).fetchall()]
        await _set_user_municipios(db, alvo.id, ids_origem)

    depois = {"somente_leitura": bool(alvo.somente_leitura)}
    depois.update(await _snapshot_acessos(db, alvo.id))
    await registrar_critico(
        db, action="usuarios.copiar_permissoes", user=current, request=request,
        target_type="user", target_id=alvo.id, alvo_nome=alvo.name,
        valor_antes={"telas": antes["telas"], "municipios": antes["municipios"],
                     "permissoes": sorted(antes_p),
                     "somente_leitura": antes["somente_leitura"]},
        valor_depois={"telas": depois["telas"], "municipios": depois["municipios"],
                      "permissoes": sorted(depois_p),
                      "somente_leitura": depois["somente_leitura"]},
        details={
            "alvo_email": alvo.email,
            # De quem veio o perfil — congelado por nome E e-mail, porque a
            # origem pode ser excluida amanha e a trilha precisa continuar
            # respondendo "copiado de quem?" sozinha.
            "origem": {"id": origem.id, "nome": origem.name, "email": origem.email},
            "incluiu_municipios": bool(req.incluir_municipios),
            "resumo": permissoes_svc.resumo(depois_p) or None,
        },
        commit=False,
    )
    await db.commit()
    return {
        "copiado": True,
        "de": {"id": origem.id, "nome": origem.name},
        "para": {"id": alvo.id, "nome": alvo.name},
        "telas": depois["telas"],
        "municipios": depois["municipios"],
        "permissoes": len(depois_p),
        "incluiu_municipios": bool(req.incluir_municipios),
    }
