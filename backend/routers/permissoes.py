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

Os MODELOS de permissao (o "molde" do Incremento 7) moram em
`routers/modelos_permissao.py`, sob `/api/permissoes/modelos`. Eles NAO gravam
permissao de ninguem: aplicar um molde CALCULA as caixinhas, e quem grava
continua sendo o `PUT` daqui — uma porta so para escrever permissao, com uma
copia so de cada guarda. O que este arquivo ganhou foi o campo `modelo_id` no
corpo do `PUT`, que existe SO para a trilha dizer de onde o administrador
partiu.

⭐ O ALCANCE POR LINHA (Incremento 6) VIAJA NAS MESMAS QUATRO ROTAS
------------------------------------------------------------------
"Editar somente os dele" nao e uma caixinha nova: e um MODIFICADOR das caixinhas
de escrita de um modulo (`{"gestao": "proprios"}`). O dono pediu que a escolha
morasse "no painel de administracao, no modulo de usuarios" — ou seja, no mesmo
clique das caixinhas —, e ha uma razao tecnica para isso alem da ergonomia: um
PUT separado abriria a janela em que a permissao ja foi concedida e a restricao
ainda nao, que e exatamente a janela em que a pessoa alcanca o registro dos
outros. Aqui as duas entram na MESMA transacao e na MESMA linha da trilha.

⚠️ `escopos` AUSENTE do corpo significa "nao mexi", e nao "sem restricao" — ver
`ConcederRequest`. Sem essa distincao, o frontend que ainda nao conhece o campo
apagaria a configuracao do administrador ao salvar as caixinhas.

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
        # O ALCANCE do PROPRIO usuario, todo modulo escopavel com o valor
        # vigente. Serve a dois consumidores: a tela pode avisar "voce so edita
        # o que voce criou" antes de a pessoa clicar, e o anti-escalonamento da
        # tela de Usuarios sabe quais radios ele nao pode mexer — a mesma regra
        # que `_barrar_escalonamento_escopo` impoe no servidor.
        "escopos": {chave: authz.escopo_de(current, chave)
                    for chave in permissoes.ESCOPO_RECURSOS},
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

    # ⭐ O ALCANCE por modulo (Incremento 6): `{"gestao": "proprios", ...}`.
    #
    # ⚠️ AUSENTE (None) e DICIONARIO VAZIO significam COISAS DIFERENTES, e a
    # assimetria e a unica coisa que impede este campo de apagar configuracao
    # alheia em silencio:
    #
    #   campo AUSENTE  -> "nao mexi no alcance". E o que o frontend que ainda
    #                     nao conhece este campo manda — e ele nao pode zerar a
    #                     restricao que o administrador acabou de configurar so
    #                     porque foi implantado antes da tela nova.
    #   `{}` ou dict    -> estado COMPLETO, igual a `permissoes`. Recurso
    #                     omitido dentro do dicionario volta para `todos`.
    escopos: Optional[dict[str, str]] = None

    # ⭐ O MODELO que serviu de PONTO DE PARTIDA para este Salvar (Incremento 7).
    #
    # ⚠️ NAO CRIA VINCULO NENHUM. Nao ha coluna que ligue usuario a modelo, aqui
    # nem no banco: aplicar e COPIAR, e o vinculo acaba no instante da copia.
    # Este campo existe SO para a trilha, e a distincao importa — quem o ler como
    # "o cadastro dela segue o modelo X" vai editar o modelo esperando corrigir a
    # pessoa, e nao vai corrigir nada.
    #
    # ⚠️ E ELE E DECLARADO PELO CLIENTE, nao verificado. O servidor NAO confere
    # se as caixinhas salvas batem com as do modelo — elas nao devem bater: o
    # dono pediu que ficassem editaveis, entao o administrador ajusta antes de
    # salvar e o normal e diferirem. A autoridade da trilha continua sendo o
    # `valor_antes`/`valor_depois` desta mesma linha, que e medido, e nao
    # afirmado. `modelo_id` responde outra pergunta: "de onde ele partiu".
    modelo_id: Optional[int] = None
    modelo_modo: Optional[str] = None


async def _concedidas(db: AsyncSession, user_id: int) -> set:
    linhas = await db.execute(
        text("SELECT permissao FROM user_permissoes WHERE user_id = :u"),
        {"u": user_id})
    return {r[0] for r in linhas.fetchall()}


