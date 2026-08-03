"""
Trilha de auditoria: quem fez o que, quando, de onde, em que sessao, sobre qual
municipio e com que resultado.

DUAS PORTAS, e a diferenca entre elas e uma decisao de risco, nao de estilo:

    registrar()          MELHOR ESFORCO. Se a gravacao falhar, a falha e
                         registrada no log da aplicacao e a acao segue. Serve a
                         navegacao, ao login e ao volume do dia a dia: derrubar
                         o sistema porque nao deu para anotar uma troca de tela
                         trocaria um problema de auditoria por uma queda.

    registrar_critico()  PROPAGA a falha, na mesma transacao da acao. Serve ao
                         punhado de atos em que a trilha E a autorizacao: se nao
                         deu para anotar que fulano revelou a senha do gov.br,
                         fulano nao revela. Chame ANTES de devolver o segredo.

`registrar()` promove sozinha para o modo critico as acoes de ACOES_CRITICAS —
fail-closed de proposito: esquecer de escolher a porta certa nao pode ser o que
apaga o rastro de uma revelacao de senha.

TRES GARANTIAS QUE ESTE MODULO DA:

1. IP REAL. Vem de `services/net.py`, que conta o X-Forwarded-For de TRAS para
   frente. O que o cliente manda no comeco do cabecalho e forjavel; o IP que o
   Traefik ACRESCENTA no fim e o que vale.

2. SEGREDO NUNCA ENTRA — em `details`, `valor_antes` e `valor_depois`. Os tres
   passam por `sanitizar()`: chave com cara de segredo tem o VALOR trocado por
   "[oculto]", recursivamente. E requisito de LGPD — uma trilha que guarda senha
   vira, ela propria, o vazamento que deveria denunciar.

   ⚠️ O ALCANCE DESSA GARANTIA TERMINA AI, e e importante nao acreditar demais
   nela: `target_id` e `alvo_nome` sao gravados como o chamador mandou. Quem
   escrever `target_id=<slug do link publico>` ou `alvo_nome=<senha>` poe isso na
   trilha, e a trilha e exportada. Antes de passar um identificador, pergunte se
   ele e uma CREDENCIAL — se for, mande um derivado (ver `_sessao`, que grava
   hash do jti e nao o jti). `http_path` tem tratamento proprio, abaixo.

3. MINIMIZACAO. De valor_antes/valor_depois so sobrevivem os campos que
   REALMENTE mudaram (LGPD art. 6, III: so o necessario para a finalidade). E
   `http_path` guarda o MOLDE da rota (`/api/users/{email}`), nao o caminho
   preenchido — ver `_rota`.

A imutabilidade NAO mora aqui, e nao poderia: ela e do BANCO
(`migrations/add_auditoria_imutavel.sql`) — gatilho append-only que recusa
UPDATE/DELETE/TRUNCATE em audit_log e cadeia de hash calculada dentro do
Postgres, justamente para que nem este modulo possa escolher o valor do hash.
O que este arquivo faz e nao atrapalhar: grava por INSERT puro, nunca UPDATE nem
DELETE, e nao manda `hash`/`hash_anterior` (o gatilho os calcula).
"""
import hashlib
import logging
import math
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.audit import AuditLog

logger = logging.getLogger("audit")


# ---------------------------------------------------------------------------
# IP do cliente
# ---------------------------------------------------------------------------
from services.net import client_ip


def _ip(request: Optional[Request]) -> Optional[str]:
    """IP real, sempre por `services/net.py`.

    Sem calculo proprio aqui de proposito: o valor certo depende de quantos
    proxies confiaveis existem na frente da API, e uma segunda implementacao
    divergiria da primeira no dia em que esse numero mudasse — com a trilha
    jurando um IP e a allowlist do control-plane outro.

    `client_ip` devolve None quando nao da para afirmar qual e o IP; gravamos o
    None. "Desconhecido" e uma resposta honesta, o IP do proxy no lugar do IP do
    usuario e uma resposta falsa."""
    if request is None:
        return None
    try:
        bruto = client_ip(request)
    except Exception:
        # Auditoria nao cai por causa de cabecalho malformado — a linha vai sem IP.
        logger.warning("Falha calculando IP do cliente", exc_info=True)
        return None
    return str(bruto)[:64] if bruto else None


