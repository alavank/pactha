"""Regras do RM COMPLETO (todos os anos) — services/rm_builder.

Testa as FUNCOES PURAS de classificacao por estagio (o coracao do completo) sem
tocar no banco, e prova o INVARIANTE de nao-regressao: com completo=False as
funcoes de retencao continuam identicas ao comportamento anual.
"""
from datetime import date

from services.rm_builder import (
    _destino_completo, _pend_municipal, _fed_retem, _fns_retem, _fed_status,
    _titulos_partes_completo, _situacao_estadual, _alteracao_campos, _ano_pagamento_ops_obs,
    _programa_limpo, _vol_pre_empenho,
    _SEC_FED_PLURAL, _SEC_FED_SINGULAR, _SEC_EST_P2, _SEC_EST_P3_RES, _SEC_EST_P3_CONV,
)
from services.rm_export import _e_pendencia
from services.rm_pdf import _processo_execucao_destaque, _alteracao_destaque, _campos_do_item

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


# --------------------------------------------------------------------------
# PARTE 4 = repasse 100% VOLUNTARIO. Proposta com nome de parlamentar e EMENDA
# (caso Junior Amaral / Min. do Esporte) e sobe para a secao superior.
# --------------------------------------------------------------------------
def test_parte4_so_aceita_voluntaria_sem_parlamentar():
    # sem parlamentar: continua sendo Parte 4 (nao esvaziar o que e voluntario)
    assert _vol_pre_empenho("ativa", ANO, ANO, "") is True
    assert _vol_pre_empenho("ativa", ANO, ANO, None) is True
    # marcador de ausencia do portal NAO e parlamentar -> segue voluntaria
    assert _vol_pre_empenho("ativa", ANO, ANO, "Nao ha") is True
    assert _vol_pre_empenho("ativa", ANO, ANO, "Nao informado") is True
    # COM parlamentar -> nao e voluntaria pura, sai da Parte 4
    assert _vol_pre_empenho("ativa", ANO, ANO, "JUNIOR AMARAL") is False


def test_parte4_expulsa_emenda_para_brasilia_ou_municipio():
    # sem pendencia municipal a bola e de Brasilia -> Parte 1
    parte, secao, _ = _destino_completo(
        "federal", "voluntaria", "ativa", ANO, None, ANO,
        pend_municipal=False, pre_empenho_novo=False, tem_convenio=False)
    assert parte == 1 and secao == _SEC_FED_PLURAL
    # com licitacao/clausula a bola e do municipio -> Parte 2
    parte2, _s2, _ = _destino_completo(
        "federal", "voluntaria", "ativa", ANO, None, ANO,
        pend_municipal=True, pre_empenho_novo=False, tem_convenio=False)
    assert parte2 == 2


def test_parte4_nunca_recebeu_empenhada_nem_ano_anterior():
    # invariante que a regra do parlamentar NAO pode mascarar: a Parte 4 sempre foi
    # so pre-empenho do ano corrente, entao condicionar a regra a empenho seria no-op.
    assert _vol_pre_empenho("empenhada", ANO, ANO, "") is False
    assert _vol_pre_empenho("paga", ANO, ANO, "") is False
    assert _vol_pre_empenho("ativa", ANO - 1, ANO, "") is False


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


def test_fns_retem_completo_exige_repasse_efetivo_em_ano_anterior():
    """Pedido do dono: FNS de 2025 e anos anteriores que NAO foram empenhadas sai
    do relatorio. O rotulo textual "Empenhado" do portal nao vale como empenho —
    havia proposta de 2014/2017 marcada assim com repasse R$ 0."""
    assert _fns_retem(2024, ANO, {}, 0, 0, "Empenhado", completo=True) is False
    assert _fns_retem(2025, ANO, {}, 0, 0, "Empenhado", completo=True) is False
    # empenhada COM saldo a receber continua (o que a docstring promete manter)
    assert _fns_retem(2024, ANO, {}, 50.0, 50.0, "Empenhado", completo=True) is True
    # paga de ano anterior continua (e o historico que alimenta a Parte 3)
    assert _fns_retem(2015, ANO, {"ano_ultimo_pagamento": ANO}, 100.0, 0, "Pago",
                      completo=True) is True
    # o ano de REFERENCIA nao e afetado, mesmo sem dinheiro
    assert _fns_retem(ANO, ANO, {}, 0, 0, "Empenhado", completo=True) is True
    # invariante: o ramo ANUAL (completo=False) nao foi tocado
    assert _fns_retem(2024, ANO, {}, 0, 0, "Empenhado", completo=False) is False


