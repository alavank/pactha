"""Dinheiro do TransfereGov: a trava que impede valor DESLOCADO de ser gravado.

Origem: auditoria externa (29/08/2026) reportou "Valor de Repasse e Valor Global
INVERTIDOS em 60% da carteira". A verificação mostrou que o auditor acertou que há
defeito e ERROU o nome dele — e o nome muda o conserto.

⚠️ NÃO É TROCA e NÃO É TRUNCAMENTO. É DESLOCAMENTO DE UM CAMPO. `grab_money`
(transferegov_http.py) procura o próximo "R$" DEPOIS do rótulo, e o portal imprime
o valor ANTES dele. Com os três campos em sequência, cada rótulo colhe o do
seguinte:

    valor_global        <- o REPASSE
    valor_repasse       <- a CONTRAPARTIDA
    valor_contrapartida <- nada

A aritmética da creche de Araújos é o que nomeia o defeito:

    3.823.677,33 - 3.819.853,65 = 3.823,68   (exato)

O número que aparecia como "repasse" ERA a contrapartida.

MEDIDO EM PRODUÇÃO (freitas, 29/08/2026): 854 de 3.199 propostas (27%) com
`global <> repasse + contrapartida`, e 3 aritmeticamente impossíveis
(`global < repasse`). O "60%" do relatório não se confirmou; o defeito, sim.
"""
import pytest

from ingestion.transferegov_voluntarias import _money, valores_coerentes

# Os números REAIS da creche de Araújos (do relatório de auditoria).
GLOBAL, REPASSE, CONTRAP = 3823677.33, 3819853.65, 3823.68


def test_a_aritmetica_que_nomeia_o_defeito():
    """⚠️ Esta é a prova de que não é truncamento nem inversão. Se fosse
    truncamento de milhar, 3.823,68 seria um pedaço de 3.823.677,33 — e não é:
    é a diferença EXATA entre o global e o repasse, ou seja, a contrapartida."""
    assert round(GLOBAL - REPASSE, 2) == CONTRAP


def test_o_trio_CORRETO_passa():
    assert valores_coerentes(GLOBAL, REPASSE, CONTRAP) is True


def test_o_trio_DESLOCADO_e_recusado():
    """O que o portal produzia: global recebe o repasse, repasse recebe a
    contrapartida, contrapartida fica vazia."""
    assert valores_coerentes(REPASSE, CONTRAP, None) is False


def test_convenio_SEM_contrapartida_e_coerente():
    """Contrapartida zero/ausente é caso normal — não pode ser recusado."""
    assert valores_coerentes(100000.0, 100000.0, None) is True
    assert valores_coerentes(100000.0, 100000.0, 0) is True


def test_faltando_uma_peca_NAO_grava():
    """⚠️ Sem global ou sem repasse não há o que conferir. Recusar é o certo: o
    CSV de dados abertos é a fonte AUTORITATIVA declarada para estes três campos
    (`transferegov_opendata._SOBRESCREVE`), e devolver None faz o COALESCE do
    upsert PRESERVAR o valor bom que o dump já gravou."""
    assert valores_coerentes(100000.0, None, None) is False
    assert valores_coerentes(None, 100000.0, 5000.0) is False
    assert valores_coerentes(None, None, None) is False


def test_o_impossivel_e_recusado():
    """3 linhas em produção têm `global < repasse` — aritmeticamente impossível."""
    assert valores_coerentes(1000.0, 5000.0, 0) is False


def test_tolerancia_de_centavo_nao_derruba_arredondamento_legitimo():
    """O portal arredonda; 1 centavo de diferença não é deslocamento."""
    assert valores_coerentes(100000.01, 100000.0, None) is True
    assert valores_coerentes(100000.50, 100000.0, None) is False


@pytest.mark.parametrize("v", ["", None, "abc", "R$"])
def test_lixo_nao_vira_numero(v):
    assert valores_coerentes(_money(v), _money(v), _money(v)) is False


def test_a_funcao_de_moeda_NAO_trunca():
    """⚠️ A hipótese que esta sessão levantou e que a medição refutou. Se `_money`
    truncasse no separador de milhar, o conserto seria outro — por isso vale um
    teste fixando que ela NÃO trunca."""
    assert _money("R$ 3.823.677,33") == 3823677.33
    assert _money("R$ 3.823,68") == 3823.68
    assert _money("R$ 3.819.853,65") == 3819853.65


def test_o_deslocamento_NUNCA_fecha_a_soma():
    """⚠️ A razão de a trava ser sobre o RESULTADO e não sobre o layout: o portal
    serve mais de um formato de página, e perseguir cada um seria correr atrás
    dele para sempre. Um trio deslocado não fecha a conta em nenhum formato."""
    for g, r, c in [(REPASSE, CONTRAP, None),          # deslocado 1 campo
                    (CONTRAP, None, None),             # deslocado 2
                    (REPASSE, GLOBAL, CONTRAP)]:       # global e repasse trocados
        assert valores_coerentes(g, r, c) is False
