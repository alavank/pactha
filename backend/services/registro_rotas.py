"""
⭐ O REGISTRO QUE FALHA FECHADO — a autorizacao deixa de ser OPT-IN.

O PROBLEMA QUE ESTE ARQUIVO RESOLVE
-----------------------------------
Ate aqui, autorizar era LEMBRAR. Quem escrevia um endpoint novo precisava
lembrar de chamar `ensure_tela`, `ensure_municipio_access`, `authz.exigir`. Nada
no sistema notava a ausencia: a rota subia, respondia, e o unico jeito de
descobrir que ela estava aberta era alguem varrer 171 endpoints a mao. Foi
exatamente assim que 55 deles ficaram sem checagem nenhuma — e sem inverter esse
default o buraco volta em seis meses, com outro nome e outro autor.

A inversao e simples de enunciar: **rota que ninguem declarou nao pode existir em
silencio.** No boot varremos `app.routes` e comparamos cada uma com duas listas:

    1. as que DECLARARAM permissao, via `exige("rm.excluir")` no router;
    2. a ALLOWLIST curta e explicita deste arquivo (`ROTAS_LIVRES`) — publicas
       ou auto-escopadas.

O que nao esta em nenhuma das duas e PENDENTE, e o sistema reage.

⚠️ O COMPORTAMENTO EM PRODUCAO — a decisao mais delicada deste incremento
--------------------------------------------------------------------------
A tentacao e "nao sobe, ponto". Fail-closed puro. Mas o custo dessa escolha nao
cai em quem errou: cai numa prefeitura. Uma rota nova esquecida derrubaria a API
INTEIRA de Monte Siao — o Painel do prefeito, a Gestao Interna, o login — por
causa de UMA funcionalidade que ninguem esta usando ainda, no meio do expediente,
com o servidor devolvendo 502 e ninguem entendendo por que. Trocar um endpoint
aberto por um apagao total e trocar um risco por um dano garantido.

Por isso o comportamento e ESCALONADO, e cada degrau paga o proprio preco:

    DESENVOLVIMENTO  -> `estrito`: o processo NAO SOBE. Aqui derrubar e barato
                        (quem paga e quem esqueceu, no minuto em que esqueceu) e
                        e o unico momento em que a correcao custa uma linha.
                        E este degrau que impede o problema de CHEGAR em
                        producao.

    PRODUCAO         -> `bloqueio`: sobe, registra CRITICO no log e devolve 403
                        NAQUELA rota. O estrago fica do tamanho do erro: a
                        funcionalidade nova nao funciona, todo o resto continua
                        de pe. E 403 e a resposta HONESTA — e literalmente o que
                        a rota devolveria se tivesse declarado a permissao e o
                        usuario nao a tivesse.

    TRANSICAO        -> `aviso`: sobe, registra CRITICO e NAO bloqueia nada.
                        E o default enquanto `AUTHZ_MODO=aviso` (ver abaixo), e
                        e a mesma promessa do Incremento 2: a trava nasce
                        FALANDO. Sem isto, o dia do deploy seria o dia em que
                        130 rotas ainda nao declaradas comecariam a devolver 403
                        de uma vez — o apagao que o incremento existe para
                        evitar.

VALVULA DE ESCAPE, e ela e proposital: `AUTHZ_REGISTRO=aviso` no ambiente do
tenant desliga o bloqueio sem deploy nenhum (no Coolify e trocar uma variavel e
reiniciar, minutos). Se um endpoint esquecido travar o trabalho de uma
prefeitura as 9h da manha, quem esta no telefone precisa de um jeito de destravar
que nao dependa de build de imagem. O incidente continua alto e visivel — o
CRITICO nao para de sair no log — mas para de ser uma emergencia.

COMO SE DECLARA (o que os routers usam)
---------------------------------------
    from services.registro_rotas import exige

    @router.delete("/{rid}", dependencies=[exige("rm.excluir")])
    async def remover(...): ...

`exige` faz as DUAS coisas com o mesmo objeto: registra a declaracao (o boot a
enxerga) e checa em tempo de requisicao. Nao ha como declarar e esquecer de
checar, nem checar sem declarar — que e a divergencia que uma tabela separada de
"rota -> permissao" produziria no primeiro refactor.

Endpoint que precisa de logica no meio (checar o dono da linha antes, escolher a
permissao pelo corpo do pedido) pode continuar chamando `authz.exigir(...)` no
corpo, mas AINDA ASSIM tem de declarar — nesse caso com `declarado(...)`, que
so marca. Sem marca, o boot considera a rota pendente.

ENV
---
    AUTHZ_REGISTRO=estrito|bloqueio|aviso   (vence tudo, quando definida)
    AUTHZ_MODO=aviso|bloqueio               (o mesmo do resto do incremento)
    ENV=production                          (decide dev x producao)

Sem `AUTHZ_REGISTRO`, o modo vem de `AUTHZ_MODO`:
    aviso     -> `aviso` (default de hoje)
    bloqueio  -> `estrito` em desenvolvimento, `bloqueio` em producao
"""
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from services import permissoes as catalogo