def test_fns_com_selecao_de_anos_cada_ano_vale_por_si():
    """Regra do dono (19/08/2026): o corte "sem empenho sai" e do relatorio de
    TODOS OS ANOS. Havendo SELECAO, quem escolheu [2023, 2024, 2025] pediu aqueles
    anos de proposito — comparar tudo contra o MAIOR ano da selecao derrubaria
    2023 e 2024, o oposto do pedido."""
    sel = {2023, 2024, 2025}
    # sem dinheiro, mas DENTRO da selecao -> permanece
    assert _fns_retem(2023, 2025, {}, 0, 0, "Empenhado", completo=True, anos_sel=sel) is True
    assert _fns_retem(2024, 2025, {}, 0, 0, "Em análise", completo=True, anos_sel=sel) is True
    # FORA da selecao -> sai (o filtro de escopo tambem o removeria depois)
    assert _fns_retem(2019, 2025, {}, 0, 0, "Empenhado", completo=True, anos_sel=sel) is False
    # sem selecao (todos os anos), volta a valer o corte por repasse efetivo
    assert _fns_retem(2023, ANO, {}, 0, 0, "Empenhado", completo=True) is False
    # e a selecao NAO ressuscita rejeitada
    assert _fns_retem(2023, 2025, {}, 0, 0, "Rejeitada", completo=True, anos_sel=sel) is False


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


def test_situacao_estadual_qt_zero_diz_sem_alteracoes():
    # qt_alteracoes == 0: o SIGCON nao registra alteracao -> e DEFINITIVO. Sem
    # esta marca, "Em vigor" sozinho confunde o leitor ("cade o detalhe?").
    assert (_situacao_estadual("Em vigor", {}, 0)
            == "Em vigor · sem alterações registradas no SIGCON")


def test_situacao_estadual_qt_positivo_declara_so_o_contador():
    # O contador (listagem/CKAN) afirma alteracao, mas o detalhe autenticado pode
    # abrir VAZIO (medido: Desterro, 1 de 9 qt>0 sem linha de alteracao). Entao
    # NAO prometemos "em coleta" — declaramos so o contador, que e sempre verdade.
    assert (_situacao_estadual("Em vigor", {}, 2)
            == "Em vigor · 2 alterações registradas no SIGCON")
    assert (_situacao_estadual("Em vigor", {}, 1)
            == "Em vigor · 1 alteração registrada no SIGCON")


def test_situacao_estadual_detalhe_capturado_ignora_qt():
    # quando o detalhe JA foi capturado, ele manda — qt_alteracoes nao interfere.
    assert _situacao_estadual("Em vigor", {
        "ultima_alteracao_situacao": "CADASTRAMENTO DA ALTERAÇÃO",
        "ultima_alteracao_tipo": "ALTERAÇÃO SIMPLES",
        "ultima_alteracao_data": "24/06/2026",
    }, 0) == ("Em vigor · Última alteração: CADASTRAMENTO DA ALTERAÇÃO "
              "(ALTERAÇÃO SIMPLES em 24/06/2026)")


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


# --------------------------------------------------------------------------
# PROGRAMA da voluntaria (ex.: "PRONE") — pedido do dono: aparecer nos detalhes,
# junto do Objeto. A coluna ja existia e ja era populada; o RM e que nao a lia.
# --------------------------------------------------------------------------
def test_programa_preserva_sigla_e_tira_codigo_numerico():
    # a SIGLA e justamente o que o dono quer ver — nao pode ser cortada
    assert _programa_limpo("PRONE - PROGRAMA NACIONAL") == "PRONE - PROGRAMA NACIONAL"
    # codigo do programa colado no comeco (so digitos) sai
    assert _programa_limpo("0036420250001 - PRONE") == "PRONE"


def test_programa_corta_lixo_com_tab_do_portal():
    # mesmo defeito do varredor generico label|valor que ja sujou `modalidade`
    assert _programa_limpo("PRONE\tEnviada para mandataria?\tNao") == "PRONE"
    assert _programa_limpo("  APOIO   A   PROJETOS ") == "APOIO A PROJETOS"


def test_programa_tolera_vazio_e_nulo():
    for vazio in (None, "", "   ", "\t"):
        assert _programa_limpo(vazio) == ""


def test_pdf_imprime_programa_logo_abaixo_do_objeto():
    campos = _campos_do_item({"objeto": "Pavimentacao", "programa": "PRONE",
                              "parlamentar": "Fulano"})
    rotulos = [r for r, _ in campos]
    assert rotulos[:3] == ["Objeto", "Programa",
                           "Parlamentar responsável pela indicação"]


