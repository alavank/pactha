"""
Autorizacao em MODO AVISO — a trava que FALA antes de morder.

POR QUE ESTE ARQUIVO EXISTE
---------------------------
55 dos 171 endpoints da API nao checavam nada alem de "esta logado". Fechar
todos de uma vez e trocar um problema de seguranca por um problema pior: nunca
houve gate ali, entao e bem possivel que gente em Monte Siao esteja trabalhando
HOJE justamente porque o gate nao existe. Ligar a trava numa sexta e apagao na
segunda de manha, com o servidor devolvendo 403 para quem sempre trabalhou e
ninguem entendendo por que.

Entao a trava nasce FALANDO. Em `AUTHZ_MODO=aviso` (o default) o servidor deixa
passar exatamente como hoje e escreve na trilha de auditoria "eu teria negado
isto, para este usuario, neste endpoint, por este motivo". Depois de uma semana
lendo essas linhas, o dono corrige a permissao de quem precisa — e so entao
liga `AUTHZ_MODO=bloqueio`.

⚠️ O RISCO DESTE ARQUIVO NAO E TECNICO, E OPERACIONAL. Ele existe para NAO
quebrar nada. Por isso, em modo aviso:
  - nenhuma excecao nova sai daqui;
  - falha ao gravar a trilha NAO derruba a requisicao (um incremento feito para
    nao quebrar nada nao pode quebrar por causa do proprio log);
  - a gravacao vai para TAREFA DE FUNDO com SESSAO PROPRIA, nunca na sessao do
    endpoint — escrever na sessao alheia no meio de uma transacao de negocio e
    exatamente como este incremento quebraria o que veio salvar.

⚠️⚠️ O QUE O MODO AVISO **NAO** AFROUXA (leia antes de subir)
------------------------------------------------------------------------
`services/auth.py::ensure_tela` e `ensure_municipio_access` ja NEGAVAM em ~128
pontos do codigo, e cada um deles e uma trava que JA VALE hoje. Elas NAO passam
por este modulo e NEGAM SEMPRE, nos dois modos. Rotea-las por aqui faria essas
128 negativas ANTIGAS pararem de negar durante a semana de observacao: quem hoje
leva 403 por pedir municipio fora do escopo passaria a receber os dados. O
sistema ficaria MAIS ABERTO justamente no incremento que existe para fecha-lo, e
o dono recebeu a promessa oposta — "em modo aviso, comportamento IDENTICO ao de
hoje".

Como em tempo de execucao nao da para distinguir um `ensure_tela` que ja existia
de um que outro agente acabou de acrescentar, a distincao e feita no CHAMADOR:

  - gate que ja existia  -> `services.auth.ensure_tela` / `ensure_municipio_access`
  - gate NOVO (este incremento) -> `authz.exigir_tela` / `authz.exigir_municipio`
    e `authz.ensure_dono` (o dono da LINHA, que tambem e novo)

So os gates NOVOS respeitam `AUTHZ_MODO`. Duas coisas seguram o preco disso:

  1. A JANELA E CURTA E VIGIADA. Toda passagem indevida vira linha na trilha —
     o alargamento e observavel, o que a ausencia de gate nunca foi.

  2. PEDIDO MALFORMADO CONTINUA SENDO NEGADO NOS DOIS MODOS. Municipio ausente
     ("Selecione um municipio permitido") e municipio nao-numerico ("Municipio
     invalido") NAO passam por aqui: continuam levantando 403 como sempre. Nao
     e permissao que falta — nenhuma correcao de cadastro faz um pedido sem
     municipio virar valido — e deixar passar trocaria um 403 honesto por um
     500 ou, pior, por uma consulta sem filtro devolvendo o tenant inteiro.
     Ver `services/auth.py::ensure_municipio_access`.

O que continua barrando normalmente, porque nao passa por este modulo: o guard
de perfil somente-leitura, o guard de quiosque, o 401 de sessao e o
`resolve_scope` do BI quando o nao-admin nao tem municipio nenhum.

COMO SE USA
-----------
    # no endpoint, o gate NOVO de tela/municipio (respeita AUTHZ_MODO):
    authz.exigir_tela(current, "rm")
    authz.exigir_municipio(current, body.municipio_id)

    # no endpoint, para o buraco que permissao de VERBO nao resolve:
    await authz.ensure_dono(db, "rm_relatorios", "id", rm_id, current)

    # so nos endpoints de ESCRITA de modulo escopavel (rm, gestao, documentos):
    # "esta linha foi criada por ele?" — o alcance por linha do Incremento 6
    await authz.exigir_dono_da_linha(db, "rm", rm_id, current)

ENV
---
    AUTHZ_MODO=aviso      (DEFAULT) deixa passar e registra
    AUTHZ_MODO=bloqueio   levanta o MESMO 403 de hoje, e registra tambem

Valor desconhecido cai em "aviso": o default tem de ser o que NAO quebra.
"""
import asyncio
import logging
import os
import re
import threading
import time
from contextvars import ContextVar
from typing import Any, Optional

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session
from services.audit import registrar
# Reaproveita o calculo do MOLDE da rota (`/api/rm/{rm_id}`, nunca o caminho
# preenchido) em vez de refaze-lo: `services/audit.py::_rota` existe porque ha
# rota cujo parametro E UMA CREDENCIAL VIVA (o slug do link publico do Painel).
# Uma segunda implementacao divergiria da primeira no dia em que aquela regra
# mudasse — e o que se perde nesse dia e um segredo dentro da trilha.
from services.audit import _rota as _molde_da_rota

logger = logging.getLogger("authz")


# ---------------------------------------------------------------------------
# Modo
# ---------------------------------------------------------------------------
MODO_AVISO = "aviso"
MODO_BLOQUEIO = "bloqueio"

