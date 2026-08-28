"""Portal da Transparência de MG -> "Pendente de desembolso" no RM.

Pedido do dono (26/08/2026): "pegue tb a informação do pagamento data e situação
da ordem de pagamento, aquele que não tiver empenho, exibir no relatório como
'pendente de desembolso', entrando no mesmo status como o transferegov".

⚠️ LEITURA ADOTADA, porque a frase admite duas: o marcador sai quando HÁ EMPENHO
no portal e NENHUM pagamento saiu dele. É a única leitura em que "pendente de
DESEMBOLSO" quer dizer alguma coisa — sem empenho o que falta é o EMPENHO, e o
relatório já tem marcador próprio para isso. E é a mesma regra da voluntária: o
processo chegou no ponto em que o dinheiro deveria sair, e não saiu.
"""
from services.rm_builder import (
    _chave_data_br, _desembolso_ops_obs, _mg_pagamentos, _situacao_com_marcas,
)

# Como `transparencia_mg.montar_pagamentos` grava (formato ops_obs de propósito).
PAGO = {
    "valor_desembolsado": 450000.0,
    "data_ultimo_desembolso": "23/06/2026",
    "obs": [{"data_emissao_ob": "23/06/2026", "valor": 450000.0,
             "numero_ob": "1120", "situacao": "Acatada pelo banco"}],
}
SEM_PAGAMENTO = {"valor_desembolsado": 0.0, "data_ultimo_desembolso": None, "obs": []}


# ---------------------------------------------------------------- o NULO -----
def test_empenho_AINDA_NAO_CONSULTADO_nao_afirma_nada():
    """⚠️ O teste que protege o dado de virar afirmação. `pagamentos` NULO
    significa NÃO CONSULTADO — nunca "não houve pagamento". Sem esta distinção
    todo convênio cuja fila de detalhe ainda não rodou sairia no relatório como
    "Pendente de desembolso": uma afirmação sobre dinheiro público feita a partir
    de uma fila de coleta."""
    assert _mg_pagamentos([(None, False)]) == {}


def test_convenio_sem_empenho_nenhum_no_portal_tambem_cala():
    """Lista vazia = o rodízio ainda não passou neste município, ou o Estado não
    empenhou. As duas coisas são indistinguíveis daqui — e nenhuma delas é
    "pendente de desembolso"."""
    assert _mg_pagamentos([]) == {}
    assert _mg_pagamentos(None) == {}


def test_detalhe_lido_e_SEM_bloco_de_pagamento_ja_e_medicao():
    """`detalhe_lido_em` preenchido e `pagamentos` nulo: o coletor ABRIU o empenho
    e não achou ordem de pagamento. Isso é medição, e vira o marcador."""
    d = _mg_pagamentos([(None, True)])
    assert d["_consultado"] is True and d["valor_desembolsado"] == 0.0


# ------------------------------------------------------- a fusão de empenhos --
def test_soma_os_pagamentos_dos_VARIOS_empenhos_do_convenio():
    """Um convênio de MG costuma ter mais de um empenho (um por exercício), cada
    um com suas próprias ordens de pagamento."""
    outro = {"valor_desembolsado": 50000.0, "data_ultimo_desembolso": "10/01/2026",
             "obs": [{"data_emissao_ob": "10/01/2026", "valor": 50000.0,
                      "numero_ob": "77", "situacao": "Acatada pelo banco"}]}
    d = _mg_pagamentos([(PAGO, True), (outro, True)])
    assert d["valor_desembolsado"] == 500000.0
    assert len(d["obs"]) == 2


def test_a_data_mais_recente_vence_e_NAO_por_ordem_alfabetica():
    """⚠️ Datas em dd/mm/aaaa comparadas como texto dão "08/08" > "25/03" — o
    relatório mostraria como último desembolso um pagamento de março quando
    houve um em agosto."""
    a = {"valor_desembolsado": 1.0, "data_ultimo_desembolso": "25/03/2026", "obs": []}
    b = {"valor_desembolsado": 1.0, "data_ultimo_desembolso": "08/08/2026", "obs": []}
    assert _mg_pagamentos([(a, True), (b, True)])["data_ultimo_desembolso"] == "08/08/2026"
    assert _mg_pagamentos([(b, True), (a, True)])["data_ultimo_desembolso"] == "08/08/2026"


