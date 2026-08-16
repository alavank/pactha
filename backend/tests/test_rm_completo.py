"""Regras do RM COMPLETO (todos os anos) — services/rm_builder.

Testa as FUNCOES PURAS de classificacao por estagio (o coracao do completo) sem
tocar no banco, e prova o INVARIANTE de nao-regressao: com completo=False as
funcoes de retencao continuam identicas ao comportamento anual.
"""
from datetime import date

from services.rm_builder import (
    _destino_completo, _pend_municipal, _fed_retem, _fns_retem, _fed_status,
    _titulos_partes_completo,
    _SEC_FED_PLURAL, _SEC_FED_SINGULAR, _SEC_EST_P2, _SEC_EST_P3_RES, _SEC_EST_P3_CONV,
)

ANO = 2026


# --------------------------------------------------------------------------
# Classificacao por ESTAGIO/SITUACAO (Partes 1-4) — a regra da referencia
# --------------------------------------------------------------------------
def test_parte1_pendencia_federal():
    # federal aprovado/em analise, sem pendencia municipal -> Parte 1 (Brasilia)
    parte, secao, suf = _destino_completo(
        "federal", "voluntaria", "ativa", 2025, None, ANO,
        pend_municipal=False, pre_empenho_novo=False, tem_convenio=False)
    assert parte == 1 and secao == _SEC_FED_PLURAL and suf == ""


def test_parte1_empenhado_aguardando_desembolso():
    parte, _s, _ = _destino_completo(
        "federal", "voluntaria", "empenhada", 2024, None, ANO,
        False, False, False)
    assert parte == 1


def test_parte2_pendencia_municipal():
    # federal cuja bola esta com o municipio (licitacao) -> Parte 2
    parte, secao, _ = _destino_completo(
        "federal", "voluntaria", "empenhada", 2025, None, ANO,
        pend_municipal=True, pre_empenho_novo=False, tem_convenio=False)
    assert parte == 2 and secao == _SEC_FED_PLURAL


def test_parte2_pago_no_ano_corrente_federal():
    # federal PAGO no ano corrente -> Parte 2, bloco "REPASSES DE {ano}", sufixo Pagos
    parte, secao, suf = _destino_completo(
        "federal", "simec", "paga", ANO, ANO, ANO, False, False, False)
    assert parte == 2
    assert secao == f"REPASSES DE {ANO}:"
    assert suf == f" - Pagos {ANO}"


def test_parte3_pago_ano_anterior_federal():
    parte, secao, suf = _destino_completo(
        "federal", "simec", "paga", 2019, 2019, ANO, False, False, False)
    assert parte == 3 and secao == _SEC_FED_SINGULAR and suf == ""


def test_parte4_voluntaria_do_ano_corrente():
    parte, secao, _ = _destino_completo(
        "federal", "voluntaria", "ativa", ANO, None, ANO,
        pend_municipal=False, pre_empenho_novo=True, tem_convenio=False)
    assert parte == 4 and secao == _SEC_FED_PLURAL


def test_estadual_pago_recente_vai_parte2():
    # estadual pago em 2025 (janela de 2 anos) -> Parte 2 estadual
    parte, secao, _ = _destino_completo(
        "estadual", "sigcon", "paga", 2025, 2025, ANO, False, False, True)
    assert parte == 2 and secao == _SEC_EST_P2


def test_estadual_convenio_antigo_parte3_convenios():
    parte, secao, _ = _destino_completo(
        "estadual", "sigcon", "paga", 2018, 2018, ANO, False, False, tem_convenio=True)
    assert parte == 3 and secao == _SEC_EST_P3_CONV


def test_estadual_indicacao_antiga_parte3_resolucoes():
    parte, secao, _ = _destino_completo(
        "estadual", "emenda_estadual", "paga", 2019, 2019, ANO, False, False, tem_convenio=False)
    assert parte == 3 and secao == _SEC_EST_P3_RES


def test_estadual_em_ciclo_nao_pago_parte2():
    parte, secao, _ = _destino_completo(
        "estadual", "sigcon", "ativa", 2025, 2025, ANO, False, False, True)
    assert parte == 2 and secao == _SEC_EST_P2


# --------------------------------------------------------------------------
# Deteccao de pendencia municipal
# --------------------------------------------------------------------------
def test_pend_municipal_detecta_licitacao_e_clausula():
    assert _pend_municipal("Aguardando processo licitatório")
    assert _pend_municipal(None, "cláusula suspensiva pendente")
    assert _pend_municipal("aguardando inserir medição")
    assert not _pend_municipal("Em execução")
    assert not _pend_municipal("", None)


# --------------------------------------------------------------------------
# INVARIANTE DE NAO-REGRESSAO: completo=False mantem a regra anual
# --------------------------------------------------------------------------
def test_fed_retem_anual_inalterado():
    # ativa de ano anterior NAO entra no anual (regra historica)
    assert _fed_retem(2020, ANO, "Aprovada", completo=False) is False
    # empenhada entra sempre no anual
    assert _fed_retem(2015, ANO, "Em execução", completo=False) is True
    # dead so no proprio ano
    assert _fed_retem(ANO, ANO, "Rejeitada", completo=False) is True
    assert _fed_retem(2020, ANO, "Rejeitada", completo=False) is False


def test_fed_retem_completo_paga_historica_fica_ativa_antiga_sai():
    # completo: pago/empenhado de QUALQUER ano permanece (histórico da Parte 3)
    assert _fed_retem(2010, ANO, "Em execução", completo=True) is True
    assert _fed_retem(2012, ANO, "Prestação de contas", completo=True) is True
    # ativa (pré-empenho) antiga NÃO permanece — Parte 1/2 é ciclo corrente
    assert _fed_retem(2018, ANO, "Aprovada", completo=True) is False
    # pré-empenho do ano de referência entra
    assert _fed_retem(ANO, ANO, "Aprovada", completo=True) is True
    # dead nunca entra no completo
    assert _fed_retem(ANO, ANO, "Rejeitada", completo=True) is False
    assert _fed_retem(2020, ANO, "Anulada", completo=True) is False


def test_fns_retem_completo_mantem_pago_antigo_descarta_pendente_antigo():
    ind = {}
    # FNS pago antigo PERMANECE no completo (é o ganho sobre o anual)
    assert _fns_retem(2015, ANO, ind, 100.0, 0, "Pago", completo=True) is True
    # pré-empenho antigo sai; do ano corrente fica
    assert _fns_retem(2015, ANO, ind, 0, 0, "Em análise", completo=True) is False
    assert _fns_retem(ANO, ANO, ind, 0, 0, "Em análise", completo=True) is True
    # rejeitada nunca entra
    assert _fns_retem(2015, ANO, ind, 0, 0, "Rejeitada", completo=True) is False


def test_titulos_partes_usam_ano_corrente():
    tit = _titulos_partes_completo(ANO)
    assert set(tit.keys()) == {1, 2, 3, 4}
    assert str(ANO) in tit[4]  # Parte 4 cita o ano de validade
    assert tit[1].startswith("Parte 1")
    assert tit[3].startswith("Parte 3")