logger = logging.getLogger("registro_rotas")


# Atributo que marca uma funcao como declaradora de permissao. Nome longo e com
# prefixo do produto para nao colidir com nada de biblioteca.
ATRIBUTO = "__pactha_permissoes__"

MODO_AVISO = "aviso"
MODO_BLOQUEIO = "bloqueio"
MODO_ESTRITO = "estrito"
MODOS = (MODO_AVISO, MODO_BLOQUEIO, MODO_ESTRITO)


# ---------------------------------------------------------------------------
# DECLARACAO
# ---------------------------------------------------------------------------
def _validar(chaves: Iterable[str]) -> tuple:
    """Chave inexistente e erro de PROGRAMACAO, e morre no IMPORT do router.

    E o melhor momento possivel para essa morte: `exige("rm.excluri")` com typo
    passaria a varredura de boot (a rota esta declarada!) e negaria todo mundo
    para sempre, inclusive o super-admin, sem nada no log dizendo o porque."""
    limpas = tuple(catalogo.normalizar(c) for c in chaves)
    if not limpas:
        raise ValueError("exige() precisa de pelo menos uma permissao")
    desconhecidas = [c for c in limpas if c not in catalogo.CATALOGO]
    if desconhecidas:
        raise ValueError(
            f"permissao desconhecida em exige(): {desconhecidas} — "
            "as chaves validas estao em services/permissoes.py::CATALOGO")
    return limpas


def exige(*chaves: str):
    """Declara E checa. Devolve um `Depends` para `dependencies=[...]`.

    TODAS as chaves passadas sao exigidas (e "e", nao "ou"): um endpoint que
    aceite dois caminhos diferentes de permissao deve declarar o denominador
    comum e resolver o resto no corpo com `authz.pode`.

    A checagem roda ANTES do corpo do endpoint e depois de `get_current_user`
    (que o FastAPI resolve uma vez so e reaproveita — o cache de dependencia
    garante que o usuario nao e lido do banco duas vezes)."""
    exigidas = _validar(chaves)

    # Import local: `services/auth.py` importa `services/authz.py`, e este
    # modulo e importado por routers. Manter o import aqui deixa este arquivo
    # importavel por qualquer um sem arrastar a cadeia inteira.
    from services.auth import get_current_user

    async def _checar(usuario=Depends(get_current_user)):
        from services import authz
        for chave in exigidas:
            authz.exigir(usuario, chave)
        return None

    setattr(_checar, ATRIBUTO, exigidas)
    _checar.__name__ = "exige_" + "_".join(c.replace(".", "_") for c in exigidas)
    return Depends(_checar)


def declarado(*chaves: str):
    """So MARCA — nao checa. Para o endpoint que precisa decidir a permissao no
    meio do corpo (pela linha que buscou, pelo tipo do pedido) e chama
    `authz.exigir(...)` la dentro.

    Existe para esse caso NAO virar "rota sem registro": a alternativa seria
    poe-lo na allowlist de rotas livres, e allowlist que cresce e allowlist que
    ninguem le. Aqui a rota continua declarando o que exige — a varredura ve, o
    leitor ve, e a checagem so acontece noutro lugar.

    ⚠️ E a unica porta deste arquivo que confia em quem escreveu o endpoint. Use
    `exige()` sempre que der."""
    exigidas = _validar(chaves)

    async def _marcador():
        return None

    setattr(_marcador, ATRIBUTO, exigidas)
    _marcador.__name__ = "declara_" + "_".join(
        c.replace(".", "_") for c in exigidas)
    return Depends(_marcador)


