"""Transferências Voluntárias de GO: separar o que é defeito da ORIGEM, já
conhecido, do que é formato novo — e acusar a origem que parou de publicar.

⚠️ O QUE ACONTECIA: o recurso "202603" do CKAN da CGE-GO é a extração histórica
2003-2025 (uma coluna só, `linha`), não o mês. O coletor o tratava como "formato
inesperado" toda rodada, a fonte ficou `partial` por mais de um mês e o vigia
repetia "fonte parada 871h" — enquanto o problema real passava calado: a origem
não publica nada depois de 202605 (medido em 10/09/2026).
"""
from datetime import date

from ingestion.transfvol_go import (ARQUIVO_ERRADO_CONHECIDO, ATRASO_MAX_MESES,
                                    COLUNAS_MINIMAS, _classificar, _meses_de_atraso)


def test_mes_com_as_colunas_certas_e_lido():
    assert _classificar("202605", set(COLUNAS_MINIMAS) | {"DESCRICAO"}) == "ok"


def test_o_202603_errado_ja_conhecido_nao_derruba_a_rodada():
    assert _classificar("202603", {"linha"}) == "errado_conhecido"


def test_se_a_origem_republicar_o_202603_certo_ele_e_lido():
    # A assinatura faz parte da chave: corrigido na origem, entra normalmente.
    assert _classificar("202603", set(COLUNAS_MINIMAS)) == "ok"


def test_terceiro_formato_no_202603_volta_a_acusar():
    assert _classificar("202603", {"coluna_nova", "outra"}) == "formato_ruim"


def test_a_mesma_assinatura_em_outro_mes_nao_e_perdoada():
    # O perdão é por (competência, assinatura). A mesma extração publicada no
    # lugar de OUTRO mês é defeito novo e tem de acusar.
    assert _classificar("202605", {"linha"}) == "formato_ruim"


def test_atraso_em_meses():
    assert _meses_de_atraso("202605", date(2026, 9, 10)) == 4
    assert _meses_de_atraso("202612", date(2027, 1, 5)) == 1


def test_o_estado_medido_em_10_09_e_origem_atrasada():
    # 202605 publicado em 22/06; em setembro faltam junho, julho e agosto.
    assert _meses_de_atraso("202605", date(2026, 9, 10)) > ATRASO_MAX_MESES


def test_publicacao_no_ritmo_normal_nao_acusa():
    # A CGE-GO publica ~3 semanas depois do fechamento: em 10/09 o normal é o
    # mais novo ser 202607 (ou 202608). Isso não pode alarmar.
    assert _meses_de_atraso("202607", date(2026, 9, 10)) <= ATRASO_MAX_MESES
    assert _meses_de_atraso("202606", date(2026, 9, 10)) <= ATRASO_MAX_MESES


def test_a_nota_do_arquivo_conhecido_explica_o_que_falta():
    nota = ARQUIVO_ERRADO_CONHECIDO["202603"][1]
    assert "sem dado de 03/2026" in nota