# Acoes gravadas por este modulo. Todas cadastradas em services/audit_catalog.py
# — chave sem entrada la cai num rotulo generico, e a semana de observacao vira
# uma lista de jargao que ninguem le.
ACAO_NEGARIA = "authz.negaria"      # modo aviso: passou, mas teria sido barrado
ACAO_NEGOU = "authz.negou"          # modo bloqueio: barrado de verdade
ACAO_SEM_DONO = "authz.sem_dono"    # linha sem municipio: nao da para decidir
# Linha cujo CRIADOR e desconhecido (`criado_por` nulo) sendo alterada por quem
# esta restrito a "somente os que ele criou". Passou — ver
# `exigir_dono_da_linha` para a decisao e o porque.
ACAO_SEM_CRIADOR = "authz.sem_criador"
# Rota que subiu sem declarar permissao e sem estar na allowlist de rotas
# livres. Ver services/registro_rotas.py — e defeito de programacao, nao de
# cadastro, e por isso a linha sai com o CAMINHO no lugar da permissao.
ACAO_ROTA_SEM_REGISTRO = "authz.rota_sem_registro"

_MODOS_DESCONHECIDOS: set = set()


def modo() -> str:
    """Modo vigente. Lido a cada chamada (nao no import) para o teste poder
    variar o ambiente e para a env valer sem rebuild da imagem — mesma
    convencao de `services/net.py::proxies_confiaveis`.

    ⭐⭐ O DEFAULT VIROU `bloqueio` EM 05/09/2026, e esta e a linha de maior
    alcance do incremento: a partir dela toda caixinha desmarcada RECUSA de
    verdade, nos cinco clientes.

    Ela mudou porque teve de mudar. O dono pediu para tirar a trava de conta
    «Somente leitura» ("prefiro dar permissao de visualizaçao separada pra cada
    menu ou modulo dai eu permito so visualizar sem editar nada") — e quem
    impedia a escrita ate a vespera era EXATAMENTE aquela trava, porque em
    `aviso` estas caixinhas so registravam na trilha. Tirar uma sem ligar a
    outra deixaria o sistema sem trava de escrita nenhuma. As duas viajam no
    mesmo deploy, por decisao explicita dele depois de a consequencia ter sido
    posta na mesa.

    ⚠️ O FAIL-OPEN CONTINUA VALENDO PARA ENV DESCONHECIDA, e agora ele aponta
    para o outro lado: `AUTHZ_MODO=avisoo` (digitado errado) NAO pode desligar a
    trava, do mesmo modo que antes `bloqueiop` nao podia liga-la. Desligar
    passou a ser o ato deliberado, e e ele que precisa ser escrito certo.

    Continua lido a cada chamada (nao no import) para o teste poder variar o
    ambiente e para a env valer sem rebuild — mesma convencao de
    `services/net.py::proxies_confiaveis`. `AUTHZ_MODO=aviso` continua
    existindo e e o caminho de recuo se um cliente for barrado indevidamente:
    troca a env no Coolify, sem deploy."""
    bruto = (os.getenv("AUTHZ_MODO", "") or "").strip().lower()
    if bruto == MODO_AVISO:
        return MODO_AVISO
    if bruto and bruto != MODO_BLOQUEIO and bruto not in _MODOS_DESCONHECIDOS:
        # Uma vez por valor: env digitada errada nao pode virar log por request.
        _MODOS_DESCONHECIDOS.add(bruto)
        logger.warning(
            "AUTHZ_MODO=%r nao e reconhecido; seguindo em %r", bruto, MODO_BLOQUEIO)
    return MODO_BLOQUEIO


# ---------------------------------------------------------------------------
# Contexto da requisicao
# ---------------------------------------------------------------------------
# `ensure_tela` e `ensure_municipio_access` sao SINCRONAS e nao recebem nem
# `Request` nem sessao de banco — e nao podem passar a receber, porque sao
# chamadas em dezenas de lugares. O contexto entra por um ContextVar preenchido
# em `get_current_user`, que ja recebe o `request`.
#
# ContextVar e seguro aqui: cada requisicao roda na propria task do asyncio, e
# task nasce com uma COPIA do contexto — escrita dentro de uma nao vaza para as
# outras. Endpoint sincrono (`def`) tambem enxerga, porque o anyio copia o
# contexto para a thread do pool.
class _Contexto:
    """So o que a gravacao precisa. Guardado por requisicao."""
    __slots__ = ("request", "usuario", "laco")

    def __init__(self, request, usuario, laco):
        self.request = request
        self.usuario = usuario
        self.laco = laco


class _UsuarioSnapshot:
    """Copia CONGELADA de quem e o usuario.

    Nao guardamos a instancia do SQLAlchemy: ela pertence a sessao do endpoint,
    que fecha quando a resposta sai. A tarefa de fundo roda depois disso, e ler
    um atributo de instancia destacada pode levantar `DetachedInstanceError` —
    dentro de uma tarefa cuja unica funcao e NAO atrapalhar ninguem."""
    __slots__ = ("id", "email", "name")

    def __init__(self, usuario):
        self.id = getattr(usuario, "id", None)
        self.email = getattr(usuario, "email", None)
        self.name = getattr(usuario, "name", None)


_CTX: ContextVar[Optional[_Contexto]] = ContextVar("authz_contexto", default=None)

# Detalhe extra de UMA chamada, para a linha da trilha dizer de onde veio a
# negativa. Existe porque `ensure_dono` delega a `exigir_municipio` (que nao
# tem por onde receber parametro novo): sem isto, "apagou RM de outro
# municipio" e "pediu tela de outro municipio" sairiam identicas na trilha.
_ORIGEM: ContextVar[Optional[dict]] = ContextVar("authz_origem", default=None)


