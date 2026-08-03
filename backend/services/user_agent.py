"""
Traducao do User-Agent CRU da trilha de auditoria em algo que uma pessoa leia:
navegador, versao, sistema operacional e tipo de dispositivo.
Ex.: "Chrome 120 · Windows 10/11 · Desktop".

POR QUE ISTO RODA NA LEITURA, E NAO NA GRAVACAO
-----------------------------------------------
O audit_log guarda o User-Agent CRU, exatamente como o navegador mandou. Esta
interpretacao acontece quando a trilha e LIDA (tela, modal, exportacao). O motivo
e retroativo: navegador novo, sistema novo e bot novo aparecem toda semana, e
melhorar o interpretador AQUI conserta a leitura de TODOS os registros antigos —
inclusive os de cinco anos atras — sem reprocessar nada e sem escrever uma unica
linha na trilha, que e append-only por projeto (Incremento 3).
Corolario: o que sai daqui e DADO DERIVADO, nunca dado. Nao persista o resultado
como se fosse a fonte; a fonte e a coluna `user_agent` crua.

Sem dependencia nova de proposito (ua-parser, user-agents etc.): seria mais uma
base de assinaturas para manter atualizada e mais superficie de supply chain num
sistema de setor publico, para resolver ~60 linhas de regex.

O User-Agent e texto controlado por quem chama a API — pode vir forjado, vazio,
truncado ou absurdo. Nada aqui estoura: o piso e sempre "Desconhecido".

Consequencia util para quem exporta (PDF/Excel/CSV): a saida NUNCA repassa
trecho do UA cru. Nome de navegador, sistema e dispositivo saem de um vocabulario
FECHADO deste arquivo, e `versao` e so digitos. Ou seja, o "resumo" nao carrega
texto de terceiro — nao da para injetar formula de planilha nem marcacao por ali.
Quem imprimir o UA cru (no modal, por exemplo) e que precisa tratar o escape.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional

__all__ = ["parse_user_agent", "resumir_user_agent", "DESCONHECIDO"]

DESCONHECIDO = "Desconhecido"

# O UA e cabecalho de terceiro: cortamos antes de rodar regex para que um valor
# gigante nao vire custo de CPU vezes o numero de linhas listadas na tela.
# A coluna do banco ja e VARCHAR(500) — o corte aqui e cinto e suspensorio.
_LIMITE = 512


# ---------------------------------------------------------------------------
# BOTS E AUTOMACAO — testados ANTES de qualquer navegador.
# O Googlebot "smartphone" copia o UA inteiro do Chrome Android e so acrescenta
# "(compatible; Googlebot/2.1; +http://...)" no fim. Testar Chrome primeiro
# rotularia rastreador como gente — e numa trilha de auditoria essa diferenca e
# justamente o que se quer enxergar.
# ---------------------------------------------------------------------------
_BOTS = (
    ("googlebot", "Googlebot"),
    ("adsbot-google", "Googlebot"),
    ("google-inspectiontool", "Googlebot"),
    ("bingbot", "Bingbot"),
    ("yandexbot", "YandexBot"),
    ("baiduspider", "Baiduspider"),
    ("duckduckbot", "DuckDuckBot"),
    ("applebot", "Applebot"),
    ("facebookexternalhit", "Facebook"),
    ("facebookcatalog", "Facebook"),
    ("twitterbot", "Twitterbot"),
    ("linkedinbot", "LinkedInBot"),
    ("whatsapp", "WhatsApp (prévia de link)"),
    ("telegrambot", "TelegramBot"),
    ("discordbot", "Discordbot"),
    ("slackbot", "Slackbot"),
    ("ahrefsbot", "AhrefsBot"),
    ("semrushbot", "SemrushBot"),
    ("mj12bot", "MJ12bot"),
    ("dotbot", "DotBot"),
    ("petalbot", "PetalBot"),
    ("bytespider", "Bytespider"),
    ("gptbot", "GPTBot"),
    ("claudebot", "ClaudeBot"),
    ("ccbot", "CCBot"),
    ("perplexitybot", "PerplexityBot"),
    ("uptimerobot", "UptimeRobot"),
    ("pingdom", "Pingdom"),
    ("statuscake", "StatusCake"),
    # Automacao: nao e crawler de busca, mas tambem nao e alguem sentado na tela.
    # Numa auditoria, "alguem dirigiu o sistema por script" e informacao.
    # Fica NESTA lista (e nao na de baixo) porque a assinatura de automacao vem
    # justamente ACOMPANHADA de um UA de navegador completo — quem dirige o
    # Chrome por script manda "Chrome/120" tambem, e ali a automacao e que e o
    # fato relevante para a trilha.
    ("headlesschrome", "Chrome sem interface (automação)"),
    ("phantomjs", "PhantomJS (automação)"),
    ("selenium", "Selenium (automação)"),
    ("playwright", "Playwright (automação)"),
)

# Bibliotecas HTTP genericas. Separadas de _BOTS de proposito: estes tokens
# aparecem TAMBEM como apendice em UA de gente de verdade — o mais comum e o
# "Java/1.6.0_23" que o plugin da Java pendurava no fim do UA do Internet
# Explorer, ainda vivo em maquina antiga de prefeitura, mas vale para "OkHttp"
# e afins. Testados so DEPOIS da tabela de navegadores: se ha navegador
# reconhecido no UA, quem estava na frente da tela era uma pessoa, e rotular a
# linha como "Java · Robô" (jogando fora sistema e dispositivo) e errar o
# registro de um acesso humano. Sem navegador nenhum, ai sim e cliente HTTP.
_CLIENTES_HTTP = (
    ("python-requests", "python-requests"),
    ("python-httpx", "httpx"),
    ("aiohttp", "aiohttp"),
    ("curl/", "curl"),
    ("wget/", "Wget"),
    ("go-http-client", "Go HTTP client"),
    ("okhttp", "OkHttp"),
    ("axios/", "axios"),
    ("node-fetch", "node-fetch"),
    ("postmanruntime", "Postman"),
    ("java/", "Java"),
    ("libwww-perl", "libwww-perl"),
)

# Rede de seguranca para o robo que ainda nao esta na lista acima. O que exige a
# forma "<algo>bot/1.2", "spider/1.0" ou "crawler/..." — e nao a mera substring
# "bot" — e o `[/ ]\d` do fim, obrigatorio.
# Armadilha real: CUBOT e fabricante de celular, e o UA legitimo
# "Linux; Android 10; CUBOT NOTE 20" viraria "robo" com um `"bot" in ua`.
# ⚠️ NAO ponha um `[\w.+-]*` na frente para "expressar" o prefixo do token: como
# ele pode casar vazio, o `search` aceita exatamente as mesmas strings (nao
# restringe nada), mas faz o motor tentar todo prefixo de todo ponto de partida —
# custo quadratico no tamanho do UA. Medido: 2,5 ms por UA de 512 chars contra
# 0,01 ms sem o prefixo. E o UA e cabecalho de terceiro que entra na trilha ate
# em `login.fail` (sem autenticar): 250x por linha listada e um multiplicador de
# custo que qualquer um pode plantar de fora.
_BOT_GENERICO = re.compile(r"(?:bot|crawler|spider)[/ ]\d", re.I)


# ---------------------------------------------------------------------------
# NAVEGADORES — A ORDEM DESTA TUPLA E A LOGICA. NAO REORDENE SEM LER ISTO.
#
# Quase todo navegador moderno MENTE no proprio User-Agent por compatibilidade
# historica: carrega os tokens "Chrome" e "Safari" sem ser nenhum dos dois.
#   Edge    -> "... Chrome/120.0.0.0 Safari/537.36 Edg/120.0.2210.91"
#   Opera   -> "... Chrome/119.0.0.0 Safari/537.36 OPR/105.0.0.0"
#   Samsung -> "... SamsungBrowser/23.0 Chrome/115.0.0.0 Mobile Safari/537.36"
#   Vivaldi, Yandex, UC -> mesma historia
# Quem tem token PROPRIO vem primeiro; o Chrome so no fim da fila, como
# "sobrou o token generico". Se o Chrome viesse antes, TODO usuario de Edge
# apareceria na auditoria como usuario de Chrome.
#
# Safari nao entra nesta tupla: ele nao tem token exclusivo ("Safari/537.36"
# aparece em quase todo UA Chromium). E reconhecido depois, por AUSENCIA —
# ver _navegador().
#
# BRAVE: o Brave atual REMOVEU a propria marca do UA de proposito (defesa
# anti-fingerprint) e e byte-a-byte igual ao Chrome. Ele esta na lista porque
# versoes antigas e alguns builds ainda mandam "Brave/x"; quando nao mandam, a
# leitura honesta e "Chrome" mesmo. Inventar uma deteccao seria mentir na
# trilha, que e pior do que ser generico nela.
# ---------------------------------------------------------------------------
_NAVEGADORES = (
    # Edge: Chromium "Edg/", Android "EdgA/", iOS "EdgiOS/", legado "Edge/"
    (re.compile(r"Edg(?:e|A|iOS)?/(\d+)", re.I), "Edge"),
    # Opera Chromium (OPR/), Opera Touch (OPT/), Opera iOS (OPiOS/)
    (re.compile(r"(?:OPR|OPT|OPiOS)/(\d+)", re.I), "Opera"),
    # Opera antigo (Presto): "Opera/9.80" e o motor, nao a versao — a versao de
    # verdade esta em "Version/12.14". Por isso esta linha vem antes da seguinte.
    (re.compile(r"Opera/[\d.]+.*Version/(\d+)", re.I), "Opera"),
    (re.compile(r"Opera[ /](\d+)", re.I), "Opera"),
    (re.compile(r"SamsungBrowser/(\d+)", re.I), "Samsung Internet"),
    (re.compile(r"Brave/(\d+)", re.I), "Brave"),
    (re.compile(r"Vivaldi/(\d+)", re.I), "Vivaldi"),
    (re.compile(r"YaBrowser/(\d+)", re.I), "Yandex"),
    (re.compile(r"UCBrowser/(\d+)", re.I), "UC Browser"),
    # Firefox e o Firefox de iOS (FxiOS), que por regra da Apple roda em WebKit
    # e por isso carrega "Safari" no UA.
    (re.compile(r"(?:Firefox|FxiOS)/(\d+)", re.I), "Firefox"),
    # Chrome e derivados diretos. CriOS = Chrome no iPhone/iPad (tambem WebKit).
    (re.compile(r"(?:Chrome|Chromium|CriOS)/(\d+)", re.I), "Chrome"),
    # Internet Explorer 11 nao diz "MSIE": so "Trident/7.0; rv:11.0".
    (re.compile(r"MSIE (\d+)", re.I), "Internet Explorer"),
    (re.compile(r"Trident/[\d.]+.*rv:(\d+)", re.I), "Internet Explorer"),
)

_RE_VERSION = re.compile(r"Version/(\d+)", re.I)

# "Windows NT 10.0" e Windows 10 E Windows 11: a Microsoft NAO subiu o numero do
# NT no 11. Separar os dois exige o cabecalho Sec-CH-UA-Platform-Version, que a
# trilha nao guarda. Escrevemos "10/11" em vez de chutar "11" — auditoria que
# afirma o que nao sabe deixa de servir como prova.
_WINDOWS_NT = {
    "10.0": "Windows 10/11",
    "6.3": "Windows 8.1",
    "6.2": "Windows 8",
    "6.1": "Windows 7",
    "6.0": "Windows Vista",
    "5.2": "Windows XP",
    "5.1": "Windows XP",
}

_RE_WIN_NT = re.compile(r"Windows NT (\d+\.\d+)", re.I)
_RE_WIN_PHONE = re.compile(r"Windows Phone(?: OS)? (\d+\.\d+)", re.I)
_RE_ANDROID = re.compile(r"Android[ /](\d+(?:\.\d+)?)", re.I)
_RE_IOS = re.compile(r"OS (\d+)[._]\d+ like Mac OS X", re.I)
_RE_MAC = re.compile(r"Mac OS X (\d+)[._](\d+)", re.I)
_RE_CROS = re.compile(r"\bCrOS\b", re.I)


def _versao_do_token(low: str, token: str) -> str:
    """Versao maior que vem logo depois do token da lista ("curl/8" -> "8")."""
    m = re.search(re.escape(token.rstrip("/")) + r"[/ ]v?(\d+)", low)
    return m.group(1) if m else ""


def _navegador(ua: str, low: str) -> tuple[str, str, bool]:
    """Devolve (nome, versao_maior, e_robo). Ver o bloco de ordem acima."""
    for token, nome in _BOTS:
        if token in low:
            return nome, _versao_do_token(low, token), True
    if _BOT_GENERICO.search(ua):
        return "Robô não identificado", "", True

    for rx, nome in _NAVEGADORES:
        m = rx.search(ua)
        if m:
            return nome, m.group(1), False

    # Safari POR EXCLUSAO: so e Safari de verdade quem chegou ate aqui carregando
    # "Safari" sem nenhum token Chromium e sem Android. A versao vem de
    # "Version/17.2" — "Safari/605.1.15" e a build do WebKit, nao do navegador.
    if "safari" in low and not any(t in low for t in ("chrome", "chromium", "crios", "android")):
        m = _RE_VERSION.search(ua)
        return "Safari", (m.group(1) if m else ""), False

    # Navegador nativo antigo do Android (pre-Chrome): WebKit com "Version/4.0".
    if "android" in low and "safari" in low:
        m = _RE_VERSION.search(ua)
        return "Navegador Android", (m.group(1) if m else ""), False

    # Nenhum navegador reconhecido: agora sim vale perguntar se e biblioteca HTTP.
    for token, nome in _CLIENTES_HTTP:
        if token in low:
            return nome, _versao_do_token(low, token), True

    return DESCONHECIDO, "", False


def _sistema(ua: str, low: str) -> str:
    """ORDEM tambem importa: os UAs sao aninhados. Android carrega "Linux"
    junto, iOS carrega "like Mac OS X", ChromeOS carrega "X11". Vai do mais
    especifico para o mais generico."""
    if "windows phone" in low:
        m = _RE_WIN_PHONE.search(ua)
        return f"Windows Phone {m.group(1)}" if m else "Windows Phone"
    if "windows nt" in low:
        m = _RE_WIN_NT.search(ua)
        return _WINDOWS_NT.get(m.group(1), "Windows") if m else "Windows"
    if "windows" in low:
        return "Windows"
    if "android" in low:
        m = _RE_ANDROID.search(ua)
        return f"Android {m.group(1)}" if m else "Android"
    if "iphone" in low or "ipod" in low or "ipad" in low:
        # iPad em "modo desktop" (padrao desde o iPadOS 13) se anuncia como
        # Macintosh e cai no ramo de baixo — nao ha como distinguir pelo UA.
        m = _RE_IOS.search(ua)
        nome = "iPadOS" if "ipad" in low else "iOS"
        return f"{nome} {m.group(1)}" if m else nome
    if _RE_CROS.search(ua):
        return "ChromeOS"
    if "mac os x" in low or "macintosh" in low:
        m = _RE_MAC.search(ua)
        if not m:
            return "macOS"
        maior, menor = int(m.group(1)), int(m.group(2))
        # Safari e Chrome CONGELARAM esse numero em 10_15_7 a partir do macOS 11
        # (anti-fingerprint). Logo "10.15" nao quer dizer Catalina: quer dizer
        # "10.15 ou qualquer coisa mais nova". Melhor nao afirmar versao nenhuma.
        if maior == 10 and menor >= 15:
            return "macOS"
        return f"macOS {maior}" if maior >= 11 else f"macOS {maior}.{menor}"
    if "ubuntu" in low:
        return "Ubuntu Linux"
    if "linux" in low or "x11" in low:
        return "Linux"
    return DESCONHECIDO


def _dispositivo(low: str, sistema: str, e_navegador: bool) -> str:
    if any(t in low for t in ("smart-tv", "smarttv", "android tv", "appletv", "apple tv", "googletv", "crkey", "hbbtv")):
        return "TV"
    if any(t in low for t in ("ipad", "tablet", "kindle", "silk", "playbook")):
        return "Tablet"
    if any(t in low for t in ("iphone", "ipod", "windows phone", "mobile", "mobi")):
        return "Celular"
    if "android" in low:
        # Convencao do proprio Android (documentada pelo Google): o telefone manda
        # o token "Mobile" e o tablet OMITE. Como "mobile" ja foi testado acima,
        # navegador Android que chegou aqui e tablet.
        # A regra so vale para NAVEGADOR: cliente HTTP de app nativo (Dalvik/2.1.0,
        # OkHttp) nunca manda "Mobile" e nao e tablet nenhum — ali preferimos
        # admitir que nao sabemos a chutar (e sem sair por aqui cairia em "Desktop").
        return "Tablet" if e_navegador else DESCONHECIDO
    if sistema != DESCONHECIDO:
        return "Desktop"
    return DESCONHECIDO


@lru_cache(maxsize=2048)
def _interpretar(ua: str) -> tuple[str, str, str, str, bool]:
    """Cache porque a tela de auditoria lista centenas de linhas por pagina e o
    mesmo punhado de UAs se repete em quase todas. Guarda TUPLA (imutavel) de
    proposito — ver parse_user_agent()."""
    low = ua.lower()
    navegador, versao, robo = _navegador(ua, low)
    if robo:
        # Nao repetimos o disfarce: o Googlebot "smartphone" se anuncia como
        # Android/Pixel, e escrever "Android 6 · Celular" na trilha seria dar
        # aparencia de pessoa a um rastreador.
        return navegador, versao, DESCONHECIDO, "Robô", True
    sistema = _sistema(ua, low)
    return navegador, versao, sistema, _dispositivo(low, sistema, navegador != DESCONHECIDO), False


def parse_user_agent(ua: Optional[str]) -> dict:
    """Interpreta o User-Agent cru. Nunca levanta excecao.

    Devolve sempre as mesmas chaves:
      navegador   "Chrome" | "Desconhecido" | nome do robo
      versao      versao MAIOR, como texto ("120"); "" quando nao da para saber
      sistema     "Windows 10/11" | "Android 14" | "macOS" | "Desconhecido"
      dispositivo "Desktop" | "Celular" | "Tablet" | "TV" | "Robô" | "Desconhecido"
      resumo      "Chrome 120 · Windows 10/11 · Desktop" (pronto para a tela)
      bot         True quando e robo/automacao, nao pessoa

    So a versao MAIOR: a tela precisa de "que Chrome, mais ou menos", e o numero
    completo (120.0.6099.144) so acrescenta ruido e poder de fingerprint. Quem
    precisar do detalhe tem o UA cru guardado na linha.
    """
    bruto = ua if isinstance(ua, str) else ""   # do banco pode vir None
    limpo = bruto.strip()[:_LIMITE]
    if not limpo:
        return {
            "navegador": DESCONHECIDO, "versao": "", "sistema": DESCONHECIDO,
            "dispositivo": DESCONHECIDO, "resumo": DESCONHECIDO, "bot": False,
        }

    navegador, versao, sistema, dispositivo, bot = _interpretar(limpo)

    partes = []
    if navegador != DESCONHECIDO:
        partes.append(f"{navegador} {versao}".strip())
    if sistema != DESCONHECIDO:
        partes.append(sistema)
    if dispositivo != DESCONHECIDO:
        partes.append(dispositivo)

    # dict NOVO a cada chamada: o cache guarda tupla imutavel justamente para que
    # um caller que mexa no resultado nao contamine a leitura de todo mundo.
    return {
        "navegador": navegador,
        "versao": versao,
        "sistema": sistema,
        "dispositivo": dispositivo,
        "resumo": " · ".join(partes) if partes else DESCONHECIDO,
        "bot": bot,
    }


def resumir_user_agent(ua: Optional[str]) -> str:
    """Uma linha so, para colar na tabela/PDF: "Chrome 120 · Windows 10/11 · Desktop"."""
    return parse_user_agent(ua)["resumo"]