# ---------------------------------------------------------------------------
# Sanitizacao (LGPD) — o valor de chave sensivel nunca chega ao banco
# ---------------------------------------------------------------------------
# Casamento por SUBSTRING, e nao por igualdade: "password" pega tambem
# "password_hash" e "new_password"; "token" pega "access_token" e "token_raw".
# Fail-closed — um falso positivo custa uma informacao a menos na tela, um falso
# negativo custa uma senha em texto claro dentro da trilha de auditoria.
CHAVES_SENSIVEIS = (
    "senha", "password", "passwd", "pwd",
    "token", "cookie", "secret", "segredo", "hash",
    "authorization", "credential", "credencial",
    "api_key", "apikey", "private_key", "jwt", "bearer", "csrf",
)

# Excecoes NOMINAIS: chaves que casam com a lista acima mas carregam METRICA
# sobre o segredo, nunca o segredo. Duas travas — precisa estar nesta lista E
# ter valor numerico/booleano. Um segredo nunca e um bool nem um tamanho, entao
# a segunda trava sozinha ja barra `{"token": "eyJhbGciOi..."}` se alguem
# acrescentar um nome aqui por engano.
CHAVES_METRICA = frozenset({
    "cookie_size",        # routers/session_capture.py: tamanho do cookie capturado
    "senha_changed",      # routers/cofre.py: a senha foi trocada? (bool)
    "password_changed",
    "token_expira_dias",
})

REDIGIDO = "[oculto]"

_MAX_TEXTO = 2000    # um texto maior que isso e anexo, nao contexto de auditoria
_MAX_ITENS = 200     # teto por dict/lista: payload gigante nao vira linha gigante
_MAX_PROF = 6        # teto de profundidade: barra recursao e JSON aninhado hostil


def _achatar(chave: str) -> str:
    """Reduz a chave ao miolo alfanumerico, em minusculas.

    ⚠️ SEM ISTO A LISTA NEGRA TEM BURACO POR GRAFIA. A comparacao e por
    substring, entao `private_key` (como esta na lista) NAO casa com
    `privateKey`: em minusculas isso vira `privatekey`, sem o sublinhado. Uma
    chave privada em camelCase — a grafia natural de quem escreve JSON de
    JavaScript — entrava inteira numa trilha que sera IMUTAVEL. Medido: o
    ataque ao sanitizador passou `{"privateKey": "<jwt>"}` e o valor saiu em
    claro, enquanto `apiKey` era barrada apenas porque a lista, por sorte,
    tinha as duas grafias.

    Achatando os dois lados, `private_key`, `privateKey`, `private-key` e
    `PRIVATE KEY` viram todas `privatekey` e casam com uma entrada so."""
    return "".join(ch for ch in str(chave).lower() if ch.isalnum())


# Formas achatadas, calculadas uma vez.
_MARCAS_ACHATADAS = tuple(sorted({_achatar(m) for m in CHAVES_SENSIVEIS}))
_METRICA_ACHATADA = frozenset(_achatar(m) for m in CHAVES_METRICA)


def _sensivel(chave: str) -> bool:
    c = _achatar(chave)
    return any(marca in c for marca in _MARCAS_ACHATADAS)


def _escalar(v: Any) -> Any:
    """Converte folha para algo que o JSONB aceite SEM perder o sentido.

    Sem isto, um `datetime` ou um `Decimal` em `details` estoura na serializacao
    — e numa gravacao critica esse estouro derruba a acao inteira."""
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        # JSONB nao aceita NaN/Infinity; viraria erro de INSERT.
        return v if math.isfinite(v) else str(v)
    if isinstance(v, str):
        return v if len(v) <= _MAX_TEXTO else v[:_MAX_TEXTO] + "...[truncado]"
    if isinstance(v, Decimal):
        # str e nao float: dinheiro nesta casa nao perde centavo por conversao.
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray)):
        return f"[{len(v)} bytes]"   # conteudo binario nao vira trilha
    return _escalar(str(v))


