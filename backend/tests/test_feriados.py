"""FERIADOS: as datas que a agenda marca, e as que ela NAO pode marcar.

Este arquivo cerca dois riscos diferentes, e o segundo e o que importa mais:

⚠️ 1. A CONTA DA PASCOA. Todas as datas moveis saem dela — Carnaval, Sexta-feira
Santa, Corpus Christi e o feriado estadual do Espirito Santo. Um erro de um dia
no algoritmo desloca as quatro, e ninguem percebe olhando o codigo: percebe-se
em fevereiro, quando o Carnaval cai na semana errada.

⚠️ 2. FERIADO x PONTO FACULTATIVO. Carnaval e Corpus Christi NAO sao feriados
nacionais — sao pontos facultativos do calendario federal (Portaria MGI
11.460/2025 para 2026: DEZ feriados e NOVE pontos facultativos). A Sexta-feira
Santa, sim, e feriado. Promover um facultativo a feriado deixa a tela AFIRMANDO
o que a lei nao diz, e e o erro mais facil de cometer aqui porque na pratica
quase ninguem trabalha na terca de carnaval.

⚠️ 3. UF SO COM A LEI CONFERIDA. Um agregador de feriados da internet dava ao
Espirito Santo "28/10 — Dia do Servidor Publico" como feriado estadual; o proprio
TJES publica essa data como PONTO FACULTATIVO, e o feriado estadual capixaba e
outro (Nossa Senhora da Penha, movel, Lei 11.010/2019). Estado sem linha no
catalogo mostra so os nacionais — ausencia e honesta, feriado inventado manda
alguem marcar visita num dia em que nao ha ninguem para receber.

Rodar: python -m pytest backend/tests/test_feriados.py -q
"""
from datetime import date

import pytest

from services import feriados as F  # noqa: E402


# ------------------------------------------------------------- a Pascoa -----

@pytest.mark.parametrize("ano,esperado", [
    (2024, date(2024, 3, 31)),
    (2025, date(2025, 4, 20)),
    (2026, date(2026, 4, 5)),
    (2027, date(2027, 3, 28)),
    (2030, date(2030, 4, 21)),
])
def test_a_pascoa_bate_com_as_datas_conhecidas(ano, esperado):
    assert F.pascoa(ano) == esperado


def test_a_pascoa_e_sempre_domingo():
    """A prova barata de que o algoritmo nao escorregou: 200 anos de domingos."""
    for ano in range(1950, 2150):
        assert F.pascoa(ano).weekday() == 6, ano


# -------------------------------------------- feriado x ponto facultativo ---

def _de(itens, tipo):
    return [i for i in itens if i["tipo"] == tipo]


def test_sao_DEZ_os_feriados_nacionais():
    """O numero e da Portaria MGI 11.460/2025 (calendario oficial de 2026):
    dez feriados nacionais e nove pontos facultativos."""
    nac = _de(F.do_ano(2026), F.TIPO_NACIONAL)
    assert len(nac) == 10, [i["nome"] for i in nac]


@pytest.mark.parametrize("nome", [
    "Carnaval", "Corpus Christi", "Dia do Servidor Público",
])
def test_o_que_NAO_e_feriado_nacional(nome):
    """⚠️ A INVARIANTE PRINCIPAL DESTE ARQUIVO. Promover um destes a feriado faz
    a tela afirmar o que a lei nao diz."""
    itens = F.do_ano(2026)
    achados = [i for i in itens if i["nome"].startswith(nome)]
    assert achados, f"{nome} sumiu do calendario"
    for i in achados:
        assert i["tipo"] == F.TIPO_FACULTATIVO, i


def test_a_sexta_feira_santa_E_feriado_e_cai_dois_dias_antes_da_pascoa():
    itens = F.do_ano(2026)
    santa = [i for i in itens if i["nome"] == "Sexta-feira Santa"]
    assert len(santa) == 1
    assert santa[0]["tipo"] == F.TIPO_NACIONAL
    # 2026: Pascoa em 05/04 -> Sexta-feira Santa em 03/04, como a Portaria MGI.
    assert santa[0]["data"] == "2026-04-03"


def test_o_carnaval_de_2026_cai_nos_dias_da_portaria():
    """16 e 17 de fevereiro, com a Quarta-feira de Cinzas em 18 — os tres como
    ponto facultativo."""
    datas = {i["data"] for i in F.do_ano(2026)
             if i["tipo"] == F.TIPO_FACULTATIVO}
    assert {"2026-02-16", "2026-02-17", "2026-02-18"} <= datas


def test_consciencia_negra_e_NACIONAL_e_nao_estadual():
    """Lei 14.759/2023. Antes dela era feriado estadual em varios estados; se
    alguem a reintroduzir no catalogo estadual, o dia aparece duas vezes."""
    itens = F.do_ano(2026, set(F.ESTADUAIS))
    cn = [i for i in itens if "Consciência Negra" in i["nome"]]
    assert len(cn) == 1
    assert cn[0]["tipo"] == F.TIPO_NACIONAL and cn[0]["data"] == "2026-11-20"


# ------------------------------------------------------------ estaduais -----

