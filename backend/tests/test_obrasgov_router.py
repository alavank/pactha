"""Obras Federais — a classificação por PRAZO, que é o que a tela ordena.

⚠️ O QUE ESTE ARQUIVO GUARDA é o par **previsto × efetivo**. Nulo na data
efetiva é "ainda não aconteceu", e é o ÚNICO sinal que a fonte dá de obra
parada: o Obras.gov.br não tem campo "atrasada". Quem preenchesse a efetiva com
a prevista — ou comparasse com a data de cadastro — apagaria exatamente esse
sinal, e a tela mostraria tudo em dia para sempre, sem erro nenhum aparecer.

A classificação mora no SERVIDOR (e não na tela) pelo mesmo motivo do
`routers/sismob.py`: tela, TV, celular e PDF precisam concordar sobre o que é
urgente. Se cada um classificasse por conta, um dia divergiriam.

Rodar:
    python -m pytest backend/tests/test_obrasgov_router.py -v
"""
from datetime import date

from routers.obrasgov import _classificar

HOJE = date(2026, 9, 4)


def obra(**kw) -> dict:
    base = {
        "situacao": "Em execução",
        "data_inicial_prevista": None, "data_final_prevista": None,
        "data_inicial_efetiva": None, "data_final_efetiva": None,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# O que a própria fonte já declara parado
# ---------------------------------------------------------------------------
def test_paralisada_e_inacabada_vao_para_acao():
    """A fonte tem estas duas situações e elas não precisam de conta nenhuma:
    são 861 canceladas, 281 inacabadas e 180 paralisadas nas 32.300 obras
    medidas em 04/09/2026."""
    for s in ("Paralisada", "Inacabada"):
        d = _classificar(obra(situacao=s), HOJE)
        assert d["grupo"] == "acao"
        assert d["alerta"] == s.lower()
        assert s.lower() in (d["motivo"] or "").lower()


def test_concluida_e_cancelada_saem_da_frente():
    for s in ("Concluída", "Cancelada"):
        d = _classificar(obra(situacao=s), HOJE)
        assert d["grupo"] == "encerradas"
        assert d["alerta"] is None


def test_encerrada_vence_o_prazo_vencido():
    """⚠️ Obra CONCLUÍDA com prazo estourado não é pendência — ela terminou
    atrasada, e isso é história. Marcá-la como "prazo vencido" encheria a lista
    de urgências com obra entregue, e uma lista de urgência que traz coisa
    resolvida deixa de ser lida."""
    d = _classificar(obra(situacao="Concluída",
                          data_final_prevista=date(2024, 1, 1),
                          data_final_efetiva=None), HOJE)
    assert d["grupo"] == "encerradas"


# ---------------------------------------------------------------------------
# ⭐ O par previsto × efetivo
# ---------------------------------------------------------------------------
def test_prazo_de_conclusao_vencido_sem_conclusao_registrada():
    d = _classificar(obra(data_final_prevista=date(2026, 8, 4),
                          data_final_efetiva=None), HOJE)
    assert d["grupo"] == "acao"
    assert d["alerta"] == "prazo_vencido"
    assert "31 dia" in d["motivo"]          # 04/08 -> 04/09
    assert "04/08/2026" in d["motivo"]


def test_prazo_vencido_MAS_concluida_de_fato_nao_e_pendencia():
    """A data efetiva preenchida é a resposta: a obra acabou. Que tenha acabado
    depois do previsto é outra conversa, e não é urgência."""
    d = _classificar(obra(data_final_prevista=date(2026, 1, 1),
                          data_final_efetiva=date(2026, 8, 20)), HOJE)
    assert d["grupo"] == "andamento"
    assert d["alerta"] is None


def test_prazo_ainda_no_futuro_nao_alarma():
    d = _classificar(obra(data_final_prevista=date(2027, 12, 31)), HOJE)
    assert d["grupo"] == "andamento"


def test_obra_que_deveria_ter_comecado_e_nao_comecou():
    d = _classificar(obra(data_inicial_prevista=date(2025, 3, 10),
                          data_inicial_efetiva=None), HOJE)
    assert d["grupo"] == "acao"
    assert d["alerta"] == "nao_comecou"
    assert "10/03/2025" in d["motivo"]


def test_comecou_no_prazo_e_segue_sem_prazo_final_vencido():
    d = _classificar(obra(data_inicial_prevista=date(2025, 3, 10),
                          data_inicial_efetiva=date(2025, 4, 2),
                          data_final_prevista=date(2027, 1, 1)), HOJE)
    assert d["grupo"] == "andamento"


def test_conclusao_vencida_tem_precedencia_sobre_inicio_vencido():
    """Uma obra pode disparar os dois. O alerta que a tela mostra é o do FIM:
    é o mais grave e o que contém o outro — se o prazo final venceu, saber que
    o início também venceu não muda o que o gestor faz."""
    d = _classificar(obra(data_inicial_prevista=date(2024, 1, 1),
                          data_final_prevista=date(2025, 1, 1)), HOJE)
    assert d["alerta"] == "prazo_vencido"


def test_obra_sem_data_nenhuma_nao_vira_urgencia():
    """⚠️ Sem data não há atraso a afirmar. Chutar "atrasada" porque a fonte não
    informou seria inventar uma pendência para a prefeitura — e são muitas: a
    maior parte das obras Cadastradas ainda não tem data efetiva de nada."""
    d = _classificar(obra(situacao="Cadastrada"), HOJE)
    assert d["grupo"] == "andamento"
    assert d["alerta"] is None


def test_situacao_desconhecida_nao_quebra():
    """Se o Governo criar uma sétima situação, a tela mostra o texto dela e a
    classificação cai no critério de prazo — nunca levanta exceção."""
    d = _classificar(obra(situacao="Em homologação especial"), HOJE)
    assert d["grupo"] == "andamento"
    d = _classificar(obra(situacao=None,
                          data_final_prevista=date(2020, 1, 1)), HOJE)
    assert d["alerta"] == "prazo_vencido"
