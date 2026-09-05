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
from services import permissoes as permissoes_svc
from services.auth import (
    ensure_tela, hash_password, get_current_user, is_super_admin,
)
from services.audit import registrar, registrar_critico
from services.registro_rotas import exige

router = APIRouter(prefix="/api/users", tags=["users"])

ALPHABET = string.ascii_letters + string.digits + "!@#$%&*"


def _gen_senha(n: int = 14) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


def _exige_tela_usuarios(user: User):
    """⭐ ERA `_require_admin`, e DEIXOU DE OLHAR O PAPEL em 05/09/2026 — a
    propria versao anterior previa o dia:

        "Trocar isto por permissao individual e o Incremento 5 (permissao por
         ACAO); fazer junto significaria mudar QUEM tem escopo e ONDE se checa no
         mesmo deploy, e a primeira mudanca ja e a que arrisca trancar o cliente
         fora. Ate la, `admin` deixou de ser deus mas continua sendo o zelador."

    O Incremento 5 aconteceu: toda rota deste router declara
    `exige("usuarios.<acao>")`, e com `AUTHZ_MODO` em `bloqueio` essas chaves
    barram de verdade. Manter o gate por PAPEL por cima virou CONTRADICAO: o
    dono marcava a aba Usuarios para o controlador interno e o papel o expulsava
    mesmo assim, sem nada na tela explicando por que.

    Sobrou a TELA — a mesma regra de toda aba de Configuracoes agora. Quem barra
    a acao sao as caixinhas, cobradas no decorador de cada rota.

    ⚠️ A migration `add_permissoes_por_tela.sql` garante `usuarios.*` e a tela
    `usuarios` a todo `role='admin'` ativo, para ninguem se trancar fora da
    unica tela que conserta o problema.
    """
    ensure_tela(user, "usuarios")


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
# ⚠️ `somente_leitura` SAIU destes payloads em 05/09/2026 com a trava de conta
# (ver o topo de `services/auth.py`). Quem nao escreve agora e quem esta sem a
# caixinha de escrita daquela tela — e essas viajam em `permissoes`, logo abaixo,
# que por isso passou a exigir `usuarios.conceder` como as telas ja exigiam.
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
    # ⭐ CADASTRO + PERMISSAO NUMA CHAMADA SO (05/09/2026). Antes a tela criava o
    # usuario aqui e concedia as caixinhas num `PUT /api/permissoes/usuario/{id}`
    # logo depois — duas transacoes, e um erro entre elas deixava a pessoa
    # cadastrada e cega, com a senha temporaria ja mostrada na tela. Agora as
    # duas coisas entram no MESMO commit: ou nasce tudo, ou nao nasce nada.
    #
    # ⚠️ `None` = "nao mexe", `[]` = "nenhuma". A distincao importa aqui pelo
    # mesmo motivo de `telas`: cliente de API que nao conhece o campo nao pode
    # zerar permissao sem querer.
    permissoes: Optional[list[str]] = None
    escopos: Optional[dict[str, str]] = None
    # ⭐ CAMPOS DE CADASTRO (05/09/2026), os dois OPCIONAIS e sem efeito nenhum
    # em permissao:
    #   `funcao`   — o cargo da pessoa na organizacao ("Secretário de
    #                Administração", "Contadora"). Texto livre de propósito: cada
    #                prefeitura nomeia os cargos dela, e uma lista fechada aqui
    #                seria mais uma tabela para o cliente manter.
    #   `whatsapp` — o numero para os disparos que o sistema vai fazer.
    funcao: Optional[str] = None
    whatsapp: Optional[str] = None


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
    # As caixinhas e o alcance, no MESMO PATCH e no mesmo commit — ver a nota em
    # `CreateUserRequest`. `None` = nao mexe.
    permissoes: Optional[list[str]] = None
    escopos: Optional[dict[str, str]] = None
    funcao: Optional[str] = None
    whatsapp: Optional[str] = None


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


# ⚠️ `_trava_inicial` SAIU em 05/09/2026 com a trava de conta «somente leitura»
# (ver o topo de `services/auth.py`). Ela semeava `somente_leitura` a partir do
# papel no nascimento da conta; sem a trava, nao ha o que semear.


def _limpar_texto(valor: Optional[str], limite: int) -> Optional[str]:
    """Campo de cadastro livre, normalizado. Vazio vira `None` e nao string
    vazia: a coluna e opcional, e `""` faria a tela desenhar um campo
    "preenchido" com nada dentro."""
    limpo = (valor or "").strip()
    return limpo[:limite] if limpo else None