async def _escopos_atuais(db: AsyncSession, user_id: int) -> dict:
    """O alcance GRAVADO deste usuario. So o que difere do default aparece —
    recurso sem linha e `todos`, e materializar os `todos` criaria uma segunda
    resposta para a pergunta "o que significa nao ter linha?"."""
    linhas = await db.execute(
        text("SELECT recurso, escopo FROM user_escopos WHERE user_id = :u"),
        {"u": user_id})
    return {r[0]: permissoes.normalizar_escopo(r[1])
            for r in linhas.fetchall()
            if permissoes.escopavel(r[0])
            and permissoes.normalizar_escopo(r[1]) != permissoes.ESCOPO_TODOS}


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
    # O ALCANCE de cada pessoa, na mesma chamada: a tela desenha os radios junto
    # das caixinhas, e uma requisicao por usuario so para saber isso seria uma
    # por linha da lista.
    escopos_linhas = await db.execute(
        text("SELECT user_id, recurso, escopo FROM user_escopos"))
    escopos: dict[str, dict] = {}
    for uid, recurso, valor in escopos_linhas.fetchall():
        if not permissoes.escopavel(recurso):
            continue        # linha orfa de um modulo que saiu do catalogo
        escopos.setdefault(str(uid), {})[permissoes.normalizar(recurso)] = \
            permissoes.normalizar_escopo(valor)
    return {
        "concedidas": {uid: sorted(chaves) for uid, chaves in mapa.items()},
        # ⚠️ SO os usuarios com alguma restricao aparecem aqui, e dentro de cada
        # um so os modulos restritos. Ausencia = `todos` — a mesma convencao do
        # banco. O catalogo (`/permissoes/catalogo` -> `escopos`) diz quais
        # modulos existem e qual e o default, entao a tela nao precisa adivinhar.
        "escopos": escopos,
    }


def _validar_escopos(pedidos) -> dict:
    """Normaliza o alcance pedido e RECUSA o que nao existe.

    400 e nao 403, pelo mesmo motivo de `_validar`: nao e permissao que falta, e
    pedido malformado. E aqui a recusa importa mais do que la — um recurso
    escrito errado (`gestaoo`) ou um valor escrito errado (`proprio`, sem o «s»)
    seria uma restricao que o administrador JURA ter configurado e que nunca se
    aplica. Silencio nessa direcao ABRE o sistema, entao ele nao pode existir:
    aqui, na restricao CHECK da tabela e na chave estrangeira, tres travas
    dizendo a mesma coisa.

    ⚠️ Recurso omitido volta para `todos` — o dicionario e o estado COMPLETO, e
    devolver o silencio ao default e o que faz "desmarquei a restricao" gravar.
    """
    limpos: dict = {}
    if not pedidos:
        return limpos
    if not isinstance(pedidos, dict):
        raise HTTPException(400, "Alcance invalido: esperado um objeto "
                                 "{modulo: 'todos'|'proprios'}")
    desconhecidos, valores_ruins = [], []
    for recurso, valor in pedidos.items():
        chave = permissoes.normalizar(recurso)
        if not permissoes.escopavel(chave):
            desconhecidos.append(str(recurso))
            continue
        bruto = str(valor or "").strip().lower()
        if bruto not in permissoes.ESCOPOS:
            valores_ruins.append(f"{chave}={valor!r}")
            continue
        if bruto != permissoes.ESCOPO_TODOS:
            # So o que RESTRINGE vira linha. `todos` e a ausencia de linha.
            limpos[chave] = bruto
    if desconhecidos:
        raise HTTPException(
            400, "Modulo sem alcance por linha: " + ", ".join(sorted(desconhecidos)))
    if valores_ruins:
        raise HTTPException(
            400, "Alcance invalido (use 'todos' ou 'proprios'): "
                 + ", ".join(sorted(valores_ruins)))
    return limpos