def test_chave_de_ordem_da_data():
    assert _chave_data_br("25/03/2026") == "20260325"
    assert _chave_data_br("08/08/2026") > _chave_data_br("25/03/2026")
    # o que nao casa perde de qualquer data real
    assert _chave_data_br(None) < _chave_data_br("01/01/1900")


def test_empenho_misturado_consultado_e_nao_consultado():
    """Um empenho já lido e outro na fila: o que foi medido vale, e o convênio
    entra como consultado. Não esperar a fila inteira é o que faz o dado aparecer
    no relatório da rodada seguinte, e não daqui a um mês."""
    d = _mg_pagamentos([(PAGO, True), (None, False)])
    assert d["_consultado"] is True and d["valor_desembolsado"] == 450000.0


# ------------------------------------------------ o MESMO texto do TransfereGov
def test_com_empenho_e_sem_pagamento_sai_PENDENTE_DE_DESEMBOLSO():
    d = _mg_pagamentos([(SEM_PAGAMENTO, True)])
    sit = _situacao_com_marcas("Em vigor", False, bool(d.get("_consultado")),
                               d.get("valor_desembolsado"))
    assert sit == "Em vigor · Pendente de desembolso"


def test_com_pagamento_sai_o_VALOR_e_nao_o_marcador():
    d = _mg_pagamentos([(PAGO, True)])
    sit = _situacao_com_marcas("Em vigor", False, True, d.get("valor_desembolsado"))
    assert "Pendente de desembolso" not in sit
    assert "Desembolsado" in sit


def test_nao_consultado_deixa_a_situacao_INTACTA():
    """A não-regressão do estadual: sem medição, a `situacao_atual` sai caractere
    a caractere como saía antes deste trabalho."""
    d = _mg_pagamentos([(None, False)])
    assert _situacao_com_marcas("Em vigor · Última alteração: VIGENTE", False,
                                bool(d.get("_consultado")),
                                d.get("valor_desembolsado")) == \
        "Em vigor · Última alteração: VIGENTE"


def test_e_LITERALMENTE_a_mesma_funcao_da_voluntaria():
    """⚠️ O pedido dizia "entrando no mesmo status como o transferegov". Compor o
    texto num segundo lugar seria a segunda cópia da mesma regra — que neste repo
    é o jeito conhecido de as duas divergirem. Estadual e voluntária, mesma
    entrada, mesma saída."""
    voluntaria = _situacao_com_marcas("Em execução", False, True, 0)
    estadual = _situacao_com_marcas("Em execução", False, True, 0)
    assert voluntaria == estadual == "Em execução · Pendente de desembolso"


# ------------------------------------------- a caixa do relatório (data/OB) ---
def test_a_caixa_recebe_data_numero_e_SITUACAO_da_ordem_de_pagamento():
    """A parte "data e situação da ordem de pagamento" do pedido. O formato é o
    `ops_obs` de propósito: `_desembolso_ops_obs` já sabe lê-lo, sem um segundo
    parser."""
    campos = _desembolso_ops_obs(_mg_pagamentos([(PAGO, True)]))
    assert campos["valor_desembolsado"] == 450000.0
    assert campos["dt_ultimo_desembolso"] == "23/06/2026"
    assert campos["desembolsos"] == [{
        "data": "23/06/2026", "valor": 450000.0,
        "numero_ob": "1120", "situacao": "Acatada pelo banco"}]


def test_sem_consulta_nao_ha_campos_de_desembolso_no_item():
    """`{}` e não zeros: um `valor_desembolsado: 0` no item faria a caixa do PDF
    desenhar "R$ 0,00 desembolsado" num convênio que ninguém consultou."""
    assert _mg_pagamentos([(None, False)]) == {}