# ---------------------------------------------------------------------------
# ALLOWLIST — rotas publicas ou auto-escopadas
# ---------------------------------------------------------------------------
# ⚠️ ESTA LISTA E A UNICA MANEIRA DE UMA ROTA FICAR SEM PERMISSAO. Ela e curta de
# proposito e cada linha carrega o MOTIVO: allowlist sem motivo vira deposito, e
# um deposito de rotas livres e o buraco de novo, so que agora com aparencia de
# decisao.
#
# Regra de forma: casamento por IGUALDADE de metodo e caminho (o MOLDE da rota,
# `/api/bi/tela-pub/{slug}`), nunca por prefixo — a nao ser nas entradas
# marcadas com `/*`, que existem para um CANAL inteiro com principal proprio.
# O precedente e `services/auth.py::KIOSK_GET_PERMITIDOS`: la o comentario
# explica que com `startswith` liberar `/api/bi/parlamentares/detalhe` abriria
# `/api/bi/parlamentares` de brinde.
#
# ⚠️ O QUE NAO ENTRA AQUI, e a ausencia e a decisao:
#   `/api/auth/register`  cria usuario e ainda decide por `role == 'admin'`.
#                         Parece "rota de auth", mas e cadastro de gente: exige
#                         `usuarios.criar`. Uma entrada `/api/auth/*` levaria
#                         essa rota junto sem ninguem perceber — por isso as
#                         rotas de auth estao listadas UMA A UMA.
#   (o modulo Telegram, que ocupava este paragrafo com `/api/telegram/my-link`,
#    saiu do codigo em 05/09/2026 — a decisao continua valendo para o proximo
#    canal de avisos: rota "do proprio usuario" tambem declara permissao.)
@dataclass(frozen=True)
class Livre:
    metodo: str      # "GET", "POST"... ou "*"
    caminho: str     # molde da rota; termina em "/*" para um canal inteiro
    motivo: str


