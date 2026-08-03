"""
IP real do cliente atras de proxy reverso (Traefik do Coolify).

PORQUE ESTE ARQUIVO EXISTE
--------------------------
Havia duas formas ERRADAS de descobrir o IP espalhadas pelo backend:

  1. `request.client.host` puro (services/audit.py, service_auth.py, auth.py):
     atras do Traefik isso e o IP INTERNO do proxy. Toda linha da auditoria
     gravava o mesmo IP — inutil para responder "de onde veio esse acesso".

  2. `x-forwarded-for.split(",")[0]` (a antiga control_auth._client_ip): pega o
     PRIMEIRO item, que e justamente o pedaco que o CLIENTE mandou. Qualquer um
     escreve `X-Forwarded-For: 1.2.3.4` no curl e passa a "ser" esse IP. Como
     esse valor alimentava a allowlist do control-plane, era uma allowlist que o
     proprio atacante preenchia.

O X-Forwarded-For e uma cadeia em que CADA proxy ACRESCENTA AO FINAL o endereco
do hop de quem ele recebeu a conexao. Logo o unico trecho confiavel e o FINAL, e
so ate onde a nossa infraestrutura escreveu. Contamos de tras para frente,
descontando os proxies confiaveis (TRUSTED_PROXIES, default 1 = Traefik):

    Cliente(200.1.1.1) -> Traefik(10.0.1.5) -> API
    cabecalho recebido:  "1.2.3.4, 200.1.1.1"   <- "1.2.3.4" foi forjado
    cadeia + peer:       ["1.2.3.4", "200.1.1.1", "10.0.1.5"]
                                          ^ resposta (1 proxy confiavel)

Lixo que o atacante empilhe a esquerda nunca desloca a resposta, porque a conta
e feita a partir da direita.

PRE-REQUISITO DE INFRA: isto so vale enquanto a porta do container NAO estiver
publicada direto na internet — o modelo assume que todo trafego entra pelo
Traefik. Se um dia a API for exposta sem proxy, TRUSTED_PROXIES tem de virar 0.

NOTA SOBRE `--proxy-headers` DO UVICORN: o uvicorn tambem reescreve
`scope["client"]` a partir do X-Forwarded-For, e o criterio dele depende do
`--forwarded-allow-ips`. Com `*` ele pega a PONTA ESQUERDA (o pedaco forjavel);
com uma lista de redes ele varre da direita para a esquerda, como aqui. O
Dockerfile.api usa a lista justamente por isso. De todo modo a conta desta
funcao nao depende disso: quando ha cabecalho, o peer entra so como ultimo
elemento da cadeia e o indice contado da direita cai sempre dentro do trecho
escrito pelos proxies. Mesmo assim, codigo sensivel (auditoria, allowlist, rate
limit) usa esta funcao e nunca `request.client.host` cru.

Sem import de fastapi de proposito: a funcao le apenas `.headers` e `.client`,
entao vale para Request de qualquer origem e o teste roda sem subir a stack web.
"""
import ipaddress
import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # apenas para type hint; nao carrega no runtime
    from fastapi import Request


# 1 = Traefik do Coolify. Se entrar CDN/WAF na frente, sobe para 2 via env.
TRUSTED_PROXIES_PADRAO = 1


def proxies_confiaveis() -> int:
    """Quantos hops da PONTA DIREITA do X-Forwarded-For sao da nossa infra.

    Lido a cada chamada (nao em import) para o teste poder variar o ambiente e
    para a env valer sem rebuild da imagem. Valor invalido cai no padrao: env
    digitada errada nao pode virar "confia em qualquer coisa".
    """
    bruto = os.getenv("TRUSTED_PROXIES", "").strip()
    if not bruto:
        return TRUSTED_PROXIES_PADRAO
    try:
        n = int(bruto)
    except ValueError:
        return TRUSTED_PROXIES_PADRAO
    return n if n >= 0 else TRUSTED_PROXIES_PADRAO


