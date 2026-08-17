"""Regras do RM COMPLETO (todos os anos) — services/rm_builder.

Testa as FUNCOES PURAS de classificacao por estagio (o coracao do completo) sem
tocar no banco, e prova o INVARIANTE de nao-regressao: com completo=False as
funcoes de retencao continuam identicas ao comportamento anual.
"""
from datetime import date

from services.rm_builder import (
    _destino_completo, _pend_municipal, _fed_retem, _fns_retem, _fed_status,
    _titulos_partes_completo, _situacao_estadual, _alteracao_campos, _ano_pagamento_ops_obs,
    _SEC_FED_PLURAL, _SEC_FED_SINGULAR, _SEC_EST_P2, _SEC_EST_P3_RES, _SEC_EST_P3_CONV,
)
from services.rm_export import _e_pendencia
from services.rm_pdf import _processo_execucao_destaque, _alteracao_destaque

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


# --------------------------------------------------------------------------
# SITUACAO do instrumento ESTADUAL (SIGCON) — o campo `situacao` sozinho e
# generico ("Em vigor"); a situacao REAL vem da ultima alteracao.
# --------------------------------------------------------------------------
def test_situacao_estadual_enriquece_com_a_alteracao():
    assert _situacao_estadual("Em vigor", {
        "ultima_alteracao_situacao": "ANÁLISE - CHECKLIST DE TERMO ADITIVO",
        "ultima_alteracao_tipo": "TERMO ADITIVO",
        "ultima_alteracao_data": "17/03/2026",
    }) == "Em vigor · Última alteração: ANÁLISE - CHECKLIST DE TERMO ADITIVO (TERMO ADITIVO em 17/03/2026)"


def test_situacao_estadual_nao_duplica_quando_dizem_o_mesmo():
    # base "Encerrado" x alteracao "ENCERRADO" -> nao repete
    assert _situacao_estadual("Encerrado", {"ultima_alteracao_situacao": "ENCERRADO"}) == "ENCERRADO"


def test_situacao_estadual_degrada_sem_alteracao():
    # a MAIORIA dos convenios ainda nao foi revisitada pelo rodizio do scraper
    assert _situacao_estadual("Em vigor", {}) == "Em vigor"
    assert _situacao_estadual("Cancelado", None or {}) == "Cancelado"


def test_alteracao_campos_aceita_captura_parcial():
    # sem `situacao` mas com tipo/data: nao pode jogar fora o que foi capturado
    campos = _alteracao_campos({"ultima_alteracao_tipo": "TERMO ADITIVO",
                                "ultima_alteracao_data": "17/03/2026"})
    assert campos.get("alteracao_tipo") == "TERMO ADITIVO"
    assert campos.get("alteracao_data") == "17/03/2026"
    assert _alteracao_campos({}) == {}


# --------------------------------------------------------------------------
# REGRESSAO: o Resumido classifica pela situacao CRUA, nunca pela narrativa.
# Um convenio ATIVO cuja ULTIMA ALTERACAO foi encerrada/concluida tem de
# CONTINUAR aparecendo como pendencia — senao ele some calado do relatorio.
# --------------------------------------------------------------------------
def test_resumido_nao_esconde_convenio_ativo_com_alteracao_encerrada():
    raw = {"ultima_alteracao_situacao": "ENCERRADO", "ultima_alteracao_tipo": "TERMO ADITIVO",
           "ultima_alteracao_data": "30/11/2022"}
    item = {
        "situacao_atual": _situacao_estadual("Em vigor", raw),   # narrativa (exibicao)
        "situacao_base": "Em vigor",                              # crua (classificacao)
        **_alteracao_campos(raw),
    }
    assert "ENCERRADO" in item["situacao_atual"]          # a narrativa CONTEM a palavra
    assert _e_pendencia("Parte 2 - Demandas do Município", item) is True


def test_resumido_ainda_exclui_convenio_realmente_encerrado():
    item = {"situacao_atual": "Encerrado", "situacao_base": "Encerrado"}
    assert _e_pendencia("Parte 2 - Demandas do Município", item) is False