def _barrar_escalonamento_escopo(atual: User, antes: dict, depois: dict, *,
                                 frase: Optional[str] = None) -> None:
    """⭐ NINGUEM MEXE NO ALCANCE DE UM MODULO EM QUE ELE MESMO ESTA RESTRITO.

    Mesma logica de `_barrar_escalonamento`, e vale sobre o que MUDOU. Um
    administrador limitado a "somente os que ele criou" na Gestao Interna nao
    pode dar a outra pessoa o alcance TOTAL que ele proprio nao tem — seria
    conceder por procuracao o que a tela lhe nega.

    A trava vale nos dois sentidos (soltar e apertar), pela mesma razao que a
    outra: o poder de decidir sobre aquele modulo pertence a quem o alcanca por
    inteiro. Um administrador restrito que pudesse APERTAR o alcance dos colegas
    derrubaria a operacao do setor inteiro sem nunca ter tido esse poder.

    ⚠️ NEGA SEMPRE, nos dois modos de `AUTHZ_MODO` — este endpoint e novo e nao
    ha comportamento antigo a preservar. Trava de escalonamento que "so avisa" e
    a ausencia da trava.

    `frase` troca so o TEXTO do 403, para o MOLDE (Incremento 7) reusar esta
    mesma implementacao em vez de copia-la: quem esta escrevendo um modelo nao
    esta "definindo o alcance de ninguem" ainda, e a mensagem tem de dizer o que
    ele estava fazendo. A REGRA continua morando aqui, num lugar so — uma
    segunda copia e como as copias divergem."""
    if is_super_admin(atual):
        return
    mudados = sorted(
        chave for chave in set(antes) | set(depois)
        if antes.get(chave, permissoes.ESCOPO_TODOS)
        != depois.get(chave, permissoes.ESCOPO_TODOS))
    fora = [chave for chave in mudados
            if authz.escopo_de(atual, chave) != permissoes.ESCOPO_TODOS]
    if not fora:
        return
    rotulos = ", ".join(
        permissoes.escopos_para_api()["recursos"][c]["recurso_rotulo"] for c in fora)
    raise HTTPException(
        403,
        (frase or "Voce so pode definir o alcance de modulos em que voce mesmo "
                  "alcanca todos os registros.")
        + f" Fora do seu alcance: {rotulos}")


async def _gravar_escopos(db: AsyncSession, user_id: int, antes: dict,
                          depois: dict, autor_id) -> None:
    """Grava so a DIFERENCA — nao apaga tudo para reinserir.

    Mesmo motivo de `_gravar_concessao`: `definido_em` e `definido_por` sao a
    resposta barata para "de onde veio esta linha?", e reescreve-las a cada
    salvamento faria a restricao imposta ha um ano por outra pessoa passar a
    dizer que fui eu, hoje.

    Voltar para `todos` APAGA a linha, em vez de gravar `escopo='todos'`: ha um
    unico jeito de dizer "sem restricao" no banco, e e a ausencia — ver o
    cabecalho da migration."""
    for chave in sorted(set(antes) - set(depois)):
        await db.execute(
            text("DELETE FROM user_escopos WHERE user_id = :u AND recurso = :r"),
            {"u": user_id, "r": chave})
    for chave in sorted(depois):
        if antes.get(chave) == depois[chave]:
            continue
        await db.execute(
            text("INSERT INTO user_escopos (user_id, recurso, escopo, definido_por) "
                 "VALUES (:u, :r, :e, :por) "
                 "ON CONFLICT (user_id, recurso) DO UPDATE SET "
                 "escopo = EXCLUDED.escopo, definido_em = NOW(), "
                 "definido_por = EXCLUDED.definido_por"),
            {"u": user_id, "r": chave, "e": depois[chave], "por": autor_id})


def _escopos_completos(gravados: dict) -> dict:
    """O alcance de TODO modulo escopavel, com o default explicito.

    O banco guarda so o que restringe (ausencia = `todos`), e essa economia e
    deliberada — mas ela nao pode vazar para a API: a tela teria de saber que
    "recurso ausente" quer dizer `todos`, e a trilha mostraria um lado vazio no
    "de -> para". Uma fonte de verdade (o banco) e uma resposta legivel (esta)."""
    return {chave: gravados.get(chave, permissoes.ESCOPO_TODOS)
            for chave in permissoes.ESCOPO_RECURSOS}


def _frase_escopo(recurso: str, escopo: str) -> str:
    """"Gestao Interna: Somente os que ele criou" — a linha que o auditor le sem
    traduzir chave nenhuma de cabeca."""
    ficha = permissoes.escopos_para_api()["recursos"].get(recurso)
    rotulo = ficha["recurso_rotulo"] if ficha else recurso
    opcao = next((o["rotulo"] for o in permissoes.ESCOPO_OPCOES
                  if o["valor"] == escopo), escopo)
    return f"{rotulo}: {opcao}"


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


