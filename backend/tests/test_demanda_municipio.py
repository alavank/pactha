"""O que é DEMANDA DO MUNICÍPIO — três pedidos do dono (26/08/2026).

  - licitação EM ELABORAÇÃO  -> quem elabora o edital é a prefeitura
  - obra sem ART/RRT         -> quem cadastra a ART é a prefeitura
  - Novo PAC                 -> demanda do município

Os três empurram o item da PARTE 1 (Brasília) para a PARTE 2 (Município).

⚠️ `_classifica_parte` NÃO é o caminho. Ela existe, mas está MORTA em produção:
os dois chamadores de `montar_conteudo` passam `completo=True` e ela só é
alcançada nos ramos `else`, com esfera fixa "estadual". Quem decide de verdade é
`_destino_completo`, alimentado por `pend_municipal`.
"""
import pytest

from services.rm_builder import (
    _destino_completo, _lic_em_elaboracao, _obra_resumo, _obra_sem_art,
)


# ------------------------------------------------- licitação em elaboração ---
@pytest.mark.parametrize("sit", [
    "Em Elaboração", "EM ELABORACAO", "em elaboração", "Em elabora��o",
])
def test_licitacao_em_elaboracao_em_qualquer_grafia(sit):
    """⚠️ `situacao` é texto CRU do portal, sem enum, e o acento chega corrompido
    em algumas rodadas. Comparar string inteira seria apostar numa grafia."""
    assert _lic_em_elaboracao([{"situacao": sit}])


@pytest.mark.parametrize("v,rot", [
    (None, "não coletado"),
    ([], "coletado e não há licitação"),
    ("lixo", "valor que não é lista"),
    ([{"situacao": "Concluído"}], "licitação concluída"),
    ([{}], "item sem o campo"),
])
def test_ausencia_NAO_classifica(v, rot):
    """⚠️ A regra que impede cobrança falsa. `None` é "não perguntei" — mandar o
    item para a Parte 2 por ausência de dado poria na mesa do prefeito uma
    pendência que ninguém mediu, e ainda o tiraria do RM Resumido, que só imprime
    a Parte 1."""
    assert _lic_em_elaboracao(v) is False, rot


def test_uma_licitacao_em_elaboracao_entre_varias_basta():
    assert _lic_em_elaboracao([{"situacao": "Concluído"},
                               {"situacao": "Em elaboração"}])


# ------------------------------------------------------------- ART / RRT ----
def test_lote_sem_art_e_demanda_do_municipio():
    assert _obra_sem_art({"lotes": [{"arts": []}]})


@pytest.mark.parametrize("v,rot", [
    (None, "não consegui ler"),
    ({}, "instrumento sem medição (o portal responde 412)"),
    ({"lotes": []}, "sem lotes"),
    ({"lotes": [{"arts": [{"n": "1"}]}]}, "tem ART"),
])
def test_obra_sem_dado_NAO_classifica(v, rot):
    assert _obra_sem_art(v) is False, rot


def test_um_lote_com_art_ja_basta():
    """A frase do RM diz "cumprir a exigência" — se ALGUM lote tem ART, a obra já
    pode ser medida e a exigência não é a pendência."""
    assert _obra_sem_art({"lotes": [{"arts": []}, {"arts": [{"n": "1"}]}]}) is False


def test_a_frase_do_RM_e_a_classificacao_saem_da_MESMA_condicao():
    """⚠️ O motivo de `_obra_resumo` CHAMAR `_obra_sem_art` em vez de repetir a
    condição. Duas cópias divergiriam calado — a frase diria "falta ART" e o item
    continuaria listado como pendência de Brasília, que é exatamente o defeito
    que o dono relatou."""
    sem_art = {"lotes": [{"arts": []}]}
    assert _obra_sem_art(sem_art)
    assert "ART/RRT" in _obra_resumo(sem_art)

    com_art = {"lotes": [{"arts": [{"n": "1"}]}]}
    assert not _obra_sem_art(com_art)
    assert "ART/RRT" not in _obra_resumo(com_art)


# ---------------------------------------------------------------- Novo PAC ---
def _pac(status, ano_item, ano_ref, pre_novo=False, pend=True):
    return _destino_completo("federal", "pac", status, ano_item, None, ano_ref,
                             pend, pre_novo, False)


def test_pac_nao_pago_vai_para_a_PARTE_2():
    parte, _, _ = _pac("ativa", 2026, 2026)
    assert parte == 2


def test_pac_do_ano_corrente_NAO_cai_mais_na_parte_4():
    """⚠️ A metade que sem a outra não entrega. `_destino_completo` devolve a
    Parte 4 ANTES de olhar a pendência, então zerar `pre_empenho_novo` é o que
    faz o pedido valer justamente para as seleções mais NOVAS.

    E a Parte 4 se chama, literalmente, "Propostas Voluntárias … cadastros
    realizados no ano de {ano} … não possuem garantia" — uma seleção do PAC não
    é proposta voluntária."""
    assert _pac("ativa", 2026, 2026, pre_novo=False)[0] == 2
    # com `pre_novo=True` iria para a 4 — é o que o código deixou de passar
    assert _pac("ativa", 2026, 2026, pre_novo=True)[0] == 4


def test_pac_PAGO_segue_o_caminho_de_sempre():
    """O pedido é sobre onde a bola está, e em seleção paga não há bola com
    ninguém — então o ramo do pago não foi tocado.

    ⚠️ E ele leva o PAC pago SEMPRE para a Parte 3, inclusive no ano corrente.
    Não é efeito desta mudança: o bloco do PAC passa `ano_pgto=None` (o coletor
    não traz data de pagamento), e `pago_corrente` compara `ano_pgto == ano_ref`.
    Ou seja, seleção do PAC nunca entra no bloco "REPASSES DE {ano}" da Parte 2.

    Fica registrado aqui porque descobri ao escrever este teste, esperando o
    contrário. É lacuna de DADO (falta a data de pagamento do PAC), não de
    classificação — consertar exige coleta, não um `if`."""
    assert _pac("paga", 2026, 2026)[0] == 3, "mudou o ramo do pago"
    assert _pac("paga", 2024, 2026)[0] == 3
    # com data de pagamento conhecida, o ano corrente iria para a Parte 2 —
    # é o que aconteceria no dia em que o coletor do PAC trouxer `dt_pgto`.
    assert _destino_completo("federal", "pac", "paga", 2026, 2026, 2026,
                             True, False, False)[0] == 2


def test_o_titulo_da_parte_4_e_o_argumento():
    from services.rm_builder import _titulos_partes_completo

    t4 = _titulos_partes_completo(2026)[4]
    assert "Voluntárias" in t4 and "2026" in t4