def definir_contexto(request: Optional[Request], usuario) -> None:
    """Chamado por `get_current_user`. NUNCA levanta: sem contexto a trilha
    perde IP e rota, mas a requisicao segue — que e a prioridade."""
    try:
        try:
            laco = asyncio.get_running_loop()
        except RuntimeError:
            laco = None
        _CTX.set(_Contexto(request, _UsuarioSnapshot(usuario), laco))
    except Exception:
        logger.exception("Falha definindo contexto de authz")


def limpar_contexto() -> None:
    """So para teste e para quem reaproveitar o processo fora de uma request."""
    try:
        _CTX.set(None)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Anti-inundacao
# ---------------------------------------------------------------------------
# Uma tela do Painel dispara uma duzia de chamadas por carregamento. Sem
# deduplicar, um unico usuario sem permissao escreveria doze linhas IGUAIS por
# minuto e afogaria a trilha justamente na semana em que ela precisa ser lida —
# o dono abriria a Auditoria, veria mil linhas do mesmo fato e desistiria.
#
# ⚠️ LIMITE DECLARADO: e memoria de PROCESSO, e a API sobe com 2 workers
# (uvicorn --workers 2). Entao o teto real e ~1 linha por worker por janela, ou
# seja ate 2 linhas iguais a cada 10 minutos, e o cache zera a cada deploy. Isso
# e de proposito: um dedupe compartilhado exigiria Redis ou uma tabela de
# estado, e a contrapartida (uma linha repetida de vez em quando) e barata
# perto de acrescentar infraestrutura a um modulo que existe para nao quebrar
# nada. Ninguem deve CONTAR ocorrencias a partir desta trilha — ela responde
# "quem esbarrou em que", nao "quantas vezes".
_JANELA_SEGUNDOS = 600
_TETO_DEDUPE = 20_000

_dedupe: dict[tuple, float] = {}
_trava = threading.Lock()


def _primeira_vez(chave: tuple) -> bool:
    """True se esta ocorrencia deve virar linha na trilha."""
    agora = time.monotonic()
    with _trava:
        visto = _dedupe.get(chave)
        if visto is not None and (agora - visto) < _JANELA_SEGUNDOS:
            return False
        if len(_dedupe) >= _TETO_DEDUPE:
            # Cache que so cresce dentro de um worker de API e vazamento de
            # memoria. Primeiro poda o que ja venceu; se ainda estourar (fluxo
            # anormal), zera — perder dedupe custa linha repetida, e um dicionario
            # sem teto custa o processo.
            for k, t in [(k, t) for k, t in _dedupe.items()
                         if (agora - t) >= _JANELA_SEGUNDOS]:
                _dedupe.pop(k, None)
            if len(_dedupe) >= _TETO_DEDUPE:
                _dedupe.clear()
                logger.warning("Dedupe de authz estourou o teto e foi zerado")
        _dedupe[chave] = agora
        return True


def limpar_dedupe() -> None:
    """Zera a memoria de deduplicacao (teste e operacao)."""
    with _trava:
        _dedupe.clear()


# ---------------------------------------------------------------------------
# Gravacao
# ---------------------------------------------------------------------------
# Referencia forte das tarefas em voo: `asyncio.create_task` so guarda uma
# referencia FRACA, entao uma tarefa sem dono pode ser coletada no meio do
# caminho e a linha nunca ser gravada — em silencio.
_TAREFAS: set = set()


async def _gravar(dados: dict) -> None:
    """Grava a linha em SESSAO PROPRIA. Engole tudo: esta corrotina roda solta,
    e excecao aqui nao tem quem a receba.

    Sessao propria custa uma conexao do pool (pool_size=5 + overflow 10). E o
    dedupe acima que mantem esse custo desprezivel: sem ele, uma tela que
    dispara doze chamadas por carregamento abriria doze conexoes so para
    escrever doze vezes o mesmo fato."""
    try:
        async with async_session() as sessao:
            await registrar(
                sessao,
                action=dados["acao"],
                user=dados["usuario"],
                request=dados["request"],
                target_type=dados["tipo"],
                target_id=dados["exigido"],
                details=dados["detalhes"],
                municipio_id=dados.get("municipio_id"),
                resultado="negado",
            )
    except Exception:
        logger.exception("Falha registrando %s", dados.get("acao"))


def _enviar(dados: dict) -> bool:
    """Agenda `_gravar` em tarefa de fundo. Devolve True se agendou.

    NUNCA na sessao do endpoint: a requisicao pode estar no meio de uma
    transacao de negocio, e um INSERT nosso ali dentro entra no commit alheio
    (ou o envenena, se falhar)."""
    coro = _gravar(dados)
    try:
        laco = asyncio.get_running_loop()
    except RuntimeError:
        # Endpoint sincrono (`def`) roda na thread do pool: nao ha laco NESTA
        # thread, mas ha o laco guardado no contexto pelo `get_current_user`.
        laco = dados.get("laco")
        if laco is not None and not laco.is_closed():
            asyncio.run_coroutine_threadsafe(coro, laco)
            return True
        # Fora de qualquer laco (teste, script). Fecha a corrotina para nao
        # deixar "coroutine was never awaited" no log.
        coro.close()
        return False

    tarefa = laco.create_task(coro)
    _TAREFAS.add(tarefa)
    tarefa.add_done_callback(_TAREFAS.discard)
    return True