def _barrar_escalonamento(atual: User, antes: set, depois: set, *,
                          frase: Optional[str] = None) -> None:
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
    avisa" e a ausencia da trava.

    `frase` troca so o TEXTO do 403 — ver `_barrar_escalonamento_escopo`. O
    MOLDE (Incremento 7) chama ESTA funcao ao gravar um modelo, e nao uma copia:
    se a trava do molde fosse escrita de novo la, o dia em que esta regra mudar
    seria o dia em que o molde vira a porta dos fundos dela."""
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
        (frase or "Voce so pode conceder ou retirar permissoes que voce mesmo "
                  "tem.")
        + f" Fora do seu alcance: {rotulos}")


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


async def _modelo_declarado(db: AsyncSession, modelo_id, modo=None) -> Optional[dict]:
    """O molde que o cliente diz ter usado, resolvido para NOME pelo banco.

    ⚠️ Molde APAGADO (ou id inexistente) NAO derruba o Salvar. A concessao e
    completa e autoritativa sozinha — `valor_antes`/`valor_depois` estao na
    mesma linha —, e recusar a gravacao porque um RÓTULO sumiu entre a
    aplicacao e o clique em Salvar seria o rabo abanando o cachorro: o
    administrador perderia o trabalho por causa de um campo que existe so para
    a trilha. Registramos o id com `nome: None`, que e a verdade do que
    aconteceu."""
    if modelo_id is None:
        return None
    try:
        alvo_id = int(modelo_id)
    except (TypeError, ValueError):
        return None
    linha = (await db.execute(
        text("SELECT nome FROM modelos_permissao WHERE id = :i"),
        {"i": alvo_id})).first()
    return {
        "id": alvo_id,
        "nome": linha[0] if linha else None,
        "modo": permissoes.normalizar_modo_aplicacao(modo),
        # Quando o molde sumiu entre aplicar e salvar, a linha da trilha diz
        # isso em vez de mostrar um nome vazio sem explicacao.
        "observacao": None if linha else
                      "o modelo nao existe mais no momento do registro",
    }


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

    # O alcance por linha viaja no MESMO endpoint e na MESMA transacao das
    # caixinhas de proposito: ele so faz sentido junto delas ("pode editar" +
    # "quais"), e um PUT separado abriria a janela em que a permissao ja esta
    # concedida e a restricao ainda nao — que e a janela em que a pessoa alcanca
    # o registro dos outros.
    escopos_antes = await _escopos_atuais(db, alvo.id)
    escopos_depois = (escopos_antes if req.escopos is None
                      else _validar_escopos(req.escopos))
    _barrar_escalonamento_escopo(current, escopos_antes, escopos_depois)

    await _gravar_concessao(db, alvo.id, antes, depois, getattr(current, "id", None))
    if req.escopos is not None:
        await _gravar_escopos(db, alvo.id, escopos_antes, escopos_depois,
                              getattr(current, "id", None))

    # `registrar_critico` com `commit=False`: a linha da trilha entra na MESMA
    # transacao da concessao. Ou as duas gravam, ou nenhuma — "permissao
    # concedida sem ninguem saber por quem" e exatamente o buraco que esta tela
    # fecha. Mesmo desenho de `routers/users.py::update_user`.
    concedidas = sorted(depois - antes)
    retiradas = sorted(antes - depois)
    # ⭐ A alteracao de ALCANCE tem de virar linha na trilha como qualquer outra
    # concessao de poder — e vai na MESMA linha de `usuarios.conceder`, e nao
    # numa acao propria, porque ela e a segunda metade da mesma frase: "pode
    # editar, e so os que ele criou". Duas linhas separadas obrigariam o auditor
    # a cruzar dois eventos para entender um unico clique em Salvar.
    escopos_mudados = sorted(
        chave for chave in set(escopos_antes) | set(escopos_depois)
        if escopos_antes.get(chave, permissoes.ESCOPO_TODOS)
        != escopos_depois.get(chave, permissoes.ESCOPO_TODOS))
    # ⭐ O MODELO de onde o administrador partiu (Incremento 7), se houve um.
    modelo = await _modelo_declarado(db, req.modelo_id, req.modelo_modo)
    await registrar_critico(
        db, action="usuarios.conceder", user=current, request=request,
        target_type="user", target_id=alvo.id, alvo_nome=alvo.name,
        # Snapshots COMPLETOS dos dois lados: `services/audit.py` reduz sozinho
        # aos campos que mudaram. Sem o par, "de -> para" nao existe e a linha
        # so diria que ALGO mudou.
        #
        # `escopos` entra nos dois snapshots preenchido com o DEFAULT explicito
        # de todo modulo escopavel, e nao so com o que tem linha no banco: o
        # auditor precisa ler "Gestao Interna: Todos os registros -> Somente os
        # que ele criou", e um lado vazio nao diz de onde a pessoa saiu.
        valor_antes={"permissoes": sorted(antes),
                     "escopos": _escopos_completos(escopos_antes)},
        valor_depois={"permissoes": sorted(depois),
                      "escopos": _escopos_completos(escopos_depois)},
        details={
            "alvo_email": alvo.email,
            # A mesma pergunta de `routers/users.py::_concessoes`: nao "de que
            # lista para que lista", e sim o que a pessoa GANHOU e o que PERDEU.
            "concedidas": concedidas or None,
            "retiradas": retiradas or None,
            # Frase pronta do estado final, para o modal da Auditoria nao exigir
            # que o auditor traduza 66 chaves de cabeca.
            "resumo": permissoes.resumo(depois) or None,
            # Idem para o alcance: so os modulos que MUDARAM, ja em portugues.
            "alcance_alterado": [
                _frase_escopo(c, escopos_depois.get(c, permissoes.ESCOPO_TODOS))
                for c in escopos_mudados
            ] or None,
            "alcance_resumo": [
                _frase_escopo(c, escopos_depois[c]) for c in sorted(escopos_depois)
            ] or None,
            # De onde o administrador partiu. `nome` vem do BANCO, e nao do
            # cliente: o que ele declara e um id.
            "modelo_aplicado": modelo,
        },
        commit=False,
    )
    # ⭐ A APLICACAO DO MOLDE VIRA LINHA PROPRIA — e so quando houve uma.
    #
    # ⚠️ Sim, sao DUAS linhas para um clique em Salvar, e o repo argumenta
    # contra isso no alcance por linha (que viaja DENTRO de `usuarios.conceder`).
    # A diferenca e qual pergunta cada linha responde. O alcance e a segunda
    # metade de uma frase so ("pode editar, e so os que ele criou") — separa-lo
    # obrigaria a cruzar dois eventos para entender uma unica decisao. O molde
    # nao: ele responde "ONDE este molde foi aplicado?", que e pergunta de
    # REVISAO DE ACESSO ("quem recebeu o molde do Cofre neste semestre?") e que
    # filtrar `usuarios.conceder` nao responde — la o molde seria um campo dentro
    # do detalhe de centenas de linhas. E exatamente o mesmo motivo pelo qual
    # `usuarios.conceder` foi separada de `user.update`.
    #
    # Na MESMA transacao (`commit=False`): ou as duas linhas entram com a
    # concessao, ou nao entra nenhuma.
    if modelo is not None:
        await registrar_critico(
            db, action="modelo_permissao.aplicar", user=current, request=request,
            # O alvo e a PESSOA — e por ela que o auditor filtra. Qual molde foi
            # usado esta no detalhe.
            target_type="user", target_id=alvo.id, alvo_nome=alvo.name,
            details={
                "modelo": modelo,
                "alvo_email": alvo.email,
                "concedidas": concedidas or None,
                "retiradas": retiradas or None,
                "efeito": "Aplicar COPIA as permissoes para o cadastro da "
                          "pessoa. Nao ha vinculo: mexer no modelo depois nao "
                          "muda mais este usuario.",
            },
            commit=False,
        )
    await db.commit()
    return {"permissoes": sorted(depois),
            "concedidas": concedidas, "retiradas": retiradas,
            # Estado COMPLETO do alcance (todo modulo escopavel, com o default
            # explicito): a tela redesenha os radios a partir da resposta sem
            # precisar saber que "ausente" quer dizer `todos`.
            "escopos": _escopos_completos(escopos_depois),
            "alcance_alterado": escopos_mudados,
            # O que foi REGISTRADO sobre o molde (nome resolvido pelo banco), ou
            # None quando o Salvar nao partiu de nenhum.
            "modelo_aplicado": modelo}
