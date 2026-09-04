"""
Obras.gov.br / CIPI — os testes das armadilhas que a MEDIÇÃO confirmou.

⚠️ Este arquivo foi reescrito em 04/09/2026, quando o coletor trocou de host
(`api.obrasgov.gestao.gov.br` → `api-publica.obrasgov.gestao.gov.br/obras`,
porque o primeiro recusa o IP da VPS). A medição contra o host novo desmentiu
TRÊS das quatro armadilhas que este arquivo guardava:

  paginação mente (`last` sempre true) ..... NÃO: `total_items` constante
  páginas se sobrepõem (41 de 200) ......... NÃO: zero repetidos, ordem estável
  rate limit apertado (3 s → 429) .......... NÃO: 12 requisições sem pausa, 0 erro

Os testes daquelas três não foram apagados: foram **substituídos** pelos das
armadilhas que a mesma medição encontrou no host novo — o filtro territorial que
não existe e é ignorado em silêncio, os nomes de campo que mudaram todos, e o
`sistema_resp`, que revela obra que outro coletor nosso já traz. A rede do 429
continua testada porque continua no código: a medição de hoje não promete o
comportamento de amanhã.

E permanece a armadilha de modelagem, hoje diretriz do dono: o município NÃO vem
da fonte, sai do **CNPJ** de tomador/executor, e nunca do nome — casar por nome
trouxe 379 obras da UFSM como se fossem da prefeitura de Santa Maria.

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

    ⚠️ A indexação é por `pagina` e não pela ordem das chamadas, porque o backoff
    do 429 REPETE o mesmo número de página. Um dublê que servisse a lista em
    sequência devolveria a página seguinte no retry — e o teste passaria por um
    motivo que a fonte real não tem.

    ⚠️ E a paginação da API nova começa em **1**, não em 0. Um dublê indexado a
    partir de 0 esconderia justamente o erro de quem pulasse a primeira página.

    Uma entrada pode ser uma LISTA DE TENTATIVAS (`[429, [obra]]` = a primeira
    chamada àquela página leva 429, a segunda responde), que é como se modela um
    rate limit passageiro."""

    def __init__(self, paginas):
        self.paginas = paginas
        self.pedidos: list[int] = []
        self.params: list[dict] = []
        self.tentativas: dict[int, int] = {}

    def get(self, url, params=None, **kw):
        params = params or {}
        n = params.get("pagina", 1)
        self.pedidos.append(n)
        self.params.append(dict(params))
        if n < 1 or n > len(self.paginas):
            return _Resposta({"data": [], "total_pages": len(self.paginas),
                              "total_items": 0, "page_number": n})
        p = self.paginas[n - 1]
        if isinstance(p, list) and p and all(
                x == 429 or isinstance(x, list) for x in p):
            i = self.tentativas.get(n, 0)
            self.tentativas[n] = i + 1
            p = p[min(i, len(p) - 1)]
        if p == 429:
            return _Resposta(None, status=429)
        # O envelope da API nova: `data`, e um total que NÃO depende da página
        # pedida (medido: constante em qualquer página e tamanho).
        return _Resposta({
            "data": p, "total_pages": len(self.paginas),
            "total_items": sum(len(x) for x in self.paginas if isinstance(x, list)),
            "page_number": n, "page_size": obrasgov.TAMANHO_PAGINA,
        })


@pytest.fixture(autouse=True)
def _sem_espera(monkeypatch):
    """Os backoffs são de 15 a 90 s na vida real. O teste mede a LÓGICA."""
    monkeypatch.setattr(obrasgov.time, "sleep", lambda _s: None)


def _obra(uid, cnpj=None, codigo_siafi=None, nome="Obra", executor=None):
    tomadores = []
    if cnpj:
        tomadores.append({"organizacao_tomador": "FUNDO MUNICIPAL",
                          "cnpj_tomador": cnpj})
    if codigo_siafi:
        tomadores.append({"organizacao_tomador": "ORGAO FEDERAL",
                          "cnpj_tomador": codigo_siafi})
    executores = ([{"organizacao_executor": "EXECUTOR", "cnpj_executor": executor}]
                  if executor else [])
    return {"id_projeto_investimento": uid, "desc_nome": nome,
            "uf_principal": "RS", "tomadores": tomadores, "executores": executores,
            "investimentos_previstos": [
                {"desc_nome_fonte_recurso": "Federal",
                 "vl_investimento_previsto": 100.0}]}


# ---------------------------------------------------------------------------
# Paginação — `total_pages` agora é confiável, e é ele que manda
# ---------------------------------------------------------------------------
def test_percorre_todas_as_paginas_ate_total_pages():
    cli = ClienteFalso([[_obra("a")], [_obra("b")], [_obra("c")]])
    projetos, completo = varrer_uf(cli, "RS")
    assert set(projetos) == {"a", "b", "c"}
    assert completo is True
    assert cli.pedidos == [1, 2, 3], cli.pedidos