ROTAS_LIVRES: tuple = (
    # --- Publicas: nao ha usuario ainda ------------------------------------
    Livre("POST", "/api/uso/lote",
          "Telemetria. Auto-escopada: o user_id vem do TOKEN e o corpo nao pode "
          "escolher outro (o UPDATE tem AND user_id = :uid). Exigir permissao "
          "aqui deixaria de medir justamente quem tem MENOS permissao — que e "
          "quem mais precisa ser entendido. A leitura (GET /uso/*) exige."),
    Livre("POST", "/api/auth/login", "Publica: e onde a sessao nasce."),
    Livre("POST", "/api/auth/refresh",
          "Publica: renova a sessao pelo cookie de refresh, que e a credencial."),
    Livre("GET", "/api/auth/sso-login",
          "Publica: aceita o token de uso unico da Central. A autorizacao E o "
          "token (2 min, uso unico, amarrado a instancia)."),
    Livre("POST", "/api/auth/logout",
          "Encerra a PROPRIA sessao. Exigir permissao para sair seria trancar "
          "alguem dentro do sistema."),
    Livre("GET", "/api/health", "Sonda de saude do container. Sem dado nenhum."),
    Livre("GET", "/api/status/ingestao",
          "Monitor de carga (contagens agregadas). Ja e publica hoje e nao "
          "expoe dado de municipio."),
    Livre("GET", "/api/bi/tela-pub/{slug}",
          "Link publico da TV: o slug de 12 chars E a credencial. O que o "
          "token resultante alcanca esta travado em KIOSK_GET_PERMITIDOS."),
    Livre("GET", "/api/bi/tela-pub/{slug}/meta",
          "So o titulo para a previa de WhatsApp (cidade + modo). NAO devolve "
          "o token nem toca no quiosque — revela menos que o proprio slug."),

    # --- Auto-escopadas: a resposta e sobre o PROPRIO usuario ---------------
    Livre("GET", "/api/auth/me", "O usuario lendo o proprio cadastro."),
    Livre("POST", "/api/auth/change-password",
          "O usuario trocando a PROPRIA senha (confere a senha atual). E "
          "obrigatorio no primeiro acesso — exigir permissao aqui trancaria o "
          "usuario novo fora."),
    Livre("GET", "/api/auditoria/minha-atividade",
          "A propria atividade. `auditoria.ver` e a trilha de TODO MUNDO; esta "
          "e a de quem pergunta, e o router ja filtra por user_id."),
    Livre("GET", "/api/auditoria/catalogo",
          "Legendas e filtros da tela — conteudo estatico, nenhum dado do "
          "cliente. «Minha atividade», que qualquer um abre, precisa delas."),
    Livre("GET", "/api/municipios",
          "Listagem AUTO-ESCOPADA: o router filtra por allowed_municipio_ids e "
          "devolve [] para quem nao tem nenhum. Toda tela do sistema depende "
          "dela para montar o seletor."),
    Livre("GET", "/api/permissoes/catalogo",
          "O catalogo de permissoes: texto do produto, igual para todo mundo."),
    Livre("GET", "/api/permissoes/minhas",
          "O que o PROPRIO usuario pode. E o que a tela usa para saber quais "
          "botoes desenhar."),
    # Preferencias e push do Painel/BI: escrevem SO na linha do proprio usuario
    # (chaveadas por user_id) e ja estao liberadas ate para o perfil
    # somente-leitura (services/auth.py::READONLY_WRITE_ALLOW).
    Livre("GET", "/api/painel/preferencias", "Preferencia do PROPRIO usuario."),
    Livre("PUT", "/api/painel/preferencias", "Preferencia do PROPRIO usuario."),
    Livre("GET", "/api/bi/preferencias", "Preferencia do PROPRIO usuario."),
    Livre("PUT", "/api/bi/preferencias", "Preferencia do PROPRIO usuario."),
    Livre("POST", "/api/painel/push/subscribe",
          "Inscricao de push do PROPRIO aparelho."),
    Livre("DELETE", "/api/painel/push/subscribe",
          "Cancelamento de push do PROPRIO aparelho."),
    Livre("POST", "/api/bi/push/subscribe",
          "Inscricao de push do PROPRIO aparelho."),
    Livre("DELETE", "/api/bi/push/subscribe",
          "Cancelamento de push do PROPRIO aparelho."),
    Livre("GET", "/api/painel/vapid-public-key",
          "Chave PUBLICA do push. Publica esta no nome."),
    Livre("GET", "/api/bi/vapid-public-key",
          "Chave PUBLICA do push. Publica esta no nome."),
    # O historico da IA. `ai.usar` paga a chamada ao modelo; ler e apagar a
    # PROPRIA conversa nao gasta nada e nao alcanca a de ninguem — as tres
    # consultas terminam em `WHERE user_id = :u`, e a tela `ai` (gate antigo)
    # continua sendo exigida no corpo. Declarar `ai.usar`, que e permissao de
    # ESCRITA, tiraria de quem so pode ler ate o proprio historico.
    Livre("GET", "/api/ai/conversas",
          "As conversas do PROPRIO usuario (WHERE user_id)."),
    Livre("GET", "/api/ai/conversas/{conversa_id}",
          "A propria conversa. Quem nao e dono leva 404 — nem descobre que "
          "existe."),
    Livre("DELETE", "/api/ai/conversas/{conversa_id}",
          "Apaga a PROPRIA conversa (DELETE ... AND user_id = :u)."),
    # Modo Tela: filtro e links do proprio gestor. Note que so o POST de
    # /tela-links fica de fora desta lista — publicar e o unico ato que cria
    # acesso para TERCEIROS, e ele declara `bi.link`.
    Livre("GET", "/api/bi/tela-filtros",
          "Filtro do PROPRIO usuario (uma linha por user_id; sem linha, "
          "default vazio). ⚠️ Esta em KIOSK_GET_PERMITIDOS: a conta de TV so "
          "resolve `bi.ver` (PERMISSOES_QUIOSQUE), entao exigir `bi.tela` aqui "
          "apagaria os links legados `?kiosk=` em silencio."),
    Livre("PUT", "/api/bi/tela-filtros",
          "O Painel grava aqui a CADA mudanca de periodo ou de municipio, para "
          "todo usuario, e a escrita e so na propria linha — exigir permissao "
          "encheria a semana de observacao de um fato que nao e o buraco."),
    Livre("GET", "/api/bi/tela-links",
          "Os links do PROPRIO usuario (WHERE owner_id). Quem nao publicou "
          "nenhum recebe lista vazia."),
    Livre("DELETE", "/api/bi/tela-links/{slug}",
          "Revoga o PROPRIO link (UPDATE ... AND owner_id = :u). Cortar um "
          "acesso publico e a acao que nunca se deve negar: barrar aqui por "
          "falta de permissao deixaria o link VIVO."),

    # Tokens do MCP: cada um administra os SEUS (como trocar a propria senha,
    # sem exigir tela). Criar/listar/revogar EM NOME DE OUTRA pessoa e ato de
    # administrador, resolvido no corpo por `_pode_gerir_outros` (tela «usuarios»
    # ou super-admin) — o mesmo portao que ja administra as pessoas.
    Livre("GET", "/api/mcp-tokens",
          "Os tokens do PROPRIO usuario; ver os de outra pessoa e checado no corpo."),
    Livre("POST", "/api/mcp-tokens",
          "Cria token do PROPRIO usuario; em nome de outra pessoa e ato de admin, "
          "checado no corpo (_pode_gerir_outros)."),
    Livre("POST", "/api/mcp-tokens/{token_id}/revoke",
          "Revoga o PROPRIO token; o de outra pessoa e checado no corpo. Cortar "
          "acesso e o ato que nunca se deve negar por falta de permissao."),

    # --- Canais com PRINCIPAL PROPRIO: nao ha `User` para ter permissao -----
    Livre("*", "/api/control/*",
          "Canal do Console Alavank. Autentica por TOKEN DE CONTROL "
          "(services/control_auth.py::get_control_principal), com allowlist de "
          "IP e escopos proprios — nao existe usuario logado nesta rota, entao "
          "permissao de usuario nao teria o que checar. E o unico prefixo desta "
          "lista, e e um prefixo porque o canal inteiro tem o mesmo dono."),
    # ⚠️ `POST /api/session-capture` ESTEVE AQUI, com o motivo "autentica por
    # service token, nao por usuario". O motivo era METADE verdade e por isso
    # nao servia: `get_capture_principal` tem DOIS modos, e o segundo aceita o
    # cookie de qualquer conta ativa. A rota cifra credencial de portal do
    # governo no Cofre e dispara o scraper. Hoje ela declara
    # `sessoes.capturar` (com `declarado`, porque so um dos dois modos tem
    # usuario de quem cobrar) — a licao fica escrita: motivo de allowlist que
    # descreve UM caminho de autenticacao precisa dizer o que acontece nos
    # OUTROS.
    # --- Gate MAIS FORTE que permissao: so o dono da plataforma --------------
    # `routers/service_tokens.py::_require_admin` exige `is_super_admin`, e
    # super-admin ja recebe o catalogo INTEIRO (services/permissoes.py). Logo nao
    # existe caixinha capaz de abrir estas rotas — e criar uma seria AFROUXAR:
    # `service_tokens.criar` poderia ser concedida a um admin do cliente, que
    # hoje nao passa daqui. Sao credenciais de maquina longevas (o scraper le o
    # Cofre com elas), nao recurso de tela.
    #
    # ⚠️ Listadas UMA A UMA, e nao como `/api/admin/service-tokens/*`: rota nova
    # neste prefixo tem de aparecer PENDENTE no boot em vez de nascer livre de
    # brinde — o mesmo motivo pelo qual as rotas de `/api/auth` estao separadas.
    # E a linha depende do gate acima: quem tirar `_require_admin` de la abre a
    # rota, porque aqui nao ha permissao a checar.
    Livre("GET", "/api/admin/service-tokens",
          "Credencial de MAQUINA: `_require_admin` exige super-admin, gate acima "
          "de qualquer permissao de usuario — nao ha caixinha que conceda isto."),
    Livre("POST", "/api/admin/service-tokens",
          "Emite token de servico em claro. Mesmo gate de super-admin; permissao "
          "de usuario seria mais fraca, porque poderia ser concedida."),
    Livre("POST", "/api/admin/service-tokens/{token_id}/revoke",
          "Revoga token de servico. Mesmo gate de super-admin do restante do "
          "canal — ver a nota acima."),
    Livre("POST", "/api/admin/service-tokens/{token_id}/rotate",
          "Rotaciona token de servico e devolve o novo em claro. Mesmo gate de "
          "super-admin do restante do canal."),
)


