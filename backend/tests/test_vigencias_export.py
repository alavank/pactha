"""Vigências a vencer em PDF/Excel — o recorte, as contas e os dois formatos.

O que estes testes protegem, em uma frase cada:
  - None NÃO é zero (o total não pode parecer completo quando não é);
  - o filtro é por NOME, que é o que a tela manda;
  - PDF e Excel saem do MESMO `normalizar` — nenhum dos dois soma por conta.
"""
from services import vigencias_export as vx


class _A:
    """Um AlertaVigencia do jeito que o endpoint devolve (só os campos lidos)."""

    def __init__(self, municipio_nome=None, dias_restantes=10, valor_total=1000.0,
                 esfera="estadual", nr_convenio=None, nr_sigcon="123/2024",
                 objeto="Obra", orgao_concedente="SEINFRA", situacao="Em vigor",
                 dt_fim_vigencia=None):
        self.municipio_nome = municipio_nome
        self.dias_restantes = dias_restantes
        self.valor_total = valor_total
        self.esfera = esfera
        self.nr_convenio = nr_convenio
        self.nr_sigcon = nr_sigcon
        self.objeto = objeto
        self.orgao_concedente = orgao_concedente
        self.situacao = situacao
        self.dt_fim_vigencia = dt_fim_vigencia


# --------------------------------------------------------------- o recorte ----
def test_filtra_por_nome_do_municipio():
    d = vx.normalizar([_A("Ibitiúra"), _A("Monte Sião"), _A("Ibitiúra")],
                      ["Ibitiúra"])
    assert d["geral"]["qtd"] == 2
    assert [t["municipio"] for t in d["totais"]] == ["Ibitiúra"]


def test_lista_vazia_de_municipios_significa_TODOS():
    """A tela manda `[]` quando o MultiSelect está em «Todos». Se isso fosse lido
    como "nenhum município", o arquivo sairia vazio no caso mais comum de uso."""
    assert vx.normalizar([_A("A"), _A("B")], [])["geral"]["qtd"] == 2
    assert vx.normalizar([_A("A"), _A("B")], None)["geral"]["qtd"] == 2


def test_sem_municipio_vira_o_MESMO_travessao_da_tela():
    d = vx.normalizar([_A(None)], None)
    assert d["totais"][0]["municipio"] == "—"


# ------------------------------------------------------------------ contas ----
def test_valor_None_NAO_entra_como_zero():
    """⚠️ O teste que justifica o campo `sem_valor`. Somar None como 0,00 daria um
    total com cara de completo — e a diferença não apareceria em lugar nenhum."""
    d = vx.normalizar([_A("X", valor_total=100.0), _A("X", valor_total=None)], None)
    t = d["totais"][0]
    assert t["valor"] == 100.0
    assert t["sem_valor"] == 1
    assert t["qtd"] == 2          # continua contando como instrumento
    assert d["geral"]["sem_valor"] == 1


def test_menor_prazo_e_o_menor_de_verdade():
    d = vx.normalizar([_A("X", dias_restantes=90), _A("X", dias_restantes=7)], None)
    assert d["totais"][0]["menor"] == 7


def test_faixas_batem_com_as_da_tela():
    """30 e 60 são os limites do `tomDias` do modal — e são INCLUSIVOS lá."""
    d = vx.normalizar([_A("X", dias_restantes=30), _A("X", dias_restantes=31),
                       _A("X", dias_restantes=60), _A("X", dias_restantes=61)], None)
    t = d["totais"][0]
    assert t["criticos"] == 1     # 30
    assert t["atencao"] == 2      # 31 e 60
    # 61 não entra em nenhuma faixa, mas continua contado
    assert t["qtd"] == 4


def test_totais_saem_do_maior_para_o_menor():
    """A mesma ordem das bolhas do modal — quem abre o PDF procura primeiro
    'onde está concentrado'."""
    d = vx.normalizar([_A("A"), _A("B"), _A("B"), _A("C"), _A("C"), _A("C")], None)
    assert [t["municipio"] for t in d["totais"]] == ["C", "B", "A"]


def test_empate_desempata_por_nome():
    d = vx.normalizar([_A("Zebra"), _A("Alfa")], None)
    assert [t["municipio"] for t in d["totais"]] == ["Alfa", "Zebra"]


def test_a_ordem_das_linhas_e_a_que_chegou():
    """Quem ordena é o endpoint (asc/desc, como a tela). `normalizar` não
    reordena a lista — senão o arquivo sairia numa ordem e a tela em outra."""
    d = vx.normalizar([_A("X", dias_restantes=90), _A("X", dias_restantes=7)], None)
    assert [l["dias"] for l in d["linhas"]] == [90, 7]


