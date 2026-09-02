"""Testes do coletor de FUNDO A FUNDO da saude (`ingestion/fns_faf.py`).

O que este arquivo protege, e por que cada coisa esta aqui:

⚠️ A DISTINCAO ENTRE "FALHOU" E "NAO TEM". `busca()` devolve `None` quando a
consulta falhou e `[]` quando o municipio realmente nao teve repasse. Se um dia
alguem "simplificar" para `return []` no erro, a rodada passa a gravar silencio
como se fosse resposta e o `status` da coleta vira mentira verde. Ha teste para
cada caminho de falha (excecao, HTTP != 200, HTML no lugar de JSON, JSON quebrado).

⚠️ O BLOCO SEM GRUPO NAO PODE SUMIR. O portal as vezes devolve o bloco sem
`repasses[]`. Descartar perderia o total; por isso vira uma linha com
`grupo_codigo = 0`. Ha teste do valor E do rotulo.

⚠️ NULO NAO E ZERO. Coluna de dinheiro ausente tem que chegar `None` no banco, e
nao `0.0` — a diferenca ja custou caro neste projeto (o `_upsert` COALESCE).

A fixture da resposta e a RESPOSTA REAL do portal para Monte Siao/MG em 2026,
copiada da chamada verificada ao vivo em 02/09/2026 — nao um formato inventado.
Um teste ja falhou neste repo por inventar o formato que o coletor grava.
"""
import pytest

pytest.importorskip("httpx")

from ingestion import fns_faf  # noqa: E402


# A resposta INTEIRA de
# GET /recursos/consulta-consolidada/repasse-bloco?ano=2026&coMunicipioIbge=314340
#     &coTipoRepasse=M&sgUf=MG  — Monte Siao/MG, captada em 02/09/2026.
#
# ⚠️ INTEIRA, E NAO UM RECORTE — a diferenca ja custou uma investigacao. A
# primeira versao trazia 2 dos 5 grupos do bloco 10, entao a soma dos grupos NAO
# batia com o total do bloco e a glosa de R$ 12.980 nao aparecia em grupo nenhum
# (ela esta no grupo 14, que o recorte tinha deixado de fora). Uma revisao leu
# essa fixture como se fosse a resposta completa e concluiu — plausivelmente —
# que o coletor JOGAVA A GLOSA FORA, reportado como defeito CRITICO. Nao jogava:
# a fixture e que mentia. Fixture recortada e um fato falso deixado no repo com
# cara de verdade; para um caso com estrutura de arvore, colar a resposta toda
# custa 30 linhas e evita conclusoes inventadas sobre codigo que estava certo.
RESPOSTA_REAL = [
    {
        "codigo": 10,
        "nome": "Manutenção das Ações e Serviços Públicos de Saúde",
        "vlTotal": 4059475.09, "vlDesconto": 12980, "vlLiquido": 4046495.09,
        "repasses": [
            {"codigo": 35, "nome": "ASSISTÊNCIA FARMACÊUTICA",
             "vlTotal": 137963.2, "vlDesconto": 0, "vlLiquido": 137963.2, "repasses": []},
            {"codigo": 14,
             "nome": "ATENÇÃO DE MÉDIA E ALTA COMPLEXIDADE AMBULATORIAL E HOSPITALAR",
             "vlTotal": 158783.52, "vlDesconto": 12980, "vlLiquido": 145803.52, "repasses": []},
            {"codigo": 12, "nome": "ATENÇÃO PRIMÁRIA",
             "vlTotal": 3447463.86, "vlDesconto": 0, "vlLiquido": 3447463.86, "repasses": []},
            {"codigo": 17, "nome": "GESTÃO DO SUS",
             "vlTotal": 8124.7, "vlDesconto": 0, "vlLiquido": 8124.7, "repasses": []},
            {"codigo": 34, "nome": "VIGILÂNCIA EM SAÚDE",
             "vlTotal": 307139.81, "vlDesconto": 0, "vlLiquido": 307139.81, "repasses": []},
        ],
    },
    {
        "codigo": 11,
        "nome": "Estruturação da Rede de Serviços Públicos de Saúde",
        "vlTotal": 4494000, "vlDesconto": 0, "vlLiquido": 4494000,
        "repasses": [
            {"codigo": 19, "nome": "ATENÇÃO ESPECIALIZADA",
             "vlTotal": 2506000, "vlDesconto": 0, "vlLiquido": 2506000, "repasses": []},
            {"codigo": 18, "nome": "ATENÇÃO PRIMÁRIA",
             "vlTotal": 1988000, "vlDesconto": 0, "vlLiquido": 1988000, "repasses": []},
        ],
    },
]