def _casa(livre: Livre, metodo: str, caminho: str) -> bool:
    if livre.metodo != "*" and livre.metodo != metodo:
        return False
    if livre.caminho.endswith("/*"):
        return caminho.startswith(livre.caminho[:-1])
    return livre.caminho == caminho


def motivo_livre(metodo: str, caminho: str) -> Optional[str]:
    for livre in ROTAS_LIVRES:
        if _casa(livre, metodo, caminho):
            return livre.motivo
    return None


# ---------------------------------------------------------------------------
# VARREDURA
# ---------------------------------------------------------------------------
@dataclass
class Rota:
    metodo: str
    caminho: str
    endpoint: str
    permissoes: tuple = ()
    motivo_livre: Optional[str] = None
    objeto: Any = None       # a APIRoute, para o bloqueio poder alcanca-la

    @property
    def pendente(self) -> bool:
        return not self.permissoes and self.motivo_livre is None

    def __str__(self) -> str:
        return f"{self.metodo:6} {self.caminho}  ({self.endpoint})"


@dataclass
class Relatorio:
    rotas: list = field(default_factory=list)

    @property
    def declaradas(self) -> list:
        return [r for r in self.rotas if r.permissoes]

    @property
    def livres(self) -> list:
        return [r for r in self.rotas if not r.permissoes and r.motivo_livre]

    @property
    def pendentes(self) -> list:
        return [r for r in self.rotas if r.pendente]