async def _gravar_permissoes(
    db: AsyncSession, *, alvo: User, atual: User,
    permissoes: Optional[list], escopos: Optional[dict],
) -> dict:
    """⭐ AS CAIXINHAS E O ALCANCE, NA MESMA TRANSACAO DO CADASTRO.

    Reusa as guardas de `routers/permissoes.py` em vez de copia-las — sao as
    mesmas quatro que o `PUT /api/permissoes/usuario/{id}` aplica, incluindo o
    ANTI-ESCALONAMENTO (ninguem concede o que nao tem, nem retira o que nao
    tem). Uma segunda copia delas aqui e como as copias divergem, e divergencia
    em regra de permissao nao aparece na tela: aparece como alguem podendo o que
    nao devia.

    ⚠️ IMPORT LOCAL, e nao no topo: `routers/permissoes.py` importa ESTE modulo
    (`_guard_target`, `_exige_tela_usuarios`), entao subir o import fecharia o
    ciclo e quebraria o boot.

    Devolve o par antes/depois para a trilha. Nao commita — quem commita e a
    rota, junto de tudo o mais."""
    from routers.permissoes import (
        _barrar_escalonamento, _barrar_escalonamento_escopo, _concedidas,
        _escopos_atuais, _gravar_concessao, _gravar_escopos, _validar,
        _validar_escopos,
    )
    from services import permissoes as catalogo

    antes = {c for c in await _concedidas(db, alvo.id) if catalogo.existe(c)}
    escopos_antes = await _escopos_atuais(db, alvo.id)

    depois, escopos_depois = antes, escopos_antes
    if permissoes is not None:
        depois = _validar(permissoes)
        _barrar_escalonamento(atual, antes, depois)
        await _gravar_concessao(db, alvo.id, antes, depois,
                                getattr(atual, "id", None))
    if escopos is not None:
        escopos_depois = _validar_escopos(escopos)
        _barrar_escalonamento_escopo(atual, escopos_antes, escopos_depois)
        await _gravar_escopos(db, alvo.id, escopos_antes, escopos_depois,
                              getattr(atual, "id", None))
    return {"antes": sorted(antes), "depois": sorted(depois),
            "escopos_antes": escopos_antes, "escopos_depois": escopos_depois}


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
    _exige_tela_usuarios(current)
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
    # `super_admin` sai CALCULADO pelo mesmo helper que o guard usa (flag OU
    # reforco), e nao lido cru da coluna: a tela precisa mostrar o que de fato
    # vale em tempo de execucao. Um usuario cuja coluna esta `false` mas cujo
    # e-mail esta na semente da Alavank manda no sistema — exibir "false" ali
    # seria a tela mentindo sobre quem tem a chave. Somente LEITURA: ele nao e
    # aceito de volta em POST/PATCH.
    return [{
        "id": u.id, "email": u.email, "name": u.name, "role": u.role,
        "funcao": u.funcao, "whatsapp": u.whatsapp,
        "active": u.active, "must_change_password": u.must_change_password,
        "municipio_ids": by_user.get(u.id, []),
        "telas": sorted(telas_by_user.get(u.id, [])),
        "super_admin": is_super_admin(u),
    } for u in users]


@router.post("", response_model=SenhaResetResponse,
             dependencies=[exige("usuarios.criar")])
