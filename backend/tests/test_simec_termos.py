"""SIMEC Termos de Compromisso — o parser puro (ingestion/simec_termos).

`parse_termos` se declara "Funcao PURA (testavel)" desde que nasceu (PR #258) e
nunca foi testada. Ela e regex sobre o HTML do portal do MEC: se o layout mudar,
TODO municipio devolve 200 com zero linhas — a falha mais cara que esta fonte
pode ter, porque e silenciosa.

Os cabecalhos da fixture sao os que o proprio modulo documenta:
  Termo de Compromisso | Processo | Nº do Documento | Tipo de Documento |
  Tipo do Objeto | Data da Validacao | Periodo do Pagamento | Vigencia |
  Valor do Termo
"""
from ingestion.simec_termos import parse_termos, _data, _valor, _mapa_colunas


_CAB = ("<tr><th>Termo de Compromisso</th><th>Processo</th>"
        "<th>N&ordm; do Documento</th><th>Tipo de Documento</th>"
        "<th>Tipo do Objeto</th><th>Data da Valida&ccedil;&atilde;o</th>"
        "<th>Per&iacute;odo do Pagamento</th><th>Vig&ecirc;ncia</th>"
        "<th>Valor do Termo</th></tr>")

_LINHA = ("<tr><td>TC</td><td>23000.012345/2023-11</td><td>202301</td>"
          "<td>TC com cl&aacute;usula suspensiva_Obra</td><td>Obra</td>"
          "<td>12/03/2024</td><td>01/2024 a 12/2024</td>"
          "<td>30/12/2024 - (-595 dias)</td><td>R$3.157.096,83</td></tr>")


def _pagina(*linhas: str) -> str:
    return "<html><body><table>" + _CAB + "".join(linhas) + "</table></body></html>"


# --------------------------------------------------------------------------
# Leitura basica
# --------------------------------------------------------------------------
def test_le_o_termo_com_todos_os_campos():
    termos = parse_termos(_pagina(_LINHA))
    assert len(termos) == 1
    t = termos[0]
    assert t["processo"] == "23000.012345/2023-11"
    assert t["nr_documento"] == "202301"
    assert t["tipo_objeto"] == "Obra"
    assert "suspensiva" in t["tipo_documento"]
    assert t["valor_termo"] == 3157096.83
    assert str(t["dt_vigencia"]) == "2024-12-30"
    assert str(t["dt_validacao"]) == "2024-03-12"


def test_deduplica_a_mesma_linha_repetida():
    """O docstring do modulo avisa: "o portal repete a MESMA linha varias vezes"
    em blocos diferentes da pagina. Se a dedup quebrar, o upsert absorve em
    silencio (a chave natural e a mesma) e ninguem ve o defeito."""
    assert len(parse_termos(_pagina(_LINHA, _LINHA, _LINHA))) == 1


def test_duas_linhas_distintas_continuam_duas():
    outra = _LINHA.replace("202301", "202302")
    assert len(parse_termos(_pagina(_LINHA, outra))) == 2


def test_tabela_de_layout_e_ignorada():
    """A pagina traz tabelas de layout sem Processo/Nº do Documento. Sem o
    filtro, cada uma viraria "termo" com todos os campos vazios."""
    layout = ("<table><tr><th>Menu</th><th>Ajuda</th></tr>"
              "<tr><td>Principal</td><td>Sair</td></tr></table>")
    html = "<html><body>" + layout + "<table>" + _CAB + _LINHA + "</table></body></html>"
    termos = parse_termos(html)
    assert len(termos) == 1
    assert termos[0]["processo"] == "23000.012345/2023-11"


def test_linha_sem_processo_e_sem_documento_nao_vira_termo():
    vazia = "<tr><td></td><td></td><td></td><td>x</td></tr>"
    assert len(parse_termos(_pagina(vazia, _LINHA))) == 1


# --------------------------------------------------------------------------
# A armadilha do cabecalho por FRAGMENTO
# --------------------------------------------------------------------------
def test_ordem_real_do_portal_mapeia_documento_certo():
    """⚠️ `_COLS["nr_documento"] = ("documento",)` tambem casa com "Tipo de
    Documento". Na ordem REAL do portal isso nao da problema porque "Nº do
    Documento" vem ANTES e o `if campo in idx: continue` protege. Este teste
    trava essa regressao: se alguem reordenar _COLS ou tirar a guarda, o numero
    do documento passa a receber o texto do tipo."""
    cab = ["Termo de Compromisso", "Processo", "Nº do Documento",
           "Tipo de Documento", "Tipo do Objeto"]
    idx = _mapa_colunas(cab)
    assert idx["nr_documento"] == 2
    assert idx["tipo_documento"] == 3


def test_cabecalho_invertido_documenta_o_limite_conhecido():
    """O mesmo mapeamento com as duas colunas TROCADAS erra — e de proposito que
    isto esta escrito: o parser depende da ORDEM do portal, nao so do texto. Se
    um dia o MEC inverter as colunas, e aqui que a causa vai estar registrada."""
    cab = ["Termo de Compromisso", "Processo", "Tipo de Documento",
           "Nº do Documento", "Tipo do Objeto"]
    idx = _mapa_colunas(cab)
    assert idx["nr_documento"] == 2       # casou com "Tipo de Documento"


def test_periodo_pagamento_exige_os_dois_fragmentos():
    """`periodo_pagamento` e o unico campo com regra `all(...)`: precisa de "per"
    E "pagamento". Sem isso, "Período" sozinho casaria com qualquer coluna."""
    idx = _mapa_colunas(["Período do Pagamento", "Período"])
    assert idx["periodo_pagamento"] == 0


# --------------------------------------------------------------------------
# Conversores
# --------------------------------------------------------------------------
def test_data_pega_a_primeira_de_varias():
    """As celulas de vigencia trazem varias datas separadas por virgula; a que
    interessa e a primeira."""
    assert str(_data("30/12/2024, 15/01/2025")) == "2024-12-30"


def test_data_ignora_texto_ao_redor():
    assert str(_data("30/12/2024 - (-595 dias)")) == "2024-12-30"


def test_data_invalida_vira_none():
    assert _data("") is None
    assert _data("sem data") is None
    assert _data("32/13/2024") is None


def test_valor_converte_moeda_brasileira():
    assert _valor("R$3.157.096,83") == 3157096.83
    assert _valor("R$ 1.000,00") == 1000.0


def test_valor_sem_centavos_vira_none():
    """O regex exige os centavos (',\\d{2}') — "Quantidade de Obra" cai nesta
    coluna em algumas tabelas e nao pode virar valor monetario."""
    assert _valor("12") is None
    assert _valor("") is None
