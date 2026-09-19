"""Voluntárias POR FASE no Painel e no Consolidado (19/09/2026).

O valor de voluntárias somava a proposta em QUALQUER fase — o pedido em análise,
o convênio assinado e o rejeitado. Na Freitas (2026), das 162 propostas, 102
estavam "enviada para análise"; Conceição do Pará mostrava R$ 45,3 mi que eram
seis pedidos de asfalto. O que se prova aqui:
- a fase de cada situação REAL (as de 2026 na Freitas, mais as de desfecho);
- "Eliminada em Análise Preliminar" é rejeitada (caía em «Em execução»);
- o espelho em Python (`fase_de`) usa os MESMOS padrões do SQL;
- Painel (`summary_core`) e BI (`bi_kpis`) somam pela MESMA função;
- rejeitada não entra nos alertas de prazo.

Rodar: python -m pytest backend/tests/test_fases_voluntaria.py -q
"""
import asyncio
import re
from pathlib import Path

import pytest

from services import fases_voluntaria as F

BACKEND = Path(__file__).resolve().parents[1]

# Situações medidas na Freitas (2026, 19/09) + as de desfecho das telas.
SITUACOES = {
    "Proposta/Plano de Trabalho enviado para Análise": "analise",
    "Proposta/Plano de Trabalho enviado para An�lise": "analise",  # acento corrompido
    "Proposta/Plano de Trabalho complementado em Análise": "analise",
    "Proposta/Plano de Trabalho em Análise": "analise",
    "Proposta/Plano de Trabalho complementado enviada para Análise": "analise",
    "Proposta/Plano de Trabalho em Complementação": "analise",
    "Proposta/Plano de Trabalho Aprovados": "analise",
    "Proposta Aprovada e Plano de Trabalho Complementado em Análise": "analise",
    "Proposta Aprovada e Plano de Trabalho em Complementação": "analise",
    "Proposta Aprovada e Plano de Trabalho em Análise": "analise",
    "Proposta/Plano de Trabalho Rejeitados por Impedimento técnico": "rejeitada",
    "Proposta/Plano de Trabalho Rejeitados": "rejeitada",
    "Eliminada em Análise Preliminar": "rejeitada",
    "Em execução": "celebrada",
    "Assinado": "celebrada",
    "Prestação de Contas enviada para Análise": "celebrada",
    "Prestação de Contas em Análise": "celebrada",
    "Prestação de Contas Aprovada": "celebrada",
    "Prestação de Contas Concluída": "celebrada",
    "Convênio Anulado": "celebrada",
    "Convênio Rescindido": "celebrada",
    None: "celebrada",  # a tela «Em execução» mostra a sem situação
}


@pytest.mark.parametrize("situacao,fase", SITUACOES.items())
def test_fase_de_cada_situacao_real(situacao, fase):
    assert F.fase_de(situacao) == fase


def _padroes(sql: str) -> set[str]:
    return set(re.findall(r"'(%[^']*%)'", sql))


def test_o_espelho_em_python_usa_os_padroes_do_sql():
    """Se alguém mudar um padrão no SQL e esquecer o `fase_de`, o Consolidado
    passa a contar sobreposição com uma regra e somar com outra."""
    fonte = Path(F.__file__).read_text(encoding="utf-8")
    corpo = fonte[fonte.index("def fase_de"):]
    no_python = set(re.findall(r'"(%[^"]*%)"', corpo))
    assert no_python == _padroes(F.VOLUNTARIA_SQL) | _padroes(F.REJEITADA_SQL)


def test_eliminada_e_rejeitada_nas_telas_tambem():
    """Caía no ELSE do `CATEGORIA_SQL` e aparecia em «Em execução»."""
    assert "eliminad" in F.REJEITADA_SQL
    assert F.REJEITADA_SQL in F.CATEGORIA_SQL and F.REJEITADA_SQL in F.VIVA_SQL
    fonte = (BACKEND / "routers" / "transferegov.py").read_text(encoding="utf-8")
    assert "_REJEITADA_LIKE" not in fonte and "rejpat" not in fonte


def test_sql_das_fases_e_valido():
    pglast = pytest.importorskip("pglast")
    for sql in (F.FASE_SQL, F.CATEGORIA_SQL):
        pglast.parse_sql(f"SELECT {sql} FROM transferegov_propostas")
    pglast.parse_sql(f"SELECT 1 FROM transferegov_propostas WHERE {F.VIVA_SQL}")


def test_painel_e_bi_somam_pela_mesma_funcao():
    """Eram duas cópias da consulta (`summary_core` e `bi_kpis`); com a fase, a
    terceira divergência seria questão de tempo."""
    for arq, fn in (("routers/municipios.py", "async def summary_core"),
                    ("services/bi.py", "async def bi_kpis")):
        fonte = (BACKEND / arq).read_text(encoding="utf-8")
        corpo = fonte[fonte.index(fn):]
        fim = corpo.find("\nasync def ", 1)
        corpo = corpo if fim < 0 else corpo[:fim]
        assert "voluntarias_por_fase(" in corpo, arq
        assert "FROM transferegov_propostas" not in corpo, arq
        assert '["celebrada"]["valor"]' in corpo, arq


class _Res:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Db:
    def __init__(self, rows):
        self.rows, self.sql, self.params = rows, None, None

    async def execute(self, stmt, params):
        self.sql, self.params = str(stmt), params
        return _Res(self.rows)


def test_voluntarias_por_fase_soma_e_separa_os_prazos():
    db = _Db([("celebrada", "31/12/2026", 1_000.0), ("celebrada", None, "500.5"),
              ("analise", None, 45_300_000.0), ("rejeitada", "01/01/2020", 9_999.0)])
    fases, vig = asyncio.run(F.voluntarias_por_fase(db, [14], [2026]))
    assert fases["celebrada"] == {"n": 2, "valor": 1_500.5}
    assert fases["analise"] == {"n": 1, "valor": 45_300_000.0}
    assert fases["rejeitada"]["n"] == 1
    # a rejeitada não tem convênio que vença: fora dos alertas
    assert vig == ["31/12/2026", None, None]
    assert "municipal IS NOT FALSE" in db.sql and db.params["anos_txt"] == ["2026"]
