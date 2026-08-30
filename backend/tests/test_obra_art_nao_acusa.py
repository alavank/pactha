"""ART/RRT: falha de LEITURA não pode virar ACUSAÇÃO ao município.

Achado por um agente de verificação (29/08/2026), fora da lista da auditoria
externa. É a pior das cinco falhas silenciosas encontradas, porque o resultado
não é um campo vazio — é uma **frase falsa num documento entregue ao prefeito**:

    "Necessário cumprir a exigência de cadastro da ART/RRT para possibilitar o
     início da obra"

⚠️ E ela também MOVE a obra de Parte: `_obra_sem_art` classifica o item como
"demanda do MUNICÍPIO" (Parte 2). Ou seja, a falha de leitura não só escrevia
uma acusação, como reorganizava o relatório em torno dela.

CAUSA: `arts` nascia `[]` e só era preenchido se a chamada respondesse. Os dois
leitores (HTTP e navegador) faziam igual, então "o portal não respondeu" e "não
há ART cadastrada" ficavam indistinguíveis no banco.
"""
import pytest

from services.rm_builder import _obra_sem_art, _obra_resumo


def _obras(*lotes):
    return {"lotes": list(lotes)}


# ------------------------------------------------- o que DEVE acusar --------
def test_lote_LIDO_e_sem_ART_acusa():
    """O caso legítimo, que é o pedido do dono: a leitura respondeu e não há ART.
    `[]` agora significa isso, e só isso."""
    assert _obra_sem_art(_obras({"arts": []})) is True
    assert "ART/RRT" in (_obra_resumo(_obras({"arts": []})) or "")


def test_lote_com_ART_nao_acusa():
    assert _obra_sem_art(_obras({"arts": [{"numero": "123"}]})) is False


# --------------------------------------------- o que NÃO pode acusar --------
def test_leitura_que_FALHOU_nao_acusa():
    """⚠️ A regressão. `arts: None` = o portal não respondeu (fora do ar, sessão
    expirada, 412). Antes isso virava `[]` e o relatório acusava o município."""
    assert _obra_sem_art(_obras({"arts": None})) is False
    assert "ART/RRT" not in (_obra_resumo(_obras({"arts": None})) or "")


def test_lote_SEM_a_chave_arts_nao_acusa():
    """Formato inesperado também é "não sei"."""
    assert _obra_sem_art(_obras({"numero": "1"})) is False


def test_UM_lote_nao_lido_ja_faz_calar():
    """⚠️ Com dois lotes — um lido e vazio, outro não lido — afirmar "não tem
    ART" seria apostar que o não lido também está vazio. Basta um para calar."""
    assert _obra_sem_art(_obras({"arts": []}, {"arts": None})) is False
    assert _obra_sem_art(_obras({"arts": None}, {"arts": []})) is False


def test_todos_lidos_e_todos_vazios_acusa():
    """Quando TODOS responderam e nenhum tem ART, a afirmação é medida."""
    assert _obra_sem_art(_obras({"arts": []}, {"arts": []})) is True


def test_um_lote_COM_ART_basta_para_nao_acusar():
    assert _obra_sem_art(_obras({"arts": []}, {"arts": [{"numero": "9"}]})) is False


# ------------------------------------------- os estados que já calavam ------
@pytest.mark.parametrize("obras", [None, {}, [], "", {"lotes": []}, {"lotes": None}])
def test_sem_obra_lida_continua_calando(obras):
    """Não-regressão: `{}` (instrumento sem medição, o portal responde 412) e
    `None` (não consegui ler) já devolviam False e continuam."""
    assert _obra_sem_art(obras) is False


def test_a_frase_e_a_classificacao_saem_da_MESMA_condicao():
    """⚠️ O repo já exigia isto: o texto que o relatório imprime e a decisão de
    Parte não podem divergir. Se divergissem, a obra iria para a Parte 2
    ("demanda do município") sem a frase que explica por quê — ou o contrário."""
    for obras in (_obras({"arts": []}), _obras({"arts": None}),
                  _obras({"arts": [{"numero": "1"}]}),
                  _obras({"arts": []}, {"arts": None})):
        acusa = _obra_sem_art(obras)
        texto = _obra_resumo(obras) or ""
        assert acusa == ("ART/RRT" in texto), obras