def test_o_feriado_do_ES_e_MOVEL_e_nao_e_28_de_outubro():
    """⚠️ O ERRO QUE UM AGREGADOR DA INTERNET COMETEU, cravado aqui.

    O feriado estadual capixaba e Nossa Senhora da Penha (Lei 11.010/2019), a
    segunda-feira OITO DIAS depois da Pascoa. 28/10 e o Dia do Servidor Publico,
    que o proprio TJES publica como PONTO FACULTATIVO."""
    itens = F.do_ano(2026, {"ES"})
    est = _de(itens, F.TIPO_ESTADUAL)
    assert len(est) == 1
    assert est[0]["nome"] == "Nossa Senhora da Penha"
    assert est[0]["data"] == "2026-04-13"          # 05/04 + 8
    assert date.fromisoformat(est[0]["data"]).weekday() == 0, "tem de ser segunda"
    # E 28/10, se aparecer, so como facultativo NACIONAL — nunca estadual do ES.
    for i in itens:
        if i["data"].endswith("-10-28"):
            assert i["tipo"] == F.TIPO_FACULTATIVO and i["uf"] is None


@pytest.mark.parametrize("uf,dia,nome", [
    ("RS", "2026-09-20", "Revolução Farroupilha"),
    ("GO", "2026-10-24", "Pedra Fundamental de Goiânia"),
])
def test_os_estaduais_fixos_conferidos(uf, dia, nome):
    est = _de(F.do_ano(2026, {uf}), F.TIPO_ESTADUAL)
    assert [(i["data"], i["nome"], i["uf"]) for i in est] == [(dia, nome, uf)]


def test_toda_regra_estadual_cita_a_lei():
    """⚠️ A CITACAO E O QUE PERMITE CONFERIR SEM REFAZER A PESQUISA. Mesma
    disciplina de `cadastro_estadual.py`: linha nova so com fonte."""
    for uf, regras in F.ESTADUAIS.items():
        for r in regras:
            assert r.get("lei"), f"{uf}: regra sem lei citada — {r}"
            assert r.get("nome"), f"{uf}: regra sem nome"


def test_UF_fora_do_catalogo_nao_ganha_feriado_inventado():
    """Sao Paulo tem feriado estadual (09/07) e NAO esta no catalogo. O certo e
    devolver so os nacionais — ausencia e honesta, invencao nao."""
    assert "SP" not in F.ESTADUAIS
    assert _de(F.do_ano(2026, {"SP"}), F.TIPO_ESTADUAL) == []


def test_sem_UF_nenhuma_so_vem_o_que_vale_no_pais_inteiro():
    for itens in (F.do_ano(2026), F.do_ano(2026, set()), F.do_ano(2026, None)):
        assert _de(itens, F.TIPO_ESTADUAL) == []
        assert len(_de(itens, F.TIPO_NACIONAL)) == 10


def test_a_UF_de_um_tenant_nao_vaza_para_o_outro():
    """⚠️ O RECORTE QUE FAZ O MODULO SERVIR AOS CINCO. Um cliente de Nova Palma
    nao pode ver o Dia do Evangelico do DF marcado na agenda dele."""
    so_rs = _de(F.do_ano(2026, {"RS"}), F.TIPO_ESTADUAL)
    assert {i["uf"] for i in so_rs} == {"RS"}
    assert not any("Evangélico" in i["nome"] for i in so_rs)


def test_a_mesma_data_pode_ter_dois_registros():
    """21 de abril e Tiradentes (nacional) E Data Magna de Minas. Quem calcula
    nao pode escolher um dos dois e esconder o outro — quem desenha decide se
    junta os rotulos."""
    do_dia = [i for i in F.do_ano(2026, {"MG"}) if i["data"] == "2026-04-21"]
    assert len(do_dia) == 2
    assert {i["tipo"] for i in do_dia} == {F.TIPO_NACIONAL, F.TIPO_ESTADUAL}


def test_MG_nao_acrescenta_dia_de_folga_nenhum():
    """A Data Magna mineira COINCIDE com o feriado nacional de Tiradentes. A
    linha existe para o rotulo, nao para marcar um dia a mais."""
    datas_nac = {i["data"] for i in _de(F.do_ano(2026), F.TIPO_NACIONAL)}
    est_mg = _de(F.do_ano(2026, {"MG"}), F.TIPO_ESTADUAL)
    assert all(i["data"] in datas_nac for i in est_mg)


# ---------------------------------------------------------------- forma -----

def test_vem_ordenado_por_data():
    itens = F.do_ano(2026, set(F.ESTADUAIS))
    assert [i["data"] for i in itens] == sorted(i["data"] for i in itens)


def test_toda_entrada_tem_a_forma_que_a_tela_espera():
    for i in F.do_ano(2026, {"RS", "ES"}):
        assert set(i) == {"data", "nome", "tipo", "uf", "lei"}
        assert i["tipo"] in (F.TIPO_NACIONAL, F.TIPO_ESTADUAL, F.TIPO_FACULTATIVO)
        date.fromisoformat(i["data"])          # levanta se nao for ISO
        # `uf` so existe no estadual: um nacional com UF faria a tela dizer que
        # o Natal e feriado "do RS".
        assert (i["uf"] is not None) == (i["tipo"] == F.TIPO_ESTADUAL)


def test_o_ano_pedido_e_o_ano_devolvido():
    """Corpus Christi cai em maio ou junho e a Pascoa nunca sai do ano — mas um
    deslocamento errado poderia atravessar dezembro."""
    for ano in (2024, 2025, 2026, 2027):
        for i in F.do_ano(ano, set(F.ESTADUAIS)):
            assert i["data"].startswith(str(ano)), i
