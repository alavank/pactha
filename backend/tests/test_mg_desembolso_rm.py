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
from ingestion.transparencia_mg import montar_pagamentos, pagamento_confirmado
from services.rm_builder import (
    _chave_data_br, _desembolso_ops_obs, _mg_pagamentos, _situacao_com_marcas,
)

# Como `transparencia_mg.montar_pagamentos` grava (formato ops_obs de propósito).
PAGO = montar_pagamentos([{"data": "23/06/2026", "numero": "1120",
                           "situacao": "Acatada pelo banco", "valor": 450000.0}])
SEM_PAGAMENTO = montar_pagamentos([])


# ---------------------------------------------------------------- o NULO -----
def test_empenho_AINDA_NAO_CONSULTADO_nao_afirma_nada():
    """⚠️ O teste que protege o dado de virar afirmação. `pagamentos` NULO
    significa NÃO CONSULTADO — nunca "não houve pagamento". Sem esta distinção
    todo convênio cuja fila de detalhe ainda não rodou sairia no relatório como
    "Pendente de desembolso": uma afirmação sobre dinheiro público feita a partir
    de uma fila de coleta."""
    assert _mg_pagamentos([None]) == {}


def test_convenio_sem_empenho_nenhum_no_portal_tambem_cala():
    """Lista vazia = o rodízio ainda não passou neste município, ou o Estado não
    empenhou. As duas coisas são indistinguíveis daqui — e nenhuma delas é
    "pendente de desembolso"."""
    assert _mg_pagamentos([]) == {}
    assert _mg_pagamentos(None) == {}


def test_LEITURA_QUE_FALHOU_nao_pode_virar_pendencia():
    """⚠️ REGRESSÃO de um defeito GRAVE que passou por aqui abençoado por um teste
    meu — ele afirmava que `detalhe_lido_em` preenchido com `pagamentos` NULO era
    "medição". Não é: o coletor carimba aquela coluna TAMBÉM quando a aba de
    Pagamento devolveu corpo vazio (o portal faz isso com cookie velho — "não
    erro, não 403: vazio"). Uma leitura FALHA virava "Pendente de desembolso"
    permanente num convênio que podia ter recebido tudo, e o texto congela em
    `rm_relatorios.conteudo`.

    O conserto tem duas metades e esta é a de cima: a coluna nem chega mais aqui,
    só o bloco prova medição. A de baixo está no coletor —
    `test_a_fila_do_coletor_resgata_a_leitura_que_falhou`."""
    assert _mg_pagamentos([None]) == {}


# ------------------------------------------------------- a fusão de empenhos --
def test_soma_os_pagamentos_dos_VARIOS_empenhos_do_convenio():
    """Um convênio de MG costuma ter mais de um empenho (um por exercício), cada
    um com suas próprias ordens de pagamento."""
    outro = {"valor_desembolsado": 50000.0, "data_ultimo_desembolso": "10/01/2026",
             "obs": [{"data_emissao_ob": "10/01/2026", "valor": 50000.0,
                      "numero_ob": "77", "situacao": "Acatada pelo banco"}]}
    d = _mg_pagamentos([PAGO, outro])
    assert d["valor_desembolsado"] == 500000.0
    assert len(d["obs"]) == 2


def test_a_data_mais_recente_vence_e_NAO_por_ordem_alfabetica():
    """⚠️ Datas em dd/mm/aaaa comparadas como texto dão "08/08" > "25/03" — o
    relatório mostraria como último desembolso um pagamento de março quando
    houve um em agosto."""
    a = {"valor_desembolsado": 1.0, "data_ultimo_desembolso": "25/03/2026", "obs": []}
    b = {"valor_desembolsado": 1.0, "data_ultimo_desembolso": "08/08/2026", "obs": []}
    assert _mg_pagamentos([a, b])["data_ultimo_desembolso"] == "08/08/2026"
    assert _mg_pagamentos([b, a])["data_ultimo_desembolso"] == "08/08/2026"


def test_chave_de_ordem_da_data():
    assert _chave_data_br("25/03/2026") == "20260325"
    assert _chave_data_br("08/08/2026") > _chave_data_br("25/03/2026")
    # o que nao casa perde de qualquer data real
    assert _chave_data_br(None) < _chave_data_br("01/01/1900")


def test_empenho_misturado_consultado_e_nao_consultado():
    """Um empenho já lido e outro na fila: o que foi medido vale, e o convênio
    entra como consultado. Não esperar a fila inteira é o que faz o dado aparecer
    no relatório da rodada seguinte, e não daqui a um mês."""
    d = _mg_pagamentos([PAGO, None])
    assert d["_consultado"] is True and d["valor_desembolsado"] == 450000.0


# ------------------------------------------------ o MESMO texto do TransfereGov
def test_com_empenho_e_sem_pagamento_sai_PENDENTE_DE_DESEMBOLSO():
    d = _mg_pagamentos([SEM_PAGAMENTO])
    sit = _situacao_com_marcas("Em vigor", False, bool(d.get("_consultado")),
                               d.get("valor_desembolsado"))
    assert sit == "Em vigor · Pendente de desembolso"


def test_com_pagamento_sai_o_VALOR_e_nao_o_marcador():
    d = _mg_pagamentos([PAGO])
    sit = _situacao_com_marcas("Em vigor", False, True, d.get("valor_desembolsado"))
    assert "Pendente de desembolso" not in sit
    assert "Desembolsado" in sit