def _rotas_api(routes, prefixo: str = ""):
    """Percorre `app.routes` e devolve as APIRoute, entrando nos routers.

    ⚠️ A partir do FastAPI 0.141 `include_router` NAO copia mais as rotas para
    `app.routes`: ele guarda um `_IncludedRouter` que aponta para o router
    original e resolve o casamento em tempo de requisicao. Uma varredura ingenua
    de `app.routes` acha QUATRO rotas (as do /docs) e conclui, feliz, que nao ha
    nada pendente — um registro fail-closed que nao enxerga rota nenhuma e pior
    que registro nenhum, porque parece que esta funcionando."""
    from fastapi.routing import APIRoute

    for rota in routes:
        if isinstance(rota, APIRoute):
            yield prefixo + rota.path, rota
            continue
        incluido = getattr(rota, "original_router", None)
        if incluido is not None:
            contexto = getattr(rota, "include_context", None)
            extra = getattr(contexto, "prefix", "") or ""
            yield from _rotas_api(incluido.routes, prefixo + extra)


def _permissoes_declaradas(rota) -> tuple:
    """Varre a arvore de dependencias da rota atras da marca de `exige()`.

    Arvore e nao lista: `exige()` pode entrar por `dependencies=[...]` da rota,
    do router ou de um `include_router`, e em qualquer profundidade."""
    achadas: list[str] = []
    vistos: set[int] = set()

    def _desce(dependente):
        if id(dependente) in vistos:
            return
        vistos.add(id(dependente))
        chamada = getattr(dependente, "call", None)
        marcadas = getattr(chamada, ATRIBUTO, None) if chamada else None
        if marcadas:
            achadas.extend(marcadas)
        for sub in getattr(dependente, "dependencies", ()) or ():
            _desce(sub)

    _desce(rota.dependant)
    # Ordenado e sem repeticao: a mesma permissao pode entrar pela rota e pelo
    # router, e o relatorio nao pode contar duas vezes.
    return tuple(sorted(set(achadas)))


def varrer(app) -> Relatorio:
    """O inventario completo. Nao muda nada — da para chamar de teste, de script
    ou do boot."""
    relatorio = Relatorio()
    for caminho, rota in _rotas_api(app.routes):
        declaradas = _permissoes_declaradas(rota)
        for metodo in sorted(rota.methods or ()):
            if metodo in ("HEAD", "OPTIONS"):
                # Gerados pelo framework a partir do GET; nao sao superficie
                # propria e nao ha o que declarar neles.
                continue
            relatorio.rotas.append(Rota(
                metodo=metodo,
                caminho=caminho,
                endpoint=f"{rota.endpoint.__module__.rsplit('.', 1)[-1]}."
                         f"{rota.endpoint.__name__}",
                permissoes=declaradas,
                motivo_livre=None if declaradas else motivo_livre(metodo, caminho),
                objeto=rota,
            ))
    return relatorio


# ---------------------------------------------------------------------------
# MODO
# ---------------------------------------------------------------------------
def _producao() -> bool:
    return (os.getenv("ENV", "") or "").strip().lower() == "production"