def _detalhes(tipo: str, exigido: Any, possui: Any, ctx: Optional[_Contexto],
              caminho: Optional[str]) -> dict:
    """O que o dono precisa ler para decidir a correcao: o que foi exigido, o
    que a pessoa TEM hoje, e por onde ela passou.

    `possui` vazio e o achado mais util da semana — e o usuario criado com ZERO
    telas que trabalha ha meses porque nunca houve gate."""
    tem = possui
    if isinstance(tem, (set, frozenset, tuple)):
        try:
            tem = sorted(tem, key=str)
        except Exception:
            tem = list(tem)
    detalhes = {
        "exigencia": tipo,
        "exigido": exigido,
        "possui": tem,
        "possui_qtd": len(tem) if isinstance(tem, (list, tuple, set)) else None,
        "metodo": getattr(getattr(ctx, "request", None), "method", None) if ctx else None,
        # MOLDE da rota, nunca o caminho preenchido — ver `_molde_da_rota`.
        "caminho": caminho,
        "modo": modo(),
    }
    origem = _ORIGEM.get()
    if origem:
        detalhes["origem"] = origem
    return detalhes


def _observar(acao: str, usuario, *, tipo: str, exigido: Any, possui: Any = None,
              municipio_id: Optional[int] = None) -> bool:
    """Monta e agenda a linha. Devolve True se agendou (False = deduplicada,
    sem contexto de laco, etc.). Chamada SEMPRE de dentro de um try/except."""
    ctx = _CTX.get()
    caminho = None
    if ctx is not None and ctx.request is not None:
        caminho = _molde_da_rota(ctx.request)

    # Quem esta sendo julgado e SEMPRE o usuario recebido, e nao o do contexto.
    # Quase sempre sao o mesmo, mas um endpoint que avalie a permissao de
    # OUTRA pessoa (tela de usuarios) gravaria o nome errado na trilha — e
    # trilha que aponta a pessoa errada e pior do que trilha que falta.
    # O contexto entra so com o que a funcao sincrona nao tem: request e laco.
    dono = _UsuarioSnapshot(usuario)

    # Chave do dedupe: quem, por onde, e por que. Fica so na memoria — o
    # caminho aqui pode ser o literal (quando nao ha rota casada) sem risco,
    # porque nao vai para o banco.
    chave = (dono.id, caminho, acao, tipo, str(exigido))
    if not _primeira_vez(chave):
        return False

    return _enviar({
        "acao": acao,
        "usuario": dono,
        "request": ctx.request if ctx else None,
        "laco": ctx.laco if ctx else None,
        "tipo": tipo,
        "exigido": exigido,
        "municipio_id": municipio_id,
        "detalhes": _detalhes(tipo, exigido, possui, ctx, caminho),
    })


def _observar_seguro(acao: str, usuario, **kwargs) -> bool:
    """`_observar` com a rede de seguranca. NADA daqui escapa.

    E a garantia mais dura deste incremento: se a trilha falhar, a requisicao
    segue mesmo assim."""
    try:
        return _observar(acao, usuario, **kwargs)
    except Exception:
        logger.exception("Falha observando %s (a requisicao segue)", acao)
        return False


# ---------------------------------------------------------------------------
# O ponto unico de decisao
# ---------------------------------------------------------------------------
def negar(usuario, *, tipo: str, exigido: Any, possui: Any = None,
          mensagem: str) -> None:
    """PONTO UNICO por onde toda negativa de tela/municipio passa.

    - modo bloqueio -> registra e levanta o MESMO 403 de hoje (mesma mensagem,
      mesmo status). O registro vem antes do `raise` porque quem liga a trava
      precisa enxergar quem ela derrubou; se o registro falhar, o 403 sai
      igual.
    - modo aviso    -> registra `authz.negaria` e RETORNA. Nenhum 403 novo,
      nenhuma resposta diferente, nenhuma excecao que escape.

    `mensagem` vem do chamador de proposito: e a mensagem que o endpoint ja
    devolvia. Reescreve-la aqui mudaria a resposta de producao — e este modulo
    nao pode mudar resposta nenhuma."""
    if modo() == MODO_BLOQUEIO:
        _observar_seguro(ACAO_NEGOU, usuario, tipo=tipo, exigido=exigido,
                         possui=possui,
                         municipio_id=exigido if tipo == "municipio" else None)
        raise HTTPException(status_code=403, detail=mensagem)

    _observar_seguro(ACAO_NEGARIA, usuario, tipo=tipo, exigido=exigido,
                     possui=possui,
                     municipio_id=exigido if tipo == "municipio" else None)
    return


# ---------------------------------------------------------------------------
# Dono da LINHA
# ---------------------------------------------------------------------------
# Identificador SQL valido do nosso schema. Tabela e coluna chegam como literal
# escrito no router (nunca de dado do usuario), mas interpolar nome em SQL sem
# validar e o tipo de atalho que fica no codigo e um dia recebe uma variavel.
_IDENTIFICADOR = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _identificador(nome: str, papel: str) -> str:
    valor = (nome or "").strip().lower()
    if not _IDENTIFICADOR.match(valor):
        # ValueError e nao 403: isto e erro de programacao num literal do
        # router, aparece na primeira chamada em desenvolvimento e nunca chega
        # a producao. Engolir em silencio desligaria a checagem sem avisar.
        raise ValueError(f"{papel} invalido para ensure_dono: {nome!r}")
    return valor


def exigir_tela(usuario, tela: str) -> None:
    """Gate NOVO de tela — este SIM respeita `AUTHZ_MODO`.

    Existe separado de `services.auth.ensure_tela` por um motivo que nao da para
    resolver em tempo de execucao: aquela funcao ja era chamada em ~128 pontos
    ANTES do Incremento 2, e cada um deles e uma trava que JA VALE hoje. Se o
    modo aviso valesse para ela, essas 128 negativas antigas parariam de negar
    durante a semana de observacao — o sistema ficaria MAIS ABERTO justamente no
    incremento que existe para fecha-lo, e o dono teria recebido o oposto do que
    foi prometido ("em modo aviso, comportamento identico ao de hoje").

    Regra pratica: gate que voce esta ACRESCENTANDO agora usa `exigir_tela`;
    checagem que ja existia continua em `ensure_tela` e continua negando."""
    permitidas = getattr(usuario, "allowed_telas", None)
    if permitidas is None:          # admin: passa, como sempre
        return
    if tela not in permitidas:
        negar(usuario, tipo="tela", exigido=tela, possui=permitidas,
              mensagem="Voce nao tem acesso a esta tela")


