"""
Testes do interpretador de User-Agent (services/user_agent.py).

Todos os UAs abaixo sao REAIS, copiados de trafego de verdade — UA sintetico nao
prova nada aqui, porque o problema deste modulo e justamente que os navegadores
mentem uns nos outros.

Roda sem pytest (o repo ainda nao tem suite):
    python backend/tests/test_user_agent.py
E tambem roda sob pytest, se um dia houver:
    pytest backend/tests/test_user_agent.py
"""
import os
import sys

# O backend importa como raiz ("from services.x import y"), entao o pai de
# services/ tem de estar no path — vale tanto rodando direto quanto sob pytest.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.user_agent import parse_user_agent, resumir_user_agent  # noqa: E402


# (user-agent, navegador, versao, sistema, dispositivo)
CASOS = [
    # --- Desktop -----------------------------------------------------------
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/120.0.0.0 Safari/537.36",
     "Chrome", "120", "Windows 10/11", "Desktop"),
    # Edge carrega "Chrome" E "Safari": se a ordem dos testes quebrar, este caso cai.
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.2210.91",
     "Edge", "120", "Windows 10/11", "Desktop"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/119.0.0.0 Safari/537.36 OPR/105.0.0.0",
     "Opera", "105", "Windows 10/11", "Desktop"),
    # Opera Presto: a versao esta em Version/12.14, nao no "Opera/9.80" do motor.
    ("Opera/9.80 (Windows NT 6.0) Presto/2.12.388 Version/12.14",
     "Opera", "12", "Windows Vista", "Desktop"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
     "Firefox", "121", "Windows 10/11", "Desktop"),
    ("Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/109.0.0.0 Safari/537.36",
     "Chrome", "109", "Windows 7", "Desktop"),
    # Safari de verdade: reconhecido pela AUSENCIA de Chrome/Chromium.
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
     "Version/17.2.1 Safari/605.1.15",
     "Safari", "17", "macOS", "Desktop"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/120.0.0.0 Safari/537.36",
     "Chrome", "120", "macOS", "Desktop"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:115.0) Gecko/20100101 Firefox/115.0",
     "Firefox", "115", "macOS", "Desktop"),
    ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/120.0.0.0 Safari/537.36",
     "Chrome", "120", "Linux", "Desktop"),
    ("Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0",
     "Firefox", "115", "Ubuntu Linux", "Desktop"),
    ("Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/117.0.0.0 Safari/537.36",
     "Chrome", "117", "ChromeOS", "Desktop"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/119.0.0.0 Safari/537.36 Vivaldi/6.5.3206.48",
     "Vivaldi", "6", "Windows 10/11", "Desktop"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/118.0.0.0 YaBrowser/23.11.0.0 Safari/537.36",
     "Yandex", "23", "Windows 10/11", "Desktop"),
    # Internet Explorer 11 nao diz "MSIE" — so Trident + rv.
    ("Mozilla/5.0 (Windows NT 6.1; Trident/7.0; rv:11.0) like Gecko",
     "Internet Explorer", "11", "Windows 7", "Desktop"),
    ("Mozilla/4.0 (compatible; MSIE 9.0; Windows NT 6.1; Trident/5.0)",
     "Internet Explorer", "9", "Windows 7", "Desktop"),

    # --- Celular -----------------------------------------------------------
    ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/120.0.6099.144 Mobile Safari/537.36",
     "Chrome", "120", "Android 14", "Celular"),
    # Samsung Internet: traz SamsungBrowser E Chrome E Safari no mesmo UA.
    ("Mozilla/5.0 (Linux; Android 13; SAMSUNG SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) "
     "SamsungBrowser/23.0 Chrome/115.0.0.0 Mobile Safari/537.36",
     "Samsung Internet", "23", "Android 13", "Celular"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 "
     "(KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
     "Safari", "17", "iOS 17", "Celular"),
    # Chrome no iPhone e WebKit por regra da Apple: token CriOS, e carrega "Safari".
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 "
     "(KHTML, like Gecko) CriOS/120.0.6099.119 Mobile/15E148 Safari/604.1",
     "Chrome", "120", "iOS 17", "Celular"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 "
     "(KHTML, like Gecko) FxiOS/121.0 Mobile/15E148 Safari/605.1.15",
     "Firefox", "121", "iOS 17", "Celular"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
     "(KHTML, like Gecko) EdgiOS/118.0.2088.68 Version/16.0 Mobile/15E148 Safari/604.1",
     "Edge", "118", "iOS 16", "Celular"),
    # Firefox Android nem cita "Linux" — o sistema so aparece como "Android 13".
    ("Mozilla/5.0 (Android 13; Mobile; rv:121.0) Gecko/20100101 Firefox/121.0",
     "Firefox", "121", "Android 13", "Celular"),
    ("Mozilla/5.0 (Linux; Android 13; SM-A536E) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/119.0.0.0 Mobile Safari/537.36 EdgA/119.0.2151.78",
     "Edge", "119", "Android 13", "Celular"),
    # Fabricante CUBOT: nao pode ser confundido com robo so por conter "bot".
    ("Mozilla/5.0 (Linux; Android 10; CUBOT NOTE 20) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/103.0.5060.71 Mobile Safari/537.36",
     "Chrome", "103", "Android 10", "Celular"),
    # Navegador nativo antigo do Android (WebKit, "Version/4.0").
    ("Mozilla/5.0 (Linux; U; Android 4.0.3; pt-br; GT-I9300 Build/IML74K) "
     "AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30",
     "Navegador Android", "4", "Android 4.0", "Celular"),

    # --- Tablet ------------------------------------------------------------
    ("Mozilla/5.0 (iPad; CPU OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
     "Version/16.6 Mobile/15E148 Safari/604.1",
     "Safari", "16", "iPadOS 16", "Tablet"),
    # Tablet Android: o token "Mobile" some — e so por isso que da para distinguir.
    ("Mozilla/5.0 (Linux; Android 13; SM-X710) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/119.0.0.0 Safari/537.36",
     "Chrome", "119", "Android 13", "Tablet"),

    # --- Robos e automacao -------------------------------------------------
    ("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
     "Googlebot", "2", "Desconhecido", "Robô"),
    # Googlebot "smartphone": UA de Chrome Android inteiro + assinatura no fim.
    # Se bot nao fosse testado ANTES de navegador, isto viraria "Chrome · Celular".
    ("Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/120.0.6099.71 Mobile Safari/537.36 "
     "(compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
     "Googlebot", "2", "Desconhecido", "Robô"),
    ("Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
     "Bingbot", "2", "Desconhecido", "Robô"),
    ("curl/8.4.0", "curl", "8", "Desconhecido", "Robô"),
    ("python-requests/2.31.0", "python-requests", "2", "Desconhecido", "Robô"),
    ("Wget/1.21.3", "Wget", "1", "Desconhecido", "Robô"),
    ("Mozilla/5.0+(compatible; UptimeRobot/2.0; http://www.uptimerobot.com/)",
     "UptimeRobot", "2", "Desconhecido", "Robô"),
    ("WhatsApp/2.23.20.0 A", "WhatsApp (prévia de link)", "2", "Desconhecido", "Robô"),
    ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "HeadlessChrome/120.0.6099.109 Safari/537.36",
     "Chrome sem interface (automação)", "120", "Desconhecido", "Robô"),
    # Robo fora da lista, pego pela rede de seguranca generica.
    ("Mozilla/5.0 (compatible; SuperNovoBot/1.4; +http://exemplo.com/bot)",
     "Robô não identificado", "", "Desconhecido", "Robô"),
    ("Java/1.8.0_181", "Java", "1", "Desconhecido", "Robô"),
    ("okhttp/4.9.3", "OkHttp", "4", "Desconhecido", "Robô"),

    # --- Biblioteca HTTP pendurada em UA de gente -------------------------
    # O plugin da Java pendurava "Java/1.6.0_23" no fim do UA do IE. E gente
    # sentada na frente da tela, em maquina antiga de prefeitura: tem de sair
    # "Internet Explorer 8 · Windows 7 · Desktop", nao "Java · Robô" (que ainda
    # por cima jogava fora sistema e dispositivo do acesso humano).
    ("Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 6.1; Trident/4.0; .NET CLR 2.0.50727; "
     "Java/1.6.0_23)",
     "Internet Explorer", "8", "Windows 7", "Desktop"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/120.0.0.0 Safari/537.36 OkHttp/4.9.3",
     "Chrome", "120", "Windows 10/11", "Desktop"),

    # --- Nao e navegador, mas tambem nao e robo ----------------------------
    # Cliente HTTP de app nativo Android. Nao manda "Mobile", e a regra
    # "Android sem Mobile = tablet" so vale para navegador: aqui o honesto e
    # admitir que nao sabemos o dispositivo (ja apareceu como "Tablet" e como
    # "Desktop" antes da guarda).
    ("Dalvik/2.1.0 (Linux; U; Android 11; Redmi Note 8 MIUI/V12.5.4.0)",
     "Desconhecido", "", "Android 11", "Desconhecido"),

    # --- Lixo, vazio, ilegivel --------------------------------------------
    ("", "Desconhecido", "", "Desconhecido", "Desconhecido"),
    ("   ", "Desconhecido", "", "Desconhecido", "Desconhecido"),
    ("-", "Desconhecido", "", "Desconhecido", "Desconhecido"),
    ("asdkjhasd", "Desconhecido", "", "Desconhecido", "Desconhecido"),
    ("Mozilla/5.0", "Desconhecido", "", "Desconhecido", "Desconhecido"),
]


