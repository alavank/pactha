"""ZERO NÃO É DADO — a "Listagem de Repasses" zerada e o contexto Struts
envenenado do TransfereGov.

Dois defeitos que produziam a MESMA aparência para o gestor: voluntária que
nunca recebeu um centavo aparecia com a aba "OPs/OBs" acesa na tela e uma caixa
"Desembolsado: R$ 0,00" no relatório.
"""
import types

from ingestion.transferegov_http import _ops_obs_vazio, _sem_contexto
from services.rm_pdf import _desembolso_destaque


class _Resp:
    """O mínimo de httpx.Response que `_sem_contexto` lê."""

    def __init__(self, text):
        self.text = text


# ---------------------------------------------------------------------------
# _ops_obs_vazio — a listagem existe para TODO convênio, zerada inclusive
# ---------------------------------------------------------------------------
def test_resumo_todo_zerado_conta_como_vazio():
    # `_num_br("R$ 0,00")` devolve 0.0, e NÃO None: era assim que o zero virava
    # dado gravado.
    assert _ops_obs_vazio({"valor_total_repasse": 0.0, "valor_desembolsado": 0.0,
                           "valor_a_desembolsar": 0.0, "obs": []}) is True


def test_dicionario_vazio_e_nao_dict_contam_como_vazio():
    assert _ops_obs_vazio({}) is True
    assert _ops_obs_vazio(None) is True
    assert _ops_obs_vazio([]) is True


def test_qualquer_valor_diferente_de_zero_e_DADO():
    assert _ops_obs_vazio({"valor_total_repasse": 368000.0}) is False
    assert _ops_obs_vazio({"valor_desembolsado": 0.01}) is False
    # A desembolsar > 0 é repasse previsto e não pago: informação de verdade.
    assert _ops_obs_vazio({"valor_a_desembolsar": 100.0}) is False


def test_ordem_bancaria_manda_mesmo_com_os_valores_zerados():
    assert _ops_obs_vazio({"valor_total_repasse": 0.0,
                           "obs": [{"numero_ob": "2026OB800123"}]}) is False


def test_data_de_desembolso_tambem_e_dado():
    assert _ops_obs_vazio({"data_ultimo_desembolso": "10/03/2026"}) is False


# ---------------------------------------------------------------------------
# _desembolso_destaque — o zero JÁ GRAVADO não pode voltar a imprimir
# ---------------------------------------------------------------------------
def test_a_caixa_de_desembolso_nao_abre_com_tudo_zerado():
    # Corrige também os registros zerados que já estão no banco, sem depender de
    # limpeza. `is None` não bastava: 0.0 passava pela guarda antiga.
    assert _desembolso_destaque({"valor_desembolsado": 0.0,
                                 "valor_a_desembolsar": 0.0,
                                 "desembolsos": []}) is None
    assert _desembolso_destaque({}) is None


def test_a_caixa_abre_quando_ha_valor_ou_lancamento():
    assert _desembolso_destaque({"valor_desembolsado": 280000.0}) is not None
    assert _desembolso_destaque({"valor_a_desembolsar": 88000.0}) is not None
    assert _desembolso_destaque({
        "valor_desembolsado": 0.0,
        "desembolsos": [{"data": "10/03/2026", "valor": 1000.0,
                         "numero_ob": "2026OB800123"}]}) is not None


# ---------------------------------------------------------------------------
# _sem_contexto — o 200 que é veneno
# ---------------------------------------------------------------------------
def test_o_Principal_do_com_Proposta_nao_encontrada_e_recusado():
    # Os endpoints guest leem o convênio do CONTEXTO server-side: marcar o
    # contexto aqui faria a chamada seguinte devolver o instrumento ANTERIOR do
    # lote, com HTTP 200 e sem exceção nenhuma.
    # As TRÊS grafias em que a frase chega, conforme o que sobrou do acento:
    # apagado, U+FFFD, e UTF-8 lido como latin-1.
    for txt in ("<span>Proposta não encontrada</span>",
                "<span>Proposta nao encontrada</span>",
                "<span>Proposta n�o encontrada</span>",
                "<span>Proposta nÃ£o encontrada</span>",
                "<div>PROPOSTA NÃO ENCONTRADA</div>"):
        assert _sem_contexto(_Resp(txt)) is True


def test_a_pagina_de_detalhe_de_verdade_passa():
    assert _sem_contexto(_Resp(
        "<td>Número da Proposta</td><td>048291/2025</td>")) is False


def test_a_frase_generica_Um_erro_ocorreu_NAO_derruba_o_enrich():
    # ⚠️ De propósito fora do regex. Se ela existir no template Struts do
    # detalhe, `detalhe()` devolveria None para TODA proposta e o enrich HTTP
    # inteiro desabaria para o Chromium (~3s/proposta em vez de ~0,7s) num host
    # de 2 vCPU — calado.
    assert _sem_contexto(_Resp("<div>Um erro ocorreu</div>")) is False


# ---------------------------------------------------------------------------
# ⚠️⚠️ O MURO SAML — achado na coleta real do Freitas (24/08/2026)
# ---------------------------------------------------------------------------
def test_o_muro_SAML_conta_como_SEM_CONTEXTO():
    """Com a sessão do SP `voluntarias` fria, o GET do detalhe devolve HTTP 200
    com ~3469 bytes de formulário SAML: não redireciona (então `_sessao_caiu`,
    que só olha a URL, não vê) e não traz a frase de erro do Struts.

    Sem esta detecção, `_seta_contexto` marcava o contexto Struts como VÁLIDO
    para essa página — e a proposta seguinte lia as OPs/OBs do instrumento
    anterior."""
    for txt in ('<form action="https://idp/sso"><input name="SAMLRequest" value="x"/></form>',
                "<p>HTTP Post Binding</p>",
                '<input name="SAMLResponse" value="y"/>'):
        assert _sem_contexto(_Resp(txt)) is True


def test_a_pagina_de_detalhe_de_verdade_continua_passando():
    # A guarda não pode ficar larga a ponto de derrubar o enrich HTTP inteiro
    # para o Chromium — ~3s/proposta em vez de ~0,7s, num host de 2 vCPU.
    assert _sem_contexto(_Resp(
        "<td>Número da Proposta</td><td>048291/2025</td>"
        "<td>Código do Instrumento</td><td>981397</td>")) is False


def test_dicionario_vazio_e_FALHA_e_nao_detalhe():
    """⚠️ O DEFEITO QUE ISTO FECHA, medido em produção: 113 de 113 propostas do
    lote do Freitas ficaram sem enriquecer.

    O chamador decide o fallback com `_via_http = det is not None`, e `{}` PASSA
    nesse teste. Com o detalhe vazio, somem de uma vez `codigo_instrumento`,
    `modalidade`, `numero_processo`, `objeto`, o portão das NEs e o de
    ops_obs/obras — e como o `_upsert` usa COALESCE, nada é sobrescrito: sem
    exceção, sem log, sem sintoma. O único rastro era a proposta parar de
    enriquecer."""
    assert ({} is not None) is True          # a armadilha, explicitada
    # `None` é o que faz o browser assumir; `{}` é o que o desligava.
    assert (None is not None) is False