def test_esfera_sai_com_nome_de_gente():
    d = vx.normalizar([_A("X", esfera="voluntaria"), _A("X", esfera="estadual")], None)
    assert {l["esfera"] for l in d["linhas"]} == {"Federal", "Estadual"}


def test_numero_cai_do_convenio_para_o_sigcon():
    d = vx.normalizar([_A("X", nr_convenio="ABC", nr_sigcon="999"),
                       _A("X", nr_convenio=None, nr_sigcon="999")], None)
    assert [l["numero"] for l in d["linhas"]] == ["ABC", "999"]


# ----------------------------------------------------------------- formatos ---
def _dados(n=3):
    return vx.normalizar([_A(f"Mun {i}", dias_restantes=i * 20) for i in range(1, n + 1)],
                         None)


def test_pdf_sai_pdf():
    b = vx.gerar_pdf(_dados(), dias=120, municipios=None)
    assert b[:4] == b"%PDF" and len(b) > 1500


def test_xlsx_sai_xlsx():
    b = vx.gerar_xlsx(_dados(), dias=120, municipios=None)
    assert b[:2] == b"PK" and len(b) > 3000


def test_recorte_vazio_gera_pdf_que_FALA():
    """Folha em branco lê-se como «não há nada vencendo». Quando o recorte é que
    está vazio, o documento tem de dizer isso."""
    b = vx.gerar_pdf(vx.normalizar([], ["Inexistente"]), dias=120,
                     municipios=["Inexistente"])
    assert b[:4] == b"%PDF"
    assert len(b) > 900          # tem conteúdo, não é uma folha só com o título


def test_excel_grava_valor_como_NUMERO_e_total_como_FORMULA():
    """⚠️ O motivo de existir. Valor em texto responde SOMA = 0 sem avisar, e um
    total constante mente depois de a pessoa filtrar linhas."""
    import io
    from openpyxl import load_workbook

    b = vx.gerar_xlsx(_dados(2), dias=120, municipios=None)
    wb = load_workbook(io.BytesIO(b))
    ws = wb["Totalizador"]
    assert isinstance(ws["F2"].value, (int, float))       # valor: número, não "R$ ..."
    assert str(ws["F4"].value).startswith("=SUM(")        # linha do TOTAL: fórmula
    assert {"Totalizador", "Lista", "Recorte"} <= set(wb.sheetnames)


def test_excel_guarda_o_recorte_numa_aba():
    """A planilha circula solta por e-mail; sem isto ninguém sabe, um mês depois,
    de quantos municípios ela é nem de que dia são os prazos."""
    import io
    from openpyxl import load_workbook

    b = vx.gerar_xlsx(_dados(2), dias=90, municipios=["Mun 1"])
    ws = load_workbook(io.BytesIO(b))["Recorte"]
    textos = [str(ws.cell(r, 1).value) + "|" + str(ws.cell(r, 2).value)
              for r in range(1, 10)]
    assert any("90" in t for t in textos)
    assert any("Mun 1" in t for t in textos)


def test_os_dois_formatos_contam_a_MESMA_coisa():
    """PDF e Excel consomem o mesmo `normalizar` — este teste falha no dia em que
    alguém puser uma soma dentro de um dos renderizadores."""
    import io
    from openpyxl import load_workbook

    d = _dados(4)
    ws = load_workbook(io.BytesIO(vx.gerar_xlsx(d, dias=120, municipios=None)))["Lista"]
    linhas_excel = sum(1 for r in range(2, ws.max_row + 1) if ws.cell(r, 2).value)
    assert linhas_excel == d["geral"]["qtd"] == 4


def test_objeto_gigante_nao_estoura_o_pdf():
    """Objeto de 4 mil caracteres existe na base. Sem o corte a célula empurra a
    tabela para fora da página e o reportlab levanta."""
    d = vx.normalizar([_A("X", objeto="w" * 4000)], None)
    assert vx.gerar_pdf(d, dias=120, municipios=None)[:4] == b"%PDF"


def test_marcacao_de_reportlab_no_objeto_nao_vira_tag():
    """`<b>` num objeto vindo da fonte quebraria o Paragraph do reportlab."""
    d = vx.normalizar([_A("X", objeto="Obra <b>&</b> reforma")], None)
    assert vx.gerar_pdf(d, dias=120, municipios=None)[:4] == b"%PDF"