def test_casos_reais():
    erros = []
    for ua, navegador, versao, sistema, dispositivo in CASOS:
        got = parse_user_agent(ua)
        esperado = {"navegador": navegador, "versao": versao,
                    "sistema": sistema, "dispositivo": dispositivo}
        real = {k: got[k] for k in esperado}
        if real != esperado:
            erros.append(f"\n  UA: {ua[:90]}\n  esperado {esperado}\n  obtido   {real}")
    assert not erros, "".join(erros)


def test_nao_estoura_com_entrada_absurda():
    """UA e texto de terceiro: pode vir None, vazio, binario ou gigante."""
    for entrada in (None, "", " ", 12345, b"bytes", object(), "\x00\x01\x02",
                    "A" * 20000, "Mozilla/5.0 (" * 3000, "<script>alert(1)</script>"):
        r = parse_user_agent(entrada)
        assert set(r) == {"navegador", "versao", "sistema", "dispositivo", "resumo", "bot"}
        assert isinstance(r["resumo"], str) and r["resumo"]


def test_resumo_formatado():
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/120.0.0.0 Safari/537.36")
    assert resumir_user_agent(ua) == "Chrome 120 · Windows 10/11 · Desktop"
    assert resumir_user_agent(None) == "Desconhecido"
    # Sem sistema conhecido, o resumo nao mostra "Desconhecido" no meio da frase.
    assert resumir_user_agent("curl/8.4.0") == "curl 8 · Robô"


