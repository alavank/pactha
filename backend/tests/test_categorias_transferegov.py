"""As quatro telas de propostas do TransfereGov, provadas com SQL DE VERDADE.

⚠️ POR QUE SQLITE. Não existe Postgres de teste em lugar nenhum deste repo, e um
teste que só afirma `"rejeitad" in _VIVA_SQL` prova que a string tem a palavra —
não que a linha certa entra na tela certa. Aqui o predicado REAL do router é
executado contra linhas reais, num sqlite em memória.

A única adaptação é `ILIKE` -> `LIKE`: o sqlite não tem `ILIKE`, e o `LIKE` dele
já é case-insensitive para ASCII, que é tudo que estes padrões usam
(`%rejeitad%`, `%anulad%`, `%presta%`, `%conclu%`, `%aprovad%`, `%an%lise%`).
A substituição é textual e está no `_sqlite`, à vista — se um padrão passar a
depender de acento, o teste deixa de valer e é aqui que se lê isso.
"""
import re
import sqlite3

import pytest

from routers.transferegov import (
    _ENCERRADA_SQL, _REJEITADA_SQL, _VIVA_SQL, _VOLUNTARIA_SQL,
)
from services.fases_voluntaria import FASE_SQL, fase_de

# O ramo `geral` do router («Em execução»), escrito uma vez só aqui.
GERAL = (f"(situacao IS NULL OR (NOT {_VOLUNTARIA_SQL} "
         f"AND NOT {_REJEITADA_SQL} AND NOT {_ENCERRADA_SQL}))")

# Situações reais do SICONV, uma por linha, com o que cada uma É.
SITUACOES = [
    "Proposta/Plano de Trabalho enviado para Análise",
    "Proposta/Plano de Trabalho em Análise",
    "Proposta/Plano de Trabalho em Complementação",
    "Proposta Aprovada e Plano de Trabalho Complementado em Análise",
    "Em execução",
    "Convênio/Contrato de Repasse em execução",
    "Assinado",
    "Rejeitados",
    "Rejeitados por Impedimento Técnico",
    # ⚠️ Sem "rejeitad" e sem "plano de trabalho": até 19/09/2026 caía no ELSE e
    # aparecia em «Em execução» como convênio vivo (1 na Freitas, 2026).
    "Eliminada em Análise Preliminar",
    "Anulado",
    "Rescindido",
    "Prestação de Contas Concluída",
    "Prestação de Contas Aprovada com Ressalvas",
    # ⚠️ A PEGADINHA: tem "presta" e tem "análise", mas NÃO tem conclu/aprovad —
    # então não é encerrada. É prestação de contas ainda EM CURSO.
    "Prestação de Contas enviada para Análise",
    None,
]


def _sqlite(frag: str) -> str:
    """O predicado do router, executável no sqlite. Só troca ILIKE por LIKE."""
    return re.sub(r"\bILIKE\b", "LIKE", frag)


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE p (situacao TEXT)")
    c.executemany("INSERT INTO p VALUES (?)", [(s,) for s in SITUACOES])
    yield c
    c.close()


def _quais(con, frag: str, **params) -> set:
    sql = f"SELECT situacao FROM p WHERE {_sqlite(frag)}"
    for k, v in params.items():
        sql = sql.replace(f":{k}", "'" + str(v).replace("'", "''") + "'")
    return {r[0] for r in con.execute(sql).fetchall()}


# --------------------------------------------------------------- Voluntárias --
def test_voluntarias_agora_inclui_as_EM_EXECUCAO():
    """O pedido literal do dono. Antes de 08/2026 a tela parava na celebração."""
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE p (situacao TEXT)")
    con.executemany("INSERT INTO p VALUES (?)", [(s,) for s in SITUACOES])
    vivas = _quais(con, _VIVA_SQL)
    assert "Em execução" in vivas
    assert "Convênio/Contrato de Repasse em execução" in vivas


def test_voluntarias_continua_com_o_pipeline_de_analise(con):
    vivas = _quais(con, _VIVA_SQL)
    for s in SITUACOES[:4]:
        assert s in vivas, s


