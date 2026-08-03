"""
Tabela-verdade de services/net.py::client_ip.

Rodar (pytest nao esta no requirements.txt da imagem, e dev-only):
    pip install pytest
    python -m pytest backend/tests/test_net.py -v

Convencao dos casos: o cabecalho X-Forwarded-For e escrito da ESQUERDA (o que o
cliente mandou, forjavel) para a DIREITA (o que cada proxy da nossa infra
acrescentou). O `peer` e o IP de container do Traefik, que a API enxerga como
origem TCP. A resposta correta e sempre o hop imediatamente antes dos N proxies
confiaveis, contado da direita.
"""
import pytest

from services.net import client_ip, normalizar_ip, proxies_confiaveis


class _Headers(dict):
    """Imita o Headers do Starlette no unico ponto que importa: get() e
    case-insensitive (o cliente pode mandar `X-Forwarded-For` com maiusculas)."""
    def __init__(self, bruto: dict):
        super().__init__({k.lower(): v for k, v in bruto.items()})

    def get(self, chave, default=None):
        return super().get(chave.lower(), default)


class _HeadersMulti:
    """Imita o Headers do Starlette quando o MESMO cabecalho vem em varias
    linhas: `get()` devolve so a primeira, `getlist()` devolve todas."""
    def __init__(self, valores: list):
        self._valores = list(valores)

    def get(self, chave, default=None):
        if chave.lower() != "x-forwarded-for":
            return default
        return self._valores[0] if self._valores else default

    def getlist(self, chave):
        return list(self._valores) if chave.lower() == "x-forwarded-for" else []


class _Peer:
    def __init__(self, host):
        self.host = host


class FakeRequest:
    def __init__(self, xff=None, peer="10.0.1.5"):
        self.headers = _Headers({} if xff is None else {"X-Forwarded-For": xff})
        self.client = _Peer(peer) if peer is not None else None


CLIENTE = "200.1.1.1"       # o IP que a auditoria tem de gravar
TRAEFIK = "10.0.1.5"        # peer TCP visto pela API
CDN = "198.51.100.9"        # segundo proxy, quando houver


CASOS = [
    # (id, xff, peer, trusted_proxies, esperado)

    # --- 1 proxy (producao de hoje: Traefik do Coolify) ---
    ("um_proxy", CLIENTE, TRAEFIK, 1, CLIENTE),

    # O defeito que motivou o arquivo: cliente forja o cabecalho e o Traefik
    # ACRESCENTA o IP real ao final. O codigo antigo devolvia "1.2.3.4".
    ("um_proxy_forjado", f"1.2.3.4, {CLIENTE}", TRAEFIK, 1, CLIENTE),

    # Empilhar lixo a esquerda nao desloca a resposta (conta e pela direita).
    ("um_proxy_forjado_com_enchimento",
     f"1.2.3.4, 5.6.7.8, 9.9.9.9, {CLIENTE}", TRAEFIK, 1, CLIENTE),

    # Token invalido ("unknown") tambem nao desloca: ocupa a vaga dele.
    ("um_proxy_token_invalido_no_prefixo",
     f"unknown, {CLIENTE}", TRAEFIK, 1, CLIENTE),

    # --- 2 proxies (se entrar CDN/WAF na frente do Traefik) ---
    ("dois_proxies", f"{CLIENTE}, {CDN}", TRAEFIK, 2, CLIENTE),
    ("dois_proxies_forjado", f"1.2.3.4, {CLIENTE}, {CDN}", TRAEFIK, 2, CLIENTE),

    # A mesma requisicao de 2 proxies lida com N=1 devolve o CDN, nao o cliente:
    # e o lembrete de que TRUSTED_PROXIES tem de espelhar a infra real.
    ("dois_proxies_lidos_como_um", f"{CLIENTE}, {CDN}", TRAEFIK, 1, CDN),

    # --- 0 proxies (dev/local, ou API exposta sem proxy) ---
    # Com N=0 o cabecalho e inteiramente ignorado: vale so a conexao TCP.
    ("zero_proxies_ignora_cabecalho", f"1.2.3.4, {CLIENTE}", "127.0.0.1", 0, "127.0.0.1"),

    # --- cabecalho ausente ---
    ("header_ausente", None, TRAEFIK, 1, TRAEFIK),
    ("header_vazio", "", TRAEFIK, 1, TRAEFIK),
    ("header_so_virgulas", " , ,", TRAEFIK, 1, TRAEFIK),

    # --- IPv6 ---
    ("ipv6", "1.2.3.4, 2001:db8::1", TRAEFIK, 1, "2001:db8::1"),
    ("ipv6_forma_longa_normalizada", "2001:0db8:0000:0000:0000:0000:0000:0001",
     TRAEFIK, 1, "2001:db8::1"),
    ("ipv6_com_colchetes_e_porta", "[2001:db8::1]:54321", TRAEFIK, 1, "2001:db8::1"),
    ("ipv6_mapeando_ipv4", "::ffff:200.1.1.1", TRAEFIK, 1, CLIENTE),
    ("peer_ipv6", None, "2001:db8::99", 1, "2001:db8::99"),

    # --- ruido de formatacao ---
    ("espacos_sobrando", f"   1.2.3.4  ,   {CLIENTE}   ", TRAEFIK, 1, CLIENTE),
    ("ipv4_com_porta", f"1.2.3.4, {CLIENTE}:44321", TRAEFIK, 1, CLIENTE),

    # --- menos itens do que proxies confiaveis ---
    # Cadeia mais curta que o declarado (CDN fora do ar, healthcheck interno...):
    # sem margem para descontar, sobra o hop mais antigo conhecido.
    ("menos_itens_que_proxies", CLIENTE, TRAEFIK, 2, CLIENTE),
    ("menos_itens_que_proxies_sem_header", None, TRAEFIK, 3, TRAEFIK),

    # --- origem indeterminada: None, nunca um chute ---
    ("valor_invalido_na_posicao_alvo", "1.2.3.4, unknown", TRAEFIK, 1, None),
    ("sem_header_e_sem_peer", None, None, 1, None),
    ("peer_ilegivel_sem_header", None, "testclient", 1, None),
]