def test_a_paginacao_comeca_em_1_e_nao_em_0():
    """⚠️ Começar em 0 custaria a PRIMEIRA página inteira — 200 obras somem e a
    varredura ainda se declara completa, porque `total_pages` bate."""
    cli = ClienteFalso([[_obra("primeira")], [_obra("b")]])
    projetos, _ = varrer_uf(cli, "RS")
    assert "primeira" in projetos
    assert cli.pedidos[0] == 1, "a primeira página pedida não foi a 1"


def test_nao_pede_pagina_depois_de_total_pages():
    """Pedir além do fim custa requisição e, em outra fonte, custaria erro."""
    cli = ClienteFalso([[_obra("a")], [_obra("b")]])
    varrer_uf(cli, "RS")
    assert max(cli.pedidos) == 2, cli.pedidos


def test_dedup_sobrevive_a_ordenacao_instavel():
    """A medição não achou repetição no host novo — mas o dedup custa nada e é
    o que separa 'a ordenação mudou' de 'a contagem inflou'."""
    cli = ClienteFalso([[_obra("a"), _obra("b")],
                        [_obra("b"), _obra("c")]])   # 'b' repete
    projetos, completo = varrer_uf(cli, "RS")
    assert set(projetos) == {"a", "b", "c"}
    assert completo is True


def test_pagina_vazia_encerra_sem_marcar_parcial():
    cli = ClienteFalso([[_obra("a")], []])
    projetos, completo = varrer_uf(cli, "RS")
    assert set(projetos) == {"a"} and completo is True


# ---------------------------------------------------------------------------
# ⚠️ Armadilha 1 — NÃO EXISTE FILTRO TERRITORIAL, e parâmetro desconhecido
# devolve HTTP 200 com o estado inteiro
# ---------------------------------------------------------------------------
def test_so_manda_os_parametros_que_o_contrato_tem():
    """⚠️ Medido em 04/09/2026: `codigo_ibge=4313102` devolve `total_items`
    IDÊNTICO ao da consulta sem filtro — a fonte ignora em silêncio. Quem
    acrescentasse esse parâmetro aqui acharia que recortou o município e gravaria
    obra do Amapá. O recorte é feito por CNPJ, em memória, e este teste existe
    para que ninguém 'otimize' isso de volta."""
    cli = ClienteFalso([[_obra("a")]])
    varrer_uf(cli, "RS")
    assert set(cli.params[0]) == {"uf_principal", "pagina", "tamanho_da_pagina"}


def test_tamanho_da_pagina_respeita_o_teto_da_fonte():
    """201 devolve 422 (medido). O teto tem de valer mesmo com env var maior."""
    assert obrasgov.TAMANHO_PAGINA <= 200
    cli = ClienteFalso([[_obra("a")]])
    varrer_uf(cli, "RS")
    assert cli.params[0]["tamanho_da_pagina"] <= 200


# ---------------------------------------------------------------------------
# 429 — a rede continua, porque o código dela continua
# ---------------------------------------------------------------------------
def test_429_persistente_devolve_parcial_e_nao_sucesso():
    """⚠️ Rate limit não é fim de varredura. Foi lendo 429 como resultado que o
    reconhecimento produziu o falso "Nova Palma: 0 obras". `completo=False` é o
    que faz a rodada sair `partial` em vez de `success` — e é a diferença entre
    "o município não tem obra" e "nós não conseguimos ver"."""
    cli = ClienteFalso([[_obra("a")], 429, 429])
    projetos, completo = varrer_uf(cli, "RS")
    assert set(projetos) == {"a"}
    assert completo is False, "429 persistente foi tratado como fim da varredura"


def test_429_passageiro_e_superado_pelo_backoff():
    cli = ClienteFalso([[_obra("a")], [429, [_obra("b")]]])
    projetos, completo = varrer_uf(cli, "RS")
    assert set(projetos) == {"a", "b"}
    assert completo is True
    assert cli.tentativas[2] == 2, "o backoff não repetiu a mesma página"


# ---------------------------------------------------------------------------
# ⚠️ Armadilha 2 — o município sai do CNPJ, nunca do nome
# ---------------------------------------------------------------------------
def test_codigo_siafi_curto_nao_e_confundido_com_cnpj():
    """Órgão federal vem com código SIAFI/UG curto (36210 = Hospital Nossa
    Senhora da Conceição). Tratá-lo como documento casaria obra de qualquer
    município com qualquer outro."""
    assert cnpjs_do_projeto(_obra("x", codigo_siafi="36210")) == set()
    assert cnpjs_do_projeto(_obra("y", cnpj="11413650000185")) == {"11413650000185"}


