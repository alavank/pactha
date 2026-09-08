"""
SICONFI/Tesouro — os testes existem pelas TRÊS armadilhas que custam caro.

Não são testes de "o parser parseia". Cada um trava um jeito específico de o
coletor mentir em silêncio, medido contra a fonte em 02/09/2026:

  (a) A CÂMARA NA CONTA DA PREFEITURA. As duas dividem o `cod_ibge` e vêm na
      MESMA resposta, com a Câmara primeiro. Sem filtro, a tela cobraria da
      prefeitura uma MSC que é do legislativo — e a fixture preserva a ordem
      real (câmara antes) justamente para que um filtro escrito de trás para a
      frente não passe por acidente.

  (b) O PORTE MUDA O NOME DO DEMONSTRATIVO. Nova Palma entrega "RREO
      Simplificado"; Santa Maria entrega "RREO". Quem consultasse
      `co_tipo_demonstrativo=RREO` receberia HTTP 200 com `count: 0` para Nova
      Palma em todos os anos e concluiria que a prefeitura nunca prestou contas
      ao Tesouro — alarme falso num item que o CAUC e o CHE cobram. O teste
      trava a leitura do nome como ele vem, com "Simplificado" e tudo.

  (c) A PLANILHA DA CAPAG NÃO COMEÇA NO CABEÇALHO e os números vêm como TEXTO.
      Assumir a linha 0, ou converter com o parser brasileiro (que trata ponto
      como separador de milhar), transforma 0,0164 em 16 bilhões.

Rodar:
    python -m pytest backend/tests/test_siconfi.py -v
"""
import json
from pathlib import Path

import pytest

from ingestion.siconfi import _num, capag_por_ibge, capag_recurso, entes, extrato_entregas

FIXTURES = Path(__file__).parent / "fixtures"

# ⚠️ A PLANILHA DA CAPAG É MONTADA AQUI, e não versionada como .xlsx — os
# `*.xlsx` são ignorados pelo `.gitignore` de propósito (planilha de dado
# baixado não entra no repo), e um binário não se lê em diff: daqui a um ano
# ninguém saberia dizer se a fixture ainda espelha a fonte.
#
# Os VALORES abaixo são reais, medidos em 02/09/2026 no recurso "Capag
# Municípios 2026 - 01/06/2026" (posição de junho/2026), e a ESTRUTURA também:
# duas linhas de sumário antes do cabeçalho, números como texto com ponto
# decimal, e uma segunda aba de memorial de cálculo sem a nota consolidada.
_CAPAG_SUMARIO = [
    [None, None, "CAPAG Ano Base 2025", "70", "6", "7", "35", "37", "64", "67"],
    [None, None, "CAPAG Ano Base 2024", "95", "10", "11", "49", "50", "88", "89"],
]
_CAPAG_CABECALHO = ["Código Município Completo", "Nome_Município", "UF", "CAPAG",
                    "Indicador 1", "Nota 1", "Indicador 2", "Nota 2",
                    "Indicador 3", "Nota 3", "ICF", "Observação"]
_CAPAG_LINHAS = [
    # Nova Palma: A+ — dívida consolidada de R$ 682 mil sobre RCL de R$ 41,5 mi.
    ["4313102", "Nova Palma", "RS", "A+",
     "0.016421077930546375", "A", "0.7793787065353057", "A",
     "0.14048340619884564", "A", "Aicf", ""],
    # Santa Maria: C — e o Indicador 3 (liquidez) é NEGATIVO. É esse sinal que
    # explica a nota, e é ele que um parser desatento perderia.
    ["4316907", "Santa Maria", "RS", "C",
     "0.14487027511946282", "A", "0.9635601786508226", "C",
     "-0.05142786307562441", "C", "Aicf", ""],
]


@pytest.fixture(scope="module")
def capag_xlsx(tmp_path_factory):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Prévia da CAPAG"
    for linha in _CAPAG_SUMARIO + [_CAPAG_CABECALHO] + _CAPAG_LINHAS:
        ws.append(linha)
    # A aba de memorial de cálculo: mesmo cabeçalho de município, SEM a coluna
    # "CAPAG". O parser tem de continuar na primeira.
    ws2 = wb.create_sheet("CAPAG Ano Base 2025")
    for _ in range(3):
        ws2.append([None])
    ws2.append(["Código Município Completo", "Nome_Município", "UF",
                "2025 - Dívida Consolidada", "2025 - Receita Corrente Líquida",
                "Indicador 1", "Nota 1"])
    ws2.append(["4313102", "Nova Palma", "RS", "682663.72", "41572406.08",
                "0.016421077930546375", "A"])
    caminho = tmp_path_factory.mktemp("siconfi") / "capag.xlsx"
    wb.save(caminho)
    return str(caminho)


