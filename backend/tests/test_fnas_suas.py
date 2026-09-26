"""FNAS (painel do MDS): o coletor `ingestion/fnas_suas.py` e a conta da tela
`services/fnas.py`, contra células REAIS do engine Qlik (26/09/2026, Monte Sião e
Nova Palma) em `fixtures/fnas_suas/`."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from ingestion import fnas_suas as f
from services.fnas import montar, ym_menos

FIX = Path(__file__).parent / "fixtures" / "fnas_suas"


def _regs(nome: str) -> list[dict]:
    d = json.loads((FIX / nome).read_text(encoding="utf-8"))
    dims, meds, reg = f.REG[d["app"]]
    assert d["campos"][: len(dims)] == [c for c, _ in dims], "fixture de outra versão das dimensões"
    return [r for r in (reg(f.linha(row, dims, meds)) for row in d["matriz"]) if r]


# --- células e linhas --------------------------------------------------------
def test_saldo_de_monte_siao_em_agosto_bate_com_o_painel():
    regs = _regs("saldo_314340_2026.json")
    ago = [r for r in regs if r["ano_mes"] == 202608]
    assert sum(r["vl_total"] for r in ago) == Decimal("890947.46")
    # Armadilha 7: uma linha por (conta, mês).
    assert all(r["n"] == 1 for r in regs)
    assert len({(r["ano_mes"], r["agencia"], r["conta"]) for r in regs}) == len(regs)
    c = next(r for r in ago if r["conta"] == "207969")
    assert c["agencia"] == "2791X" and c["bloco"] == "PROGRAMAS"
    assert c["vl_total"] == Decimal("207413.17")
    assert c["monitorado"] is True


def test_repasses_de_monte_siao_em_2026():
    regs = _regs("repasse_314340_2026.json")
    assert sum(r["valor"] for r in regs) == Decimal("345324.61")
    assert len({r["processo_entidade"] for r in regs}) == len(regs)
    ob = next(r for r in regs if r["ob"] == "9703")
    assert ob["dt_ob"] == date(2026, 8, 28) and ob["mes"] == 8
    assert ob["conta"] == "189820"              # "000000189820" sem os zeros
    assert ob["piso"] == "COMPONENTE - SCFV"


def test_conta_da_ob_casa_com_a_conta_do_saldo_mesmo_com_zeros_diferentes():
    """Armadilha 4: as OBs de 09/2026 vêm com 4 zeros, as de antes com 6."""
    regs = _regs("repasse_314340_2026.json")
    contas_saldo = {r["conta"] for r in _regs("saldo_314340_2026.json")}
    setembro = [r for r in regs if r["mes"] == 9]
    assert setembro and all(r["conta"] in contas_saldo for r in setembro)


def test_emendas_trazem_parlamentar_e_a_conta():
    regs = _regs("emenda_314340_431310.json")
    ms = [r for r in regs if r["ibge"] == "314340"]
    assert len(ms) == 10
    abramo = next(r for r in ms if r["parlamentar"].startswith("GILBERTO"))
    assert abramo["conta"] == "207969" and abramo["valor"] == Decimal("150000")
    assert abramo["gnd"] == "3"


def test_nulo_do_qlik_vira_none_e_numero_nan_nao_quebra():
    assert f.txt({"qText": "-", "qNum": "NaN"}) is None
    assert f.txt({"qText": "x", "qIsNull": True}) is None
    assert f.num({"qText": "1,234.50", "qNum": "NaN"}) == Decimal("1234.50")
    assert f.num({"qText": "", "qNum": float("nan")}) == Decimal("0")


@pytest.mark.parametrize("cru,limpo", [("000000197475", "197475"), ("0000197475", "197475"),
                                       ("02791X", "2791X"), ("19834X", "19834X"),
                                       ("0000", "0"), (None, None), ("", None)])
def test_sem_zeros(cru, limpo):
    assert f.sem_zeros(cru) == limpo


def test_datas():
    assert f.data_qlik("2026-08-28 03:00:00.000000") == date(2026, 8, 28)
    assert f.data_qlik("-") is None
    assert f.dh_carga("9/25/2026 9:47:56 AM") == datetime(2026, 9, 25, 9, 47, 56)
    assert f.dh_carga("9/25/2026 11:30:18 PM") == datetime(2026, 9, 25, 23, 30, 18)


# --- o filtro ---------------------------------------------------------------
def test_filtro_de_ano_e_lista_nunca_busca():
    """Armadilha 5: `{">=2025"}` devolve zero linhas em silêncio."""
    s = f.set_expr(["431310", "314340"], "NU_ANO_SALDO", 2025)
    assert ">=" not in s
    assert "CO_IBGE={314340,431310}" in s
    assert "CO_ESFERA_ADMINISTRATIVA={'MUNICIPAL'}" in s
    assert "NU_ANO_SALDO={2025,2026" in s
    assert "NU_ANO" not in f.set_expr(["314340"])


def test_so_a_chave_suprime_nulo():
    """Armadilha 3: dimensão nula suprimida some com a linha."""
    for app in ("saldo", "repasse", "emenda"):
        dims, meds, _ = f.REG[app]
        d = f.cubo_def(dims, meds, "{<CO_IBGE={1}>}")["qHyperCubeDef"]
        assert [x["qNullSuppression"] for x in d["qDimensions"]] == [True] + [False] * (len(dims) - 1)
        assert all("{<CO_IBGE={1}>}" in m["qDef"]["qDef"] for m in d["qMeasures"])
        # O Count segura a conta zerada no cubo (armadilha 7).
        assert any(m["qDef"]["qDef"].startswith("Count(") for m in d["qMeasures"])


def test_municipio_nao_pedido_derruba_a_rodada():
    regs = _regs("emenda_314340_431310.json")
    with pytest.raises(f.FiltroIgnorado):
        f.confere(regs, {"314340"}, "emenda")
    por = f.confere(regs, {"314340", "431310", "431690"}, "emenda")
    assert len(por["431690"]) == 0 and len(por["314340"]) == 10


def test_teto_por_municipio():
    regs = [{"ibge": "314340"}] * (f.TETO_POR_MUNICIPIO["emenda"] + 1)
    with pytest.raises(f.FiltroIgnorado):
        f.confere(regs, {"314340"}, "emenda")


# --- gravação ---------------------------------------------------------------
class _Cur:
    def __init__(self):
        self.sql: list[str] = []

    def execute(self, sql, params=None):
        self.sql.append(sql)


def test_janela_vazia_nao_apaga_nada():
    cur = _Cur()
    n, recusa = f.grava(cur, "saldo", f.Alvo(1, "Monte Sião", "314340"), [], 2025, None)
    assert n == 0 and recusa and "nenhuma linha" in recusa
    assert not any("DELETE" in s for s in cur.sql)


def test_janela_apaga_so_do_ano_para_ca(monkeypatch):
    import psycopg2.extras
    monkeypatch.setattr(psycopg2.extras, "execute_values", lambda *a, **k: None)
    cur = _Cur()
    regs = _regs("repasse_314340_2026.json")
    f.grava(cur, "repasse", f.Alvo(1, "Monte Sião", "314340"), regs, 2025, None)
    assert "ano >= %s" in cur.sql[0]
    cur = _Cur()
    f.grava(cur, "saldo", f.Alvo(1, "Monte Sião", "314340"), _regs("saldo_314340_2026.json"),
            2025, None)
    assert "ano_mes >= %s" in cur.sql[0]


def test_migrations_registradas():
    from services.startup import MIGRATION_FILES
    i = MIGRATION_FILES.index("add_fnas_suas.sql")
    assert i < MIGRATION_FILES.index("add_auditoria_imutavel.sql")
    assert MIGRATION_FILES.index("add_tela_fnas.sql") < MIGRATION_FILES.index("add_auditoria_imutavel.sql")
    sql = (Path(__file__).parents[1] / "migrations" / "add_fnas_suas.sql").read_text(encoding="utf-8")
    for t in ("fnas_saldo_conta", "fnas_repasse", "fnas_emenda", "fnas_carga"):
        assert f"CREATE TABLE IF NOT EXISTS {t}" in sql
    for app, cols in f.COLS.items():
        bloco = sql.split(f"CREATE TABLE IF NOT EXISTS {f.TABELA[app]}")[1].split(");")[0]
        for c in cols:
            assert f"\n    {c} " in bloco, f"{f.TABELA[app]} sem a coluna {c}"


# --- a conta da tela --------------------------------------------------------
def _saldo(ym, conta, total, bloco="PROGRAMAS"):
    t = Decimal(str(total))
    return {"ano_mes": ym, "cnpj": "1", "tipo_entidade": "FUNDO MUNICIPAL", "agencia": "2791X",
            "conta": conta, "bloco": bloco, "tipo_conta": conta, "vl_conta_corrente": Decimal("0"),
            "vl_poupanca": Decimal("0"), "vl_fundos": t, "vl_cdb_rdb": Decimal("0"), "vl_total": t}


def _rep(ano, mes, conta, valor):
    return {"ano": ano, "mes": mes, "bloco": "Bloco da Proteção Social Básica", "piso": "SCFV",
            "programa": "SCFV", "ob": "1", "dt_ob": date(ano, mes, 28), "conta": conta,
            "valor": Decimal(str(valor))}


def test_parado_e_so_juros_sem_repasse():
    saldos = [_saldo(202508, "207969", 190000), _saldo(202608, "207969", 207413.17),
              _saldo(202508, "189820", 300000, "BL PSB FNAS"),
              _saldo(202608, "189820", 240105, "BL PSB FNAS"),
              _saldo(202508, "999", 50000), _saldo(202608, "999", 20000)]
    reps = [_rep(2026, m, "189820", 13000) for m in range(1, 9)] + \
           [_rep(2025, m, "189820", 13000) for m in range(9, 13)]
    emendas = [{"parlamentar": "GILBERTO", "partido": "REPUB", "tipo_emenda": "Emendas individuais",
                "programa": "SIGTV", "ano": 2020, "valor": Decimal("150000"),
                "dt_ob": date(2021, 12, 15), "ob": "808502", "conta": "207969"}]
    r = montar(saldos=saldos, repasses=reps, ultimos={"189820": date(2026, 8, 28)}, emendas=emendas)
    assert r["mes_referencia"] == "2026-08"
    por = {c["conta"]: c for c in r["contas"]}
    assert por["207969"]["parado"] is True                       # só rendeu
    assert por["207969"]["emendas"][0]["parlamentar"] == "GILBERTO"
    assert por["189820"]["parado"] is False                      # recebe todo mês
    assert por["189820"]["meses_de_repasse"] == round(240105 / 13000, 1)
    assert por["999"]["parado"] is False                         # caiu: foi gasto
    assert r["contas"][0]["conta"] == "207969"                   # parado primeiro
    assert r["totais"]["contas_paradas"] == 1
    assert r["totais"]["saldo_parado"] == 207413.17
    assert r["totais"]["repassado_12m"] == 12 * 13000
    assert r["totais"]["saldo_12m_antes"] == 540000.0
    assert r["emendas"][0]["saldo_conta_hoje"] == 207413.17


def test_sem_o_ano_anterior_parado_e_none_nunca_false():
    r = montar(saldos=[_saldo(202608, "207969", 207413.17)], repasses=[], ultimos={}, emendas=[])
    assert r["contas"][0]["parado"] is None
    assert r["totais"]["saldo_12m_antes"] is None


def test_com_o_dado_real_de_monte_siao():
    saldos = _regs("saldo_314340_2026.json")
    reps = _regs("repasse_314340_2026.json")
    r = montar(saldos=saldos, repasses=reps, ultimos={}, emendas=[])
    assert r["mes_referencia"] == "2026-08"
    assert r["totais"]["saldo"] == 890947.46
    # 12 meses de competência até 08/2026, só 2026 na fixture: jan-ago.
    assert r["totais"]["repassado_12m"] == float(sum(x["valor"] for x in reps if x["mes"] <= 8))


def test_ym_menos():
    assert ym_menos(202608, 12) == 202508
    assert ym_menos(202601, 1) == 202512
    assert ym_menos(202608, 11) == 202509