def modo() -> str:
    """Modo vigente. Lido a cada chamada (nao no import) pelo mesmo motivo de
    `services/authz.py::modo`: o teste precisa variar o ambiente e a env precisa
    valer sem rebuild da imagem.

    Valor desconhecido em `AUTHZ_REGISTRO` cai no modo derivado de `AUTHZ_MODO`
    — digitar errado nunca pode LIGAR nem DESLIGAR uma trava por acidente."""
    bruto = (os.getenv("AUTHZ_REGISTRO", "") or "").strip().lower()
    if bruto in MODOS:
        return bruto
    if bruto:
        logger.warning("AUTHZ_REGISTRO=%r nao e reconhecido; derivando de "
                       "AUTHZ_MODO", bruto)

    from services import authz
    if authz.modo() != authz.MODO_BLOQUEIO:
        # A trava geral ainda esta em modo aviso: aqui tambem so se fala.
        return MODO_AVISO
    return MODO_BLOQUEIO if _producao() else MODO_ESTRITO


# ---------------------------------------------------------------------------
# BLOQUEIO DA ROTA PENDENTE
# ---------------------------------------------------------------------------
# Uma vez por caminho por processo. Rota bloqueada costuma ser chamada em laco
# pelo frontend (a tela tenta, falha, o usuario clica de novo), e um log por
# requisicao afogaria o log justamente quando ele precisa ser lido.
_ja_logadas: set = set()
_TETO_LOG = 500

MENSAGEM_BLOQUEIO = (
    "Esta funcionalidade está indisponível: a rota subiu sem permissão "
    "declarada. Avise o suporte."
)


async def _bloquear(request: Request):
    """Nega a rota pendente. Roda ANTES de tudo (inserida na posicao 0), entao
    nao chega a abrir sessao de banco nem a carregar o usuario.

    ⚠️ Por isso a linha da trilha sai SEM autor quando a rota nao autentica: o
    que importa aqui e QUAL rota subiu sem registro, e isso e defeito de
    programacao, nao de cadastro — nao ha permissao a conceder para nenhum
    usuario que resolva."""
    try:
        caminho = request.scope.get("path") or ""
    except Exception:
        caminho = ""
    caminho = caminho or str(getattr(request, "url", "?"))
    if caminho not in _ja_logadas:
        if len(_ja_logadas) < _TETO_LOG:
            _ja_logadas.add(caminho)
        logger.error(
            "[REGISTRO] 403 em %s: rota sem permissao declarada e fora da "
            "allowlist. Corrija em routers/ com exige(...) ou, se ela for "
            "mesmo publica, em ROTAS_LIVRES.", caminho)
    try:
        from services import authz
        authz.registrar_rota_sem_registro(None, caminho)
    except Exception:
        logger.exception("Falha registrando rota sem registro (o 403 sai igual)")
    raise HTTPException(status_code=403, detail=MENSAGEM_BLOQUEIO)


def _padrao_da_rota(caminho: str) -> "re.Pattern":
    """Molde de rota (`/api/rm/{rid}`) -> expressao que casa o caminho real.

    ⚠️ POR QUE NAO INSERIMOS MAIS UMA DEPENDENCIA NA ROTA. A versao anterior
    pregava `_bloquear` como primeira dependencia do objeto `APIRoute` achado na
    varredura, via `get_parameterless_sub_dependant`. MEDIDO: nao funciona nesta
    versao do FastAPI. `include_router` guarda um no `_IncludedRouter` em
    `app.routes`, e o objeto que a varredura alcanca NAO e o que atende a
    requisicao — a dependencia entrava (o objeto ficava com `deps=1`) e a rota
    respondia 200 assim mesmo. Era uma trava que parecia instalada e nao estava,
    que e a pior especie.

    Middleware nao depende de nenhum detalhe interno de roteamento: roda ANTES
    de resolver a rota, entao tambem nao vira 401 (a autenticacao nem chega a
    ser chamada) — e 401 aqui seria mentira, porque nao ha login que resolva
    rota sem permissao declarada."""
    partes = []
    for pedaco in re.split(r"(\{[^}]*\})", caminho):
        if pedaco.startswith("{") and pedaco.endswith("}"):
            partes.append(r"[^/]+")          # um segmento, nunca a barra
        else:
            partes.append(re.escape(pedaco))
    return re.compile("^" + "".join(partes) + "/?$")