def sanitizar(valor: Any, _prof: int = 0) -> Any:
    """Poda segredo de qualquer estrutura, recursivamente (dict e lista).

    Onde corta, DEIXA MARCA. Corte silencioso e pior aqui do que em qualquer
    outro lugar do sistema: quem le a trilha nao tem como saber que o que esta
    vendo esta incompleto. Uma lista de 300 municipios cortada calada em 200
    faria o auditor concluir que o admin RETIROU 100 municipios de alguem — a
    trilha estaria inventando um ato que ninguem praticou."""
    if _prof > _MAX_PROF:
        return "[profundo demais]"
    if isinstance(valor, dict):
        saida: dict = {}
        itens = list(valor.items())
        for k, v in itens[:_MAX_ITENS]:
            chave = str(k)
            # A excecao tambem casa achatada, pelo mesmo motivo da lista negra:
            # senao `cookieSize` seria redigida e `cookie_size` nao, para o
            # mesmo dado.
            if _sensivel(chave) and not (
                _achatar(chave) in _METRICA_ACHATADA and isinstance(v, (bool, int, float))
            ):
                saida[chave] = REDIGIDO
            else:
                saida[chave] = sanitizar(v, _prof + 1)
        if len(itens) > _MAX_ITENS:
            saida["[truncado]"] = f"+{len(itens) - _MAX_ITENS} campos nao registrados"
        return saida
    if isinstance(valor, (list, tuple, set, frozenset)):
        itens_l = list(valor)
        saida_l = [sanitizar(v, _prof + 1) for v in itens_l[:_MAX_ITENS]]
        if len(itens_l) > _MAX_ITENS:
            saida_l.append(f"[+{len(itens_l) - _MAX_ITENS} itens nao registrados]")
        return saida_l
    return _escalar(valor)


# ---------------------------------------------------------------------------
# Minimizacao: so o que mudou
# ---------------------------------------------------------------------------
def _normalizar(v: Any) -> Any:
    """Forma canonica para COMPARAR. Lista de permissao vem do banco em ordem
    arbitraria: sem isto, ["bi","cofre"] contra ["cofre","bi"] seria registrado
    como alteracao de permissao que ninguem fez — ruido que ensina o auditor a
    ignorar a trilha."""
    if isinstance(v, (list, tuple, set, frozenset)):
        itens = [_normalizar(x) for x in v]
        try:
            return sorted(itens, key=lambda x: (str(type(x)), str(x)))
        except Exception:
            return itens
    if isinstance(v, dict):
        # Chaves ORDENADAS, e nao so convertidas para str: a ordenacao da lista
        # acima usa `str(x)` como criterio, e `str()` de dict depende da ordem de
        # insercao. Sem isto, duas listas com os MESMOS dicionarios em ordem
        # diferente nao se alinham no sort e viram "mudanca" — a mesma classe de
        # ruido que a ordenacao existe para eliminar.
        return {str(k): _normalizar(x) for k, x in sorted(v.items(), key=lambda kv: str(kv[0]))}
    return v


def campos_alterados(antes: Optional[dict], depois: Optional[dict]) -> tuple[Optional[dict], Optional[dict]]:
    """Reduz o par (antes, depois) aos campos que REALMENTE mudaram.

    Passe SNAPSHOTS COMPLETOS dos dois lados. Campo ausente de um dos lados
    conta como mudanca (de/para ausente) — entao nao mande um `dict` de PATCH
    com so o que veio no corpo: os campos nao enviados apareceriam como se
    tivessem sido apagados."""
    if not isinstance(antes, dict) or not isinstance(depois, dict):
        return (antes if isinstance(antes, dict) else None,
                depois if isinstance(depois, dict) else None)
    a: dict = {}
    d: dict = {}
    for k in sorted(set(antes) | set(depois), key=str):
        va, vd = antes.get(k), depois.get(k)
        if _normalizar(va) == _normalizar(vd):
            continue
        a[str(k)] = va
        d[str(k)] = vd
    return (a or None, d or None)


