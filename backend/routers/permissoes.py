"""
O CATALOGO de permissoes, servido por API.

Existe por uma regra so: **o frontend nunca copia a lista de permissoes**. Ele a
busca aqui. Este repo ja tem a cicatriz do contrario — `services/telas_catalog.py`
e `frontend/src/lib/telas.ts` divergiram em seis chaves, e o comentario de la
ainda avisa que tela nova precisa entrar em TRES lugares. Divergencia de catalogo
de permissao nao aparece na tela: ela some com o acesso de alguem, em silencio.

Quatro rotas. As duas de LEITURA PROPRIA sao auto-escopadas (por isso estao em
`services/registro_rotas.py::ROTAS_LIVRES`); as duas que falam de OUTRA pessoa
declaram permissao como qualquer rota de recurso:

    GET /api/permissoes/catalogo          o texto do produto, igual para todo mundo
    GET /api/permissoes/minhas            o que o PROPRIO usuario pode
    GET /api/permissoes/usuarios          quem tem o que (a tela de Usuarios)
    PUT /api/permissoes/usuario/{id}      ⭐ o ato de CONCEDER

⚠️ `minhas` NAO e a lista de caixinhas marcadas: e o conjunto EFETIVO, ja
resolvido pela funcao pura (super-admin recebe tudo, somente-leitura perde os
verbos de escrita). E o que a tela precisa para saber quais botoes desenhar — e
desenhar botao que o servidor vai negar e pior do que nao desenhar.

⭐ POR QUE O PUT MORA AQUI, E NAO EM `routers/users.py`
------------------------------------------------------
`PATCH /api/users/{id}` ja concede telas, municipios e a trava de escrita, e
poderia receber mais um campo. Nao recebeu por duas razoes:

  1. ⚠️ ANTI-ESCALONAMENTO. Quem concede so pode conceder o que ELE MESMO tem, e
     essa regra NAO existe para os outros campos daquele PATCH. Enfiada la
     dentro, ela valeria para um campo e nao para os outros tres, num endpoint
     que ja carrega seis guardas — e a proxima pessoa a mexer nao teria como
     saber qual guarda cobre qual campo.

  2. A TRILHA. Conceder poder e a pergunta "quem deu isso a essa pessoa, e
     quando". Com acao propria (`usuarios.conceder`), o auditor filtra por ela e
     ve so isso; misturada em `user.update`, ela viria junto com toda correcao
     de nome e toda troca de rotulo.

O que este endpoint NAO afrouxa: as duas guardas de `routers/users.py`
(`_require_admin` pelo PAPEL e `_guard_target`, que protege conta de dono)
valem aqui IMPORTADAS de la, e nao reescritas — uma segunda copia de regra de
permissao e como as copias divergem.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services import authz, permissoes
from services.audit import registrar_critico
from services.auth import get_current_user, is_super_admin
from services.registro_rotas import exige

router = APIRouter(prefix="/api/permissoes", tags=["permissoes"])


@router.get("/catalogo")
async def catalogo(current: User = Depends(get_current_user)):
    """Todas as permissoes que existem, agrupadas por secao e recurso.

    Sem gate de permissao de proposito: e conteudo estatico do produto (nenhum
    dado de municipio) e a propria tela de permissoes precisa dele para
    desenhar. Quem PODE conceder e outra pergunta, respondida por
    `usuarios.conceder` no endpoint que grava."""
    return permissoes.catalogo_para_api()


@router.get("/minhas")
async def minhas(current: User = Depends(get_current_user)):
    """O conjunto EFETIVO de quem esta perguntando, mais um resumo legivel.

    `chaves` e o que a tela usa para habilitar botao; `resumo` e a frase que o
    administrador le na tela de Usuarios ("Relatorio de Monitoramento: Ver,
    Editar")."""
    efetivas = authz.permissoes_de(current)
    return {
        "chaves": sorted(efetivas),
        "resumo": permissoes.resumo(efetivas),
        # O frontend precisa saber que este usuario passa por cima de tudo para
        # nao desenhar a tela de permissoes como se houvesse algo a conceder a
        # ele — e para nao sugerir que da para tirar.
        "super_admin": is_super_admin(current),
        "somente_leitura": bool(getattr(current, "somente_leitura", False)),
        # `AUTHZ_MODO`: enquanto for "aviso" a trava so registra, e a tela pode
        # explicar isso a quem estranhar ver um botao que ainda funciona.
        "modo": authz.modo(),
    }


# ---------------------------------------------------------------------------
# CONCESSAO — o que a tela de Usuarios le e grava
# ---------------------------------------------------------------------------
# As duas guardas da tela de Usuarios, importadas e nao copiadas:
#   `_require_admin`  o PAPEL de zelador continua abrindo esta tela (nega SEMPRE,
#                     nos dois modos de AUTHZ_MODO) — sem ele, enquanto a trava
#                     estiver em modo aviso, QUALQUER usuario logado gravaria
#                     permissao para si mesmo, porque `exige()` so registraria.
#   `_guard_target`   protege conta de dono da plataforma e conta de admin.
from routers.users import _guard_target, _require_admin  # noqa: E402


class ConcederRequest(BaseModel):
    """O conjunto COMPLETO que a pessoa deve ficar tendo — nao um delta.

    A tela manda o estado inteiro das caixinhas, e o servidor calcula o que
    entrou e o que saiu. Delta ("acrescente rm.ver") pareceria mais economico e
    seria pior: dois administradores editando a mesma pessoa produziriam uma
    soma silenciosa em vez de a segunda gravacao sobrescrever a primeira, e a
    trilha nao teria como dizer com que estado cada um trabalhava."""

    permissoes: list[str]


async def _concedidas(db: AsyncSession, user_id: int) -> set:
    linhas = await db.execute(
        text("SELECT permissao FROM user_permissoes WHERE user_id = :u"),
        {"u": user_id})
    return {r[0] for r in linhas.fetchall()}


@router.get("/usuarios", dependencies=[exige("usuarios.ver")])
async def por_usuario(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Quem tem o que, para a tela de Usuarios desenhar a lista inteira sem uma
    chamada por pessoa.

    Devolve as chaves CONCEDIDAS (as linhas de `user_permissoes`), e nao as
    efetivas: e o estado das caixinhas, que e o que a tela edita. O que cada uma
    dessas pessoas de fato ALCANCA depende de super-admin, de somente-leitura e
    de quiosque, e quem resolve isso e a funcao pura — a tela explica a
    diferenca em vez de esconde-la."""
    _require_admin(current)
    linhas = await db.execute(text("SELECT user_id, permissao FROM user_permissoes"))
    mapa: dict[str, list] = {}
    for uid, chave in linhas.fetchall():
        # Chave ORFA (existe no banco e nao no catalogo do Python, porque foi
        # removida numa versao) e descartada aqui pela mesma razao que a funcao
        # pura a descarta: ela nao vale nada e nao tem caixinha onde aparecer.
        # Ela continua no banco — ver `_gravar_concessao`, que nao a apaga.
        if permissoes.existe(chave):
            mapa.setdefault(str(uid), []).append(permissoes.normalizar(chave))
    return {"concedidas": {uid: sorted(chaves) for uid, chaves in mapa.items()}}


def _validar(pedidas) -> set:
    """Normaliza e recusa chave fora do catalogo.

    400 e nao 403: nao e permissao que falta, e pedido malformado. A chave
    invalida tambem seria recusada pela CHAVE ESTRANGEIRA de `user_permissoes`,
    mas ai o erro sairia como 500 no meio da transacao, sem dizer qual chave."""
    limpas = {permissoes.normalizar(c) for c in (pedidas or [])}
    limpas.discard("")
    desconhecidas = sorted(c for c in limpas if not permissoes.existe(c))
    if desconhecidas:
        raise HTTPException(
            400, f"Permissao desconhecida: {', '.join(desconhecidas)}")
    return limpas


def _barrar_escalonamento(atual: User, antes: set, depois: set) -> None:
    """⭐ NINGUEM CONCEDE O QUE NAO TEM.

    A regra vale sobre o que MUDOU, e nao sobre o conjunto inteiro: a tela manda
    o estado completo das caixinhas, e as travadas voltam exatamente como vieram.
    Barrar pelo CONJUNTO impediria um administrador sem `cofre.revelar` de mexer
    em qualquer caixinha de quem ja tivesse aquela — o pedido inteiro recusado
    por uma linha que ele nem tocou.

    RETIRAR tambem entra na conta, e a simetria e deliberada. Parece inofensivo
    ("estou tirando poder, nao dando"), mas e um administrador sem acesso ao
    Cofre desligando o acesso de quem tem: o poder de decidir sobre aquela
    caixinha pertence a quem a possui. Um atacante que so pudesse RETIRAR ja
    teria como derrubar a operacao de uma prefeitura inteira em dois cliques.

    ⚠️ NEGA SEMPRE, nos dois modos de `AUTHZ_MODO`. O modo aviso existe para nao
    quebrar comportamento que ja existia; este endpoint e NOVO, e nao ha
    comportamento antigo para preservar. Uma trava de escalonamento que "so
    avisa" e a ausencia da trava."""
    if is_super_admin(atual):
        return
    minhas_chaves = authz.permissoes_de(atual)
    fora = sorted((antes ^ depois) - minhas_chaves)
    if not fora:
        return
    rotulos = ", ".join(
        p.rotulo for p in (permissoes.descrever(c) for c in fora) if p)
    raise HTTPException(
        403,
        "Voce so pode conceder ou retirar permissoes que voce mesmo tem. "
        f"Fora do seu alcance: {rotulos}")


async def _gravar_concessao(db: AsyncSession, user_id: int, antes: set,
                            depois: set, autor_id) -> None:
    """Grava so a DIFERENCA — nao apaga tudo para reinserir.

    `user_permissoes` guarda `concedido_em` e `concedido_por` por linha. Um
    DELETE + INSERT do conjunto inteiro reescreveria as duas colunas de TODAS as
    permissoes a cada salvamento: a concessao feita ha um ano por outra pessoa
    passaria a dizer que fui eu, hoje. A trilha continuaria certa, mas a
    resposta barata que aquelas colunas existem para dar viraria mentira.

    Chave orfa (fora do catalogo do Python) nao entra em `antes` e por isso nao
    e apagada: ela ja e inerte para a funcao pura, e apagar linha que a tela nem
    mostra e decidir por quem nao pediu."""
    for chave in sorted(antes - depois):
        await db.execute(
            text("DELETE FROM user_permissoes WHERE user_id = :u AND permissao = :p"),
            {"u": user_id, "p": chave})
    for chave in sorted(depois - antes):
        await db.execute(
            text("INSERT INTO user_permissoes (user_id, permissao, concedido_por) "
                 "VALUES (:u, :p, :por) ON CONFLICT DO NOTHING"),
            {"u": user_id, "p": chave, "por": autor_id})


@router.put("/usuario/{user_id}", dependencies=[exige("usuarios.conceder")])
async def conceder(
    user_id: int,
    req: ConcederRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """⭐ O ato de conceder. Grava as caixinhas de OUTRA pessoa.

    A ordem das guardas e a de sempre: primeiro quem PODE mexer nesta tela
    (papel), depois em QUEM se pode mexer (`_guard_target`), depois O QUE se
    pode conceder (anti-escalonamento) — e so entao a escrita, com a trilha
    dentro da mesma transacao."""
    _require_admin(current)
    alvo: Optional[User] = (await db.execute(
        select(User).where(User.id == user_id))).scalar_one_or_none()
    if not alvo:
        raise HTTPException(404, "Usuario nao encontrado")
    _guard_target(current, alvo)

    depois = _validar(req.permissoes)
    antes = {c for c in await _concedidas(db, alvo.id) if permissoes.existe(c)}
    _barrar_escalonamento(current, antes, depois)

    await _gravar_concessao(db, alvo.id, antes, depois, getattr(current, "id", None))

    # `registrar_critico` com `commit=False`: a linha da trilha entra na MESMA
    # transacao da concessao. Ou as duas gravam, ou nenhuma — "permissao
    # concedida sem ninguem saber por quem" e exatamente o buraco que esta tela
    # fecha. Mesmo desenho de `routers/users.py::update_user`.
    concedidas = sorted(depois - antes)
    retiradas = sorted(antes - depois)
    await registrar_critico(
        db, action="usuarios.conceder", user=current, request=request,
        target_type="user", target_id=alvo.id, alvo_nome=alvo.name,
        # Snapshots COMPLETOS dos dois lados: `services/audit.py` reduz sozinho
        # aos campos que mudaram. Sem o par, "de -> para" nao existe e a linha
        # so diria que ALGO mudou.
        valor_antes={"permissoes": sorted(antes)},
        valor_depois={"permissoes": sorted(depois)},
        details={
            "alvo_email": alvo.email,
            # A mesma pergunta de `routers/users.py::_concessoes`: nao "de que
            # lista para que lista", e sim o que a pessoa GANHOU e o que PERDEU.
            "concedidas": concedidas or None,
            "retiradas": retiradas or None,
            # Frase pronta do estado final, para o modal da Auditoria nao exigir
            # que o auditor traduza 66 chaves de cabeca.
            "resumo": permissoes.resumo(depois) or None,
        },
        commit=False,
    )
    await db.commit()
    return {"permissoes": sorted(depois),
            "concedidas": concedidas, "retiradas": retiradas}
