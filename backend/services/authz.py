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

_MODOS_DESCONHECIDOS: set = set()


def modo() -> str:
    """Modo vigente. Lido a cada chamada (nao no import) para o teste poder
    variar o ambiente e para a env valer sem rebuild da imagem — mesma
    convencao de `services/net.py::proxies_confiaveis`.

    Fail-OPEN de proposito, e e o unico lugar do sistema onde isso e a escolha
    certa: aqui "fechar por engano" e o apagao de segunda-feira que este modulo
    inteiro existe para evitar. Digitar `AUTHZ_MODO=bloqueiop` nao pode LIGAR a
    trava; tem de deixa-la como estava."""
    bruto = (os.getenv("AUTHZ_MODO", "") or "").strip().lower()
    if bruto == MODO_BLOQUEIO:
        return MODO_BLOQUEIO
    if bruto and bruto != MODO_AVISO and bruto not in _MODOS_DESCONHECIDOS:
        # Uma vez por valor: env digitada errada nao pode virar log por request.
        _MODOS_DESCONHECIDOS.add(bruto)
        logger.warning(
            "AUTHZ_MODO=%r nao e reconhecido; seguindo em %r", bruto, MODO_AVISO)
    return MODO_AVISO


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
