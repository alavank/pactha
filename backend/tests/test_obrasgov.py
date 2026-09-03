"""
Obras.gov.br / CIPI — os testes existem por três medições que contradizem o que
a resposta da API parece dizer.

Todas de 02/09/2026, contra `uf=RS`:

  (a) A PAGINAÇÃO MENTE PARA O LADO PERIGOSO. `last` volta `true` em TODA
      página, e `totalElements`/`totalPages` são derivados da página pedida — a
      página 0 informa "200 elementos, 1 página" e a página 1 informa "400, 2".
      Um coletor que confiasse neles pararia na primeira e afirmaria ter todas
      as obras do estado.

  (b) AS PÁGINAS SE SOBREPÕEM: 41 dos 200 itens da página 1 já estavam na
      página 0. Sem dedup, a contagem infla.

  (c) 429 VEM COM CORPO VAZIO, e não pode virar "acabou". Foi assim que a
      varredura de reconhecimento parou na página 2 e produziu o falso
      "Nova Palma: 0 obras" — que este arquivo existe para nunca mais acontecer.

E uma quarta, que é de modelagem: o município NÃO vem da fonte. O vínculo é por
CNPJ de tomador/executor, e códigos SIAFI curtos (36210) não podem ser
confundidos com CNPJ.

Rodar:
    python -m pytest backend/tests/test_obrasgov.py -v
"""
import pytest

import ingestion.obrasgov as obrasgov
from ingestion.obrasgov import cnpjs_do_projeto, linha, varrer_uf


class _Resposta:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")


class ClienteFalso:
    """Serve páginas POR NÚMERO, e registra o que foi pedido.

    ⚠️ A indexação é por `pagina` e não pela ordem das chamadas, porque o
    backoff do 429 REPETE o mesmo número de página. Um dublê que servisse a
    lista em sequência devolveria a página seguinte no retry — e o teste passaria
    por um motivo que a fonte real não tem.

    Uma entrada pode ser uma LISTA DE TENTATIVAS (`[429, [obra]]` = a primeira
    chamada àquela página leva 429, a segunda responde), que é como se modela um
    rate limit passageiro."""

    def __init__(self, paginas):
        self.paginas = paginas
        self.pedidos: list[int] = []
        self.tentativas: dict[int, int] = {}

    def get(self, url, params=None, **kw):
        n = (params or {}).get("pagina", 0)
        self.pedidos.append(n)
        if n >= len(self.paginas):
            return _Resposta({"content": []})
        p = self.paginas[n]
        if isinstance(p, list) and p and all(
                x == 429 or isinstance(x, list) for x in p):
            i = self.tentativas.get(n, 0)
            self.tentativas[n] = i + 1
            p = p[min(i, len(p) - 1)]
        if p == 429:
            return _Resposta(None, status=429)
        # A fonte SEMPRE diz last=true e deriva o total da página pedida — é a
        # armadilha (a), reproduzida fielmente.
        return _Resposta({
            "content": p, "last": True,
            "totalElements": (n + 1) * 200, "totalPages": n + 1, "number": n,
        })


@pytest.fixture(autouse=True)
def _sem_espera(monkeypatch):
    """Os backoffs são de 30 a 120 s na vida real. O teste mede a LÓGICA."""
    monkeypatch.setattr(obrasgov.time, "sleep", lambda _s: None)


def _obra(uid, cnpj=None, codigo_siafi=None, nome="Obra"):
    tomadores = []
    if cnpj:
        tomadores.append({"nome": "FUNDO MUNICIPAL", "codigo": cnpj})
    if codigo_siafi:
        tomadores.append({"nome": "ORGAO FEDERAL", "codigo": codigo_siafi})
    return {"idUnico": uid, "nome": nome, "uf": "RS", "tomadores": tomadores,
            "fontesDeRecurso": [{"origem": "Federal", "valorInvestimentoPrevisto": 100.0}]}


# ---------------------------------------------------------------------------
# (a) e (b) — paginação
# ---------------------------------------------------------------------------
def test_nao_para_na_primeira_pagina_apesar_de_last_true():
    """A página 0 diz `last: true` e `totalPages: 1`. Há mais três páginas."""
    cli = ClienteFalso([[_obra("a")], [_obra("b")], [_obra("c")], []])
    projetos, completo = varrer_uf(cli, "RS")
    assert set(projetos) == {"a", "b", "c"}
    assert completo is True


def test_deduplica_paginas_que_se_sobrepoem():
    """41 de 200 repetiam, na medição real. Aqui, 2 de 3."""
    cli = ClienteFalso([[_obra("a"), _obra("b")],
                        [_obra("b"), _obra("c")],   # 'b' repete
                        []])
    projetos, completo = varrer_uf(cli, "RS")
    assert set(projetos) == {"a", "b", "c"}
    assert completo is True


