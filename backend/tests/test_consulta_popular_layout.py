"""Consulta Popular (RS): a planilha de cada COREDE e montada a mao, e o layout varia.

Medido em 13/09/2026 nos 28 arquivos da edicao 2026/2027, quando o BGK (10
municipios) nasceu sem COREDE e a primeira rodada com o campo preenchido deixou
Girua sem dado:

- Missoes escreve a demanda na coluna C (a B fica vazia) e intercala
  "Nº Eleitores" e "Percent. Municipios" no bloco municipal — o passo fixo de 3
  colunas lia o total de eleitores como votos.
- "-serra-" solto na URL casa "alto-da-serra-do-botucarai"; o nome do COREDE
  vem logo depois do prefixo numerico do arquivo.

Sem rede: as planilhas sao construidas aqui com openpyxl, no mesmo desenho das
reais (linhas copiadas dos arquivos publicados).
"""
import io
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.consulta_popular_rs import _escolher_planilha, parse_planilha  # noqa: E402


def _xlsx(linhas: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in linhas:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# Layout "classico" (Vale do Rio dos Sinos): demanda na coluna B, grupo de 3.
PLANILHA_SINOS = [
    ["Resultado Consulta - Municipios X Demandas Eleitas"],
    [],
    ["Corede", "Demandas Eleitas", None, "Secretarias", None, "Total Votos na Demandas Eleitas", "Valor Total"],
    ["Vale do Rio dos Sinos", "4 - Bem estar Animal.", None, "Secretaria do Meio Ambiente e Infraestrutura", None, 2996, 1114285.72],
    ["Vale do Rio dos Sinos", "1 - Fortalecimento da Defesa Civil.", None, "Defesa Civil RS - CEDEC-RS", None, 2251, 1114285.73],
    ["Âmbito Municipal", "1ª DEMANDA ELEITA - SEMA (Votos)", "STATUS", "Âmbito Municipal", "2ª DEMANDA ELEITA - Defesa Civil (Votos)", "STATUS"],
    ["Araricá", 29, "Classificado", "Araricá", 80, "Classificado"],
    ["Portão", 153, "Classificado", "Portão", 33, "Classificado"],
]

# Layout de Missoes: coluna B vazia, demanda na C; bloco municipal com
# "Nº Eleitores" e "Percent." intercalados, e larguras DIFERENTES por grupo.
PLANILHA_MISSOES = [
    ["Resultado Consulta - Municipios X Demandas Eleitas"],
    [],
    ["Corede", None, "Demandas Eleitas", None, None, "Secretarias", None, None, "Total Votos na Demandas Eleitas", "Valor Total"],
    ["Missões", None, "1 - Caminhos da Produção: Estradas Vicinais", None, None, "Secretaria da Agricultura, Pecuária, Produção Sustentável e Irrigação", None, None, 5704, 1234285.72],
    ["Missões", None, "2 - Espaços Vivos Missões: Revitalização", None, None, "Secretaria de Desenvolvimento Urbano e Metropolitano", None, None, 736, 822857.14],
    ["Âmbito Municipal", "Nº Eleitores", "1ª DEMANDA ELEITA - SEAPI (Votos)", "Percent. Municípios", "STATUS", "Âmbito Municipal", "2ª DEMANDA ELEITA - SEDUR (Votos)", "Percent. Municípios", "STATUS"],
    ["Bossoroca", 5127, 41, 0.007996, None, "Bossoroca", 1, 0.000195, None],
    ["Giruá", 12753, 628, 0.049243, "Classificado", "Giruá", 45, 0.003528, "Classificado"],
]


def _por_ordem(demandas):
    return {d["ordem"]: d for d in demandas}


def test_layout_classico_continua_igual():
    d = _por_ordem(parse_planilha(_xlsx(PLANILHA_SINOS), "Portão"))
    assert set(d) == {"4", "1"}
    assert d["4"]["votos_municipio"] == 153 and d["4"]["status_municipio"] == "Classificado"
    assert d["1"]["votos_municipio"] == 33
    assert d["4"]["votos_corede"] == 2996 and d["4"]["valor"] == 1114285.72
    assert d["1"]["orgao"] == "Defesa Civil RS - CEDEC-RS"


def test_missoes_demanda_na_coluna_c_e_eleitores_intercalados():
    d = _por_ordem(parse_planilha(_xlsx(PLANILHA_MISSOES), "Giruá"))
    assert set(d) == {"1", "2"}, "coluna B vazia nao pode zerar as demandas"
    # 628 sao os VOTOS; 12753 e o total de eleitores, que o passo fixo lia no lugar
    assert d["1"]["votos_municipio"] == 628
    assert d["1"]["status_municipio"] == "Classificado"
    assert d["2"]["votos_municipio"] == 45
    assert d["1"]["votos_corede"] == 5704 and d["1"]["valor"] == 1234285.72
    assert d["1"]["orgao"].startswith("Secretaria da Agricultura")


def test_municipio_sem_status_fica_none_e_nao_percentual():
    d = _por_ordem(parse_planilha(_xlsx(PLANILHA_MISSOES), "Bossoroca"))
    assert d["1"]["votos_municipio"] == 41
    assert d["1"]["status_municipio"] is None


def test_municipio_ausente_nao_ganha_votos():
    d = parse_planilha(_xlsx(PLANILHA_MISSOES), "Santa Maria")
    assert len(d) == 2
    assert all(x.get("votos_municipio") is None for x in d)


URLS = [
    "https://admin.consultapopular.rs.gov.br/upload/arquivos/202608/04144124-alto-da-serra-do-botucarai-resultado-consulta-municipios-x-demandas-eleitas.xlsx",
    "https://admin.consultapopular.rs.gov.br/upload/arquivos/202608/04144308-serra-resultado-consulta-municipios-x-demandas-eleitas.xlsx",
    "https://admin.consultapopular.rs.gov.br/upload/arquivos/202608/04144301-missoes-resultado-consulta-municipios-x-demandas-eleitas-ok-via-whats.xlsx",
    "https://admin.consultapopular.rs.gov.br/upload/arquivos/202608/04144308-serra-resultado-consulta-programa-valor.xlsx",
]


def test_serra_nao_casa_alto_da_serra_do_botucarai():
    assert _escolher_planilha(URLS, "serra") == URLS[1]
    assert _escolher_planilha(URLS, "alto-da-serra-do-botucarai") == URLS[0]


def test_sufixo_livre_do_corede_nao_atrapalha():
    # Missoes publicou com "-ok-via-whats" no fim do nome
    assert _escolher_planilha(URLS, "missoes") == URLS[2]


def test_republicacao_prefere_o_mais_recente():
    urls = URLS + [URLS[1].replace("04144308-serra", "05090000-serra")]
    assert _escolher_planilha(urls, "serra").endswith("05090000-serra-resultado-consulta-municipios-x-demandas-eleitas.xlsx")


def test_corede_sem_planilha_devolve_none():
    assert _escolher_planilha(URLS, "litoral") is None
