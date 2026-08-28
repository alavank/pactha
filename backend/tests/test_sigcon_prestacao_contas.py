"""SIGCON-MG: a secao 'PRESTAÇÃO DE CONTAS' do detalhe do convenio.

Pedido do dono (27/08/2026): levar para a tela e para o RM a SITUACAO ATUAL, o
Nº SEI e a DATA que essa secao exibe.

⚠️ O texto das fixtures e o da TELA (captura de 27/08/2026, convenio da PM
Araujos), com os acentos e o 'Nº' como o portal escreve. Reconstruir "mais
limpo" e o que faz um parser passar no teste e falhar no ar — foi assim que o
`ler_detalhe_empenho` do Portal de MG passou verde parando em "dois espacos".
"""
import pytest

from ingestion.sigcon_scraper import _fold, ler_prestacao_contas

# Como o innerText do painel chega: um par por linha, tabulacao entre rotulo e
# valor em parte deles (PrimeFaces mistura os dois).
PAINEL = """Status Atual:\tAguardando análise da prestação de contas final
Data do Preenchimento do Status: 06/05/2024
Data da Apresentação da Prestação de Contas Final: 08/08/2024
Nº SEI: 1500.01.0234833/2024-4
"""


def test_le_os_quatro_campos():
    d = ler_prestacao_contas(PAINEL)
    assert d == {
        "prestacao_contas_status": "Aguardando análise da prestação de contas final",
        "prestacao_contas_status_data": "06/05/2024",
        "prestacao_contas_data": "08/08/2024",
        "prestacao_contas_sei": "1500.01.0234833/2024-4",
    }


def test_o_SEI_nao_engole_o_resto_do_painel():
    """⚠️ O SEI e o ULTIMO rotulo conhecido. Sem o corte no proximo rotulo — mesmo
    um que o parser NAO conhece — ele levaria junto meia secao, e o numero do
    processo apareceria na tela com um paragrafo grudado."""
    d = ler_prestacao_contas(PAINEL + "Responsável pela Análise: FULANO DE TAL\n"
                                      "Observações: nada consta\n")
    assert d["prestacao_contas_sei"] == "1500.01.0234833/2024-4"


def test_o_rotulo_pode_ter_sufixo_que_eu_nao_previ():
    """'Nº SEI' e 'Nº SEI Prestação de Contas' sao o mesmo campo."""
    d = ler_prestacao_contas("Nº SEI Prestação de Contas: 1500.01.0234833/2024-4")
    assert d == {"prestacao_contas_sei": "1500.01.0234833/2024-4"}


def test_o_dobramento_de_acentos_NAO_muda_o_comprimento():
    """⚠️ A invariante de que o parser inteiro depende: os rotulos sao casados no
    texto DOBRADO e o valor e fatiado do texto ORIGINAL, pelos mesmos indices.
    `unicodedata.normalize('NFKD', ...)` quebraria o 'ç' em dois e deslocaria
    todo o resto — o valor sairia cortado, e so em convenio com acento antes do
    rotulo."""
    for s in ["ção", "Nº", "PREFEITURA MUNICIPAL DE ARAÚJOS", PAINEL]:
        assert len(_fold(s)) == len(s)


def test_acento_antes_do_rotulo_nao_desloca_o_valor():
    d = ler_prestacao_contas("Órgão: SEGOV\nStatus Atual: Aprovada\n")
    assert d == {"prestacao_contas_status": "Aprovada"}


def test_status_ATUAL_nao_se_confunde_com_o_Status_do_convenio():
    """⚠️ A pagina de detalhe ja tem um campo 'Status' (vira `status_detalhe`), e
    a leitura cai no CORPO inteiro quando o painel nao rende texto. O rotulo daqui
    e 'Status Atual' — exigir a palavra inteira e o que separa os dois."""
    assert ler_prestacao_contas("Status: Em execução\nConcedente: SEGOV\n") is None


def test_valor_em_linha_separada_do_rotulo():
    """PrimeFaces as vezes poe rotulo e valor em celulas diferentes: o innerText
    vem com quebra de linha no meio, e o valor NAO pode virar vazio."""
    d = ler_prestacao_contas("Status Atual:\nAguardando análise\nNº SEI: 123/2024\n")
    assert d["prestacao_contas_status"] == "Aguardando análise"
    assert d["prestacao_contas_sei"] == "123/2024"


def test_a_data_FINAL_vence_a_parcial():
    """As duas casam no mesmo rotulo ate a palavra 'contas'. A do pedido e a
    FINAL — e ela pode vir DEPOIS da parcial na tela."""
    d = ler_prestacao_contas(
        "Data da Apresentação da Prestação de Contas Parcial: 01/01/2024\n"
        "Data da Apresentação da Prestação de Contas Final: 08/08/2024\n")
    assert d["prestacao_contas_data"] == "08/08/2024"