def test_le_o_campo_certo_de_cada_lista():
    """⚠️ Tomador e executor têm nomes de campo DIFERENTES (`cnpj_tomador`,
    `cnpj_executor`) — não há um `codigo` genérico como na API antiga. Ler o
    nome errado devolve conjunto vazio e o município fica sem NENHUMA obra, sem
    erro nenhum no log."""
    p = _obra("z", cnpj="11413650000185", executor="92963560000160")
    assert cnpjs_do_projeto(p) == {"11413650000185", "92963560000160"}


def test_cnpj_com_mascara_e_normalizado():
    p = {"tomadores": [{"cnpj_tomador": "11.413.650/0001-85"}], "executores": []}
    assert cnpjs_do_projeto(p) == {"11413650000185"}


def test_projeto_sem_tomador_nao_quebra():
    assert cnpjs_do_projeto({"id_projeto_investimento": "z"}) == set()


# ---------------------------------------------------------------------------
# Montagem da linha — TODOS os nomes de campo mudaram com o host
# ---------------------------------------------------------------------------
def test_le_os_nomes_novos_dos_campos():
    """⚠️ `nome` → `desc_nome`, `descricao` → `desc_projeto`, `uf` →
    `uf_principal`, `qdtEmpregosGerados` → `qtd_empregos_gerados`. Ler um nome
    antigo devolve `None` sem erro: a linha grava vazia e ninguém percebe."""
    m = linha(1, {"id_projeto_investimento": "53409.43-83",
                  "desc_nome": "Ponte sobre o Arroio",
                  "desc_projeto": "Reconstrução",
                  "desc_funcao_social": "Escoamento da produção",
                  "desc_meta_global": "120 m de ponte",
                  "natureza_intervencao": "Obra", "especie_intervencao": "Construção",
                  "uf_principal": "RS", "nr_cep": "97250000",
                  "desc_endereco": "RS-149, km 12",
                  "qtd_empregos_gerados": 40, "populacao_beneficiada": 6300})
    assert m["uid"] == "53409.43-83"
    assert m["nome"] == "Ponte sobre o Arroio"
    assert m["desc"] == "Reconstrução"
    assert m["social"] == "Escoamento da produção"
    assert m["meta"] == "120 m de ponte"
    assert m["natureza"] == "Obra" and m["especie"] == "Construção"
    assert m["uf"] == "RS" and m["cep"] == "97250000"
    assert m["end"] == "RS-149, km 12"
    assert m["empregos"] == 40 and m["pop"] == 6300


def test_valor_soma_as_origens_de_recurso():
    """A fonte traz uma linha por origem; a tela quer o investimento total."""
    p = {"id_projeto_investimento": "a", "investimentos_previstos": [
        {"desc_nome_fonte_recurso": "Federal", "vl_investimento_previsto": 1000.0},
        {"desc_nome_fonte_recurso": "Municipal", "vl_investimento_previsto": 250.5},
    ]}
    m = linha(1, p)
    assert m["valor"] == 1250.5
    assert m["origens"] == ["Federal", "Municipal"]


def test_sem_fonte_de_recurso_o_valor_e_nulo_e_nao_zero():
    """Obra sem valor declarado não é obra de graça — é obra sem valor
    declarado. Zero na tela seria uma afirmação que a fonte não faz."""
    m = linha(1, {"id_projeto_investimento": "a", "investimentos_previstos": []})
    assert m["valor"] is None


def test_data_efetiva_nula_continua_nula():
    """⚠️ Nulo aqui é 'ainda não aconteceu', e é o que denuncia obra parada.
    Preencher com a data prevista apagaria exatamente esse sinal."""
    m = linha(1, {"id_projeto_investimento": "a",
                  "dt_inicial_prevista": "2024-11-05T00:00:00",
                  "dt_inicial_efetiva": None, "investimentos_previstos": []})
    assert m["dt_ini_prev"] == "2024-11-05"
    assert m["dt_ini_efe"] is None


def test_eixos_e_tipos_saem_da_mesma_lista_aninhada():
    """A API nova junta os dois em `eixos_tipos`; a tela filtra por cada um."""
    m = linha(1, {"id_projeto_investimento": "a", "eixos_tipos": [
        {"eixo": "Infraestrutura Social e Urbana", "tipo": "Prevenção a desastres"}]})
    assert m["eixos"] == ["Infraestrutura Social e Urbana"]
    assert m["tipos"] == ["Prevenção a desastres"]


# ---------------------------------------------------------------------------
# ⚠️ Armadilha 4 — `sistema_resp` denuncia obra que outro coletor nosso já traz
# ---------------------------------------------------------------------------
def test_sistema_de_origem_e_preservado():
    """Uma UBS do RS veio com `sistema_resp: SISMOB` — a mesma obra que
    `sismob_obras` já traz. Sem guardar isso, a tela mostra duas obras onde há
    uma."""
    m = linha(1, {"id_projeto_investimento": "a", "sistema_resp": "SISMOB"})
    assert m["sistema"] == "SISMOB"
