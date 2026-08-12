"""O "parlamentar" que nao existe.

No cliente freitas, o maior parlamentar do ranking era **"Não há"**: 12
convenios, R$ 14.936.735,03, em 7 municipios — treze vezes o segundo colocado.
O SIGCON-MG escreve esse texto no campo `responsaveis` quando nao ha
responsavel, e tres telas (Parlamentares, Painel de Indicadores e relatorio RM)
tratavam a frase como nome de pessoa.

O teste que importa e o ultimo: a regra e por IGUALDADE EXATA, nunca por
substring. Uma regra por substring apagaria um parlamentar de verdade cujo nome
contenha o fragmento — o oposto do defeito que ela conserta, e silencioso.
"""
import pytest

from services.nome_parlamentar import e_parlamentar_real


@pytest.mark.parametrize("texto", [
    "Não há",
    "NÃO HÁ",
    "nao ha",
    "  não   há  ",      # espaco duplo e sobra dos dois lados
    "N/A",
    "n/a",
    "Não informado",
    "Sem responsável",
    "-",
    "--",
    "AB",                 # abaixo do piso de 3 caracteres
    "",
    None,
])
def test_marcador_de_ausencia_nao_e_parlamentar(texto):
    assert e_parlamentar_real(texto) is False


@pytest.mark.parametrize("nome", [
    "LOHANNA",
    "EDUARDO AZEVEDO",
    "BLOCO DEMOCRACIA E LUTA",   # bancada tambem conta
    "Betinho Pinto Coelho",
    "CFFO",                      # sigla curta, mas >= 3 caracteres
])
def test_parlamentar_real_passa(nome):
    assert e_parlamentar_real(nome) is True


@pytest.mark.parametrize("nome", [
    "Ana Não Sei",
    "Não Aparecido da Silva",
    "Joao Nao Ha Mais",
])
def test_nome_que_CONTEM_o_marcador_nao_pode_ser_engolido(nome):
    """A trava contra a correcao virar um defeito pior.

    Se alguem trocar a igualdade por `in` ou por `startswith` para "pegar mais
    casos", estes tres nomes somem do ranking sem erro nenhum e sem ninguem
    notar — que e exatamente como o "Não há" entrou.
    """
    assert e_parlamentar_real(nome) is True