# --------------------------------------------------------------------------
# LICITACAO (ex-"Processo de Execucao") — rotulo, detalhe por licitacao e o
# alerta de contratacao Normal SEM licitacao.
# --------------------------------------------------------------------------
def test_licitacao_alerta_quando_zero_em_contratacao_normal():
    txt = _processo_execucao_destaque({"processo_execucao_qtd": 0, "situacao_contratacao": "Normal"})
    assert txt is not None
    assert "Licitação" in txt and "nenhum registro" in txt
    assert "Processo de Execução" not in txt   # rotulo antigo nao volta


def test_licitacao_lista_cada_registro():
    txt = _processo_execucao_destaque({
        "processo_execucao_qtd": 2, "situacao_contratacao": "Normal",
        "processo_execucao_lista": [
            {"situacao": "Concluído", "modalidade": "Licitação - Pregão", "numero": "102026",
             "data_publicacao": "19/06/2026", "aceite": "Aceito"},
            {"situacao": "Em elaboração", "modalidade": "Licitação - Concorrência", "numero": "042026"},
        ],
    })
    assert "2 registro(s)" in txt
    assert "Concluído" in txt and "Pregão" in txt and "102026" in txt and "Aceito" in txt
    assert "Em elaboração" in txt


def test_licitacao_tolera_lista_ausente_str_e_lixo():
    base = {"processo_execucao_qtd": 1, "situacao_contratacao": "Normal"}
    # sem lista -> so a contagem (degrada suave)
    assert "1 registro(s)" in _processo_execucao_destaque(base)
    # JSONB que chegou como string
    assert "Concluído" in _processo_execucao_destaque(
        {**base, "processo_execucao_lista": '[{"situacao": "Concluído"}]'})
    # lixo nao derruba
    for lixo in (None, [], "nao-json", [None, 42, "x"], {"a": 1}):
        assert _processo_execucao_destaque({**base, "processo_execucao_lista": lixo}) is not None


def test_licitacao_nao_aparece_fora_de_contratacao_normal():
    assert _processo_execucao_destaque({"processo_execucao_qtd": 3, "situacao_contratacao": "Cláusula Suspensiva"}) is None
    assert _processo_execucao_destaque({"processo_execucao_qtd": None, "situacao_contratacao": "Normal"}) is None


# --------------------------------------------------------------------------
# ANO DO PAGAMENTO da voluntaria (OPs/OBs) — alimenta "REPASSES DE {ano}".
# Sem ele o ano_pgto era sempre None e TODA voluntaria paga descia p/ a Parte 3,
# inclusive a paga NESTE ano.
# --------------------------------------------------------------------------
def test_ano_pagamento_ops_obs():
    assert _ano_pagamento_ops_obs({"data_ultimo_desembolso": "24/07/2026", "obs": []}) == 2026
    # sem a data do ultimo desembolso, usa a MAIOR data de emissao de OB
    assert _ano_pagamento_ops_obs({"obs": [{"data_emissao_ob": "10/01/2024"},
                                           {"data_emissao_ob": "24/07/2026"}]}) == 2026
    # tolera vazio/lixo/str
    for lixo in ({}, None, "x", [], {"obs": [None, 42]}):
        assert _ano_pagamento_ops_obs(lixo) is None


def test_voluntaria_paga_no_ano_vai_para_repasses_do_ano():
    ano_pgto = _ano_pagamento_ops_obs({"data_ultimo_desembolso": f"24/07/{ANO}", "obs": []})
    parte, secao, suf = _destino_completo("federal", "voluntaria", "paga", ANO - 1,
                                          ano_pgto, ANO, False, False, True)
    assert parte == 2 and secao == f"REPASSES DE {ANO}:" and suf == f" - Pagos {ANO}"
    # paga em ano anterior continua na Parte 3
    parte2, secao2, _ = _destino_completo("federal", "voluntaria", "paga", 2021,
                                          _ano_pagamento_ops_obs({"data_ultimo_desembolso": "10/03/2022"}),
                                          ANO, False, False, True)
    assert parte2 == 3 and secao2 == _SEC_FED_SINGULAR
