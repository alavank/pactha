"""Situação da obra no RM — a frase e o percentual derivado.

O percentual existe no "Resumo Físico-Financeiro" do portal, mas os dois valores
que o compõem já vêm no JSONB de obras. Derivar em vez de buscar economiza um GET
por instrumento num host de 2 vCPU — e estes testes provam que o número bate com
o exemplo que o dono passou, dígito a dígito.
"""
from services.rm_builder import _obra_pct, _obra_resumo


# --------------------------------------------------------------------------
# Percentual — derivado, sem requisição
# --------------------------------------------------------------------------
def test_percentual_bate_com_o_exemplo_do_dono():
    # 344.827,46 / 368.000,00 = 93,70% — o número do print, dígito a dígito
    assert _obra_pct(368000.00, 344827.46) == 93.70


def test_percentual_tolera_total_ausente_ou_zero():
    """Divisão por zero não pode derrubar a emissão do relatório."""
    assert _obra_pct(0, 100) is None
    assert _obra_pct(None, 100) is None
    assert _obra_pct(100, None) is None


def test_percentual_aceita_numero_como_texto():
    """O JSONB pode trazer o valor como string, dependendo do driver."""
    assert _obra_pct("368000.00", "344827.46") == 93.70


# --------------------------------------------------------------------------
# A frase — as duas saídas que o dono especificou
# --------------------------------------------------------------------------
def _obra(total, realizado, com_art=True):
    lote = {"arts": [{"numero": "123"}] if com_art else []}
    return {"valor_total_submetas": total, "valor_total_realizado": realizado,
            "lotes": [lote]}


def test_frase_de_execucao_no_formato_pedido():
    t = _obra_resumo(_obra(368000.00, 344827.46))
    assert t == ("A obra encontra-se em execução, totalizando R$ 344.827,46 em "
                 "valor executado, correspondente a 93,70% do valor total de "
                 "R$ 368.000,00.")


def test_frase_com_a_contagem_de_medicoes_quando_ela_existir():
    """⚠️ O dono escreveu "com 02 medições atestadas", mas essa contagem NÃO é
    coletada hoje por nenhum endpoint que o obras() consulta. O parâmetro existe
    para a frase nascer completa no dia em que o dado entrar — e o teste fixa o
    formato com zero à esquerda, como ele escreveu."""
    t = _obra_resumo(_obra(368000.00, 344827.46), medicoes=2)
    assert "com 02 medições atestadas, totalizando" in t


def test_singular_da_medicao():
    assert "com 01 medição atestada, " in _obra_resumo(_obra(1000.0, 500.0), medicoes=1)


def test_sem_art_a_pendencia_e_o_cadastro_e_vence_os_numeros():
    """Sem ART/RRT a obra NÃO PODE ser medida — então nenhum número de execução
    importa, e a frase é a da pendência, mesmo havendo valor executado."""
    t = _obra_resumo(_obra(368000.00, 344827.46, com_art=False))
    assert t == ("Necessário cumprir a exigência de cadastro da ART/RRT para "
                 "possibilitar o lançamento da primeira medição no sistema.")


def test_sem_obra_nao_inventa_frase():
    for vazio in (None, {}, {"lotes": []}, "nao e json"):
        assert _obra_resumo(vazio) == ""


def test_sem_valor_executado_fica_calado():
    """Obra com ART mas sem nenhum valor realizado ainda: o RM não afirma
    execução — melhor calar do que dizer "0,00% executado" como se fosse notícia."""
    assert _obra_resumo(_obra(368000.00, None)) == ""


# --------------------------------------------------------------------------
# Contagem de medições vinda do coletor (endpoint /contratos/{id}/medicoes)
# --------------------------------------------------------------------------
def _obra_com_medicoes(atestadas, com_art=True):
    return {"valor_total_submetas": 368000.00, "valor_total_realizado": 344827.46,
            "lotes": [{"arts": [{"numero": "1"}] if com_art else [],
                       "medicoes_atestadas": atestadas}]}


def test_conta_medicoes_dos_lotes_sem_precisar_do_parametro():
    """O coletor passou a contar as atestadas por lote; a frase soma sozinha."""
    t = _obra_resumo(_obra_com_medicoes(2))
    assert "com 02 medições atestadas, totalizando" in t


def test_soma_medicoes_de_varios_lotes():
    o = {"valor_total_submetas": 1000.0, "valor_total_realizado": 500.0,
         "lotes": [{"arts": [{"n": 1}], "medicoes_atestadas": 2},
                   {"arts": [{"n": 2}], "medicoes_atestadas": 3}]}
    assert "com 05 medições atestadas" in _obra_resumo(o)


def test_parametro_explicito_vence_a_soma():
    """Quem chama pode sobrescrever — útil para teste e para dado vindo de outra
    origem."""
    assert "com 07 medições atestadas" in _obra_resumo(_obra_com_medicoes(2), medicoes=7)


def test_proposta_coletada_antes_desta_versao_nao_inventa_numero():
    """Sem a chave `medicoes_atestadas` (JSONB antigo), a oração some — a frase
    continua correta, só mais curta."""
    o = {"valor_total_submetas": 368000.00, "valor_total_realizado": 344827.46,
         "lotes": [{"arts": [{"numero": "1"}]}]}
    t = _obra_resumo(o)
    assert "medições atestadas" not in t
    assert t.startswith("A obra encontra-se em execução, totalizando")