def test_bot_marcado():
    assert parse_user_agent("curl/8.4.0")["bot"] is True
    assert parse_user_agent(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36")["bot"] is False


def test_resultado_nao_e_compartilhado():
    """O cache guarda tupla; cada chamada devolve dict novo. Se vazasse o dict
    cacheado, um caller que mexesse nele estragaria a leitura de todo mundo."""
    ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    a = parse_user_agent(ua)
    a["navegador"] = "ADULTERADO"
    assert parse_user_agent(ua)["navegador"] == "Chrome"


def test_automacao_vence_o_navegador():
    """Contraparte do teste acima: biblioteca HTTP perde para o navegador, mas
    assinatura de AUTOMACAO nao — ela so aparece junto com UA de navegador
    completo (o script dirige o Chrome), e ali o fato a registrar e o script."""
    base = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "HeadlessChrome/120.0.6099.109 Safari/537.36")
    assert parse_user_agent(base)["bot"] is True
    # E o rastreador continua vencendo o UA de navegador que ele copia inteiro.
    disfarce = ("Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.6099.71 Mobile Safari/537.36 "
                "(compatible; Googlebot/2.1; +http://www.google.com/bot.html)")
    assert parse_user_agent(disfarce)["navegador"] == "Googlebot"


def test_custo_nao_explode_com_ua_hostil():
    """O UA e cabecalho de terceiro e entra na trilha ATE em login.fail, sem
    autenticar: quem quiser pode plantar 500 chars escolhidos a dedo e depois a
    tela de auditoria paga o custo em CADA linha listada. Ja houve regressao
    aqui: um `[\\w.+-]*` decorativo na frente da regra generica de robo (que nem
    restringia nada, por casar vazio) custava 2,5 ms por UA em vez de 0,01 ms.
    Teto folgado de proposito — o que se quer pegar e ordem de grandeza."""
    import time
    hostis = [("a" * 400) + "bo" + str(i) for i in range(300)]  # nunca casam
    inicio = time.perf_counter()
    for ua in hostis:
        parse_user_agent(ua)
    ms = (time.perf_counter() - inicio) * 1000 / len(hostis)
    assert ms < 1.0, f"{ms:.2f} ms por user-agent hostil — regra com backtracking?"


def test_marca_propria_vence_o_token_chrome():
    """Regressao da ordem: todo navegador Chromium carrega "Chrome" e "Safari".
    Se alguem reordenar a tabela, o usuario de Edge vira usuario de Chrome."""
    base = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36 ")
    for sufixo, nome in (("Edg/120.0.0.0", "Edge"), ("OPR/106.0.0.0", "Opera"),
                         ("Brave/1.60", "Brave"), ("Vivaldi/6.5", "Vivaldi")):
        assert parse_user_agent(base + sufixo)["navegador"] == nome, sufixo
    # E o Chrome puro continua Chrome (o Brave atual cai aqui de proposito:
    # ele removeu a propria marca do UA e e indistinguivel).
    assert parse_user_agent(base)["navegador"] == "Chrome"


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok    {nome}")
            except AssertionError as e:
                falhas += 1
                print(f"FALHA {nome}: {e}")
    print(f"\n{'FALHOU' if falhas else 'PASSOU'} — {len(CASOS)} user-agents reais, {falhas} falha(s)")
    raise SystemExit(1 if falhas else 0)
