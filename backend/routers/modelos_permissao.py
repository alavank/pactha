"""
⭐ MODELOS DE PERMISSAO — o MOLDE, e o CRUD dele.

O PROBLEMA QUE ESTE ARQUIVO RESOLVE, E ELE E DE OPERACAO
--------------------------------------------------------
O catalogo tem dezenas de permissoes, mais o alcance por modulo. Cadastrar um
servidor novo virou marcar todas as caixinhas a mao — e um administrador cansado
marca TUDO. Sem esta peca, o RBAC por usuario do Incremento 5 se desfaz sozinho
na pratica, sem ninguem mexer numa linha de codigo.

⚠️⚠️ E ELA NAO PODE TRAIR A REGRA DO DONO
-----------------------------------------
    "as permissoes sao colocadas no usuario da pessoa, INDIVIDUALMENTE. Grupo e
     so ROTULO. Nao da pra limitar dentro de uma prefeitura que todos os
     analistas terao o mesmo acesso, isso e besteira."

Entao: **APLICAR E COPIAR**. Nao ha vinculo persistente entre usuario e modelo —
procure por uma coluna ligando os dois neste arquivo, no schema ou na API: nao
existe, e a ausencia e a feature. Aplicar preenche as caixinhas DAQUELE usuario
NAQUELE instante, e acabou. Depois disso o modelo pode mudar, ser renomeado ou
ser APAGADO que o usuario nao muda.

E o que mantem o sistema respondivel: "o que esta pessoa pode?" continua tendo
resposta olhando A PESSOA. Com heranca, seria preciso saber a que grupo ela
pertence, o que aquele grupo tem HOJE e o que ele tinha na semana em que alguem
reclamou.

⭐ POR ISSO O `aplicar` DESTE ARQUIVO NAO ESCREVE NADA
-----------------------------------------------------
`POST /{id}/aplicar` CALCULA e devolve; quem grava e o `PUT
/api/permissoes/usuario/{id}` de sempre, depois de o administrador conferir e
ajustar as caixinhas. Sao duas razoes:

  1. O DONO PEDIU ASSIM: "as caixas do usuario sao preenchidas e ficam
     EDITAVEIS — o administrador ajusta antes de salvar". Um endpoint que
     gravasse na hora tiraria o ajuste do caminho, e o clique por engano ja
     estaria commitado antes de alguem ver.
  2. UMA PORTA SO PARA GRAVAR PERMISSAO. O `PUT` ja carrega o
     anti-escalonamento, o `_guard_target`, a trilha com valor-antes/depois e a
     transacao unica. Uma segunda porta de escrita seria uma segunda copia
     dessas quatro guardas — e a copia que diverge e a que abre.

AS ROTAS
--------
    GET    /api/permissoes/modelos                 usuarios.conceder  (ler e usar)
    POST   /api/permissoes/modelos                 usuarios.modelos   (escrever)
    PUT    /api/permissoes/modelos/{id}            usuarios.modelos
    DELETE /api/permissoes/modelos/{id}            usuarios.modelos
    POST   /api/permissoes/modelos/{id}/aplicar    usuarios.conceder  (so calcula)

⭐ POR QUE DUAS PERMISSOES, E NAO UMA (o item D)
-----------------------------------------------
LER e APLICAR um molde exigem `usuarios.conceder` — quem ja decide o que uma
pessoa faz nao ganha poder nenhum por usar uma receita: toda aplicacao continua
limitada ao que ELE MESMO tem (ver `permissoes.aplicar_modelo`). Exigir mais aqui
mataria a funcao para exatamente quem ela existe para ajudar.

⚠️ E `usuarios.modelos` e checada DUAS vezes de proposito: no decorador (que
DECLARA a rota para o registro do boot) e em `_exigir_gerir`, que NEGA SEMPRE.
So o decorador nao bastaria — com `AUTHZ_MODO=aviso`, que e o default e o que
esta valendo hoje, `exige()` registra e deixa passar, e a caixinha seria
decoracao ate a semana de observacao terminar. Ver `_exigir_gerir`.

ESCREVER um molde exige `usuarios.modelos`, uma caixinha PROPRIA, e nao e
preciosismo — e um vetor de ataque que marcar caixinha a mao nao tem. Um molde e
uma RECEITA: o administrador A escreve "Somente consulta" com `cofre.revelar`
dentro; o administrador B, que tambem tem `cofre.revelar`, aplica confiando no
NOME e concede a chave do Cofre sem ter querido. E o "confused deputy" classico,
e nenhuma trava de escalonamento o pega — B podia mesmo conceder aquilo. O que o
pega e (a) as caixinhas ficarem visiveis e editaveis na tela antes de salvar, e
(b) escrever molde ser um poder que alguem CONCEDEU a A, deliberadamente.

⚠️ Nao ha backfill desta caixinha nos tenants que ja subiram (ver
migrations/add_permissoes_por_acao.sql): la ela nasce com NINGUEM, e o dono da
plataforma a concede a quem escolher. Ninguem perde nada — era funcao que nao
existia — e a receita que dirige o que os outros concedem nao sai distribuida
por deploy.

O QUE ESTE ARQUIVO NAO REESCREVE
--------------------------------
`_require_admin`, `_guard_target`, `_barrar_escalonamento`,
`_barrar_escalonamento_escopo`, `_validar`, `_validar_escopos` sao IMPORTADOS.
Uma segunda implementacao de regra de permissao e como as copias divergem — e a
divergencia nao aparece na tela, aparece no acesso de alguem.
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
from services.auth import get_current_user
from services.registro_rotas import exige

# Importadas, e nao copiadas — ver o cabecalho.
from routers.permissoes import (
    _barrar_escalonamento,
    _barrar_escalonamento_escopo,
    _concedidas,
    _escopos_atuais,
    _escopos_completos,
    _frase_escopo,
    _validar,
    _validar_escopos,
)
from routers.users import _guard_target, _require_admin

router = APIRouter(prefix="/api/permissoes/modelos", tags=["permissoes"])


# Um seletor com nome de 200 caracteres nao e seletor. E o nome vai para a
# trilha (`alvo_nome`), onde o que importa e caber na linha que o auditor le.
LIMITE_NOME = 80
LIMITE_DESCRICAO = 600


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
class ModeloRequest(BaseModel):
    """O conteudo COMPLETO do molde — nao um delta.

    Mesma doutrina de `ConcederRequest`: a tela manda o estado inteiro e o
    servidor calcula o que entrou e o que saiu. Delta produziria soma silenciosa
    entre dois administradores editando o mesmo molde."""

    nome: str
    descricao: Optional[str] = None
    permissoes: list[str]
    # ⚠️ AUSENTE (None) e `{}` significam coisas DIFERENTES, pela mesma razao de
    # `ConcederRequest.escopos`: ausente e "nao mexi no alcance", `{}` e "estado
    # completo, sem restricao nenhuma".
    escopos: Optional[dict[str, str]] = None


class AplicarRequest(BaseModel):
    """A quem, e como. NAO grava nada — ver o cabecalho."""

    user_id: int
    # ⚠️ Omitido = `substituir`, e a escolha esta explicada em
    # `services/permissoes.py::MODO_APLICACAO_OPCOES`: somar por engano CONCEDE
    # em silencio; substituir por engano TIRA, e isso e visivel antes de salvar.
    # O campo omitido nao pode ser o campo mais permissivo.
    modo: Optional[str] = None
    # ⭐ O ESTADO QUE ESTA NA TELA, quando houver — e por que aceitar isto do
    # cliente e correto:
    #
    #   1. O MODAL E EDITAVEL ANTES DE APLICAR. O administrador abre as
    #      permissoes de alguem, mexe em duas caixinhas e SO ENTAO escolhe um
    #      molde. Calculando contra o banco, a conta ignoraria essas duas
    #      caixinhas e a tela mostraria "a marcar 7" quando sao 5 — numero
    #      errado na cara de quem esta decidindo.
    #
    #   2. NAO ABRE BRECHA, e a razao e estrutural: esta rota NAO GRAVA. Quem
    #      grava e o `PUT /api/permissoes/usuario/{id}`, e la o anti-escalonamento
    #      compara contra o BANCO, nao contra o que o cliente disse. Um cliente
    #      que mentisse aqui — omitindo `cofre.revelar` do proprio estado para
    #      "conseguir" retira-la — receberia um plano que o PUT recusa com 403.
    #      Mentir para si mesmo nao e um vetor.
    #
    # Ausente (None) = "use o cadastro gravado", que e o certo para cliente de
    # API, que nao tem tela nenhuma. Lista vazia e um estado legitimo ("nao tem
    # nada marcado") e NAO pode virar "nao opinei" — por isso `None` e `[]`
    # significam coisas diferentes aqui, como em `ConcederRequest.escopos`.
    estado_atual: Optional[list[str]] = None
    escopos_atual: Optional[dict[str, str]] = None


# ---------------------------------------------------------------------------
# Validacao do rotulo
# ---------------------------------------------------------------------------
def _texto(bruto, limite: int) -> str:
    """Colapsa espaco e corta. O nome do molde vira `alvo_nome` na trilha e
    rotulo de seletor: quebra de linha e espaco duplo ali viram linha torta."""
    return " ".join(str(bruto or "").split())[:limite]


def _validar_nome(bruto) -> str:
    nome = _texto(bruto, LIMITE_NOME)
    if not nome:
        raise HTTPException(400, "O modelo precisa de um nome.")
    return nome


def _exigir_gerir(current: User) -> None:
    """⚠️ ESCREVER MOLDE NEGA SEMPRE, nos dois modos de `AUTHZ_MODO`.

    O `exige("usuarios.modelos")` do decorador DECLARA a rota (o registro do
    boot a enxerga) mas, com `AUTHZ_MODO=aviso` — o default, e o que esta
    valendo em Monte Siao durante a semana de observacao —, ele so REGISTRA e
    deixa passar. Sem esta linha, qualquer `role='admin'` escrevia molde apesar
    de o proprio servidor responder `pode_gerenciar: false` em `GET
    /api/permissoes/modelos` e de a tela esconder os botoes por causa disso: o
    servidor ficava mais frouxo do que a resposta que ele mesmo manda.

    E o mesmo argumento de `_barrar_escalonamento`, e ele vale igual aqui:
    escrever molde e funcao NOVA, nao ha comportamento antigo a preservar, e uma
    trava que so avisa e a ausencia da trava. O modo `aviso` existe para nao
    quebrar o que ja funcionava — e nada disto funcionava ontem.

    Ninguem perde nada: aplicar um molde continua exigindo so
    `usuarios.conceder`, que e o uso normal e o motivo operacional do
    incremento. O que fica fechado e a RECEITA, que e o que pauta o gesto dos
    outros administradores — exatamente como a migration promete por escrito
    ("ela e concedida a mao, pelo dono da plataforma, a quem ele escolher").
    Super-admin passa: `authz.pode` devolve o catalogo inteiro para ele."""
    if not authz.pode(current, "usuarios.modelos"):
        raise HTTPException(
            403,
            "Criar, alterar e apagar MODELOS de permissao exige a caixinha "
            "«Gerenciar modelos». Aplicar um modelo ja existente continua "
            "liberado para quem concede permissoes.")


async def _nome_livre(db: AsyncSession, nome: str,
                      ignorar_id: Optional[int] = None) -> None:
    """Nome duplicado e 409, e a checagem e SEM CAIXA ALTA.

    O molde e escolhido PELO NOME num seletor: "Cofre" e "cofre" lado a lado
    fariam o administrador aplicar um achando que era o outro — e ele so
    descobriria pelo que a pessoa passou a poder. O banco tem a mesma trava num
    indice unico sobre `lower(nome)`; aqui ela existe para o erro sair legivel
    em vez de virar 500 no meio da transacao."""
    linha = (await db.execute(
        text("SELECT id FROM modelos_permissao WHERE lower(nome) = lower(:n) "
             "LIMIT 1"),
        {"n": nome})).first()
    if linha and (ignorar_id is None or int(linha[0]) != int(ignorar_id)):
        raise HTTPException(409, f"Ja existe um modelo chamado «{nome}».")


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
_SELECT_MODELO = (
    "SELECT m.id, m.nome, m.descricao, m.criado_em, m.criado_por, "
    "       m.atualizado_em, m.atualizado_por, autor.name, editor.name "
    "  FROM modelos_permissao m "
    "  LEFT JOIN users autor ON autor.id = m.criado_por "
    "  LEFT JOIN users editor ON editor.id = m.atualizado_por "
)


def _ficha(linha) -> dict:
    return {
        "id": linha[0],
        "nome": linha[1],
        "descricao": linha[2],
        "criado_em": linha[3],
        "criado_por": linha[4],
        "atualizado_em": linha[5],
        "atualizado_por": linha[6],
        "criado_por_nome": linha[7],
        "atualizado_por_nome": linha[8],
    }


async def _carregar_um(db: AsyncSession, modelo_id: int) -> Optional[dict]:
    linha = (await db.execute(
        text(_SELECT_MODELO + "WHERE m.id = :i"), {"i": modelo_id})).first()
    if linha is None:
        return None
    ficha = _ficha(linha)
    ficha["permissoes"] = await _permissoes_do_modelo(db, modelo_id)
    ficha["escopos"] = await _escopos_do_modelo(db, modelo_id)
    return ficha


async def _permissoes_do_modelo(db: AsyncSession, modelo_id: int) -> set:
    linhas = await db.execute(
        text("SELECT permissao FROM modelo_permissoes WHERE modelo_id = :i"),
        {"i": modelo_id})
    # Chave ORFA (existe no banco e nao no catalogo do Python, porque foi
    # removida numa versao) e descartada aqui pela mesma razao que a funcao pura
    # a descarta: ela nao vale nada e nao tem caixinha onde aparecer.
    return {permissoes.normalizar(r[0]) for r in linhas.fetchall()
            if permissoes.existe(r[0])}


async def _escopos_do_modelo(db: AsyncSession, modelo_id: int) -> dict:
    linhas = await db.execute(
        text("SELECT recurso, escopo FROM modelo_escopos WHERE modelo_id = :i"),
        {"i": modelo_id})
    return {permissoes.normalizar(r[0]): permissoes.normalizar_escopo(r[1])
            for r in linhas.fetchall()
            if permissoes.escopavel(r[0])
            and permissoes.normalizar_escopo(r[1]) != permissoes.ESCOPO_TODOS}


def _meus_modulos(current: User) -> set:
    """Os modulos em que QUEM ESTA PEDINDO alcanca todos os registros — os
    unicos em que ele pode mexer no alcance (`_barrar_escalonamento_escopo`)."""
    return {chave for chave in permissoes.ESCOPO_RECURSOS
            if authz.escopo_de(current, chave) == permissoes.ESCOPO_TODOS}


def _para_api(ficha: dict, *, minhas: frozenset, meus_modulos: set,
              pode_gerenciar: bool) -> dict:
    """O molde como a tela o le.

    Alem do conteudo, devolve o que ESTE usuario alcanca dele. A tela precisa
    disso para avisar ANTES do clique: aplicar um molde com `cofre.revelar` por
    quem nao tem `cofre.revelar` nao concede a chave (o servidor recusa), e uma
    tela que nao avisasse deixaria o administrador jurando ter concedido o que
    nao concedeu."""
    chaves = set(ficha["permissoes"])
    escopos = dict(ficha["escopos"])
    fora = sorted(chaves - minhas)
    alcance_fora = sorted(r for r in escopos if r not in meus_modulos)
    return {
        "id": ficha["id"],
        "nome": ficha["nome"],
        "descricao": ficha["descricao"],
        "permissoes": sorted(chaves),
        "total_permissoes": len(chaves),
        # Estado COMPLETO do alcance, com o default explicito: a tela nao
        # precisa saber que "ausente" quer dizer `todos`.
        "escopos": _escopos_completos(escopos),
        # Frases prontas, para o seletor nao obrigar ninguem a traduzir chave.
        "resumo": permissoes.resumo(sorted(chaves)),
        "alcance_resumo": [_frase_escopo(r, escopos[r]) for r in sorted(escopos)],
        # O que ESTE usuario nao consegue aplicar deste molde.
        "fora_do_meu_alcance": fora,
        "alcance_fora_do_meu": alcance_fora,
        "aplicavel_por_inteiro": not fora and not alcance_fora,
        # Quem pode EDITAR o molde e outra pergunta de quem pode APLICA-LO.
        "editavel": pode_gerenciar,
        "criado_em": ficha["criado_em"],
        "criado_por": ficha["criado_por"],
        "criado_por_nome": ficha["criado_por_nome"],
        "atualizado_em": ficha["atualizado_em"],
        "atualizado_por": ficha["atualizado_por"],
        "atualizado_por_nome": ficha["atualizado_por_nome"],
    }


# ---------------------------------------------------------------------------
# LISTAR
# ---------------------------------------------------------------------------
@router.get("", dependencies=[exige("usuarios.conceder")])
async def listar(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Todos os moldes, com o conteudo de cada um.

    Em UMA chamada, e nao uma por molde: o seletor do modal precisa mostrar o
    que cada molde carrega ANTES de o administrador escolher — um molde que so
    revela o conteudo depois de aplicado e um molde em que ninguem confia.

    `usuarios.conceder` e nao `usuarios.modelos`: ler e aplicar sao o uso
    normal; escrever e que e a caixinha propria."""
    _require_admin(current)
    linhas = (await db.execute(text(_SELECT_MODELO + "ORDER BY m.nome"))).fetchall()
    conteudo: dict = {}
    for mid, chave in (await db.execute(
            text("SELECT modelo_id, permissao FROM modelo_permissoes"))).fetchall():
        if permissoes.existe(chave):
            conteudo.setdefault(mid, set()).add(permissoes.normalizar(chave))
    alcances: dict = {}
    for mid, recurso, valor in (await db.execute(
            text("SELECT modelo_id, recurso, escopo FROM modelo_escopos"))).fetchall():
        if not permissoes.escopavel(recurso):
            continue
        escopo = permissoes.normalizar_escopo(valor)
        if escopo != permissoes.ESCOPO_TODOS:
            alcances.setdefault(mid, {})[permissoes.normalizar(recurso)] = escopo

    minhas = authz.permissoes_de(current)
    meus_modulos = _meus_modulos(current)
    pode_gerenciar = authz.pode(current, "usuarios.modelos")
    modelos = []
    for linha in linhas:
        ficha = _ficha(linha)
        ficha["permissoes"] = conteudo.get(ficha["id"], set())
        ficha["escopos"] = alcances.get(ficha["id"], {})
        modelos.append(_para_api(ficha, minhas=minhas, meus_modulos=meus_modulos,
                                 pode_gerenciar=pode_gerenciar))
    return {
        "modelos": modelos,
        # A tela desenha (ou nao) os botoes de criar/editar/apagar a partir
        # daqui, em vez de adivinhar pelo papel.
        "pode_gerenciar": pode_gerenciar,
        # O vocabulario (modos de aplicacao + o aviso obrigatorio de que aplicar
        # e COPIAR) vem no `GET /api/permissoes/catalogo`, em `modelos`.
        "modos": [dict(m) for m in permissoes.MODO_APLICACAO_OPCOES],
    }