def test_as_DUAS_datas_sao_campos_diferentes():
    """⚠️ Nao colapsar numa so: 06/05 e quando o ESTADO mexeu no status, 08/08 e
    quando o MUNICIPIO entregou. Escolher uma seria adivinhar qual pergunta o
    leitor esta fazendo."""
    d = ler_prestacao_contas(PAINEL)
    assert d["prestacao_contas_status_data"] != d["prestacao_contas_data"]


@pytest.mark.parametrize("t", [None, "", "   ", "Convênio 1234/2024 — SEGOV"])
def test_painel_sem_rotulo_devolve_None(t):
    """None, e nao {}: chave ausente e 'nao veio', e o upsert faz MERGE em
    `raw_data`. Gravar vazio APAGARIA o valor da rodada anterior num convenio
    cujo accordion nao abriu."""
    assert ler_prestacao_contas(t) is None


def test_campo_vazio_nao_vira_string_vazia():
    d = ler_prestacao_contas("Status Atual:\nNº SEI: 123/2024\n")
    assert "prestacao_contas_status" not in d
    assert d["prestacao_contas_sei"] == "123/2024"


# --------------------------------------------------------------------------
# AS CAMADAS DE CIMA: builder -> caixa do PDF/Word.
# --------------------------------------------------------------------------
from services.rm_builder import _prestacao_contas_campos          # noqa: E402
from services.rm_pdf import _prestacao_contas_destaque            # noqa: E402
from services.texto_rm import normalizar_item                     # noqa: E402

RAW = {
    "prestacao_contas_status": "Aguardando análise da prestação de contas final",
    "prestacao_contas_status_data": "06/05/2024",
    "prestacao_contas_data": "08/08/2024",
    "prestacao_contas_sei": "1500.01.0234833/2024-4",
}


def test_o_builder_leva_os_quatro_campos_para_o_item():
    assert _prestacao_contas_campos(RAW) == RAW


def test_convenio_sem_prestacao_nao_ganha_campo_nenhum():
    """{} e nao chaves vazias: `add_item` funde isto com `**`, e chave vazia faria
    a caixa do PDF existir em todo convenio de fonte que nao e SIGCON-MG."""
    assert _prestacao_contas_campos({}) == {}
    assert _prestacao_contas_campos({"outra_coisa": "x"}) == {}
    assert _prestacao_contas_campos(None) == {}


def test_captura_PARCIAL_vale():
    """Mesma regra de `_alteracao_campos`: exigir o status jogaria fora um SEI ja
    capturado num convenio cujo status ainda nao foi preenchido."""
    assert _prestacao_contas_campos({"prestacao_contas_sei": "123/2024"}) == {
        "prestacao_contas_status": "", "prestacao_contas_data": "",
        "prestacao_contas_status_data": "", "prestacao_contas_sei": "123/2024"}


def test_a_caixa_do_relatorio_ROTULA_as_duas_datas():
    """⚠️ Sem rótulo, "06/05/2024 · 08/08/2024" nao diz qual e a entrega do
    municipio e qual e o carimbo do Estado — e a leitura natural (a primeira e a
    principal) e justamente a errada."""
    cx = _prestacao_contas_destaque(dict(RAW))
    assert "apresentada em 08/08/2024" in cx
    assert "status preenchido em 06/05/2024" in cx
    assert "1500.01.0234833/2024-4" in cx


def test_sem_dado_nao_ha_caixa():
    assert _prestacao_contas_destaque({}) is None
    assert _prestacao_contas_destaque({"prestacao_contas_status": ""}) is None


def test_so_o_SEI_ja_rende_caixa():
    cx = _prestacao_contas_destaque({"prestacao_contas_sei": "123/2024"})
    assert cx and "sem status informado" in cx and "123/2024" in cx


def test_o_numero_do_SEI_NAO_e_reescrito_pelo_normalizador():
    """⚠️ `normalizar_item` poe os campos de LEITURA em caixa de frase — e um
    numero de processo passado por `frase()` viraria '1500.01.0234833/2024-4'
    remontado. So o STATUS entra em `_CAMPOS_FRASE`."""
    item = normalizar_item({**RAW, "prestacao_contas_status": "AGUARDANDO ANÁLISE"})
    assert item["prestacao_contas_sei"] == "1500.01.0234833/2024-4"
    assert item["prestacao_contas_data"] == "08/08/2024"
    assert item["prestacao_contas_status"] == "Aguardando análise"