def test_para_depois_de_duas_paginas_sem_nada_novo():
    """Quando a fonte passa a repetir, a varredura acabou — mas UMA página
    repetida não basta, porque a ordenação instável faz isso acontecer no meio."""
    cli = ClienteFalso([[_obra("a")], [_obra("a")], [_obra("a")],
                        [_obra("z")]])   # nunca deve ser alcançada
    projetos, _ = varrer_uf(cli, "RS")
    assert set(projetos) == {"a"}
    assert cli.pedidos == [0, 1, 2], cli.pedidos


def test_uma_pagina_repetida_nao_encerra_a_varredura():
    cli = ClienteFalso([[_obra("a")], [_obra("a")], [_obra("b")], []])
    projetos, _ = varrer_uf(cli, "RS")
    assert set(projetos) == {"a", "b"}


# ---------------------------------------------------------------------------
# (c) — 429 não é "acabou"
# ---------------------------------------------------------------------------
def test_429_persistente_devolve_parcial_e_nao_sucesso():
    """⚠️ O TESTE MAIS IMPORTANTE DESTE ARQUIVO. Foi exatamente isto que
    produziu o falso "Nova Palma: 0 obras" no reconhecimento: a varredura parou
    por rate limit e o número foi lido como resultado. `completo=False` é o que
    faz a rodada sair `partial` em vez de `success`."""
    cli = ClienteFalso([[_obra("a")], 429, 429, 429, 429])
    projetos, completo = varrer_uf(cli, "RS")
    assert set(projetos) == {"a"}
    assert completo is False, "429 persistente foi tratado como fim da varredura"


def test_429_passageiro_e_superado_pelo_backoff():
    """A página 1 leva 429 na primeira tentativa e responde na segunda — foi o
    que aconteceu na medição real (3 s levava 429; 20 s passava). A varredura
    tem de continuar e terminar COMPLETA."""
    cli = ClienteFalso([[_obra("a")], [429, [_obra("b")]], []])
    projetos, completo = varrer_uf(cli, "RS")
    assert set(projetos) == {"a", "b"}
    assert completo is True
    assert cli.tentativas[1] == 2, "o backoff não repetiu a mesma página"


def test_pagina_vazia_encerra_sem_marcar_parcial():
    cli = ClienteFalso([[_obra("a")], []])
    projetos, completo = varrer_uf(cli, "RS")
    assert set(projetos) == {"a"} and completo is True


# ---------------------------------------------------------------------------
# O vínculo com o município é NOSSO, e sai do CNPJ
# ---------------------------------------------------------------------------
def test_codigo_siafi_curto_nao_e_confundido_com_cnpj():
    """Órgão federal vem com código SIAFI/UG curto (36210 = Hospital Nossa
    Senhora da Conceição). Tratá-lo como documento casaria obra de qualquer
    município com qualquer outro."""
    assert cnpjs_do_projeto(_obra("x", codigo_siafi="36210")) == set()
    assert cnpjs_do_projeto(_obra("y", cnpj="11413650000185")) == {"11413650000185"}


def test_cnpj_com_mascara_e_normalizado():
    p = {"tomadores": [{"codigo": "11.413.650/0001-85"}], "executores": []}
    assert cnpjs_do_projeto(p) == {"11413650000185"}


def test_projeto_sem_tomador_nao_quebra():
    assert cnpjs_do_projeto({"idUnico": "z"}) == set()


# ---------------------------------------------------------------------------
# Montagem da linha
# ---------------------------------------------------------------------------
def test_valor_soma_as_origens_de_recurso():
    """A fonte traz uma linha por origem; a tela quer o investimento total."""
    p = {"idUnico": "a", "fontesDeRecurso": [
        {"origem": "Federal", "valorInvestimentoPrevisto": 1000.0},
        {"origem": "Municipal", "valorInvestimentoPrevisto": 250.5},
    ]}
    m = linha(1, p)
    assert m["valor"] == 1250.5
    assert m["origens"] == ["Federal", "Municipal"]


def test_sem_fonte_de_recurso_o_valor_e_nulo_e_nao_zero():
    """Obra sem valor declarado não é obra de graça — é obra sem valor
    declarado. Zero na tela seria uma afirmação que a fonte não faz."""
    m = linha(1, {"idUnico": "a", "fontesDeRecurso": []})
    assert m["valor"] is None


def test_data_efetiva_nula_continua_nula():
    """⚠️ Nulo aqui é 'ainda não aconteceu', e é o que denuncia obra parada.
    Preencher com a data prevista apagaria exatamente esse sinal."""
    m = linha(1, {"idUnico": "a", "dataInicialPrevista": "2024-11-05",
                  "dataInicialEfetiva": None, "fontesDeRecurso": []})
    assert m["dt_ini_prev"] == "2024-11-05"
    assert m["dt_ini_efe"] is None