@pytest.mark.parametrize(
    "xff,peer,n,esperado",
    [c[1:] for c in CASOS],
    ids=[c[0] for c in CASOS],
)
def test_client_ip(xff, peer, n, esperado):
    assert client_ip(FakeRequest(xff, peer), trusted_proxies=n) == esperado


def test_peer_ilegivel_nao_encurta_a_cadeia():
    """TestClient/socket unix poem um peer que nao e IP. Ele tem de continuar
    ocupando o ultimo lugar da cadeia, senao o indice anda e a resposta vira o
    item forjado."""
    req = FakeRequest(f"1.2.3.4, {CLIENTE}", peer="testclient")
    assert client_ip(req, trusted_proxies=1) == CLIENTE


def test_varias_linhas_do_mesmo_cabecalho_contam_todas():
    """O cliente manda o proprio X-Forwarded-For e o proxy ACRESCENTA outra
    linha em vez de reescrever a existente. Ler so a primeira (o que
    `headers.get()` faz) encurtaria a cadeia e o indice contado da direita
    cairia em cima do item forjado — que e exatamente o ataque que este arquivo
    existe para impedir."""
    req = FakeRequest()
    req.headers = _HeadersMulti(["1.2.3.4", CLIENTE])
    assert client_ip(req, trusted_proxies=1) == CLIENTE


def test_varias_linhas_com_lista_em_cada_uma():
    req = FakeRequest()
    req.headers = _HeadersMulti(["1.2.3.4, 5.6.7.8", f"{CLIENTE}, {CDN}"])
    assert client_ip(req, trusted_proxies=2) == CLIENTE
    assert client_ip(req, trusted_proxies=1) == CDN


def test_usa_env_quando_nao_recebe_parametro(monkeypatch):
    req = FakeRequest(f"1.2.3.4, {CLIENTE}, {CDN}", TRAEFIK)
    monkeypatch.setenv("TRUSTED_PROXIES", "2")
    assert client_ip(req) == CLIENTE
    monkeypatch.setenv("TRUSTED_PROXIES", "1")
    assert client_ip(req) == CDN


@pytest.mark.parametrize("valor,esperado", [
    ("", 1),          # default de fabrica = Traefik do Coolify
    ("   ", 1),
    ("2", 2),
    ("0", 0),         # sem proxy: vale so a conexao TCP
    ("abc", 1),       # env digitada errada nao pode virar "confia em tudo"
    ("-1", 1),
    (" 3 ", 3),
])
def test_proxies_confiaveis(monkeypatch, valor, esperado):
    monkeypatch.setenv("TRUSTED_PROXIES", valor)
    assert proxies_confiaveis() == esperado


def test_proxies_confiaveis_sem_env(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    assert proxies_confiaveis() == 1


@pytest.mark.parametrize("valor,esperado", [
    ("200.1.1.1", "200.1.1.1"),
    (" 200.1.1.1 ", "200.1.1.1"),
    ("200.1.1.1:8080", "200.1.1.1"),
    ("2001:0db8::0001", "2001:db8::1"),
    ("[2001:db8::1]", "2001:db8::1"),
    ("[2001:db8::1]:443", "2001:db8::1"),
    ("::ffff:200.1.1.1", "200.1.1.1"),   # mesmo cliente, uma linha so na trilha
    ("[2001:db8::1", None),              # colchete sem fechar
    ("unknown", None),
    ("", None),
    (None, None),
    ("200.1.1.999", None),
    ("nao-e-ip", None),
    ("200.1.1.1/24", None),              # CIDR nao e endereco
])
def test_normalizar_ip(valor, esperado):
    assert normalizar_ip(valor) == esperado