def test_voluntarias_NAO_traz_rejeitada_nem_encerrada(con):
    """Rejeitada e encerrada são DESFECHO, não trabalho em curso — e cada uma tem
    aba própria. Trazê-las faria a tela duplicar duas outras."""
    vivas = _quais(con, _VIVA_SQL)
    for s in ("Rejeitados", "Rejeitados por Impedimento Técnico",
              "Eliminada em Análise Preliminar", "Anulado", "Rescindido",
              "Prestação de Contas Concluída",
              "Prestação de Contas Aprovada com Ressalvas"):
        assert s not in vivas, s


def test_situacao_NULA_e_viva(con):
    """Ausência de informação não é encerramento. Sumir com a linha seria afirmar
    um desfecho que ninguém viu."""
    assert None in _quais(con, _VIVA_SQL)


def test_prestacao_de_contas_EM_CURSO_continua_viva(con):
    """Tem "presta" e tem "análise", mas não tem conclu/aprovad: o instrumento
    ainda está em andamento. É a linha que um `ILIKE '%presta%'` solto mataria."""
    assert "Prestação de Contas enviada para Análise" in _quais(con, _VIVA_SQL)


# ------------------------------------------------------------ as outras telas --
def test_encerradas_pega_so_o_que_acabou(con):
    assert _quais(con, _ENCERRADA_SQL) == {
        "Anulado", "Rescindido",
        "Prestação de Contas Concluída",
        "Prestação de Contas Aprovada com Ressalvas",
    }


def test_rejeitadas_pega_as_tres_formas(con):
    assert _quais(con, _REJEITADA_SQL) == {
        "Rejeitados", "Rejeitados por Impedimento Técnico",
        "Eliminada em Análise Preliminar",
    }


def test_em_execucao_NAO_ganhou_o_pipeline_de_analise(con):
    """⚠️ O teste que impede as duas telas de virarem a mesma. Se alguém trocar o
    `_VOLUNTARIA_SQL` do ramo `geral` por `_VIVA_SQL`, «Em execução» passa a
    mostrar proposta que nunca foi celebrada — e este teste cai."""
    em_exec = _quais(con, GERAL)
    assert "Em execução" in em_exec
    assert "Eliminada em Análise Preliminar" not in em_exec
    for s in SITUACOES[:4]:
        assert s not in em_exec, s


def test_as_duas_telas_se_SOBREPOEM_e_isso_e_intencional(con):
    """«Em execução» virou um SUBCONJUNTO de «Voluntárias». Nenhuma proposta some
    de aba nenhuma por causa disso — são perguntas diferentes sobre o mesmo dado."""
    assert _quais(con, GERAL) <= _quais(con, _VIVA_SQL)


def test_nenhuma_situacao_fica_sem_tela(con):
    """Toda linha da base tem de caber em ALGUMA das telas — senão existe dado
    que o sistema coleta e nunca mostra."""
    cobertas = (_quais(con, _VIVA_SQL)
                | _quais(con, GERAL)
                | _quais(con, _ENCERRADA_SQL)
                | _quais(con, _REJEITADA_SQL))
    assert cobertas == set(SITUACOES)


def test_o_ramo_geral_do_router_e_o_deste_teste():
    """O `GERAL` acima só prova algo se for o que o router executa."""
    from pathlib import Path
    fonte = (Path(__file__).resolve().parents[1] / "routers" / "transferegov.py").read_text(
        encoding="utf-8")
    assert ('f"(situacao IS NULL OR (NOT {_VOLUNTARIA_SQL} AND NOT {_REJEITADA_SQL} '
            'AND NOT {_ENCERRADA_SQL}))"') in fonte


# ------------------------------------------------------- a fase do Painel ------
def test_a_fase_do_painel_no_sql_e_a_mesma_do_python(con):
    """`FASE_SQL` soma o Painel; `fase_de` conta a sobreposição no Consolidado.
    Executados sobre as MESMAS linhas, têm de dar a mesma resposta."""
    sql = f"SELECT situacao, {_sqlite(FASE_SQL)} FROM p"
    for situacao, fase in con.execute(sql).fetchall():
        assert fase_de(situacao) == fase, situacao


def test_celebrada_e_em_execucao_mais_encerradas(con):
    """A fase `celebrada` = as telas «Em execução» + «Encerradas», e nada mais."""
    celebradas = {s for s, f in con.execute(f"SELECT situacao, {_sqlite(FASE_SQL)} FROM p")
                  if f == "celebrada"}
    assert celebradas == _quais(con, GERAL) | _quais(con, _ENCERRADA_SQL)
