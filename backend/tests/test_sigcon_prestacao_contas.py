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


# --------------------------------------------------------------------------
# COMO A SEÇÃO É ACHADA NA PÁGINA. Dois buracos que faziam o dado nunca sair,
# calado — e "calado" é a forma exata do defeito das Notas de Empenho.
# --------------------------------------------------------------------------
from ingestion.sigcon_scraper import (                                # noqa: E402
    _PC_JS, _PC_JS_TEXTO, _scrape_prestacao_contas,
)


class _PageFake:
    """Uma `page` do Playwright reduzida ao que esta leitora usa. O JS não roda:
    cada `evaluate` devolve o que o teste disser, então dá para fixar "não achei
    cabeçalho" + "o corpo tem os campos" e observar a DECISÃO do Python, que é o
    que está sob teste."""
    def __init__(self, diag, texto):
        self._diag, self._texto = diag, texto
        self.esperou = 0

    async def evaluate(self, js):
        return self._diag if js is _PC_JS else self._texto

    async def wait_for_timeout(self, ms):
        self.esperou += ms


def _corre(page):
    import asyncio
    return asyncio.run(_scrape_prestacao_contas(page))


def test_cabecalho_NAO_ACHADO_ainda_assim_le_o_corpo():
    """⚠️ REGRESSÃO. A 1ª versão fazia `if not achou: return None` — e isso matava
    a própria rede de segurança duas linhas abaixo. Bastava o cabeçalho ter outro
    nome (ou a seção ser uma ABA e não um accordion) para o dado nunca sair,
    calado, MESMO ESTANDO NA PÁGINA. Falha contra o código anterior."""
    p = _PageFake({"achou": False, "did": False, "headers": ["IDENTIFICAÇÃO"]},
                  {"painel": "", "corpo": PAINEL})
    d = _corre(p)
    assert d and d["prestacao_contas_sei"] == "1500.01.0234833/2024-4"


def test_sem_cabecalho_nao_clica_nem_espera():
    """Não achou o que clicar => não paga os 3s. O custo continua condicional."""
    p = _PageFake({"achou": False, "did": False, "headers": []},
                  {"painel": "", "corpo": PAINEL})
    _corre(p)
    assert p.esperou == 0


def test_secao_ja_aberta_nao_paga_os_3s():
    p = _PageFake({"achou": True, "wasExp": "true", "did": False, "headers": []},
                  {"painel": PAINEL, "corpo": ""})
    assert _corre(p)["prestacao_contas_status"].startswith("Aguardando")
    assert p.esperou == 0


def test_pagina_sem_o_dado_continua_devolvendo_None():
    """A rede de segurança não pode virar invenção: sem os rótulos, nada sai."""
    p = _PageFake({"achou": False, "did": False, "headers": []},
                  {"painel": "", "corpo": "Convênio 1234/2024 — SEGOV\nStatus: Em vigor"})
    assert _corre(p) is None


def test_o_seletor_cobre_ACCORDION_E_ABA():
    """⚠️ O dono escreveu "no sigcon na ABA prestação de contas". A 1ª versão
    procurava só `.ui-accordion-header` — o que as outras duas leitoras usam. Num
    `p:tabView` do PrimeFaces aquele seletor não acha nada."""
    for js in (_PC_JS, _PC_JS_TEXTO):
        assert "ui-accordion-header" in js
        assert "ui-tabs-nav" in js and 'role="tab"' in js


def test_o_painel_da_ABA_e_achado_por_aria_controls_e_href():
    """Accordion: o conteúdo é o próximo irmão. Aba: o painel vive em OUTRO lugar
    do DOM e o cabeçalho aponta para ele por `aria-controls`/`href="#id"`."""
    assert "aria-controls" in _PC_JS_TEXTO and "href" in _PC_JS_TEXTO


def test_aba_ja_selecionada_conta_como_aberta():
    """Accordion usa `aria-expanded`; aba usa `aria-selected`/`ui-state-active`.
    Sem os três, uma aba já aberta seria clicada de novo e pagaria 3s à toa."""
    assert "aria-selected" in _PC_JS and "ui-state-active" in _PC_JS


# --------------------------------------------------------------------------
# O QUE A PRODUÇÃO MOSTROU (29/08/2026, freitas, 99 convênios).
# O status saía certo; os outros TRÊS campos saíam lixo. A causa não era o
# parser de rótulos — era a FONTE do texto: o painel é um FORMULÁRIO, as datas
# e o SEI são <input>, e `innerText` não inclui valor de input.
# --------------------------------------------------------------------------
from ingestion.sigcon_scraper import _pc_forma                        # noqa: E402