# ---------------------------------------------------------------------------
# ESCRITA — as guardas, na ordem de sempre
# ---------------------------------------------------------------------------
_FRASE_ESCALONAMENTO = (
    "Um modelo so pode carregar permissoes que voce mesmo tem — senao ele "
    "seria a porta dos fundos da trava que impede conceder o que nao se tem."
)
_FRASE_ESCALONAMENTO_ESCOPO = (
    "Um modelo so pode definir o alcance de modulos em que voce mesmo alcanca "
    "todos os registros."
)


def _conferir(current: User, antes: set, depois: set,
              escopos_antes: dict, escopos_depois: dict) -> None:
    """⭐ ANTI-ESCALONAMENTO NO SERVIDOR, e nao so na tela (item C).

    Vale sobre o que MUDOU, exatamente como na concessao a uma pessoa: barrar
    pelo CONJUNTO impediria um administrador sem `cofre.revelar` de corrigir a
    descricao de um molde que tem aquela chave — um pedido inteiro recusado por
    uma linha que ele nem tocou.

    E vale nos DOIS SENTIDOS: tirar `cofre.revelar` de um molde tambem exige
    te-la. Quem nao alcanca o Cofre nao decide o que os moldes do Cofre fazem —
    e um atacante que so pudesse RETIRAR ja teria como esvaziar, em dois
    cliques, os moldes de que a prefeitura inteira depende."""
    _barrar_escalonamento(current, antes, depois, frase=_FRASE_ESCALONAMENTO)
    _barrar_escalonamento_escopo(current, escopos_antes, escopos_depois,
                                 frase=_FRASE_ESCALONAMENTO_ESCOPO)