def test_pdf_nao_imprime_programa_quando_a_fonte_nao_tem():
    # estadual/SIMEC/PAC nao preenchem a chave — a linha nao pode aparecer vazia
    campos = _campos_do_item({"objeto": "Reforma"})
    assert "Programa" not in [r for r, _ in campos]


# --------------------------------------------------------------------------
# EM "TODOS OS ANOS", PRÉ-EMPENHO ANTIGA SÓ VOLTA SE FOI PARA FRENTE.
#
# ⚠️ AS LINHAS ABAIXO SÃO DE PRODUÇÃO, não inventadas para casar com o código.
# Foram lidas do banco do freitas em 30/08/2026 e conferidas contra a própria
# `_fed_retem`; é essa procedência que faz o teste valer alguma coisa. Um caso
# escrito a partir da implementação só repete a implementação de volta.
#
# O caso do dono é o instrumento 932836 (proposta 059522/2021, situação ainda
# "Proposta/Plano de Trabalho Aprovados", vigência até 31/12/2026). O #317 dizia
# que a vigência dela tinha encerrado em 16/12/2024 — não é o que o banco diz.
# --------------------------------------------------------------------------
from datetime import date as _date                                    # noqa: E402
from services.rm_builder import (_vigencia_vencida,                   # noqa: E402
                                 _vigencia_em_curso)

_APROV = "Proposta/Plano de Trabalho Aprovados"
_ANALISE = "Proposta/Plano de Trabalho enviado para Análise"
_HOJE = _date(2026, 8, 30)

# --- as linhas, como estão no banco (numero, situacao, instrumento, vigencia) --
_932836 = (2021, _APROV, "932836", _date(2026, 12, 31))       # Araújos, viva
_006961 = (2017, _ANALISE, None, _date(2017, 12, 31))         # nunca virou nada
_055157 = (2010, _APROV, "738737", _date(2010, 11, 12))       # virou, e morreu
_006244 = (2024, _ANALISE, None, _date(2027, 6, 1))           # promessa sem instrumento


def _retem(linha, ref=2026, anos_sel=None):
    """⚠️ `hoje` FIXO. A vigência da 932836 vai até 31/12/2026: preso a
    `date.today()`, este arquivo passaria agora e quebraria sozinho em janeiro —
    e o caso do dono deixaria de estar coberto justo quando ninguém olha."""
    ano, sit, instr, dt = linha
    return _fed_retem(ano, ref, sit, True, anos_sel=anos_sel,
                      dt_fim=dt, celebrado=bool(instr), hoje=_HOJE)


def test_932836_entra_no_relatorio_de_todos_os_anos():
    """O caso que o dono apontou duas vezes. Ela é de 2021 e a situação textual
    nunca saiu de "Aprovados", mas ela VIROU O INSTRUMENTO 932836 e a vigência
    corre até 31/12/2026 — foi para frente e está viva."""
    assert _retem(_932836) is True


def test_o_que_NAO_foi_para_frente_fica_de_fora():
    """A reclamação do dono em 30/08/2026: o relatório completo estava cheio de
    proposta "enviada para análise" de 2009/2015/2017, sem instrumento nenhum e
    com a janela fechada há anos. Medido em produção: eram +41 itens em Araújos
    e +111 em três municípios — o #317 as trazia todas."""
    assert _retem(_006961) is False


def test_celebrada_mas_VENCIDA_tambem_fica_de_fora():
    """Virar instrumento não basta: 738737 foi celebrado em 2010 e a vigência
    morreu em 12/11/2010. Sozinho, "foi celebrada" traria 4 dessas em Araújos e
    21 em três municípios."""
    assert _retem(_055157) is False


def test_vigencia_futura_SEM_instrumento_tambem_fica_de_fora():
    """E viva não basta: a proposta traz a vigência PRETENDIDA no plano de
    trabalho mesmo sem nunca ter sido celebrada. Sozinho, "está viva" traria
    006244/2024 e 063849/2025, que nunca viraram instrumento."""
    assert _retem(_006244) is False


def test_a_regra_do_317_nao_resgatava_a_propria_932836():
    """⚠️ O #317 dizia "pré-empenho antiga entra quando a vigência VENCEU" e foi
    escrito exatamente para resgatar a 932836. A vigência dela é 31/12/2026:
    nunca venceu. A regra errava dos dois lados — deixava de fora quem devia
    entrar e trazia para dentro quem devia ficar de fora."""
    assert _vigencia_vencida(_932836[3], hoje=_HOJE) is False
    assert _vigencia_vencida(_006961[3], hoje=_HOJE) is True


