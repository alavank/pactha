"""A Emenda Pix deixa de sair só "CIENTE" no Consolidado e na aba Federais
(24/09/2026) — achado (b) da revisão do 97e4903.

CIENTE é a situação do PLANO (cadastro), não do dinheiro. As duas telas têm UMA
coluna de situação e mostravam só ela; agora mostram "CIENTE · Pago em parte",
com a execução da MESMA leitura do RM e da tela Parlamentares
(`services/execucao_te.py`).

E, de carona, a gramática real do Postgres (pglast, sem banco) sobre TODO SQL que
`detalhe_core` manda — erro de SQL nos blocos com `try` não levanta: a seção some
calada.
"""
import asyncio
import re

import pytest

import routers.emendas_parlamentares as EP
import routers.parlamentares as P
from ingestion.transferegov_te import pagamentos_da_arvore
from routers.consolidado import lancamentos
from tests.test_detalhe_core_ordem import _DbNaOrdemDoSelect, _valores
from tests.test_te_arvore import PLANO_91573, _arvore


# ---------------------------------------------------------------------------
# Consolidado
# ---------------------------------------------------------------------------
def test_consolidado_mostra_a_execucao_ao_lado_do_ciente():
    det = {"plano_acao": [{"municipio_id": 2, "municipio_nome": "Araújos",
                           "codigo": "09032026-091573", "situacao": "CIENTE",
                           "execucao": "Pago em parte", "valor_total": 398000.0}]}
    (l,) = lancamentos(det)
    assert l["situacao"] == "CIENTE · Pago em parte"


def test_consolidado_nao_mexe_na_situacao_das_outras_fontes():
    det = {"voluntarias": [{"municipio_id": 2, "numero_proposta": "1/2025",
                            "situacao": "Em execução", "execucao": "Pago",
                            "valor_global": 1.0}]}
    (l,) = lancamentos(det)
    assert l["situacao"] == "Em execução"


def test_consolidado_de_ponta_a_ponta_pelo_detalhe_real():
    """Do SELECT ao Consolidado: o plano 91573 da captura real."""
    det = asyncio.run(P.detalhe_core(_DbNaOrdemDoSelect(_valores()), "LUIS TIBE", [2], None))
    te = [l for l in lancamentos(det) if l["fonte"].startswith("Emenda Pix")]
    assert [l["situacao"] for l in te] == ["CIENTE · Pago em parte"]


# ---------------------------------------------------------------------------
# Aba Federais (`_fontes_federais`)
# ---------------------------------------------------------------------------
class _Map:
    def __init__(self, linhas):
        self._l = linhas

    def mappings(self):
        return self

    def all(self):
        return self._l


class _DbFederais:
    def __init__(self, te):
        self.te, self.sqls = te, []

    async def execute(self, sql, params=None):
        self.sqls.append(str(sql))
        return _Map([dict(r) for r in self.te] if "FROM transferegov_te" in str(sql) else [])

    async def rollback(self):
        pass


@pytest.fixture
def sem_carteira(monkeypatch):
    async def _carteira(db, municipio_id):
        return {}
    monkeypatch.setattr(EP, "buscar_carteira", _carteira)


def test_aba_federais_mostra_a_execucao_ao_lado_do_ciente(sem_carteira):
    arv = _arvore(PLANO_91573)
    te = [{"plano_acao_id": 91573, "emenda": "202627620003-LUIS TIBÉ",
           "parlamentar": "LUIS TIBÉ", "objeto": "Pavimentação", "situacao": "CIENTE",
           "valor_total": 398000.0, "pagamentos": pagamentos_da_arvore(arv, 398000.0),
           "empenhos": arv["empenhos"], "detalhe_coletado": True}]
    db = _DbFederais(te)
    f = asyncio.run(EP._fontes_federais(db, 2))
    (t,) = f["te"]
    assert t["situacao"] == "CIENTE · Pago em parte"
    # As colunas cruas do dinheiro não vazam para a resposta da tela.
    assert not {"pagamentos", "empenhos", "detalhe_coletado"} & set(t)


def test_aba_federais_sem_execucao_consultada_diz_isso(sem_carteira):
    te = [{"plano_acao_id": 1, "emenda": "202611110001-X", "parlamentar": "X",
           "situacao": "CIENTE", "valor_total": 10.0, "pagamentos": None,
           "empenhos": None, "detalhe_coletado": False}]
    (t,) = asyncio.run(EP._fontes_federais(_DbFederais(te), 2))["te"]
    assert t["situacao"] == "CIENTE · Execução não consultada"


# ---------------------------------------------------------------------------
# Gramática real do Postgres sobre o SQL que sai de verdade
# ---------------------------------------------------------------------------
def _parse(sql: str):
    pglast = pytest.importorskip("pglast")
    n = iter(range(1, 99))
    pglast.parse_sql(re.sub(r"(?<!:):(\w+)", lambda _m: f"${next(n)}", sql))


def test_todo_sql_do_detalhe_core_e_valido():
    db = _DbNaOrdemDoSelect(_valores())
    sqls = []
    execute = db.execute

    async def _grava(sql, params=None):
        sqls.append(str(sql))
        return await execute(sql, params)

    db.execute = _grava
    # Com anos: entram os recortes de ano de cada fonte.
    asyncio.run(P.detalhe_core(db, "LUIS TIBE", [2], [2024, 2025]))
    assert len(sqls) == 7
    for s in sqls:
        _parse(s)


def test_o_sql_da_te_na_aba_federais_e_valido(sem_carteira):
    db = _DbFederais([])
    asyncio.run(EP._fontes_federais(db, 2))
    (sql,) = [s for s in db.sqls if "FROM transferegov_te" in s]
    assert "te.pagamentos" in sql and "(te.detalhe IS NOT NULL) AS detalhe_coletado" in sql
    _parse(sql)