async def _gravar_conteudo(db: AsyncSession, modelo_id: int, chaves: set,
                           escopos: dict) -> None:
    """Apaga e reinsere o conteudo do molde.

    ⚠️ AQUI ISSO E CERTO, e em `_gravar_concessao` seria ERRADO — a diferenca
    vale a linha: `user_permissoes` guarda `concedido_em`/`concedido_por` por
    linha, e reescrever tudo faria a concessao de um ano atras passar a dizer
    que fui eu, hoje. `modelo_permissoes` nao guarda procedencia por caixinha
    (a procedencia e do MOLDE, e mora em `modelos_permissao`), entao nao ha nada
    que o DELETE possa apagar por engano — e o codigo fica com uma leitura so."""
    await db.execute(
        text("DELETE FROM modelo_permissoes WHERE modelo_id = :i"),
        {"i": modelo_id})
    for chave in sorted(chaves):
        await db.execute(
            text("INSERT INTO modelo_permissoes (modelo_id, permissao) "
                 "VALUES (:i, :p) ON CONFLICT DO NOTHING"),
            {"i": modelo_id, "p": chave})
    await db.execute(
        text("DELETE FROM modelo_escopos WHERE modelo_id = :i"), {"i": modelo_id})
    for recurso in sorted(escopos):
        await db.execute(
            text("INSERT INTO modelo_escopos (modelo_id, recurso, escopo) "
                 "VALUES (:i, :r, :e) ON CONFLICT (modelo_id, recurso) "
                 "DO UPDATE SET escopo = EXCLUDED.escopo"),
            {"i": modelo_id, "r": recurso, "e": escopos[recurso]})