def test_nao_consultado_deixa_a_situacao_INTACTA():
    """A não-regressão do estadual: sem medição, a `situacao_atual` sai caractere
    a caractere como saía antes deste trabalho."""
    d = _mg_pagamentos([None])
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
    campos = _desembolso_ops_obs(_mg_pagamentos([PAGO]))
    assert campos["valor_desembolsado"] == 450000.0
    assert campos["dt_ultimo_desembolso"] == "23/06/2026"
    assert campos["desembolsos"] == [{
        "data": "23/06/2026", "valor": 450000.0,
        "numero_ob": "1120", "situacao": "Acatada pelo banco"}]


def test_sem_consulta_nao_ha_campos_de_desembolso_no_item():
    """`{}` e não zeros: um `valor_desembolsado: 0` no item faria a caixa do PDF
    desenhar "R$ 0,00 desembolsado" num convênio que ninguém consultou."""
    assert _mg_pagamentos([None]) == {}


# --------------------------------------------------------------------------
# A SITUAÇÃO DA ORDEM DE PAGAMENTO. Somar toda linha da aba fazia uma OP
# devolvida virar dinheiro recebido — e, pior, APAGAR o "Pendente de
# desembolso", tirando da lista de cobrança justamente quem não recebeu.
# --------------------------------------------------------------------------
def test_OP_devolvida_nao_e_dinheiro_recebido():
    """⚠️ O defeito: `_situacao_com_marcas` usa `vd > 0` para SUPRIMIR a
    pendência. Com a devolvida somada, o convênio saía "Desembolsado:
    R$ 938.793,55" com o dinheiro ainda no caixa do Estado — e sumia da lista do
    que falta cobrar, que é literalmente o que o dono pediu para ver."""
    d = montar_pagamentos([{"data": "25/03/2026", "numero": "1939",
                            "situacao": "Devolvida pelo banco", "valor": 938793.55}])
    assert d["valor_desembolsado"] == 0.0
    assert d["valor_nao_confirmado"] == 938793.55
    sit = _situacao_com_marcas("Em vigor", False, True, d["valor_desembolsado"])
    assert sit == "Em vigor · Pendente de desembolso"


def test_a_OP_devolvida_CONTINUA_visivel_na_caixa():
    """Não conta como dinheiro, mas não desaparece: a linha e a situação literal
    seguem em `obs`, porque quem lê o relatório precisa saber que houve uma
    tentativa devolvida — isso é cobrança diferente de "nunca saiu nada"."""
    d = montar_pagamentos([{"data": "25/03/2026", "numero": "1939",
                            "situacao": "Devolvida pelo banco", "valor": 938793.55}])
    assert d["obs"][0]["situacao"] == "Devolvida pelo banco"
    assert _desembolso_ops_obs(d)["desembolsos"][0]["numero_ob"] == "1939"


def test_situacao_DESCONHECIDA_faz_o_relatorio_CALAR():
    """⚠️ O TERCEIRO ESTADO, e ele não é um dos outros dois. O vocabulário do
    portal não está documentado e só um valor foi medido ("Acatada pelo banco").
    Numa situação que este código não sabe ler, dizer "Pendente de desembolso"
    pode ser falso e dizer "Desembolsado" também — então não diz nenhum dos
    dois. Calar no desconhecido é o que faz o marcador valer alguma coisa quando
    ele aparece."""
    d = _mg_pagamentos([montar_pagamentos([
        {"data": "01/02/2026", "numero": "9", "situacao": "Em processamento",
         "valor": 1000.0}])])
    assert d["_incerto"] is True
    sit = _situacao_com_marcas("Em vigor", False,
                               bool(d["_consultado"]) and not d["_incerto"],
                               d["valor_desembolsado"])
    assert sit == "Em vigor"          # nem pendente, nem desembolsado


def test_o_vocabulario_medido_e_o_negado():
    assert pagamento_confirmado("Acatada pelo banco") is True
    assert pagamento_confirmado("ACATADA PELO BANCO") is True
    assert pagamento_confirmado("Devolvida pelo banco") is False
    assert pagamento_confirmado("Cancelada") is False
    assert pagamento_confirmado("Em processamento") is None
    assert pagamento_confirmado("") is None
    assert pagamento_confirmado(None) is None


def test_a_data_do_ultimo_desembolso_e_a_da_OP_QUE_PAGOU():
    """Uma devolvida em agosto não pode virar "último desembolso" por ser a mais
    recente: ela não desembolsou nada."""
    d = montar_pagamentos([
        {"data": "23/06/2026", "numero": "1", "situacao": "Acatada pelo banco",
         "valor": 100.0},
        {"data": "08/08/2026", "numero": "2", "situacao": "Devolvida pelo banco",
         "valor": 500.0}])
    assert d["data_ultimo_desembolso"] == "23/06/2026"
    assert d["valor_desembolsado"] == 100.0


def test_bloco_ANTIGO_sem_a_chave_nova_e_reclassificado_pelas_obs():
    """⚠️ Linhas gravadas antes deste conserto não têm
    `tem_situacao_desconhecida`. Sem a reclassificação elas passariam por "tudo
    confirmado" — exatamente a afirmação que este conserto existe para impedir."""
    antigo = {"valor_desembolsado": 0.0, "data_ultimo_desembolso": None,
              "obs": [{"data_emissao_ob": "01/02/2026", "valor": 1000.0,
                       "numero_ob": "9", "situacao": "Em processamento"}]}
    assert _mg_pagamentos([antigo])["_incerto"] is True