# innerText de um formulário PrimeFaces: sobra o rótulo, o "*" de obrigatório e,
# logo depois, a barra de botões. Foi ISTO que os 99 convênios gravaram.
PAINEL_INNERTEXT = """Status Atual: Aguardando análise da prestação de contas final
Data do Preenchimento do Status: *
Nº SEI:
Cancelar Histórico Status
"""


def test_o_LIXO_que_a_producao_gravou_nao_passa_mais():
    """⚠️ Reprodução literal do medido: `prestacao_contas_sei` = "Cancelar
    Histórico Status" em 99 de 99, e `prestacao_contas_status_data` = "*".
    Nenhum dos dois é dado — e um número de processo inventado num documento
    entregue ao município é pior do que campo vazio."""
    d = ler_prestacao_contas(PAINEL_INNERTEXT)
    assert d["prestacao_contas_status"] == "Aguardando análise da prestação de contas final"
    assert "prestacao_contas_sei" not in d
    assert "prestacao_contas_status_data" not in d


def test_a_forma_manda_por_campo():
    """Data tem cara de data, processo tem cara de processo. O que não tem, não
    entra — e o valor bom é EXTRAÍDO de dentro do ruído, não descartado junto."""
    assert _pc_forma("prestacao_contas_sei", "Cancelar Histórico Status") is None
    assert _pc_forma("prestacao_contas_status_data", "*") is None
    assert _pc_forma("prestacao_contas_sei", "1500.01.0234833/2024-4 Cancelar") \
        == "1500.01.0234833/2024-4"
    assert _pc_forma("prestacao_contas_data", "08/08/2024 *") == "08/08/2024"
    # o status é texto livre: não dá para exigir forma sem inventar vocabulário
    assert _pc_forma("prestacao_contas_status", "Prestação de contas aprovada") \
        == "Prestação de contas aprovada"


def test_uma_DATA_nao_vira_numero_de_processo():
    """Se a fatia do SEI escorregar para a data vizinha, o relatório mostraria
    "Nº SEI 08/08/2024" — um processo que não existe."""
    assert _pc_forma("prestacao_contas_sei", "08/08/2024") is None


def test_o_caminhador_le_INPUT_e_ignora_BOTAO():
    """⚠️ As duas metades da correção, e a segunda é a que mata o lixo na
    origem: `value` de <button>/<input type=submit> é o RÓTULO dele ("Cancelar"),
    que foi exatamente a contaminação medida."""
    js = _PC_JS_TEXTO
    assert "n.value" in js, "tem de ler o valor dos campos"
    assert "BUTTON" in js and "submit|button|reset" in js, "tem de excluir botao"
    assert "selectedOptions" in js, "select tambem tem valor"
    assert "innerText" not in js.split("const alvo")[0], \
        "o texto do painel NAO pode voltar a sair de innerText"


def test_o_texto_do_caminhador_e_lido_certo():
    """Com os valores dos <input> no lugar, os quatro campos saem — é o mesmo
    texto de antes, mas agora com o que estava dentro dos campos."""
    d = ler_prestacao_contas(
        "Status Atual: Aguardando análise da prestação de contas final\n"
        "Data do Preenchimento do Status: * 06/05/2024\n"
        "Data de Apresentação da Prestação de Contas Final: * 08/08/2024\n"
        "Nº SEI: 1500.01.0234833/2024-4\n")
    assert d["prestacao_contas_status_data"] == "06/05/2024"
    assert d["prestacao_contas_data"] == "08/08/2024"
    assert d["prestacao_contas_sei"] == "1500.01.0234833/2024-4"


def test_o_rotulo_da_data_tolera_a_grafia_do_portal():
    """⚠️ A 1ª versão exigia a frase inteira `data DA apresentacao DA prestacao DE
    CONTAS`, copiada de UMA captura de tela. "de" no lugar de "da" derruba a
    frase e o parser cala sem dizer por quê."""
    for r in ("Data da Apresentação da Prestação de Contas Final",
              "Data de Apresentação da Prestação de Contas",
              "Data de Apresentacao"):
        assert ler_prestacao_contas(f"{r}: 08/08/2024")["prestacao_contas_data"] \
            == "08/08/2024"