def _instantaneo(nome, descricao, chaves, escopos) -> dict:
    """O molde inteiro num dicionario, para o valor-antes/valor-depois da
    trilha. `services/audit.py` reduz sozinho aos campos que mudaram."""
    return {
        "nome": nome,
        "descricao": descricao,
        "permissoes": sorted(chaves),
        "escopos": _escopos_completos(escopos),
    }


@router.post("", dependencies=[exige("usuarios.modelos")])
async def criar(
    req: ModeloRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Cria um molde. A ordem das guardas e a de sempre: quem pode mexer nesta
    tela (papel), o que se pode escrever dentro (anti-escalonamento) e so entao
    a escrita, com a trilha na MESMA transacao."""
    _require_admin(current)
    _exigir_gerir(current)
    nome = _validar_nome(req.nome)
    descricao = _texto(req.descricao, LIMITE_DESCRICAO) or None
    chaves = _validar(req.permissoes)
    escopos = _validar_escopos(req.escopos)
    _conferir(current, set(), chaves, {}, escopos)
    await _nome_livre(db, nome)

    modelo_id = (await db.execute(
        text("INSERT INTO modelos_permissao (nome, descricao, criado_por) "
             "VALUES (:n, :d, :por) RETURNING id"),
        {"n": nome, "d": descricao, "por": getattr(current, "id", None)})).scalar()
    await _gravar_conteudo(db, modelo_id, chaves, escopos)

    await registrar_critico(
        db, action="modelo_permissao.criar", user=current, request=request,
        target_type="modelo_permissao", target_id=modelo_id, alvo_nome=nome,
        valor_depois=_instantaneo(nome, descricao, chaves, escopos),
        details={
            "resumo": permissoes.resumo(sorted(chaves)) or None,
            "alcance_resumo": [_frase_escopo(r, escopos[r])
                               for r in sorted(escopos)] or None,
            "total_permissoes": len(chaves),
        },
        commit=False,
    )
    await db.commit()
    ficha = {"id": modelo_id, "nome": nome, "descricao": descricao,
             "criado_em": None, "criado_por": getattr(current, "id", None),
             "atualizado_em": None, "atualizado_por": None,
             "criado_por_nome": getattr(current, "name", None),
             "atualizado_por_nome": None,
             "permissoes": chaves, "escopos": escopos}
    return _para_api(ficha, minhas=authz.permissoes_de(current),
                     meus_modulos=_meus_modulos(current), pode_gerenciar=True)


@router.put("/{modelo_id}", dependencies=[exige("usuarios.modelos")])
async def editar(
    modelo_id: int,
    req: ModeloRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Altera um molde.

    ⚠️ ISTO NAO ALTERA NINGUEM. Quem ja recebeu este molde continua exatamente
    como estava — aplicar COPIOU as caixinhas para o cadastro da pessoa, e o
    vinculo acabou ali. Se o molde saiu errado e ja foi aplicado a cinco
    pessoas, sao cinco cadastros a corrigir. E o preco da regra do dono, e a
    trilha diz isso em portugues (services/audit_catalog.py)."""
    _require_admin(current)
    _exigir_gerir(current)
    atual = await _carregar_um(db, modelo_id)
    if atual is None:
        raise HTTPException(404, "Modelo nao encontrado")

    nome = _validar_nome(req.nome)
    descricao = _texto(req.descricao, LIMITE_DESCRICAO) or None
    chaves = _validar(req.permissoes)
    # ⚠️ `escopos` ausente e "nao mexi", e nao "sem restricao" — mesma assimetria
    # de `ConcederRequest`. Sem ela, um cliente que ainda nao conheca o campo
    # apagaria o alcance do molde ao salvar so as caixinhas.
    escopos = (atual["escopos"] if req.escopos is None
               else _validar_escopos(req.escopos))
    _conferir(current, atual["permissoes"], chaves, atual["escopos"], escopos)
    await _nome_livre(db, nome, ignorar_id=modelo_id)

    await db.execute(
        text("UPDATE modelos_permissao SET nome = :n, descricao = :d, "
             "atualizado_em = NOW(), atualizado_por = :por WHERE id = :i"),
        {"n": nome, "d": descricao, "por": getattr(current, "id", None),
         "i": modelo_id})
    await _gravar_conteudo(db, modelo_id, chaves, escopos)

    await registrar_critico(
        db, action="modelo_permissao.editar", user=current, request=request,
        target_type="modelo_permissao", target_id=modelo_id, alvo_nome=nome,
        valor_antes=_instantaneo(atual["nome"], atual["descricao"],
                                 atual["permissoes"], atual["escopos"]),
        valor_depois=_instantaneo(nome, descricao, chaves, escopos),
        details={
            "acrescentadas": sorted(chaves - atual["permissoes"]) or None,
            "removidas": sorted(atual["permissoes"] - chaves) or None,
            "resumo": permissoes.resumo(sorted(chaves)) or None,
            "alcance_resumo": [_frase_escopo(r, escopos[r])
                               for r in sorted(escopos)] or None,
            # A frase que separa este evento de uma concessao de verdade.
            "efeito": "Alterar o modelo NAO altera quem ja o recebeu: aplicar "
                      "copia as permissoes no instante da aplicacao.",
        },
        commit=False,
    )
    await db.commit()
    ficha = {**atual, "nome": nome, "descricao": descricao,
             "permissoes": chaves, "escopos": escopos,
             "atualizado_por": getattr(current, "id", None),
             "atualizado_por_nome": getattr(current, "name", None)}
    return _para_api(ficha, minhas=authz.permissoes_de(current),
                     meus_modulos=_meus_modulos(current), pode_gerenciar=True)


@router.delete("/{modelo_id}", dependencies=[exige("usuarios.modelos")])
async def apagar(
    modelo_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Apaga um molde.

    ⚠️ NINGUEM PERDE ACESSO POR ISTO, e e a prova mais limpa de que o molde nao
    e grupo: as permissoes que ele copiou continuam nos cadastros das pessoas,
    porque sao delas desde o instante da aplicacao. O que some e a receita.

    O conteudo apagado vai INTEIRO para a trilha (`valor_antes`) — e o unico
    lugar onde ele ainda vai existir depois do commit."""
    _require_admin(current)
    _exigir_gerir(current)
    atual = await _carregar_um(db, modelo_id)
    if atual is None:
        raise HTTPException(404, "Modelo nao encontrado")
    # ⚠️ Anti-escalonamento tambem para APAGAR: apagar e retirar o molde inteiro,
    # e quem nao alcanca uma das caixinhas dele nao decide sobre ele. Sem esta
    # linha, um administrador sem acesso ao Cofre derrubaria o molde do Cofre —
    # a mesma acao que a trava recusa quando ele tenta esvazia-lo caixinha a
    # caixinha pelo PUT.
    _conferir(current, atual["permissoes"], set(), atual["escopos"], {})

    await db.execute(
        text("DELETE FROM modelos_permissao WHERE id = :i"), {"i": modelo_id})

    await registrar_critico(
        db, action="modelo_permissao.excluir", user=current, request=request,
        target_type="modelo_permissao", target_id=modelo_id,
        alvo_nome=atual["nome"],
        valor_antes=_instantaneo(atual["nome"], atual["descricao"],
                                 atual["permissoes"], atual["escopos"]),
        details={
            "resumo": permissoes.resumo(sorted(atual["permissoes"])) or None,
            "efeito": "Ninguem perde acesso: as permissoes ja copiadas "
                      "continuam nos cadastros das pessoas.",
        },
        commit=False,
    )
    await db.commit()
    return {"apagado": True, "id": modelo_id, "nome": atual["nome"]}


# ---------------------------------------------------------------------------
# ⭐⭐ APLICAR — CALCULA e devolve. NAO grava.
# ---------------------------------------------------------------------------
@router.post("/{modelo_id}/aplicar", dependencies=[exige("usuarios.conceder")])
async def aplicar(
    modelo_id: int,
    req: AplicarRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """⭐ O estado que as caixinhas devem mostrar depois de aplicar o molde.

    NAO ESCREVE NADA — nem em `user_permissoes`, nem em `user_escopos`, nem na
    trilha. Quem grava e `PUT /api/permissoes/usuario/{id}`, depois de o
    administrador conferir e ajustar (ver o cabecalho do modulo).

    ⚠️ POR QUE ISTO E UM ENDPOINT, E NAO uma juncao de conjuntos no JavaScript:

      1. O ANTI-ESCALONAMENTO E DO SERVIDOR (item C). A tela nao pode ser a
         unica a saber que este administrador nao alcanca `cofre.revelar` — e
         nao pode PROPOR uma caixinha que o `PUT` vai recusar, senao o
         administrador salva, leva 403 e nao entende o que fez de errado.
      2. PRESERVAR O QUE ELE NAO ALCANCA exige ler o cadastro ATUAL do alvo. A
         tela tem essas caixinhas, mas a regra de qual delas e intocavel e a
         mesma que o `PUT` aplica — e regra que mora em dois lugares diverge.
      3. NAO GRAVA, MAS NAO E INOFENSIVO DE LER: a resposta e o retrato das
         permissoes de outra pessoa. Por isso `usuarios.conceder` e
         `_guard_target`, como no `PUT`.

    ⚠️ E POR QUE NAO E `GET`: a resposta descreve o acesso de uma pessoa
    nomeada, e um `GET` levaria `user_id` para o log de acesso do proxy e para o
    historico do navegador. O corpo do POST nao vai para nenhum dos dois. (Nao
    havendo escrita, o guard de somente-leitura barrar o POST tambem nao tira
    nada de ninguem: quem e somente-leitura nao resolve `usuarios.conceder`, que
    e permissao de escrita, e portanto nao chegaria aqui de qualquer forma.)
    """
    _require_admin(current)
    modelo = await _carregar_um(db, modelo_id)
    if modelo is None:
        raise HTTPException(404, "Modelo nao encontrado")
    alvo: Optional[User] = (await db.execute(
        select(User).where(User.id == req.user_id))).scalar_one_or_none()
    if not alvo:
        raise HTTPException(404, "Usuario nao encontrado")
    _guard_target(current, alvo)

    modo = permissoes.normalizar_modo_aplicacao(req.modo)
    minhas = authz.permissoes_de(current)
    meus_modulos = _meus_modulos(current)

    # O estado da TELA vence o do banco quando ele vem — ver `AplicarRequest`.
    # `is None` e nao falsy: lista vazia e "nao tem nada marcado", que e
    # diferente de "nao me mandaram nada".
    if req.estado_atual is None:
        atuais = {c for c in await _concedidas(db, alvo.id)
                  if permissoes.existe(c)}
    else:
        atuais = _validar(req.estado_atual)
    if req.escopos_atual is None:
        escopos_atuais = await _escopos_atuais(db, alvo.id)
    else:
        escopos_atuais = _validar_escopos(req.escopos_atual)

    conta = permissoes.aplicar_modelo(
        do_modelo=modelo["permissoes"], do_alvo=atuais, pode_conceder=minhas,
        modo=modo)
    conta_escopo = permissoes.aplicar_modelo_escopos(
        do_modelo=modelo["escopos"], do_alvo=escopos_atuais,
        pode_definir=meus_modulos, modo=modo)

    return {
        "modelo": {"id": modelo["id"], "nome": modelo["nome"],
                   "descricao": modelo["descricao"]},
        "usuario": {"id": alvo.id, "nome": alvo.name, "email": alvo.email},
        "modo": modo,
        # ⭐ O QUE A TELA DEVE MARCAR. Mandar de volta para o
        # `PUT /api/permissoes/usuario/{id}` (junto de `modelo_id` e
        # `modelo_modo`, para a trilha saber de onde isto veio).
        "permissoes": conta["permissoes"],
        "escopos": _escopos_completos(conta_escopo["escopos"]),
        # O estado de HOJE, para a tela poder mostrar o antes e o depois.
        "atuais": conta["atuais"],
        "escopos_atuais": _escopos_completos(conta_escopo["atuais"]),
        "vai_conceder": conta["vai_conceder"],
        "vai_retirar": conta["vai_retirar"],
        "alcance_alterado": [
            _frase_escopo(r, conta_escopo["escopos"].get(
                r, permissoes.ESCOPO_TODOS))
            for r in conta_escopo["alterados"]
        ],
        # ⚠️ O QUE A TELA TEM DE DIZER EM VOZ ALTA (ver `_para_api`):
        # `nao_aplicadas` sao caixinhas DO MOLDE que nao entraram porque quem
        # aplica nao as tem; `preservadas` sao caixinhas DA PESSOA que ficaram
        # intocadas pela mesma razao. Silencio em qualquer um dos dois faz o
        # administrador jurar ter feito o que nao fez.
        "nao_aplicadas": conta["nao_aplicadas"],
        "preservadas": conta["preservadas"],
        "alcance_nao_aplicado": conta_escopo["nao_aplicados"],
        "resumo": permissoes.resumo(conta["permissoes"]),
        # A frase obrigatoria: aplicar e COPIAR, e nada foi gravado ainda.
        "aviso": permissoes.modelos_para_api()["aviso"],
        "gravado": False,
    }