# ---------------------------------------------------------------------------
# PERMISSAO POR ACAO (Incremento 5)
# ---------------------------------------------------------------------------
def permissoes_de(usuario) -> frozenset:
    """O conjunto EFETIVO de permissoes deste usuario.

    Adaptador fino: le os fatos do objeto e entrega a decisao a funcao PURA
    `services/permissoes.py::permissoes_efetivas`. Nenhuma regra mora aqui de
    proposito — regra espalhada em adaptador e exatamente o que faz um
    `if role == 'admin'` reaparecer daqui a seis meses.

    `user.allowed_permissoes` e anexado por `services/auth.py::load_user_scopes`
    (None para super-admin, que a funcao pura ignora porque ja decide por
    `super_admin=True`).

    ⚠️ IMPORT LOCAL, e nao no topo: `services/auth.py` importa ESTE modulo no
    topo dele. Subir o import de la para ca fecharia o ciclo e quebraria o boot.
    """
    from services.auth import ehQuiosque, is_super_admin
    from services import permissoes as catalogo

    return catalogo.permissoes_efetivas(
        super_admin=is_super_admin(usuario),
        concedidas=getattr(usuario, "allowed_permissoes", None),
        # ⚠️ `somente_leitura` SAIU do calculo em 05/09/2026 com a trava de conta
        # (ver `services/auth.py`). Quem nao escreve agora e quem esta sem a
        # caixinha de escrita daquela tela — e isso ja esta em `concedidas`.
        quiosque=ehQuiosque(usuario),
        # `active` e NOT NULL com default true; `getattr` porque este modulo
        # tambem e chamado com objetos que nao sao o modelo completo (teste,
        # snapshot). Ausente = ativo, que e o que o objeto parcial representa.
        ativo=bool(getattr(usuario, "active", True)),
    )


def pode(usuario, permissao: str) -> bool:
    """"Este usuario pode X?" — SEM efeito nenhum: nao levanta, nao registra.

    E o que a LISTAGEM usa. O gate de uma listagem e o filtro, nao o 403: negar
    a tela inteira de quem tem escopo legitimo e o oposto do que este incremento
    quer (ver `routers/fns.py::municipios_pacta`). Serve tambem para a resposta
    dizer ao frontend quais botoes desenhar."""
    from services import permissoes as catalogo

    chave = catalogo.normalizar(permissao)
    return chave in permissoes_de(usuario)


def exigir(usuario, permissao: str) -> None:
    """A CHECAGEM de permissao por acao. Respeita `AUTHZ_MODO` como o resto:
    em `aviso` deixa passar e registra, em `bloqueio` levanta 403.

    Combina com o que ja existe em vez de substituir: a PERMISSAO diz O QUE a
    pessoa faz, o MUNICIPIO diz ONDE, e as duas valem juntas. Um endpoint de
    escrita escopado por municipio continua precisando das duas linhas:

        authz.exigir(current, "rm.excluir")
        await authz.ensure_dono(db, "rm_relatorios", "id", rid, current)

    Super-admin passa sempre — a funcao pura ja devolve o catalogo inteiro para
    ele, entao nao ha um `if super_admin` aqui para alguem copiar.

    ⚠️ Chave fora do catalogo levanta ValueError, e nao 403. E erro de
    PROGRAMACAO num literal do router (`authz.exigir(u, "rm.excluri")`), aparece
    na primeira chamada em desenvolvimento e nunca chega a producao. Tratada
    como "sem permissao" ela viraria um 403 permanente e silencioso: o endpoint
    negaria TODO MUNDO, inclusive o super-admin, e ninguem saberia por que."""
    from services import permissoes as catalogo

    chave = catalogo.normalizar(permissao)
    if chave not in catalogo.CATALOGO:
        raise ValueError(
            f"permissao desconhecida: {permissao!r} — nao esta em "
            "services/permissoes.py::CATALOGO")

    efetivas = permissoes_de(usuario)
    if chave in efetivas:
        return

    negar(usuario, tipo="permissao", exigido=chave, possui=efetivas,
          # Mensagem PROPRIA, e nao a de tela: quem le "Voce nao tem acesso a
          # esta tela" depois de clicar em Excluir procura o erro no lugar
          # errado — e o administrador vai conceder a tela inteira quando
          # faltava uma caixinha.
          mensagem="Voce nao tem permissao para esta acao")


def registrar_rota_sem_registro(usuario, caminho: str) -> None:
    """Uma requisicao esbarrou numa rota que subiu sem permissao declarada.

    NAO decide nada — quem barra e `services/registro_rotas.py`. Aqui so vira
    linha na trilha, para o defeito aparecer na Auditoria e nao so no log do
    container, que ninguem le."""
    _observar_seguro(ACAO_ROTA_SEM_REGISTRO, usuario, tipo="rota",
                     exigido=caminho)


def exigir_municipio(usuario, municipio_id: Any) -> None:
    """Gate NOVO de municipio — respeita `AUTHZ_MODO`. Ver `exigir_tela`.

    Pedido MALFORMADO (sem municipio, ou nao-numerico) continua negado nos dois
    modos: nao e permissao que falta, e nenhuma correcao de cadastro faz um
    pedido sem municipio virar valido. Deixa-lo passar trocaria um 403 honesto
    por um 500 (o None desce ate a consulta) ou por uma consulta sem filtro
    devolvendo o tenant inteiro."""
    permitidos = getattr(usuario, "allowed_municipio_ids", None)
    if permitidos is None:
        return
    if municipio_id is None:
        raise HTTPException(status_code=403, detail="Selecione um municipio permitido")
    try:
        mid = int(municipio_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=403, detail="Municipio invalido")
    if mid not in permitidos:
        negar(usuario, tipo="municipio", exigido=mid, possui=permitidos,
              mensagem="Voce nao tem acesso a este municipio")