# ---------------------------------------------------------------------------
# Acoes criticas
# ---------------------------------------------------------------------------
# CRITICO = a trilha e pre-condicao do ato. Sao os casos em que o registro vem
# ANTES do efeito, entao propagar a falha realmente IMPEDE o ato:
#
#   *.reveal    revelar senha do Cofre (tela do cliente e control-plane). O log
#               e gravado antes de devolver o texto claro; sem log, sem senha.
#   control.sso.mint  emissao de sessao para alguem da Alavank dentro do tenant
#               do cliente: e a porta de entrada externa.
#
# NAO sao criticos, e a razao importa:
#
#   login/logout  a falha de gravacao aqui quase sempre significa banco fora do
#                 ar — e sem banco o login ja nao acontece. Fazer a auditoria
#                 derrubar a autenticacao transformaria soluco de banco em
#                 prefeitura sem acesso, sem ganhar rastro nenhum.
#   nav.*         navegacao e volume; perder uma linha nao muda conclusao.
#   export.*      NAO e promovido em bloco, e isso e uma correcao consciente: a
#                 promocao automatica derrubava, em silencio, a decisao ESCRITA
#                 em quatro routers (export_pdf, rm, documentos, gestao), todos
#                 argumentando a mesma coisa — o PDF e leitura do que o usuario
#                 ja tem na tela, entao bloquear o download por falha de trilha
#                 nao impede exfiltracao nenhuma (ele fotografa a tela) e so
#                 quebra o trabalho de quem nao fez nada de errado. Uma rede de
#                 seguranca que anula uma escolha deliberada e documentada nao e
#                 rede de seguranca, e politica escondida. Exportacao que PRECISA
#                 ser fail-closed chama `registrar_critico` no nome — e o que a
#                 exportacao da PROPRIA trilha ja faz (routers/auditoria.py).
#                 Registrar toda exportacao continua valendo; o que mudou e so o
#                 que acontece quando o INSERT falha.
#   escritas ja COMMITADAS (cofre.create/update/delete, user.*) — hoje essas
#                 chamadas acontecem DEPOIS do commit da acao. Propagar ali nao
#                 desfaria nada: so devolveria 500 para uma alteracao que ja
#                 aconteceu, e o operador repetiria, duplicando o registro.
#                 O certo e mover a chamada para ANTES do commit (commit=False,
#                 a linha entra na mesma transacao) e so entao promove-las —
#                 esta na lista de follow-up do incremento.
ACOES_CRITICAS = frozenset({
    "control.sso.mint",
})


def eh_critica(action: str) -> bool:
    a = (action or "").lower()
    return a in ACOES_CRITICAS or a.endswith(".reveal")


# ---------------------------------------------------------------------------
# Contexto extraido do Request
# ---------------------------------------------------------------------------
RESULTADOS = ("sucesso", "negado", "erro")

_MARCAS_NEGADO = (".fail", ".falha", ".negado", ".denied", ".bloqueado",
                  ".unauthorized", ".forbidden", "disabled_user")
_MARCAS_ERRO = (".erro", ".error", ".exception")


def _resultado(action: str, informado: Optional[str]) -> str:
    """Normaliza o resultado. Valor desconhecido nao e gravado como veio (a
    coluna tem vocabulario fechado): cai na deducao pela acao."""
    if informado:
        r = str(informado).strip().lower()
        if r in RESULTADOS:
            return r
        if r in ("ok", "success", "sucesso!"):
            return "sucesso"
        if r in ("fail", "failed", "denied", "403", "401"):
            return "negado"
        if r in ("error", "500", "exception"):
            return "erro"
    a = (action or "").lower()
    if any(m in a for m in _MARCAS_NEGADO):
        return "negado"
    if any(m in a for m in _MARCAS_ERRO):
        return "erro"
    return "sucesso"


def _inteiro(v: Any) -> Optional[int]:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _municipio(request: Optional[Request], explicito: Any, details: Optional[dict]) -> Optional[int]:
    """Descobre o municipio do ato. A ordem vai do mais confiavel (o chamador
    disse) para o mais circunstancial (estava na URL): quem escreveu o endpoint
    sabe o recorte melhor que a query string."""
    candidatos = [explicito]
    if request is not None:
        candidatos.append(getattr(request.state, "municipio_id", None))
        try:
            candidatos.append(request.path_params.get("municipio_id"))
            candidatos.append(request.query_params.get("municipio_id"))
        except Exception:
            pass
    if isinstance(details, dict):
        candidatos.append(details.get("municipio_id"))
    for c in candidatos:
        mid = _inteiro(c)
        if mid is not None:
            return mid
    return None