def normalizar_ip(valor: Optional[str]) -> Optional[str]:
    """Valida e normaliza um endereco. Devolve None se nao for IP.

    Normalizar importa para a AUDITORIA: sem isto o mesmo visitante aparece como
    duas pessoas diferentes na trilha (`2001:0db8::1` e `2001:db8::1`, ou
    `::ffff:200.1.1.1` e `200.1.1.1`). Tambem descarta os `unknown`/`_hidden`
    que alguns proxies escrevem no lugar do endereco.
    """
    v = (valor or "").strip()
    if not v:
        return None

    if v.startswith("["):
        # RFC 7239: IPv6 vem entre colchetes, com ou sem porta -> "[2001:db8::1]:443"
        fim = v.find("]")
        if fim == -1:
            return None
        v = v[1:fim]
    elif v.count(":") == 1:
        # um unico ":" so pode ser IPv4:porta — IPv6 sem colchetes tem 2 ou mais
        v = v.split(":", 1)[0]

    try:
        ip = ipaddress.ip_address(v)
    except ValueError:
        return None

    # ::ffff:200.1.1.1 e o MESMO cliente que 200.1.1.1: guarda na forma curta
    mapeado = getattr(ip, "ipv4_mapped", None)
    if mapeado is not None:
        return str(mapeado)
    return str(ip)


def client_ip(request: "Request", *, trusted_proxies: Optional[int] = None) -> Optional[str]:
    """IP real do cliente, ou None quando nao da para afirmar qual e.

    Devolver None (em vez de chutar) e proposital: em allowlist o None nao casa
    com nada e nega o acesso, e na auditoria fica registrado "IP desconhecido" —
    melhor do que gravar o IP do proxy como se fosse o do usuario.
    """
    n = proxies_confiaveis() if trusted_proxies is None else max(0, int(trusted_proxies))

    # TODAS as linhas X-Forwarded-For, na ordem, e nao so a primeira. Pela RFC
    # 9110 varias linhas de mesmo nome equivalem a uma unica unida por virgula,
    # mas `headers.get()` do Starlette devolve so a PRIMEIRA ocorrencia. Se o
    # cliente mandar um X-Forwarded-For proprio e algum proxy da frente
    # ACRESCENTAR uma linha nova em vez de reescrever a existente, ler so a
    # primeira encurta a cadeia — e o indice contado da direita anda para a
    # esquerda e cai justamente em cima do item forjado. O uvicorn ja junta
    # todas (middleware/proxy_headers.py); aqui tem de ser igual, senao as duas
    # camadas discordam sobre quem e o cliente.
    headers = getattr(request, "headers", None)
    linhas: list = []
    if headers is not None:
        getlist = getattr(headers, "getlist", None)
        if callable(getlist):
            linhas = [v for v in getlist("x-forwarded-for") if v]
        else:   # objeto simulado/duck-typed que so tem .get()
            uma = headers.get("x-forwarded-for")
            if uma:
                linhas = [uma]
    cabecalho = ",".join(linhas)

    # Token vazio (virgula sobrando) NAO e um hop e nao pode entrar na contagem;
    # token invalido E um hop (alguem o escreveu), entao ocupa a posicao como
    # None — descartar deslocaria a conta e entregaria a vaga a um item forjado.
    cadeia: list = [normalizar_ip(t) for t in cabecalho.split(",") if t.strip()]

    # O peer TCP e sempre o ultimo hop conhecido. Entra mesmo se ilegivel
    # (socket unix, TestClient) para nao encurtar a cadeia.
    peer = getattr(getattr(request, "client", None), "host", None)
    cadeia.append(normalizar_ip(peer))

    indice = len(cadeia) - 1 - n
    if indice < 0:
        # Menos hops do que proxies declarados: ou a requisicao nao passou pela
        # cadeia inteira (healthcheck local, acesso direto), ou TRUSTED_PROXIES
        # esta maior que a realidade. Sem margem para descontar, fica o hop mais
        # antigo que conhecemos — no caso comum (cadeia so com o peer) e o peer.
        indice = 0

    return cadeia[indice]