async def ensure_dono(
    db: AsyncSession,
    tabela: str,
    coluna_id: str,
    id_do_registro: Any,
    usuario,
    *,
    coluna_municipio: str = "municipio_id",
) -> Optional[int]:
    """O municipio da LINHA, checado contra o escopo de quem pediu.

    E o que a permissao de VERBO nao resolve. `ensure_tela(user, "rm")` diz que
    a pessoa pode mexer em Relatorio de Monitoramento; nao diz nada sobre
    `DELETE /api/rm/{id}` com o id do relatorio de OUTRO municipio. Sem isto,
    quem tem a tela tem a tela do tenant inteiro.

    Assincrona e na SESSAO DO ENDPOINT de proposito: e leitura, e uma sessao
    nova so para um SELECT de uma coluna custaria uma conexao do pool por
    requisicao.

    Devolve o `municipio_id` da linha, ou None quando nao houve decisao —
    registro inexistente NAO vira 403 aqui: quem decide o 404 e o endpoint, que
    e o unico que sabe se "nao achei" significa "nao existe" ou "nao e seu".
    """
    tab = _identificador(tabela, "tabela")
    col_id = _identificador(coluna_id, "coluna_id")
    col_mun = _identificador(coluna_municipio, "coluna_municipio")

    if id_do_registro is None:
        return None

    try:
        # SAVEPOINT: se o SELECT falhar (tabela renomeada, id de tipo errado), o
        # erro fica contido e a transacao do endpoint continua utilizavel. Sem
        # ele, o Postgres aborta a transacao inteira e a proxima consulta do
        # endpoint quebraria com um erro sem relacao aparente.
        async with db.begin_nested():
            linha = (await db.execute(
                text(f"SELECT {col_mun} FROM {tab} WHERE {col_id} = :id LIMIT 1"),
                {"id": id_do_registro},
            )).first()
    except Exception:
        # Sem leitura nao ha decisao. Nao inventamos 403 (seria negativa nova,
        # que e o que este incremento existe para evitar) — e o endpoint vai
        # esbarrar no mesmo problema na consulta dele, em seguida.
        logger.exception("ensure_dono nao conseguiu ler %s.%s", tab, col_mun)
        return None

    if linha is None:
        return None

    municipio_id = linha[0]
    if municipio_id is None:
        # Linha sem municipio (a coluna e NULL em `documentos_gerados`, por
        # exemplo) nao tem dono, e "sem dono" nao e "de todo mundo" nem "de
        # ninguem" — e um buraco de modelagem. Registramos para ele aparecer na
        # semana de observacao em vez de continuar invisivel; a correcao e
        # tornar a coluna NOT NULL, e ai esta ramificacao morre sozinha.
        _observar_seguro(ACAO_SEM_DONO, usuario, tipo="linha",
                         exigido=f"{tab}#{id_do_registro}")
        return None

    # `exigir_municipio`, e NAO `services.auth.ensure_municipio_access`: esta
    # checagem do dono da LINHA nao existia em lugar nenhum antes do Incremento
    # 2 — todos os `ensure_dono(...)` do sistema foram escritos agora. Gate novo
    # respeita `AUTHZ_MODO`; usar a funcao antiga faria o `DELETE /api/rm/{id}`
    # de outro municipio passar a levar 403 ja na semana de observacao, que e
    # exatamente o apagao que este modulo existe para evitar.
    # Mais duas razoes, alem da de cima, para NAO ser `ensure_municipio_access`
    # aqui: (1) o cabecalho deste modulo promete que "em modo aviso nenhuma
    # excecao nova sai daqui", e a funcao antiga levanta 403 nos dois modos;
    # (2) o `_ORIGEM` abaixo so existe para carimbar a linha da trilha, e linha
    # da trilha so nasce dentro de `negar` — com a funcao antiga o carimbo nunca
    # seria lido, porque negativa nenhuma passaria por la.
    ficha = _ORIGEM.set({"tabela": tab, "coluna": col_id,
                         "id": str(id_do_registro)[:100]})
    try:
        exigir_municipio(usuario, municipio_id)
    finally:
        _ORIGEM.reset(ficha)
    return municipio_id


# ---------------------------------------------------------------------------
# ⭐ ALCANCE POR LINHA (Incremento 6) — "so os registros que ele criou"
# ---------------------------------------------------------------------------
# ⚠️ ISTO NAO E `ensure_dono`, E AS DUAS VALEM JUNTAS. Sao perguntas diferentes
# sobre a MESMA linha, e confundi-las deixaria um buraco de cada lado:
#
#     ensure_dono            -> esta linha e de um MUNICIPIO que ele alcanca?
#     exigir_dono_da_linha   -> esta linha foi criada POR ELE?
#
# A primeira e sobre territorio (e vale para leitura tambem); a segunda e a
# regra que o dono pediu agora, e vale SO PARA ESCRITA (editar e excluir) —
# decisao dele, ja tomada: a pessoa continua VENDO a lista inteira do municipio,
# porque filtrar a leitura faria dois servidores do mesmo setor deixarem de ver
# o trabalho um do outro e sumiria com o registro de quem saiu da prefeitura.
#
# O endpoint de escrita de um modulo escopavel usa AS TRES coisas:
#
#     authz.exigir(current, "gestao.editar")                        # o QUE
#     await authz.ensure_dono(db, "gestao_anotacoes", "id", i, u)   # o ONDE
#     await authz.exigir_dono_da_linha(db, "gestao", i, u)          # de QUEM
def escopo_de(usuario, recurso) -> str:
    """O alcance vigente deste usuario NAQUELE modulo. Nunca levanta.

    Devolve sempre `todos` ou `proprios`; qualquer outra coisa (recurso que nao
    aceita alcance, valor torto no banco, usuario sem o atributo carregado) cai
    em `todos`, que e o valor que NAO restringe ninguem — ver
    `services/permissoes.py::normalizar_escopo` para o porque do fail-open."""
    from services.auth import is_super_admin
    from services import permissoes as catalogo

    chave = catalogo.normalizar(recurso)
    if not catalogo.escopavel(chave):
        return catalogo.ESCOPO_TODOS
    # "Esses tem tudo, fazem tudo no sistema... eles sao tipo ROOT" — a regra do
    # dono, e a mesma razao de `permissoes_efetivas` nem olhar as caixinhas do
    # super-admin: nao pode existir jeito de um administrador do cliente
    # restringir o dono da plataforma.
    if is_super_admin(usuario):
        return catalogo.ESCOPO_TODOS
    escopos = getattr(usuario, "allowed_escopos", None) or {}
    return catalogo.normalizar_escopo(escopos.get(chave))