def _claims_sessao(tok: str) -> dict:
    """Le os claims de um access token PARA AGRUPAR, nao para autorizar.

    Nao usa `services.auth.decode_access` de proposito, e o motivo e concreto:
    aquele decode recusa token REVOGADO — e o logout revoga o proprio access
    ANTES de registrar o evento (routers/auth.py: `revoke_jti` e so depois
    `registrar(action="logout")`). Com ele, justamente o evento que FECHA a
    sessao seria o unico a sair sem `sessao_id`: a trilha mostraria a entrada e
    os atos agrupados, e a saida solta, como se o usuario nunca tivesse saido.

    O que fica de fora e SO a lista de revogacao. Assinatura, emissor, validade e
    `typ` continuam verificados — sem a assinatura, qualquer um mandaria um
    Authorization forjado e escolheria em qual sessao seus atos aparecem, que e
    envenenar a prova. Reaproveita o `settings` de services.auth (mesmo objeto,
    mesmo segredo): duas leituras de configuracao divergiriam no dia em que o
    algoritmo mudasse."""
    import jwt as pyjwt
    from services.auth import settings as _auth_settings

    dados = pyjwt.decode(
        tok,
        _auth_settings.JWT_SECRET,
        algorithms=[_auth_settings.JWT_ALGORITHM],
        issuer="pactha-api",
        options={"require": ["exp", "iat", "jti", "iss"]},
    )
    if dados.get("typ") != "access":
        raise ValueError("token que nao e de acesso nao define sessao de trabalho")
    return dados


def _sessao(request: Optional[Request]) -> tuple[Optional[str], Optional[datetime]]:
    """Identifica a SESSAO de trabalho, para agrupar "entrou as 9h12 e ate as
    9h40 fez isto e aquilo".

    Sai do proprio token ja autenticado, nunca de cabecalho mandado pelo cliente
    — sessao que o navegador escolhe nao serve de evidencia.

    Grava um HASH do identificador: o `jti` e a chave usada na revogacao, e nao
    ha motivo para a trilha (que muita gente le e que sera exportada) carregar
    identificador de token vivo. Hash curto agrupa igual e nao serve de credencial.

    Enquanto o access token nao tiver um claim de sessao proprio, a "sessao" e a
    vida do token (~60 min) e `sessao_inicio` e a emissao dele — o refresh abre
    uma sessao nova na trilha. Se um dia o token passar a carregar `sid`
    atravessando o refresh, ele passa a mandar aqui sem mudar mais nada.

    BURACO CONHECIDO, do lado de quem chama: em `login.success` e `sso.login` o
    token acabou de ser criado e ainda esta na RESPOSTA — a request nao tem
    cookie nenhum, entao esses dois eventos saem com `sessao_id` nulo e a sessao
    so passa a agrupar a partir do segundo ato. Fechar isso e uma linha em
    routers/auth.py: apos `create_access_token`, `request.state.sessao_id = ...`
    (e `request.state.sessao_inicio`), que e o atalho lido logo abaixo."""
    if request is None:
        return None, None
    try:
        forcado = getattr(request.state, "sessao_id", None)
        if forcado:
            return str(forcado)[:64], getattr(request.state, "sessao_inicio", None)

        from services.auth import COOKIE_NAME_ACCESS

        tok = request.cookies.get(COOKIE_NAME_ACCESS)
        if not tok:
            autorizacao = request.headers.get("authorization", "")
            if autorizacao.lower().startswith("bearer "):
                tok = autorizacao[7:].strip()
        if not tok:
            return None, None

        dados = _claims_sessao(tok)
        bruto = dados.get("sid") or dados.get("jti")
        sid = hashlib.sha256(str(bruto).encode("utf-8")).hexdigest()[:32] if bruto else None
        iat = dados.get("iat")
        inicio = datetime.fromtimestamp(int(iat), timezone.utc) if iat else None
        return sid, inicio
    except Exception:
        # Token expirado/ausente/invalido: o ato continua auditavel, so nao da
        # para amarra-lo a uma sessao. Nunca deixar isso derrubar a gravacao.
        return None, None


def _rota(request: Optional[Request]) -> Optional[str]:
    """Caminho da rota, preferindo o MOLDE (`/api/users/{email}`) ao caminho
    preenchido (`/api/users/joao@montesiao.mg.gov.br`).

    A query string ja ficava de fora porque parametro de busca carrega CPF, nome
    e e-mail digitados. O caminho tem exatamente o mesmo problema, e pior: alem
    do e-mail de pessoa real em `/control/users/{email}`, ha rota cujo parametro
    E UMA CREDENCIAL VIVA — o slug do link publico do Painel
    (`/api/bi/tela-links/{slug}`; routers/bi.py diz, com todas as letras, "o slug
    e o segredo"). Guardar o caminho preenchido colocaria esse segredo dentro da
    trilha, que e o objeto que mais circula: ela e lida por admin e EXPORTADA
    para PDF e Excel.

    O molde nao perde informacao de auditoria: QUEM esta em `user_email`, SOBRE
    QUEM esta em `target_id`/`alvo_nome`, e o que o caminho acrescenta e a rota.

    Fallback para o caminho literal quando nao ha rota casada (404, chamada fora
    do roteador). Nesses casos nao ha acao de negocio a registrar, entao o
    fallback nao e por onde um segredo entra na pratica."""
    if request is None:
        return None
    try:
        rota = request.scope.get("route")
        molde = getattr(rota, "path", None)
        if molde:
            # root_path: quando a API sobe montada sob um prefixo, `route.path` e
            # relativo a ele e sozinho nao identifica a rota real.
            return f"{request.scope.get('root_path', '')}{molde}"
    except Exception:
        pass
    return getattr(getattr(request, "url", None), "path", None)