def test_o_achatamento_nao_perde_dinheiro_nem_glosa():
    """⚠️ A INVARIANTE DA FONTE: os grupos somam o bloco, glosa inclusa.

    O portal publica o total no bloco E detalhado nos grupos, e as duas contas
    fecham — conferido ao vivo. Achatar a arvore so e seguro enquanto isso valer,
    e este teste e o alarme para o dia em que a fonte mudar: se um bloco passar a
    trazer valor que nao esta em grupo nenhum, o coletor comeca a subnotificar
    dinheiro publico em silencio, e a tela some com a glosa.

    Foi a AUSENCIA desta invariante que deixou a fixture recortada passar por
    completa e gerar um achado critico falso.
    """
    linhas = achata_pura = fns_faf.achata(RESPOSTA_REAL)
    for bloco in RESPOSTA_REAL:
        do_bloco = [l for l in achata_pura if l["bloco_codigo"] == bloco["codigo"]]
        assert round(sum(l["vl_total"] for l in do_bloco), 2) == round(bloco["vlTotal"], 2)
        assert round(sum(l["vl_desconto"] for l in do_bloco), 2) == round(bloco["vlDesconto"], 2)
        assert round(sum(l["vl_liquido"] for l in do_bloco), 2) == round(bloco["vlLiquido"], 2)
    # E o total do municipio, que e o numero que aparece grande na tela.
    assert round(sum(l["vl_total"] for l in linhas), 2) == 8553475.09
    assert round(sum(l["vl_desconto"] for l in linhas), 2) == 12980.00


def test_achata_expande_grupos():
    """Uma linha por grupo, com o bloco carimbado em cada uma."""
    linhas = fns_faf.achata(RESPOSTA_REAL)
    assert len(linhas) == 7                      # 5 grupos do bloco 10 + 2 do 11
    assert {l["grupo_codigo"] for l in linhas} == {35, 14, 12, 17, 34, 19, 18}
    do_dez = [l for l in linhas if l["bloco_codigo"] == 10]
    assert len(do_dez) == 5
    assert all(l["bloco_nome"].startswith("Manutenção") for l in do_dez)
    farmacia = next(l for l in linhas if l["grupo_codigo"] == 35)
    assert farmacia["vl_total"] == 137963.2
    assert farmacia["grupo_nome"] == "ASSISTÊNCIA FARMACÊUTICA"
    # ⚠️ A GLOSA MORA NUM GRUPO, e nao no bloco: R$ 12.980 estao em Média e Alta
    # Complexidade. Foi por nao ter este grupo na fixture que uma revisao
    # concluiu que o coletor descartava a glosa.
    mac = next(l for l in linhas if l["grupo_codigo"] == 14)
    assert mac["vl_desconto"] == 12980
    assert mac["vl_liquido"] == 145803.52


