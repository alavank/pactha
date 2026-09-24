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
from datetime import date
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
    pglast.parse_sql(f"SELECT {F.FASE_SQL} AS fase, {F.RESUMO_SQL} FROM transferegov_propostas")


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


HOJE = date(2026, 9, 19)


def test_voluntarias_por_fase_soma_e_separa_os_prazos():
    # a última coluna é `INSTRUMENTO_VIGENTE_SQL` (vence?), calculada no banco
    db = _Db([("celebrada", "31/12/2026", 1_000.0, None, None, True),
              ("celebrada", None, "500.5", None, None, True),
              ("celebrada", "30/11/2026", 700.0, None, None, False),   # cancelada/encerrada
              ("analise", "15/10/2026", 45_300_000.0, "22/07/2026 11:11:41", "PROPOSTA_ENVIADA_ANALISE", False),
              ("analise", None, 305_000.0, "15/03/2009 10:00:00", "PROPOSTA_ENVIADA_ANALISE", False),
              ("rejeitada", "01/01/2020", 9_999.0, None, None, False)])
    fases, vig = asyncio.run(F.voluntarias_por_fase(db, [14], [2026], hoje=HOJE))
    assert fases["celebrada"] == {"n": 3, "valor": 2_200.5}
    assert fases["analise"] == {"n": 1, "valor": 45_300_000.0}
    assert fases["parada"] == {"n": 1, "valor": 305_000.0}
    assert fases["rejeitada"]["n"] == 1
    # só instrumento que pode vencer entra nos prazos dos cards — proposta em
    # análise, rejeitada ou cancelada não (23/09/2026, relato da Freitas)
    assert vig == ["31/12/2026", None]
    assert "municipal IS NOT FALSE" in db.sql and db.params["anos_txt"] == ["2026"]
    assert "arvore->'_resumo'->>'situacao_desde'" in db.sql
    assert F.INSTRUMENTO_VIGENTE_SQL in db.sql, "os cards e a lista têm de usar o MESMO recorte"


def test_o_recorte_do_instrumento_que_vence_e_SQL_valido_e_tira_cancelado():
    pglast = pytest.importorskip("pglast")
    pglast.parse_sql(f"SELECT 1 FROM transferegov_propostas WHERE {F.INSTRUMENTO_VIGENTE_SQL}")
    assert "cancelad" in F.INSTRUMENTO_VIGENTE_SQL and "'geral'" in F.INSTRUMENTO_VIGENTE_SQL


@pytest.mark.parametrize("fase,desde,hist,esperado", [
    # o corte do dono: MAIS de 2 anos sem mudar de situação
    ("analise", "19/09/2024 09:00:00", "PROPOSTA_ENVIADA_ANALISE", "analise"),   # 730 dias
    ("analise", "18/09/2024 09:00:00", "PROPOSTA_ENVIADA_ANALISE", "parada"),    # 731
    ("analise", "30/06/2023 21:53:26", "PROPOSTA_ENVIADA_ANALISE", "parada"),
    ("analise", "2023-06-30", "PROPOSTA_EM_ANALISE", "parada"),                 # ISO também
    # sem histórico coletado: não se afirma abandono
    ("analise", None, None, "analise"),
    ("analise", "", None, "analise"),
    # o histórico diz reprovada e a foto da proposta nunca foi refeita
    ("analise", "18/01/2012 09:43:52", "PROPOSTA_REPROVADA", "rejeitada"),
    ("analise", "01/09/2026 09:00:00", "PLANO_TRABALHO_REJEITADO", "rejeitada"),
    # celebrada e rejeitada não se mexem, por mais velho que seja o histórico
    ("celebrada", "01/01/2009 00:00:00", "EM_EXECUCAO", "celebrada"),
    ("celebrada", "01/01/2009 00:00:00", "PROPOSTA_REPROVADA", "celebrada"),
    ("rejeitada", "01/01/2009 00:00:00", None, "rejeitada"),
])
def test_refinar_com_o_historico(fase, desde, hist, esperado):
    assert F.refinar(fase, desde, hist, HOJE) == esperado


def test_parada_nao_aparece_em_tela():
    """"2 anos atrás, mais que isso não precisa" (dono, 19/09/2026): nenhuma tela
    nem a planilha leem a fase `parada`."""
    raiz = BACKEND.parent / "frontend" / "src"
    for arq in list(raiz.rglob("*.tsx")) + list(raiz.rglob("*.ts")):
        assert "parada\"]" not in arq.read_text(encoding="utf-8"), arq
    fonte = (BACKEND / "services" / "consolidado_relatorios.py").read_text(encoding="utf-8")
    assert '"parada"' not in fonte