def _corta(v: Any, n: int) -> Optional[str]:
    if v is None:
        return None
    s = str(v)
    return s[:n] if s else None


def _montar(
    *,
    action: str,
    user,
    user_email: Optional[str],
    usuario_nome: Optional[str],
    request: Optional[Request],
    target_type: Optional[str],
    target_id: Optional[Any],
    alvo_nome: Optional[str],
    details: Optional[dict],
    municipio_id: Optional[Any],
    resultado: Optional[str],
    valor_antes: Optional[dict],
    valor_depois: Optional[dict],
    sessao_id: Optional[str],
    sessao_inicio: Optional[datetime],
) -> AuditLog:
    antes, depois = campos_alterados(valor_antes, valor_depois)

    # O que o chamador informou vence; o resto sai do proprio token da request.
    sid, inicio = sessao_id, sessao_inicio
    if sid is None or inicio is None:
        sid_auto, inicio_auto = _sessao(request)
        sid, inicio = sid or sid_auto, inicio or inicio_auto

    det = sanitizar(details) if details else None

    return AuditLog(
        user_id=getattr(user, "id", None) if user else None,
        user_email=_corta(user_email or (getattr(user, "email", None) if user else None), 255),
        usuario_nome=_corta(usuario_nome or (getattr(user, "name", None) if user else None), 200),
        action=_corta(action, 100),
        target_type=_corta(target_type, 50),
        target_id=_corta(target_id, 100),
        alvo_nome=_corta(alvo_nome, 300),
        resultado=_resultado(action, resultado),
        municipio_id=_municipio(request, municipio_id, details),
        ip=_ip(request),
        user_agent=_corta(request.headers.get("user-agent") if request else None, 500),
        http_metodo=_corta(getattr(request, "method", None) if request else None, 10),
        # SO o molde da rota — nem query string, nem parametro preenchido. Ver
        # `_rota`: os dois carregam dado pessoal, e um deles carrega credencial.
        http_path=_corta(_rota(request), 300),
        sessao_id=_corta(sid, 64),
        sessao_inicio=inicio,
        details=det or None,
        valor_antes=sanitizar(antes) if antes else None,
        valor_depois=sanitizar(depois) if depois else None,
    )