def test_achata_bloco_sem_grupo_vira_linha_total():
    """⚠️ Bloco sem `repasses[]` NAO some: vira `grupo_codigo = 0`.

    Descartar perderia o total do bloco — que e justamente o numero que o gestor
    ve. E o codigo 0 nao colide com grupo real nenhum (o portal comeca no 12).
    """
    linhas = fns_faf.achata([
        {"codigo": 99, "nome": "Bloco Solto", "vlTotal": 1000.0,
         "vlDesconto": 0, "vlLiquido": 1000.0},
    ])
    assert len(linhas) == 1
    assert linhas[0]["grupo_codigo"] == 0
    assert linhas[0]["vl_total"] == 1000.0
    # O rotulo do "grupo" repete o nome do bloco: a tela nunca mostra vazio.
    assert linhas[0]["grupo_nome"] == "Bloco Solto"


def test_achata_repasses_vazio_tambem_vira_total():
    """`repasses: []` e o mesmo caso de bloco sem detalhamento."""
    linhas = fns_faf.achata([
        {"codigo": 7, "nome": "Vazio", "vlTotal": 5.0, "repasses": []},
    ])
    assert [l["grupo_codigo"] for l in linhas] == [0]


def test_achata_nulo_nao_vira_zero():
    """⚠️ Campo de dinheiro ausente chega None, e nao 0.0.

    No banco a coluna e anulavel de proposito: NULL = "nao veio", 0 = "veio zero".
    Se `_num` devolvesse 0.0 aqui, a plataforma passaria a afirmar que o
    municipio recebeu zero quando na verdade o portal nao informou.
    """
    linhas = fns_faf.achata([{"codigo": 1, "nome": "X", "repasses": [
        {"codigo": 2, "nome": "Y", "vlTotal": None, "vlDesconto": "", "vlLiquido": "abc"},
    ]}])
    assert linhas[0]["vl_total"] is None
    assert linhas[0]["vl_desconto"] is None
    assert linhas[0]["vl_liquido"] is None


def test_achata_ignora_lixo_sem_estourar():
    """Resposta malformada nao pode derrubar a rodada inteira."""
    assert fns_faf.achata(None) == []
    assert fns_faf.achata([]) == []
    assert fns_faf.achata(["texto solto", None, 42]) == []
    # Bloco sem codigo nao tem identidade -> nao entra (a chave unica exige).
    assert fns_faf.achata([{"nome": "sem codigo", "vlTotal": 1}]) == []
    # Grupo sem codigo e descartado, mas o bloco irmao valido sobrevive.
    linhas = fns_faf.achata([{"codigo": 3, "nome": "B", "repasses": [
        {"nome": "sem codigo", "vlTotal": 9}, {"codigo": 4, "vlTotal": 8},
    ]}])
    assert [l["grupo_codigo"] for l in linhas] == [4]


def test_achata_preserva_o_bruto():
    """`raw` guarda o objeto do portal — a origem de qualquer conferencia."""
    linhas = fns_faf.achata(RESPOSTA_REAL)
    assert linhas[0]["raw"]["nome"] == "ASSISTÊNCIA FARMACÊUTICA"


# --------------------------------------------------------------------------
# busca(): o contrato None-vs-lista
# --------------------------------------------------------------------------

class _Resposta:
    """Fake com o comportamento do httpx — e o realismo aqui NAO e enfeite.

    ⚠️ A PRIMEIRA VERSAO DESTE FAKE DEIXOU UM TESTE CEGO. Ele devolvia `.json()`
    normalmente mesmo com corpo HTML, entao o teste do muro passava pelo caminho
    errado (o `.get()` de None estourava e caia no `except`). Apagar a guarda de
    content-type do coletor nao quebrava teste nenhum — provado por mutacao.
    Aqui `.json()` estoura quando o corpo nao e JSON, como o httpx de verdade.
    """

    def __init__(self, status=200, payload=None, ctype="application/json", corpo=b""):
        self.status_code = status
        self.headers = {"content-type": ctype}
        self._payload = payload
        self.content = corpo

    def json(self):
        if self._payload is _QUEBRADO or "json" not in self.headers["content-type"]:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


_QUEBRADO = object()


class _Cliente:
    def __init__(self, resposta=None, erro=None):
        self._r, self._e = resposta, erro
        self.params = None

    def get(self, url, params=None):
        self.params = params
        if self._e:
            raise self._e
        return self._r