def _mesmo_criador(usuario, criado_por) -> bool:
    """O id de quem pediu e o id de quem criou a linha sao o mesmo?

    Comparacao por INTEIRO e nao por identidade de objeto: `criado_por` vem do
    banco (pode chegar como Decimal ou str conforme o driver) e `usuario.id` vem
    do ORM. Comparar `==` cru faria `'7' != 7` e negaria o autor do proprio
    registro — o defeito mais embaracoso que esta funcao poderia ter."""
    meu = getattr(usuario, "id", None)
    if meu is None or criado_por is None:
        return False
    try:
        return int(meu) == int(criado_por)
    except (TypeError, ValueError):
        return False


def pode_escrever_na_linha(usuario, recurso, criado_por) -> bool:
    """"Este usuario pode ALTERAR esta linha?" — SEM efeito nenhum: nao levanta,
    nao registra, nao toca no banco.

    E a versao de LISTAGEM da checagem abaixo, e existe para a resposta da API
    poder dizer `pode_editar` item a item (o pedido literal do dono: "o botao
    some ou fica bloqueado"). Recebe o `criado_por` que a consulta da lista JA
    trouxe, entao custa zero consulta a mais.

    ⚠️ So responde pelo ALCANCE. A permissao de verbo (`gestao.editar`) e outra
    pergunta e tem `pode()` para ela — quem monta a resposta combina as duas
    (ver `pode_editar_item`)."""
    from services import permissoes as catalogo

    if escopo_de(usuario, recurso) == catalogo.ESCOPO_TODOS:
        return True
    # Linha sem criador conhecido: PASSA. Ver a decisao completa em
    # `exigir_dono_da_linha` — o front tem de desenhar o botao que o servidor
    # vai deixar clicar, senao a tela e o servidor discordam.
    if criado_por is None:
        return True
    return _mesmo_criador(usuario, criado_por)


def pode_editar_item(usuario, recurso, verbo, criado_por) -> bool:
    """O que a LISTA devolve por item: `pode_editar` / `pode_excluir`.

    Combina as duas perguntas — a permissao de verbo E o alcance — mas de
    formas deliberadamente diferentes, e a assimetria e o ponto:

      * O ALCANCE vale SEMPRE, nos dois modos de `AUTHZ_MODO`. Ele nunca e
        retroativo: nasce `todos` para todo mundo e so vira `proprios` quando um
        administrador marca aquele radio, para aquela pessoa, naquele modulo.
        Nao ha comportamento antigo para preservar, entao esconder o botao
        obedece a configuracao no instante em que ela e salva — que e o que o
        dono pediu ver acontecer.

      * A PERMISSAO DE VERBO so entra em modo BLOQUEIO. Em modo aviso o servidor
        NAO barra quem nao tem `gestao.editar` (registra e deixa passar), e uma
        conta que trabalha hoje justamente porque nunca houve gate continua
        trabalhando. Se a lista escondesse o botao dela agora, ESTA peca teria
        provocado o apagao que o modo aviso inteiro existe para evitar — e sem
        nem mudar o servidor, o que e a pior forma de quebrar: ninguem
        procuraria a causa numa resposta de listagem.

    Ou seja: o botao so some por um motivo que o servidor JA estaria barrando
    hoje, ou pelo alcance que o administrador acabou de configurar."""
    from services import permissoes as catalogo

    chave = f"{catalogo.normalizar(recurso)}.{catalogo.normalizar(verbo)}"
    if modo() == MODO_BLOQUEIO and not pode(usuario, chave):
        return False
    return pode_escrever_na_linha(usuario, recurso, criado_por)


