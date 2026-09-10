"""FNS: nas propostas PAGAS, a DATA do pagamento e o NUMERO DA CONTA saem no RM.

Pedido do dono (09/09/2026), com o print da proposta 63000724643202600 (Araujos,
Custeio PAP, R$ 200.000, "Proposta Paga"): nas propostas ja pagas da Saude (FNS),
"precisamos da data que foi pago e o numero da conta".

De onde vem cada dado (medido na API publica do ConsultaFNS):
- O `obter-proposta` traz os pagamentos com a data (dtCriacaoSiafi) e a Ordem
  Bancaria (nuOb), mas NAO o numero da conta.
- A conta (contaCorrente) + banco/agencia so aparecem no `detalhe-pagamento` da
  Consulta Detalhada (/#/detalhada), chaveado por (ano do PAGAMENTO, UF, IBGE6,
  proposta). Para a proposta do print: data 08/04/2026, banco 001, agencia
  038296, conta 0000139750.

O coletor (ingestion/run_fns_local.py) passa a gravar `data_pagamento`,
`conta_corrente`, `codigo_banco`, `codigo_agencia` e a lista `pagamentos` em cada
`raw_data['linhaPropostas'][]`; o RM (services/rm_builder.py) le esses campos e o
render (rm_pdf/rm_export) mostra "Conta" (ja existia, so vinha vazio no FNS) e o
campo NOVO "Data do pagamento". Ver [[fns-emenda-saude-tres-telas]].
"""
import os
import re

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLETOR = os.path.join(RAIZ, "ingestion", "run_fns_local.py")
BUILDER = os.path.join(RAIZ, "services", "rm_builder.py")
RM_PDF = os.path.join(RAIZ, "services", "rm_pdf.py")
RM_EXPORT = os.path.join(RAIZ, "services", "rm_export.py")


def _fonte(caminho: str) -> str:
    return open(caminho, encoding="utf-8").read()


# --- _iso_de_br: a data BR do FNS vira ISO, o formato que o RM usa -----------

def test_iso_de_br_converte_e_tolera():
    from services.rm_builder import _iso_de_br
    assert _iso_de_br("08/04/2026") == "2026-04-08"
    assert _iso_de_br("2026-04-08") == "2026-04-08"   # ja ISO: passa direto
    assert _iso_de_br("") is None
    assert _iso_de_br(None) is None


# --- helpers do coletor ------------------------------------------------------

def test_ordena_pagamentos_por_data_e_pega_o_ultimo():
    from ingestion.run_fns_local import _ord_data_br
    datas = ["23/10/2019", "08/04/2026", "01/01/2026"]
    assert sorted(datas, key=_ord_data_br)[-1] == "08/04/2026"
    assert _ord_data_br(None) == (0, 0, 0)     # ausencia = mais antigo, nunca o "ultimo"
    assert _ord_data_br("lixo") == (0, 0, 0)


def test_data_br_ms_formata_o_epoch_do_obter_proposta():
    from ingestion.run_fns_local import _data_br_ms
    # 1775617200000 ms = 08/04/2026 (a data da proposta do print)
    assert _data_br_ms(1775617200000) == "08/04/2026"
    assert _data_br_ms(None) is None
    assert _data_br_ms("nan") is None


def test_detalhe_pagamento_manda_os_params_que_o_portal_exige():
    """O endpoint responde 400 se faltar qualquer um destes (mesmo vazio) — foi
    o motivo do 400 na primeira sondagem. Guarda contra alguem "enxugar" o dict."""
    from ingestion.run_fns_local import _DETALHE_PGTO_VAZIOS
    for k in ("mes", "tipoConsulta", "blocos", "grupo", "componentes", "acoes",
              "repasse", "dataInicialOb", "dataFinalOb", "nuAcaoJudicial",
              "cpfCnpjUg", "processo", "portaria"):
        assert k in _DETALHE_PGTO_VAZIOS


# --- o RENDER: os dois dados aparecem na PAGA e somem na nao-paga ------------

def _item(**over):
    base = {"tipo": "Proposta", "objeto": "Custeio pap", "valor_global": 200000,
            "valor_repasse": 200000, "valor_contrapartida": 0,
            "banco": "001", "agencia": "038296", "conta": "0000139750",
            "dt_pagamento": "2026-04-08", "situacao_atual": "Proposta Paga"}
    base.update(over)
    return base


def test_completo_mostra_conta_e_data_do_pagamento_na_paga():
    from services.rm_pdf import _campos_do_item
    d = dict(_campos_do_item(_item()))
    assert d.get("Conta") == "0000139750"
    assert d.get("Data do pagamento") == "08/04/2026"   # ISO -> dd/mm/aaaa


def test_resumido_mostra_conta_e_data_do_pagamento_na_paga():
    from services.rm_export import _campos_resumido
    d = dict(_campos_resumido(_item()))
    assert d.get("Conta") == "0000139750"
    assert d.get("Data do pagamento") == "08/04/2026"


def test_proposta_nao_paga_nao_inventa_linha_vazia():
    """Sem pagamento: nem "Conta" nem "Data do pagamento" na tela — ausencia e
    ausencia, nao um campo em branco. Mesma disciplina de medido x ausente."""
    from services.rm_pdf import _campos_do_item
    from services.rm_export import _campos_resumido
    vazio = _item(conta="", banco="", agencia="", dt_pagamento=None,
                  valor_repasse=0, situacao_atual="Em análise")
    for render in (_campos_do_item, _campos_resumido):
        rotulos = [l for l, _ in render(vazio)]
        assert "Conta" not in rotulos
        assert "Data do pagamento" not in rotulos


# --- guarda de fiacao: coletor grava, builder le -----------------------------

def test_o_coletor_grava_conta_e_data_em_cada_proposta():
    src = _fonte(COLETOR)
    for campo in ('"data_pagamento"', '"conta_corrente"',
                  '"codigo_banco"', '"codigo_agencia"', '"pagamentos"'):
        assert campo in src, f"coletor deixou de gravar {campo}"
    # a chamada ao endpoint da conta tem de existir
    assert "detalhe-pagamento" in src


def test_o_builder_passa_conta_e_data_do_FNS_para_o_item():
    """A proposta paga do FNS enche banco/agencia/conta (antes cravados "") e o
    campo novo dt_pagamento a partir do que o coletor gravou em linhaPropostas."""
    src = _fonte(BUILDER)
    assert 'ind.get("conta_corrente")' in src
    assert 'ind.get("codigo_banco")' in src
    assert 'ind.get("codigo_agencia")' in src
    assert '_iso_de_br(ind.get("data_pagamento"))' in src


def test_os_dois_renders_tem_a_linha_data_do_pagamento():
    """Completo (rm_pdf) e Resumido (rm_export): o campo novo precisa estar nos
    DOIS, senao um relatorio mostra e o outro nao."""
    assert 'Data do pagamento' in _fonte(RM_PDF)
    assert 'Data do pagamento' in _fonte(RM_EXPORT)