def test_busca_sucesso_devolve_lista():
    cli = _Cliente(_Resposta(payload={"resultado": RESPOSTA_REAL}))
    assert fns_faf.busca(cli, 2026, "314340", "MG") == RESPOSTA_REAL


def test_busca_manda_os_parametros_que_o_portal_exige():
    """O portal responde 400 sem `sgUf`/`coTipoRepasse` — nao sao opcionais."""
    cli = _Cliente(_Resposta(payload={"resultado": []}))
    fns_faf.busca(cli, 2026, "314340", "MG")
    assert cli.params["ano"] == 2026
    assert cli.params["coMunicipioIbge"] == "314340"
    assert cli.params["sgUf"] == "MG"
    assert cli.params["coTipoRepasse"] == "M"


def test_busca_sem_repasse_e_lista_vazia_nao_None():
    """⚠️ Municipio sem repasse RESPONDEU. Isso e `[]`, e nao falha."""
    cli = _Cliente(_Resposta(payload={"resultado": []}))
    assert fns_faf.busca(cli, 2026, "314340", "MG") == []
    # `resultado` ausente tambem e resposta valida vazia.
    cli2 = _Cliente(_Resposta(payload={}))
    assert fns_faf.busca(cli2, 2026, "314340", "MG") == []


@pytest.mark.parametrize("cli,rotulo", [
    (_Cliente(erro=TimeoutError("estourou")), "excecao de rede"),
    (_Cliente(_Resposta(status=500)), "HTTP 500"),
    (_Cliente(_Resposta(status=404)), "HTTP 404"),
    (_Cliente(_Resposta(ctype="text/html", corpo=b"<html>manutencao</html>")), "HTML no lugar de JSON"),
    (_Cliente(_Resposta(payload=_QUEBRADO)), "JSON ilegivel"),
])
def test_busca_falha_devolve_None(cli, rotulo):
    """⚠️ TODO caminho de falha devolve None — nunca `[]`.

    `[]` seria lido pelo `run()` como "consultado, nao tem", e o municipio
    sumiria da lista de falhas. O status da rodada mentiria verde.
    """
    assert fns_faf.busca(cli, 2026, "314340", "MG") is None, rotulo


def test_html_com_status_200_e_diagnosticado_como_muro(caplog):
    """200 com HTML e muro/manutencao — e o LOG tem que dizer isso.

    ⚠️ POR QUE ESTE TESTE OLHA O LOG, e nao so o retorno. Sem a guarda de
    content-type o retorno seria None do mesmo jeito (o parse de JSON estoura e
    cai no except), entao afirmar so `is None` nao testa nada — foi exatamente o
    buraco que a mutacao encontrou. O que a guarda ACRESCENTA e o diagnostico:
    "muro" e "JSON quebrado" sao problemas diferentes e mandam o proximo
    plantonista para lados opostos. E isso que esta sendo protegido aqui.
    """
    cli = _Cliente(_Resposta(status=200, ctype="text/html; charset=utf-8",
                             corpo=b"<html>" + b"x" * 3000 + b"</html>"))
    with caplog.at_level("WARNING", logger="fns_faf"):
        assert fns_faf.busca(cli, 2026, "314340", "MG") is None
    assert "nao-JSON" in caplog.text
    assert "3013B" in caplog.text  # o tamanho do corpo ajuda a reconhecer o muro
    assert "ilegivel" not in caplog.text


def test_json_quebrado_e_diagnosticado_diferente_do_muro(caplog):
    """O par do teste acima: content-type certo e corpo podre e OUTRO problema."""
    cli = _Cliente(_Resposta(status=200, payload=_QUEBRADO))
    with caplog.at_level("WARNING", logger="fns_faf"):
        assert fns_faf.busca(cli, 2026, "314340", "MG") is None
    assert "ilegivel" in caplog.text
    assert "nao-JSON" not in caplog.text