async def exigir_dono_da_linha(
    db: AsyncSession,
    recurso: str,
    id_do_registro: Any,
    usuario,
    *,
    coluna_id: str = "id",
) -> Any:
    """⭐ A CHECAGEM: "esta linha foi criada por voce?".

    Respeita `AUTHZ_MODO` como todo o resto do modulo — passa por `negar`, entao
    em modo aviso registra `authz.negaria` e DEIXA PASSAR; em bloqueio levanta
    403. Devolve o `criado_por` lido, ou None quando nao houve decisao.

    ⚠️ A TABELA NAO E PARAMETRO, e a ausencia e deliberada. Ela sai de
    `services/permissoes.py::ESCOPO_RECURSOS` a partir do `recurso`, que e a
    mesma chave que a tela configura, que a API grava e que a FK do banco valida.
    Recebe-la do router criaria um segundo lugar onde o nome da tabela e escrito:
    o dia em que os dois divergissem, esta funcao leria a coluna errada — ou
    leria a tabela certa de um recurso que o administrador configurou em outra —
    e a checagem passaria a nao checar, em silencio. O `recurso` sozinho amarra
    tela, banco e consulta na mesma chave.

    ⚠️⚠️ A DECISAO DIFICIL: `criado_por` NULO **PASSA** (e vira linha na trilha).

    Linha sem criador conhecido existe por dois motivos, e nenhum deles e culpa
    de quem esta editando agora: (1) e anterior a coluna `criado_por` — as tres
    tabelas nasceram com ela anulavel e sem backfill; (2) a conta de quem criou
    foi EXCLUIDA, e a chave estrangeira zera a coluna (`ON DELETE SET NULL`, ver
    routers/control.py::_null_fk). Negar essas linhas seria:

      * RETROATIVO num sistema em que a restricao nao e. O alcance e uma regra
        que passa a valer daqui para frente, para quem o administrador escolher;
        ele nao pode confiscar anos de trabalho que ninguem sabia que precisava
        de dono registrado. Na pratica, o servidor de Monte Siao nao
        conseguiria corrigir um erro de digitacao numa anotacao de 2024, e nao
        haveria nada que ele ou o administrador pudessem fazer pela tela.

      * EXATAMENTE O QUE O DONO JA RECUSOU, uma camada abaixo. Ele vetou
        filtrar a LEITURA porque "o registro de quem saiu da prefeitura
        sumiria". Trancar a edicao do registro de quem saiu da prefeitura e o
        mesmo dano com outro nome: a conta foi excluida, entao a linha JA esta
        com `criado_por` nulo, e ela ficaria congelada para sempre.

    O que segura o preco de deixar passar:

      1. Nao e porta aberta a estranho. Para chegar aqui a pessoa ja passou pela
         permissao de verbo, pela tela e pelo municipio da linha — o alcance e a
         quarta trava, nao a unica.
      2. A passagem e VISIVEL: cada uma vira `authz.sem_criador` na trilha, com
         a tabela e o id. O buraco tem tamanho medivel, coisa que a ausencia de
         criador nunca teve.
      3. A correcao mora no DADO, nao aqui: preenchido o `criado_por` (ou tornada
         a coluna obrigatoria), esta ramificacao morre sozinha — mesmo desenho
         de `ensure_dono` com municipio nulo.

    A alternativa "negar" nao e mais segura, e mais BARULHENTA: ela troca um
    risco pequeno e observavel por um apagao certo no instante em que um
    administrador marca um radio — e ninguem ligaria as duas coisas.
    """
    from services import permissoes as catalogo

    ficha_recurso = catalogo.descrever_recurso_escopavel(recurso)
    if ficha_recurso is None:
        # ValueError e nao 403, pelo mesmo motivo de `exigir` com chave fora do
        # catalogo: e erro de programacao num literal do router, aparece na
        # primeira chamada em desenvolvimento e nunca chega a producao. Tratado
        # como "sem permissao" viraria um 403 permanente e silencioso.
        raise ValueError(
            f"recurso sem alcance por linha: {recurso!r} — nao esta em "
            "services/permissoes.py::ESCOPO_RECURSOS")

    if escopo_de(usuario, ficha_recurso.recurso) == catalogo.ESCOPO_TODOS:
        # O caminho de todo mundo, hoje: nenhuma consulta a mais. O custo do
        # incremento so aparece para quem foi deliberadamente restringido.
        return None

    if id_do_registro is None:
        return None

    tab = _identificador(ficha_recurso.tabela, "tabela")
    col_dono = _identificador(ficha_recurso.coluna_dono, "coluna_dono")
    col_id = _identificador(coluna_id, "coluna_id")

    try:
        # SAVEPOINT pelo mesmo motivo de `ensure_dono`: erro contido, transacao
        # do endpoint continua utilizavel.
        async with db.begin_nested():
            linha = (await db.execute(
                text(f"SELECT {col_dono} FROM {tab} WHERE {col_id} = :id LIMIT 1"),
                {"id": id_do_registro},
            )).first()
    except Exception:
        # Sem leitura nao ha decisao. Nao inventamos 403 — o endpoint vai
        # esbarrar no mesmo problema na consulta dele, em seguida.
        logger.exception("exigir_dono_da_linha nao conseguiu ler %s.%s", tab,
                         col_dono)
        return None

    if linha is None:
        # Registro inexistente NAO vira 403 aqui: quem decide o 404 e o endpoint,
        # que e o unico que sabe se "nao achei" significa "nao existe" ou "nao e
        # seu". Mesma regra de `ensure_dono`.
        return None

    criado_por = linha[0]
    if criado_por is None:
        _observar_seguro(ACAO_SEM_CRIADOR, usuario, tipo="linha",
                         exigido=f"{tab}#{id_do_registro}",
                         possui=f"alcance={catalogo.ESCOPO_PROPRIOS}")
        return None

    if _mesmo_criador(usuario, criado_por):
        return criado_por

    ficha = _ORIGEM.set({"recurso": ficha_recurso.recurso, "tabela": tab,
                         "coluna": col_dono, "id": str(id_do_registro)[:100],
                         "criado_por": criado_por,
                         "alcance": catalogo.ESCOPO_PROPRIOS})
    try:
        negar(usuario, tipo="linha_propria",
              exigido=f"{tab}#{id_do_registro}",
              possui={"usuario_id": getattr(usuario, "id", None),
                      "criado_por": criado_por},
              # Mensagem PROPRIA, e nao a de permissao: quem le "Voce nao tem
              # permissao para esta acao" depois de clicar em Editar vai pedir ao
              # administrador a caixinha «Editar» — que ele JA TEM. O que falta
              # nao e a caixinha, e o alcance.
              mensagem="Voce so pode alterar os registros que voce mesmo criou")
    finally:
        _ORIGEM.reset(ficha)
    return criado_por