def _instalar_bloqueio(app, pendentes) -> int:
    """Barra as rotas pendentes por MIDDLEWARE. Devolve quantas cobriu."""
    moldes = []
    for r in pendentes:
        moldes.append((r.metodo.upper(), _padrao_da_rota(r.caminho), r.caminho))
    if not moldes:
        return 0

    @app.middleware("http")
    async def _barrar_pendentes(request: Request, call_next):
        caminho = request.scope.get("path") or ""
        metodo = (request.scope.get("method") or "").upper()
        for m, padrao, molde in moldes:
            if m == metodo and padrao.match(caminho):
                if molde not in _ja_logadas:
                    if len(_ja_logadas) < _TETO_LOG:
                        _ja_logadas.add(molde)
                    logger.error(
                        "[REGISTRO] 403 em %s %s: rota sem permissao declarada e "
                        "fora da allowlist. Corrija em routers/ com exige(...) "
                        "ou, se ela for mesmo publica, em ROTAS_LIVRES.",
                        metodo, molde)
                try:
                    from services import authz
                    authz.registrar_rota_sem_registro(None, molde)
                except Exception:
                    logger.exception(
                        "Falha registrando rota sem registro (o 403 sai igual)")
                return JSONResponse(status_code=403,
                                    content={"detail": MENSAGEM_BLOQUEIO})
        return await call_next(request)

    return len(moldes)

# ---------------------------------------------------------------------------
# BOOT
# ---------------------------------------------------------------------------
class RegistroIncompleto(RuntimeError):
    """Modo estrito: ha rota sem permissao declarada e fora da allowlist."""


TETO_LISTA = 40


def _falar(relatorio: Relatorio, modo_atual: str) -> None:
    total = len(relatorio.rotas)
    pendentes = relatorio.pendentes
    resumo = (f"[REGISTRO] {len(relatorio.declaradas)} rota(s) com permissao "
              f"declarada, {len(relatorio.livres)} livre(s) por allowlist, "
              f"{len(pendentes)} PENDENTE(S) de {total} — modo {modo_atual}")
    if not pendentes:
        print(resumo, flush=True)
        logger.warning(resumo)
        return

    # print() alem do logger: o log do container e o unico lugar onde isto sera
    # visto no dia de um deploy, e a convencao do repo (services/startup.py) e
    # garantir a saida nos dois canais.
    print(resumo, flush=True)
    logger.critical(resumo)
    for rota in pendentes[:TETO_LISTA]:
        linha = f"[REGISTRO]   PENDENTE  {rota}"
        print(linha, flush=True)
        logger.critical(linha)
    if len(pendentes) > TETO_LISTA:
        resto = f"[REGISTRO]   ... e mais {len(pendentes) - TETO_LISTA} rota(s)"
        print(resto, flush=True)
        logger.critical(resto)


def aplicar(app) -> Relatorio:
    """Varre, fala e — conforme o modo — derruba o boot ou tranca as pendentes.

    Chamada do `lifespan` em main.py, FORA de try/except: em modo estrito a
    excecao TEM de subir, senao o degrau de desenvolvimento vira decoracao."""
    relatorio = varrer(app)
    modo_atual = modo()
    _falar(relatorio, modo_atual)

    pendentes = relatorio.pendentes
    if not pendentes:
        return relatorio

    if modo_atual == MODO_ESTRITO:
        nomes = "\n  ".join(str(r) for r in pendentes[:TETO_LISTA])
        raise RegistroIncompleto(
            f"{len(pendentes)} rota(s) subiram sem permissao declarada e fora "
            f"da allowlist de rotas livres:\n  {nomes}\n"
            "Declare com `exige(\"recurso.acao\")` em routers/, ou — se a rota "
            "for mesmo publica ou auto-escopada — acrescente a linha com o "
            "MOTIVO em services/registro_rotas.py::ROTAS_LIVRES.\n"
            "Para subir assim mesmo (incidente em producao): AUTHZ_REGISTRO=aviso."
        )

    if modo_atual == MODO_BLOQUEIO:
        # Por OBJETO de rota, e nao por linha do relatorio: o relatorio tem uma
        # linha por metodo, e uma APIRoute declarada com `methods=["GET","POST"]`
        # apareceria duas vezes — instalar o bloqueio duas vezes na mesma rota
        # so duplicaria trabalho. (O caso normal e uma rota por metodo, porque
        # cada decorador cria a sua.)
        instaladas = _instalar_bloqueio(app, pendentes)
        aviso = (f"[REGISTRO] {instaladas} rota(s) pendente(s) passam a "
                 "devolver 403 ate declararem permissao")
        print(aviso, flush=True)
        logger.critical(aviso)

    return relatorio