# ---------------------------------------------------------------------------
# As duas portas
# ---------------------------------------------------------------------------
async def registrar(
    db: AsyncSession,
    *,
    action: str,
    user=None,
    user_email: Optional[str] = None,
    usuario_nome: Optional[str] = None,
    request: Optional[Request] = None,
    target_type: Optional[str] = None,
    target_id: Optional[Any] = None,
    alvo_nome: Optional[str] = None,
    details: Optional[dict] = None,
    municipio_id: Optional[Any] = None,
    resultado: Optional[str] = None,
    valor_antes: Optional[dict] = None,
    valor_depois: Optional[dict] = None,
    sessao_id: Optional[str] = None,
    sessao_inicio: Optional[datetime] = None,
    commit: bool = True,
) -> bool:
    """Registra o ato em MELHOR ESFORCO. Devolve True se gravou.

    `user_email` existe separado de `user=` para o caso em que nao HA usuario:
    em `login.fail` o e-mail tentado costuma nem existir no banco, e e por ele
    que se procura tentativa de invasao.

    Falha nao vaza para o chamador — mas tambem nao contamina a transacao dele:
    o INSERT vai dentro de um SAVEPOINT. Sem o savepoint, um erro aqui deixaria
    a sessao SQLAlchemy envenenada e a proxima operacao do endpoint quebraria
    com um erro sem relacao aparente, dificil de rastrear.

    Acoes de ACOES_CRITICAS sao promovidas automaticamente para
    `registrar_critico` — fail-closed: usar a porta errada nao pode ser o que
    apaga o rastro de uma revelacao de senha."""
    if eh_critica(action):
        return await registrar_critico(
            db, action=action, user=user, user_email=user_email,
            usuario_nome=usuario_nome, request=request, target_type=target_type,
            target_id=target_id, alvo_nome=alvo_nome, details=details,
            municipio_id=municipio_id, resultado=resultado,
            valor_antes=valor_antes, valor_depois=valor_depois,
            sessao_id=sessao_id, sessao_inicio=sessao_inicio, commit=commit,
        )

    try:
        entry = _montar(
            action=action, user=user, user_email=user_email, usuario_nome=usuario_nome,
            request=request, target_type=target_type, target_id=target_id,
            alvo_nome=alvo_nome, details=details, municipio_id=municipio_id,
            resultado=resultado, valor_antes=valor_antes, valor_depois=valor_depois,
            sessao_id=sessao_id, sessao_inicio=sessao_inicio,
        )
        async with db.begin_nested():
            db.add(entry)
        if commit:
            await db.commit()
        return True
    except Exception:
        # ⚠️ Este `except` e o unico lugar do modulo onde uma falha de auditoria
        # some. Ele existe so para navegacao e afins — e por isso o log e
        # `exception` e nao `debug`: auditoria que falha em silencio parece
        # auditoria sem eventos, que foi um dos defeitos que este incremento
        # veio corrigir. Se aparecer no log, e para investigar.
        logger.exception("Falha registrando audit_log (action=%s)", action)
        return False


async def registrar_critico(
    db: AsyncSession,
    *,
    action: str,
    user=None,
    user_email: Optional[str] = None,
    usuario_nome: Optional[str] = None,
    request: Optional[Request] = None,
    target_type: Optional[str] = None,
    target_id: Optional[Any] = None,
    alvo_nome: Optional[str] = None,
    details: Optional[dict] = None,
    municipio_id: Optional[Any] = None,
    resultado: Optional[str] = None,
    valor_antes: Optional[dict] = None,
    valor_depois: Optional[dict] = None,
    sessao_id: Optional[str] = None,
    sessao_inicio: Optional[datetime] = None,
    commit: bool = True,
) -> bool:
    """Registra o ato PROPAGANDO a falha. Sem registro, sem ato.

    Nao ha try/except aqui de proposito: a excecao sobe, o endpoint devolve
    erro, a dependency de sessao desfaz a transacao — e o segredo nao e
    revelado, o dado nao e exportado.

    COMO CHAMAR:
      - antes de devolver o segredo (o `return` so acontece se a linha gravou);
      - `commit=False` quando a acao ainda vai commitar: a linha entra na MESMA
        transacao e as duas caem juntas se algo der errado. Nesse caso fazemos
        `flush()` para a falha aparecer AQUI, e nao la na frente disfarcada de
        erro do commit da acao."""
    entry = _montar(
        action=action, user=user, user_email=user_email, usuario_nome=usuario_nome,
        request=request, target_type=target_type, target_id=target_id,
        alvo_nome=alvo_nome, details=details, municipio_id=municipio_id,
        resultado=resultado, valor_antes=valor_antes, valor_depois=valor_depois,
        sessao_id=sessao_id, sessao_inicio=sessao_inicio,
    )
    db.add(entry)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return True


async def log_event(
    db: AsyncSession,
    *,
    action: str,
    user=None,
    request: Optional[Request] = None,
    target_type: Optional[str] = None,
    target_id: Optional[Any] = None,
    details: Optional[dict] = None,
    commit: bool = True,
    **extras,
) -> bool:
    """Nome antigo, mantido para as chamadas que ainda nao migraram.

    ⚠️ Nao e mais so um apelido inofensivo: passa por `registrar()`, entao as
    acoes criticas (qualquer `*.reveal`) agora PROPAGAM falha de gravacao mesmo
    pelo nome antigo. Isso e intencional — era o caminho por onde
    `cofre.reveal` devolvia a senha sem deixar rastro quando o INSERT falhava.

    Aceita `**extras` para que um chamador antigo possa passar campo novo
    (municipio_id, valor_antes, ...) sem trocar de funcao no mesmo commit."""
    return await registrar(
        db, action=action, user=user, request=request, target_type=target_type,
        target_id=target_id, details=details, commit=commit, **extras,
    )
