"""Convênio vindo do Novo PAC não pode sair duas vezes no relatório.

Quando a seleção do PAC vira instrumento, o mesmo recurso aparecia como
voluntária (o instrumento de verdade — valores, vigência, execução) E como item
do Novo PAC (que é só a etapa da seleção). O elo entre os dois é o "Número da
Proposta Novo PAC" que a própria voluntária carrega no `detalhe`, e que até agora
não era lido por ninguém.
"""
from services.rm_builder import _pac_da_voluntaria, _mesma_proposta


# --------------------------------------------------------------------------
# Achar o número no detalhe
# --------------------------------------------------------------------------
def test_acha_o_numero_com_o_rotulo_do_portal():
    det = {"Código do Instrumento": "992968",
           "Número da Proposta Novo PAC - Seleção": "56000004633/2025"}
    assert _pac_da_voluntaria(det) == "56000004633/2025"


def test_busca_tolerante_a_grafia():
    """⚠️ O rótulo tem acento, hífen e espaços, e passa por limpeza antes de virar
    chave. Casar a string inteira seria apostar na grafia — basta conter
    "novo pac", normalizado."""
    for chave in ("numero da proposta novo pac selecao",
                  "Número da Proposta NOVO PAC – Seleção",
                  "Proposta Novo PAC"):
        assert _pac_da_voluntaria({chave: "56000004633/2025"}) == "56000004633/2025"


def test_ignora_chaves_internas_e_valores_vazios():
    assert _pac_da_voluntaria({"_novo_pac_interno": "x"}) == ""
    assert _pac_da_voluntaria({"Número da Proposta Novo PAC": "   "}) == ""


def test_voluntaria_sem_pac_nao_inventa_vinculo():
    det = {"Código do Instrumento": "981397", "Modalidade": "Convênio"}
    assert _pac_da_voluntaria(det) == ""
    for vazio in (None, {}, "nao e json"):
        assert _pac_da_voluntaria(vazio) == ""


# --------------------------------------------------------------------------
# Comparar os dois números
# --------------------------------------------------------------------------
def test_mesma_proposta_ignora_pontuacao():
    """O número chega de duas telas diferentes; um espaço a mais deixaria a
    duplicata passar."""
    assert _mesma_proposta("56000004633/2025", "56000004633/2025") is True
    assert _mesma_proposta("56000004633/2025", " 56000004633 / 2025 ") is True


def test_propostas_diferentes_nao_se_confundem():
    assert _mesma_proposta("56000004633/2025", "56000004634/2025") is False
    assert _mesma_proposta("56000004633/2025", "56000004633/2024") is False


def test_vazio_nunca_casa():
    """Comparar vazios daria True e o RM esconderia TODO item do PAC — o oposto
    do pedido, e calado."""
    assert _mesma_proposta("", "") is False
    assert _mesma_proposta(None, None) is False
    assert _mesma_proposta("", "56000004633/2025") is False