def test_selecao_de_VARIOS_anos_nao_derruba_todos_menos_o_maior():
    """⚠️ O router calcula `ano_emissao = max(anos)`. Quem marcou [2021, 2025]
    pediu os dois de propósito. É o MESMO defeito já corrigido no `_fns_retem`
    em 19/08/2026 — o conserto ficou só no FNS e o federal nunca o recebeu."""
    assert _retem(_932836, ref=2025, anos_sel={2021, 2025}) is True
    # e a seleção continua sendo respeitada: quem não foi pedido, não entra
    assert _retem(_932836, ref=2025, anos_sel={2025}) is False


def test_quem_escolhe_anos_recebe_os_anos_que_escolheu():
    """⚠️ O resgate mora DEPOIS do `anos_sel`, e não junto do `vigente` lá em
    cima. Testada nas linhas de produção, a versão "junto do vigente" enfiava
    instrumento de 2026 vivo até 2028 dentro de um relatório pedido só para
    2025 — em quatro municípios, 994997, 7AABMT, 7AABSA e 7AAFZT."""
    _994997 = (2026, "Proposta Aprovada e Plano de Trabalho Complementado",
               "994997", _date(2028, 3, 13))
    assert _retem(_994997, ref=2025, anos_sel={2025}) is False
    assert _retem(_994997, ref=2026) is True     # no completo ela entra pelo ano


def test_chamada_ANTIGA_de_4_argumentos_sai_identica():
    """Não-regressão: os parâmetros novos são opcionais e sem eles o resultado é
    caractere a caractere o de antes."""
    for ano, ref, sit in [(2021, 2026, _APROV), (2026, 2026, _APROV),
                          (2019, 2026, "Em execução"), (2021, 2026, "Rejeitada")]:
        assert _fed_retem(ano, ref, sit, True) == _fed_retem(
            ano, ref, sit, True, anos_sel=None, dt_fim=None, celebrado=False)


def test_empenhada_e_paga_seguem_entrando_em_qualquer_ano():
    assert _fed_retem(2014, 2026, "Em execução", True) is True
    assert _fed_retem(2014, 2026, "Prestação de contas", True) is True


def test_vigencia_vencida_aceita_os_formatos_que_o_banco_devolve():
    assert _vigencia_vencida(_date(2024, 12, 16), hoje=_date(2026, 8, 29)) is True
    assert _vigencia_vencida("2024-12-16", hoje=_date(2026, 8, 29)) is True
    assert _vigencia_vencida("16/12/2024", hoje=_date(2026, 8, 29)) is True
    assert _vigencia_vencida(_date(2027, 1, 1), hoje=_date(2026, 8, 29)) is False


def test_sem_data_NUNCA_conta_como_vencida():
    """⚠️ "Não sei quando vence" não pode virar "venceu": este marcador
    ACRESCENTA item ao relatório, e supor vencimento encheria o documento de
    proposta que ninguém pode afirmar estar vencida."""
    for v in (None, "", "   ", "sem data", "13/2024", 0):
        assert _vigencia_vencida(v, hoje=_date(2026, 8, 29)) is False


def test_sem_data_TAMBEM_nao_conta_como_em_curso():
    """⚠️ `_vigencia_em_curso` NÃO é `not _vigencia_vencida`. As duas devolvem
    False sem data, de propósito: as duas ACRESCENTAM item ao relatório, e o que
    não se sabe não pode virar afirmação em documento entregue ao cliente. Se
    fosse a negação, um convênio celebrado sem vigência lida entraria calado."""
    for v in (None, "", "   ", "sem data", "13/2024", 0):
        assert _vigencia_em_curso(v, hoje=_date(2026, 8, 29)) is False
        assert _vigencia_vencida(v, hoje=_date(2026, 8, 29)) is False
    # e um convênio celebrado sem vigência lida NÃO é resgatado
    assert _fed_retem(2015, 2026, _APROV, True, dt_fim=None, celebrado=True) is False


def test_vigencia_em_curso_e_a_data_de_hoje():
    assert _vigencia_em_curso("31/12/2026", hoje=_HOJE) is True
    assert _vigencia_em_curso("2026-12-31", hoje=_HOJE) is True
    assert _vigencia_em_curso(_date(2026, 8, 29), hoje=_HOJE) is False   # ontem