class _Resposta:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class ClienteFalso:
    """Devolve a fixture e registra o que foi pedido — nenhum teste sai para a
    internet, e a URL pedida é ela mesma parte do contrato."""

    def __init__(self, payload):
        self.payload = payload
        self.chamadas: list[tuple] = []

    def get(self, url, params=None, **kw):
        self.chamadas.append((url, params))
        return _Resposta(self.payload)


def _fixture(nome):
    return json.loads((FIXTURES / nome).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# (a) A Câmara não pode entrar na conta da Prefeitura
# ---------------------------------------------------------------------------
def test_extrato_descarta_a_camara_de_vereadores():
    """A fixture é a resposta real de Nova Palma/2025: 3 linhas da Câmara ANTES
    de 7 da Prefeitura. Só as da Prefeitura podem sair daqui."""
    cliente = ClienteFalso(_fixture("siconfi_extrato_entregas.json"))
    linhas = extrato_entregas(cliente, "4313102", 2025)

    assert linhas, "a fixture tem entregas da prefeitura; nenhuma sobreviveu ao filtro"
    assert all("Prefeitura" in x["instituicao"] for x in linhas)
    assert not any("mara de Vereadores" in x["instituicao"] for x in linhas)
    # E o filtro tem de ter descartado ALGO — se a fixture perder as linhas da
    # câmara, este teste vira tautologia e precisa ser revisto, não apagado.
    assert len(linhas) < len(_fixture("siconfi_extrato_entregas.json")["items"])


def test_extrato_pede_o_ente_e_o_ano_certos():
    cliente = ClienteFalso({"items": []})
    extrato_entregas(cliente, "4313102", 2025)
    url, params = cliente.chamadas[0]
    assert url.endswith("/tt/extrato_entregas")
    assert params == {"an_referencia": 2025, "id_ente": "4313102"}


# ---------------------------------------------------------------------------
# (b) "Simplificado" faz parte do nome, e é ele que explica a periodicidade
# ---------------------------------------------------------------------------
def test_entregavel_preserva_o_simplificado_do_municipio_pequeno():
    cliente = ClienteFalso(_fixture("siconfi_extrato_entregas.json"))
    linhas = extrato_entregas(cliente, "4313102", 2025)
    nomes = {x["entregavel"] for x in linhas}
    # Nova Palma tem 5,6 mil habitantes: o que ela entrega é a versão
    # simplificada. Normalizar para "RREO" apagaria a explicação da cadência.
    assert any("Simplificado" in n for n in nomes), nomes


def test_entrega_sem_status_ainda_e_entrega():
    """⚠️ O `status_relatorio` NÃO é uniforme, e quem confiar nele perde metade.

    Medido em Nova Palma/2025: RREO, RGF e DCA vêm com `status='HO'`
    (homologado); as MSC — que são 12 das 22 entregas do ano — vêm com
    `status=None` e a data preenchida. Um coletor que filtrasse por
    `status == 'HO'` jogaria fora toda a MSC e diria que o município deixou de
    entregar a matriz contábil o ano inteiro. Quem prova a entrega é a DATA."""
    cliente = ClienteFalso(_fixture("siconfi_extrato_entregas.json"))
    linhas = extrato_entregas(cliente, "4313102", 2025)

    com_data = [x for x in linhas if x.get("data_status")]
    assert len(com_data) == len(linhas), "toda linha do extrato traz data"

    sem_status = [x for x in com_data if x.get("status_relatorio") is None]
    com_status = [x for x in com_data if x.get("status_relatorio")]
    # Os dois grupos existem de verdade — é isso que torna o filtro por status
    # uma armadilha, e não uma questão de gosto.
    assert sem_status and com_status, {
        "sem": [x["entregavel"] for x in sem_status],
        "com": [x["entregavel"] for x in com_status]}
    assert all("MSC" in x["entregavel"] for x in sem_status)


# ---------------------------------------------------------------------------
# (c) A planilha da CAPAG
# ---------------------------------------------------------------------------
def test_capag_acha_o_cabecalho_fora_da_primeira_linha(capag_xlsx):
    """A fixture reproduz a planilha do Tesouro: duas linhas de sumário antes do
    cabeçalho. Um parser com índice fixo leria '70' como código de município."""
    achados = capag_por_ibge(capag_xlsx,
                             {"4313102", "4316907"})
    assert set(achados) == {"4313102", "4316907"}
    assert achados["4313102"]["capag"] == "A+"
    assert achados["4316907"]["capag"] == "C"


def test_capag_ignora_municipio_que_nao_foi_pedido(capag_xlsx):
    """O arquivo real tem 5.571 linhas; carregar todas seria desperdício e
    gravar as de outro tenant seria vazamento."""
    achados = capag_por_ibge(capag_xlsx, {"4313102"})
    assert set(achados) == {"4313102"}


def test_capag_prefere_a_aba_da_nota_consolidada(capag_xlsx):
    """A fixture tem duas abas: a da nota ('CAPAG') e a de memorial de cálculo
    ('CAPAG Ano Base 2025', sem a nota). Escolher a segunda daria indicadores
    sem veredito — e é a que vem depois na ordem das abas."""
    achados = capag_por_ibge(capag_xlsx, {"4313102"})
    assert "capag" in achados["4313102"], "veio da aba errada (sem nota consolidada)"
    assert achados["4313102"]["capag"] == "A+"


@pytest.mark.parametrize("texto,esperado", [
    ("0.016421077930546375", 0.016421077930546375),
    ("-0.05142786307562441", -0.05142786307562441),   # liquidez negativa: Santa Maria
    ("0,5", 0.5),                                      # se um dia vier com vírgula
    ("", None), (None, None), ("-", None), ("n/d", None),
])
def test_num_le_o_ponto_como_decimal(texto, esperado):
    """⚠️ `parse_decimal_br` do `ingestion/base.py` trataria o ponto como
    separador de MILHAR: 0.0164 viraria 164 e o endividamento do município
    apareceria 10 mil vezes maior. Por isso este coletor tem o seu."""
    assert _num(texto) == esperado


def test_liquidez_negativa_sobrevive(capag_xlsx):
    """Santa Maria tem Indicador 3 negativo (obrigações maiores que o caixa) — é
    o número que explica a nota C. Um parser que descartasse o sinal diria o
    contrário do que a fonte diz."""
    achados = capag_por_ibge(capag_xlsx, {"4316907"})
    assert _num(achados["4316907"]["indicador 3"]) < 0


# ---------------------------------------------------------------------------
# Escolha do recurso no CKAN
# ---------------------------------------------------------------------------
def test_capag_escolhe_o_recurso_mais_novo_e_nao_o_de_nome_bonito():
    """Os nomes reais oscilam entre 'CAPAG' e 'Capag', repetem o ano em várias
    revisões e um deles começa com espaço. A escolha é por `last_modified`."""
    cliente = ClienteFalso({"success": True, "result": {"resources": [
        {"format": "XLSX", "name": "CAPAG Municípios 2023",
         "url": "u1", "last_modified": "2024-08-12T18:20:09"},
        {"format": "PDF", "name": "Metadados", "url": "u0",
         "last_modified": "2026-12-01T00:00:00"},          # mais novo, e não é XLSX
        {"format": "XLSX", "name": " Capag Municípios 2026 - 01/06/2026",
         "url": "u2", "last_modified": "2026-06-18T14:23:55"},
        {"format": "XLSX", "name": "Capag Municípios 2025 - 09/11/2025",
         "url": "u3", "last_modified": "2025-11-10T21:07:58"},
    ]}})
    rec = capag_recurso(cliente)
    assert rec["url"] == "u2"
    assert rec["exercicio"] == 2026
    assert rec["posicao"].isoformat() == "2026-06-01"


def test_capag_sem_xlsx_devolve_none_em_vez_de_explodir():
    cliente = ClienteFalso({"success": True, "result": {"resources": [
        {"format": "PDF", "name": "Metadados", "url": "u0"}]}})
    assert capag_recurso(cliente) is None


# ---------------------------------------------------------------------------
# Cadastro de entes
# ---------------------------------------------------------------------------
def test_entes_devolve_cnpj_so_com_digito():
    cliente = ClienteFalso({"count": 2, "hasMore": False, "items": [
        {"cod_ibge": 4313102, "ente": "Nova Palma", "uf": "RS",
         "populacao": 5676, "cnpj": "88.488.358/0001-56"},
        {"cod_ibge": 999, "ente": "lixo", "uf": "??", "cnpj": "1"},
    ]})
    out = entes(cliente)
    assert out["4313102"]["cnpj"] == "88488358000156"
    assert "999" not in out, "IBGE malformado não pode virar chave"


def test_entes_avisa_se_a_resposta_passar_a_paginar(caplog):
    """Hoje os 5.598 entes vêm de uma vez. Se um dia paginar, o coletor não pode
    truncar em silêncio — tem de dizer."""
    cliente = ClienteFalso({"count": 9999, "hasMore": True, "items": [
        {"cod_ibge": 4313102, "ente": "Nova Palma", "uf": "RS", "cnpj": "88488358000156"}]})
    with caplog.at_level("WARNING"):
        entes(cliente)
    assert any("paginado" in r.message for r in caplog.records)
