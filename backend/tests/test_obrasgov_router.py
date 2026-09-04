"""Obras Federais — a classificação, e por que ela NÃO usa a data efetiva.

⚠️⚠️ **A PRIMEIRA VERSÃO DESTE ARQUIVO GUARDAVA A REGRA ERRADA**, e só a
produção mostrou. Ele testava "previsto no passado + efetivo vazio = atrasada",
uma regra que parece certa e que a fonte não sustenta:

    data_inicial_efetiva / data_final_efetiva
      · vazias em 100% das 1.011 obras coletadas nos cinco tenants
      · na API, preenchidas em 4 de 200
      · e 65 obras "Concluída" NÃO TÊM data de conclusão

O Governo encerra a obra mudando a SITUAÇÃO, não preenchendo a data. Com a regra
antiga, Nova Palma abria com **27 de 30** obras "exigindo atenção" e Arapuá com
3 de 3 — uma lista em que quase tudo é urgente não é lida, e o gestor perde
justamente a obra que travou.

Então quem classifica é a `situacao`, e a data prevista só gradua. E há um grupo
a mais, «não saiu do papel», porque projeto encalhado e obra parada pedem
cobranças diferentes: uma se cobra do executor, a outra do órgão repassador.

Rodar:
    python -m pytest backend/tests/test_obrasgov_router.py -v
"""
from datetime import date

import pytest

from routers.obrasgov import _classificar

HOJE = date(2026, 9, 4)
VENCIDA = date(2026, 6, 30)      # 66 dias atrás
FUTURA = date(2027, 12, 31)


def obra(**kw) -> dict:
    base = {
        "situacao": "Cadastrada",
        "data_inicial_prevista": None, "data_final_prevista": None,
        "data_inicial_efetiva": None, "data_final_efetiva": None,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# ⭐ A regra que a produção corrigiu
# ---------------------------------------------------------------------------
def test_a_data_efetiva_vazia_NAO_torna_a_obra_urgente():
    """⚠️ O TESTE MAIS IMPORTANTE DESTE ARQUIVO. A efetiva está vazia em 100%
    das obras coletadas — se ela fosse sinal, TUDO seria urgente, que foi
    exatamente o defeito da primeira versão."""
    d = _classificar(obra(situacao="Em execução",
                          data_final_prevista=FUTURA,
                          data_final_efetiva=None), HOJE)
    assert d["grupo"] == "andamento"
    assert d["alerta"] is None


def test_concluida_sem_data_de_conclusao_continua_encerrada():
    """São 65 de 200 na API: "Concluída" com `dt_final_efetiva` vazia. Ler a
    ausência da data como "não terminou" mandaria obra entregue para a lista de
    urgências — e lista de urgência com coisa resolvida deixa de ser lida."""
    d = _classificar(obra(situacao="Concluída",
                          data_final_prevista=date(2024, 1, 1),
                          data_final_efetiva=None), HOJE)
    assert d["grupo"] == "encerradas"
    assert d["alerta"] is None


# ---------------------------------------------------------------------------
# Ação: a obra começou e travou
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("situacao", ["Paralisada", "Inacabada"])
def test_a_fonte_declarando_o_problema_basta(situacao):
    """Não precisa de conta nenhuma: são 281 inacabadas e 180 paralisadas nas
    32.300 obras medidas."""
    d = _classificar(obra(situacao=situacao), HOJE)
    assert d["grupo"] == "acao"
    assert d["alerta"] == situacao.lower()
    assert situacao.lower() in (d["motivo"] or "").lower()


def test_em_execucao_com_prazo_vencido_e_acao():
    d = _classificar(obra(situacao="Em execução",
                          data_final_prevista=VENCIDA), HOJE)
    assert d["grupo"] == "acao"
    assert d["alerta"] == "prazo_vencido"
    assert "66 dia" in d["motivo"] and "30/06/2026" in d["motivo"]


def test_em_execucao_dentro_do_prazo_e_andamento():
    d = _classificar(obra(situacao="Em execução",
                          data_final_prevista=FUTURA), HOJE)
    assert d["grupo"] == "andamento"


def test_em_execucao_sem_prazo_declarado_nao_vira_urgencia():
    """Sem data não há atraso a afirmar. Chutar "atrasada" porque a fonte não
    informou seria inventar uma pendência para a prefeitura."""
    d = _classificar(obra(situacao="Em execução"), HOJE)
    assert d["grupo"] == "andamento"


def test_em_execucao_ignora_o_inicio_previsto_vencido():
    """Ela já está em execução — que o início previsto tenha passado é história,
    e repeti-la como alerta encheria a lista de urgência de ruído."""
    d = _classificar(obra(situacao="Em execução",
                          data_inicial_prevista=date(2020, 1, 1),
                          data_final_prevista=FUTURA), HOJE)
    assert d["grupo"] == "andamento"


# ---------------------------------------------------------------------------
# ⭐ «Não saiu do papel» — o grupo que a produção pediu
# ---------------------------------------------------------------------------
def test_cadastrada_com_inicio_previsto_vencido_e_projeto_encalhado():
    """⚠️ NÃO É "obra atrasada" — é obra que não começou, e a cobrança é outra.
    Em Nova Palma são as 21 da Defesa Civil: R$ 24,7 milhões cadastrados que
    ainda não viraram canteiro."""
    d = _classificar(obra(situacao="Cadastrada",
                          data_inicial_prevista=date(2024, 8, 1)), HOJE)
    assert d["grupo"] == "papel"
    assert d["alerta"] == "nao_saiu_do_papel"
    assert "Cadastrada" in d["motivo"]
    assert "início" in d["motivo"]          # diz QUAL data venceu
    assert "01/08/2024" in d["motivo"]


def test_cadastrada_sem_inicio_mas_com_fim_vencido_tambem_encalhou():
    d = _classificar(obra(situacao="Cadastrada",
                          data_final_prevista=VENCIDA), HOJE)
    assert d["grupo"] == "papel"
    assert "conclusão" in d["motivo"]


def test_cadastrada_com_prazo_no_futuro_esta_em_dia():
    d = _classificar(obra(situacao="Cadastrada",
                          data_inicial_prevista=FUTURA), HOJE)
    assert d["grupo"] == "andamento"
    assert d["alerta"] is None


def test_cadastrada_sem_data_nenhuma_nao_vira_urgencia():
    d = _classificar(obra(situacao="Cadastrada"), HOJE)
    assert d["grupo"] == "andamento"


def test_cancelada_nunca_entra_em_urgencia():
    """Cancelada com prazo estourado é história, não pendência."""
    d = _classificar(obra(situacao="Cancelada",
                          data_inicial_prevista=date(2019, 1, 1)), HOJE)
    assert d["grupo"] == "encerradas"


# ---------------------------------------------------------------------------
# O que a fonte ainda não inventou
# ---------------------------------------------------------------------------
def test_situacao_desconhecida_cai_na_regra_de_projeto_e_nao_quebra():
    """Se o Governo criar uma sétima situação, ela é tratada como projeto (o
    caso conservador: ainda não está em execução declarada) e a tela mostra o
    texto dela como veio — nunca levanta exceção nem vira "Outros"."""
    d = _classificar(obra(situacao="Em homologação especial",
                          data_inicial_prevista=VENCIDA), HOJE)
    assert d["grupo"] == "papel"
    assert "Em homologação especial" in d["motivo"]


def test_sem_situacao_nenhuma_nao_quebra():
    d = _classificar(obra(situacao=None, data_final_prevista=VENCIDA), HOJE)
    assert d["grupo"] == "papel"
    assert "sem situação" in d["motivo"]