async def create_user(
    req: CreateUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _exige_tela_usuarios(current)
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
    # ⚠️ `permissoes` entra na MESMA conta: criar alguem ja com as caixinhas
    # marcadas e conceder tanto quanto marcar telas.
    if req.telas or req.municipio_ids or req.permissoes:
        authz.exigir(current, "usuarios.conceder")

    senha = _gen_senha()
    user = User(
        email=email,
        name=req.name.strip(),
        password_hash=hash_password(senha),
        role=req.role,
        funcao=_limpar_texto(req.funcao, 120),
        whatsapp=_limpar_texto(req.whatsapp, 32),
        active=True,
        must_change_password=True,
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
    # ⭐ AS CAIXINHAS ENTRAM AQUI, dentro do MESMO flush/commit — e e o que faz o
    # cadastro ser tudo-ou-nada. Ate 05/09/2026 a tela criava a conta neste
    # endpoint e concedia num `PUT /api/permissoes/usuario/{id}` logo depois:
    # falhando a segunda chamada, sobrava uma pessoa cadastrada e cega, com a
    # senha temporaria ja exibida na tela e sem caminho de repeticao (o e-mail
    # ja estava tomado).
    perms = await _gravar_permissoes(
        db, alvo=user, atual=current,
        permissoes=req.permissoes, escopos=req.escopos)
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
            "funcao": user.funcao,
            "telas": depois["telas"],
            "municipios": depois["municipios"],
            "municipios_nomes": await _nomes_municipios(db, depois["municipios"]),
            # As caixinhas que a conta JA NASCE tendo. Sem esta linha, "quem deu
            # essa permissao a essa pessoa" nao teria resposta para o caso mais
            # comum de todos — o cadastro inicial.
            "permissoes": perms["depois"] or None,
            "resumo_permissoes": permissoes_svc.resumo(perms["depois"]) or None,
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
    _exige_tela_usuarios(current)
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
    _exige_tela_usuarios(current)
    # ⭐ `usuarios.conceder` e SEPARADA de `usuarios.editar`, e as duas entram
    # pelo mesmo PATCH: corrigir o nome de alguem e uma coisa, decidir o que essa
    # pessoa alcanca e outra. Por isso a rota declara o denominador comum
    # (`editar`) e a segunda so e cobrada quando o pedido mexe em ACESSO.
    #
    # ⚠️ `permissoes` e `escopos` entram na mesma conta desde 05/09/2026: mexer
    # nas caixinhas e conceder tanto quanto mexer em telas ou municipios.
    #
    # `authz.exigir` e nao `exige(...)` no decorador: gate NOVO, que respeita
    # `AUTHZ_MODO` — e com o modo em `bloqueio` (default desde 05/09/2026) ele
    # nega de verdade, e nao mais so registra.
    if (req.telas is not None or req.municipio_ids is not None
            or req.permissoes is not None or req.escopos is not None):
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
    # ⚠️ A GUARDA DE AUTO-TRANCAMENTO EM SOMENTE-LEITURA saiu com a propria
    # trava (05/09/2026). O risco que ela cobria mudou de lugar e NAO sumiu:
    # hoje da para se tirar a tela `usuarios` desmarcando a caixinha, e ai a
    # pessoa perde a porta que conserta. Quem avisa disso e a TELA (a mesma
    # confirmacao que ja existia para "voce vai ficar sem nenhuma tela"), e o
    # servidor nao proibe — pode ser exatamente o que o administrador quer, e a
    # conta continua recuperavel por outro admin.
    #
    # Foto do ANTES tirada antes de qualquer atribuicao: `u` e o objeto vivo da
    # sessao, entao ler `u.name` depois do `u.name = ...` ja devolveria o valor
    # novo e o "de -> para" sairia dizendo que nada mudou.
    antes = {"name": u.name, "email": u.email, "role": u.role,
             "funcao": u.funcao, "whatsapp": u.whatsapp,
             "active": bool(u.active)}
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
    if req.funcao is not None:
        u.funcao = _limpar_texto(req.funcao, 120)
    if req.whatsapp is not None:
        u.whatsapp = _limpar_texto(req.whatsapp, 32)
    if req.municipio_ids is not None:
        await _set_user_municipios(db, u.id, req.municipio_ids)
    if req.telas is not None:
        await _set_user_telas(db, u.id, req.telas)
    # As caixinhas, no MESMO commit de tudo o mais — ver `_gravar_permissoes`.
    perms = await _gravar_permissoes(
        db, alvo=u, atual=current,
        permissoes=req.permissoes, escopos=req.escopos)
    depois = {"name": u.name, "email": u.email, "role": u.role,
              "funcao": u.funcao, "whatsapp": u.whatsapp,
              "active": bool(u.active)}
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
            # As CAIXINHAS, na mesma linha que as telas e os municipios — e vao
            # como GANHOU/PERDEU, e nao "de que lista para que lista": e a
            # pergunta que o auditor faz, a mesma de `_concessoes`.
            "acoes_concedidas": sorted(
                set(perms["depois"]) - set(perms["antes"])) or None,
            "acoes_retiradas": sorted(
                set(perms["antes"]) - set(perms["depois"])) or None,
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
    # editada, e `super_admin` cru da coluna mentiria sobre quem esta na semente
    # da Alavank. Ver `schemas/auth.py`.
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
    _exige_tela_usuarios(current)
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
    retrato = {"alvo_email": u.email, "role": u.role, "funcao": u.funcao}
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

    _exige_tela_usuarios(current)
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

    antes: dict = {}
    antes.update(await _snapshot_acessos(db, alvo.id))

    # A COPIA: telas + permissoes + alcance; municipios so com a caixinha
    # marcada. (A trava de leitura saiu da copia junto com a propria trava.)
    await _set_user_telas(db, alvo.id, telas_origem)
    await _gravar_concessao(db, alvo.id, antes_p, depois_p, getattr(current, "id", None))
    await _gravar_escopos(db, alvo.id, escopos_antes, escopos_depois,
                          getattr(current, "id", None))
    if req.incluir_municipios:
        ids_origem = [r[0] for r in (await db.execute(
            text("SELECT municipio_id FROM user_municipios WHERE user_id = :u"),
            {"u": origem.id})).fetchall()]
        await _set_user_municipios(db, alvo.id, ids_origem)

    depois: dict = {}
    depois.update(await _snapshot_acessos(db, alvo.id))
    await registrar_critico(
        db, action="usuarios.copiar_permissoes", user=current, request=request,
        target_type="user", target_id=alvo.id, alvo_nome=alvo.name,
        valor_antes={"telas": antes["telas"], "municipios": antes["municipios"],
                     "permissoes": sorted(antes_p)},
        valor_depois={"telas": depois["telas"], "municipios": depois["municipios"],
                      "permissoes": sorted(depois_p)},
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
