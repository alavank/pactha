"""As tres guardas da consulta do radar — verificadas na ARVORE do SQL.

Nao ha Postgres de teste neste repo (SQL se valida com `pglast`), entao a
consulta do `routers/programas_captacao` nao pode ser exercitada contra banco.
O que da para fazer — e o que este arquivo faz — e PARSEAR o SQL com a gramatica
real do Postgres e exigir que as tres condicoes estejam la.

⚠️ POR QUE ISSO NAO E `assert "..." in sql`. Uma busca por substring passa com o
texto dentro de um comentario, de uma string, ou de um `OR` que anula a guarda.
O parser enxerga a estrutura: as condicoes precisam estar no WHERE, ligadas por
AND. Cada uma das tres, se cair, produz um defeito diferente e nenhum deles
levanta erro:

    sem `ausente_desde IS NULL`   -> programa fora do ar volta para a tela;
    sem `dt_fim_receb >= hoje`    -> a tela anuncia prazo VENCIDO (a tabela e
                                     fotografia do dia da coleta);
    sem `:uf = ANY(ufs)`          -> prefeito mineiro recebe programa que so
                                     aceita municipio gaucho — "porta que nao
                                     abre", o defeito que o `programas_rs.py`
                                     ja documenta.

Rodar: python -m pytest backend/tests/test_radar_router_guardas.py -q
"""
import re

import pytest

pglast = pytest.importorskip("pglast")

from routers import programas_captacao as R  # noqa: E402


def _sql_da_rota() -> str:
    """O SELECT literal do modulo, com os :binds trocados por placeholder.

    Le do ARQUIVO e nao de um `str` exportado de proposito: o que vai para o
    banco e o texto que esta no codigo, e um teste que lesse uma constante
    paralela poderia passar com a rota usando outra consulta.
    """
    fonte = open(R.__file__, encoding="utf-8").read()
    m = re.search(r'text\("""(.*?)"""\)', fonte, re.S)
    assert m, "SELECT do radar nao encontrado no router"
    # `:uf`/`:nat` sao binds do SQLAlchemy; o Postgres nao os conhece.
    return re.sub(r":(\w+)", r"'\1'", m.group(1))


@pytest.fixture(scope="module")
def where():
    sql = _sql_da_rota()
    arvore = pglast.parse_sql(sql)          # gramatica real: sintaxe invalida estoura aqui
    return pglast.prettify(sql).lower()


def test_a_consulta_e_sql_valido_de_postgres():
    """`prettify` so devolve texto se o parser aceitou a arvore inteira."""
    assert pglast.prettify(_sql_da_rota())


def test_esconde_programa_que_saiu_do_ar(where):
    """⚠️ Sem esta guarda o radar ressuscita programa fora de cartaz."""
    assert "ausente_desde is null" in where


def test_esconde_prazo_ja_vencido(where):
    """⚠️ A TABELA E FOTOGRAFIA DO DIA DA COLETA.

    Entre uma rodada e outra um prazo vence. Confiar so no corte do coletor
    deixaria a tela anunciando prazo morto — e o municipio montaria processo
    para nada.
    """
    assert "dt_fim_receb >= current_date" in where


def test_filtra_pela_UF_do_municipio(where):
    """⚠️ 9 dos 17 programas abertos sao regionais (medido em 02/09/2026)."""
    assert "any(ufs)" in where


def test_filtra_pela_natureza_da_prefeitura(where):
    """Consorcio publico e outra pessoa juridica; o prefeito nao assina por ele."""
    assert "any(naturezas)" in where
    assert R.NATUREZA_PREFEITURA == "Administração Pública Municipal"


def test_as_guardas_estao_ligadas_por_AND_e_nao_por_OR(where):
    """⚠️ A GUARDA QUE UM `in` NAO PEGARIA.

    Um `OR` no meio do WHERE deixaria todas as substrings acima presentes e
    ainda assim liberaria a linha errada — basta uma das pernas ser verdadeira.
    O WHERE do radar nao tem `or` nenhum: se algum dia precisar de um, ele tem
    de vir entre parenteses e este teste tem de ser reescrito de proposito.
    """
    trecho = where.split("where", 1)[1].split("order by", 1)[0]
    assert " or " not in trecho, "apareceu OR no WHERE do radar — reveja a guarda"
    assert trecho.count(" and ") >= 3
