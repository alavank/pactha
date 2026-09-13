"""A listagem do TransfereGov que vem CURTA nao pode passar por completa.

⚠️ O DEFEITO QUE ISTO IMPEDE (13/09/2026): com o portal lento, a pagina 1 da
consulta chegava antes do displaytag desenhar a barra de paginacao. Sem o banner
"Pagina X de Y (Z item(s))" o coletor nao sabia o total, andava pelos links e
parava na primeira pagina que chegasse sem link — achando que era a ultima. A trava
de completude comparava com o Z, que nunca tinha sido lido, e ficava calada.
Resultado medido: Palmas "fechou" com 100 de 2.121 propostas e Goiania com 2.460 de
3.472, as duas gravadas como `success` e carimbadas como coletadas.
"""
from ingestion.transferegov_voluntarias import _listagem_incompleta, _proximo_link


# --- trava de completude -------------------------------------------------------
def test_com_total_oficial_lista_inteira_passa():
    assert _listagem_incompleta(2121, 2121, 0) is None


def test_com_total_oficial_tolera_divergencia_pequena():
    # `listadas` e deduplicada; o Z conta itens brutos. 1-2 itens de diferenca
    # estavel nao pode marcar subcoleta em toda visita.
    assert _listagem_incompleta(2119, 2121, 0) is None
    assert _listagem_incompleta(98, 100, 0) is None


def test_com_total_oficial_corte_real_acusa():
    assert _listagem_incompleta(100, 2121, 0) == (2121, "total oficial do portal")
    assert _listagem_incompleta(2460, 3472, 0)[0] == 3472


def test_sem_total_oficial_usa_o_que_o_banco_conhece():
    # O caso de 13/09: banner ausente, total desconhecido.
    esperado, ref = _listagem_incompleta(100, None, 2121)
    assert esperado == 2121
    assert "banco" in ref


def test_sem_total_oficial_lista_perto_do_conhecido_passa():
    # o banco guarda proposta que o portal ja nao lista: 90% e o piso
    assert _listagem_incompleta(1950, None, 2121) is None


def test_sem_referencia_nenhuma_nao_inventa_corte():
    # municipio novo (nada no banco) ou pequeno demais para julgar
    assert _listagem_incompleta(5, None, 0) is None
    assert _listagem_incompleta(5, None, 12) is None


# --- proximo link ----------------------------------------------------------------
def _res(nums, prox=None):
    return {"links": [{"num": n, "href": f"?p={n}"} for n in nums], "prox": prox}


def test_proximo_link_dentro_da_janela_usa_o_numero():
    assert _proximo_link(_res([1, 2, 3, 4]), 2) == "?p=3"


def test_proximo_link_na_borda_da_janela_usa_o_prox():
    assert _proximo_link(_res([1, 2, 3], prox="?g=11"), 10) == "?g=11"


def test_proximo_link_sem_numero_nem_prox_e_none():
    # e o caso que, com total conhecido e cur < total, agora rele a pagina antes
    # de desistir — em vez de encerrar a listagem achando que era a ultima
    assert _proximo_link(_res([]), 5) is None
