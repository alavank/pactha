"""FEAS (cofinanciamento estadual da assistência social): o coletor
`ingestion/feas_estadual.py` e a conta da tela `services/feas.py`, contra recortes
REAIS da despesa aberta de MG (dados.mg, 2026) e do RS (dados.rs, 06/2026) em
`fixtures/feas_estadual/`."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ingestion import feas_estadual as f
from services.feas import montar

FIX = Path(__file__).parent / "fixtures" / "feas_estadual"
FMAS_MS, PREF_MS = "13474332000150", "22646525000131"
FMAS_SM, PREF_SM = "14841318000100", "88488366000100"


def _gz(nome: str) -> bytes:
    return (FIX / f"{nome}.csv.gz").read_bytes()


def _mg(alvos: dict[str, int]):
    favs, nomes = {}, {}
    for r in f._csv_gz(_gz("dm_favorecido")):
        if r["tp_documento"] == "2" and f.cnpj14(r["nr_documento_anonimizado"]) in alvos:
            favs[r["id_favorecido"]] = f.cnpj14(r["nr_documento_anonimizado"])
            nomes[r["id_favorecido"]] = r["nome_anonimizado"]
    empenho_ue = {r["id_empenho"]: r["unidade_executora"] for r in f._csv_gz(_gz("dm_empenho_desp_2026"))
                  if r["unidade_executora"].startswith(f.UE_FEAS_MG)}
    ids_op = {r["id_tipo_documento"] for r in f._csv_gz(_gz("dm_tipo_documento"))
              if f._RE_OP.match(r["nome"])}
    acoes = {r["id_acao"]: f"{r['cd_acao']} {r['nome']}" for r in f._csv_gz(_gz("dm_acao"))}
    tempo = {r["id_tempo"]: f.data_br(r["data_formatada"]) for r in f._csv_gz(_gz("dm_tempo_diario"))}
    return f.pagamentos_mg(f._csv_gz(_gz("ft_despesa_2026")), empenho_ue, favs, alvos, ids_op,
                           acoes, tempo, nomes)


# --- MG ----------------------------------------------------------------------
def test_piso_mineiro_de_monte_siao_em_2026():
    regs, n = _mg({FMAS_MS: 1, PREF_MS: 1})
    assert n > 0
    # Só o FEAS (UE 1480004): os R$ 3,3 mi de escolas e o SEINFRA à prefeitura ficam fora.
    assert {r["unidade"][:7] for r in regs} == {f.UE_FEAS_MG}
    assert all(r["favorecido_cnpj"] == FMAS_MS for r in regs)      # cai no FUNDO, não na prefeitura
    assert sum(r["valor"] for r in regs) == Decimal("68160.00")
    assert {r["acao"] for r in regs} == {"4431 PISO MINEIRO DE ASSISTENCIA SOCIAL"}
    abril = next(r for r in regs if r["data"] == date(2026, 4, 27))
    assert abril["valor"] == Decimal("25560.00") and abril["documento"] == "1111"


def test_mg_sem_o_cnpj_do_fundo_nao_acha_o_piso():
    """Armadilha 2: só com a prefeitura, o Piso Mineiro não casa."""
    regs, _ = _mg({PREF_MS: 1})
    assert regs == []


# --- RS ----------------------------------------------------------------------
def _rs(alvos):
    return f.pagamentos_rs(f.linhas_rs((FIX / "despesa_rs_202606_recorte.zip").read_bytes()), alvos)


def test_piso_gaucho_de_santa_maria_em_junho():
    regs, n = _rs({FMAS_SM: 3, PREF_SM: 3})
    assert n > 250
    assert len(regs) == 1
    r = regs[0]
    assert r["favorecido_cnpj"] == FMAS_SM and r["valor"] == Decimal("25000")
    assert r["acao"].startswith("197501022 Cofinanciamento Unificado - Piso Gaucho")
    assert r["unidade"].startswith("2178") and r["uf"] == "RS" and (r["ano"], r["mes"]) == (2026, 6)


def test_rs_so_uo_do_feas_e_so_pagamento():
    regs, _ = _rs({f.cnpj14("87.613.634/0001-06"): 9})            # Tuparendi, modalidade 40
    assert regs and all(r["unidade"].startswith("2178") for r in regs)


def test_rs_cabecalho_mudado_e_recusado(tmp_path):
    import io, zipfile
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("Gasto.csv", "Exercicio;Mes;Valor\n2026;6;1,00\n".encode("latin-1"))
    with pytest.raises(f.ArquivoRecusado):
        list(f.linhas_rs(b.getvalue()))


# --- puro --------------------------------------------------------------------
@pytest.mark.parametrize("cru,limpo", [("14.841.318/0001-00", FMAS_SM), ("13474332000150", FMAS_MS),
                                       ("394460055477", "00394460055477"), ("", "")])
def test_cnpj14(cru, limpo):
    assert f.cnpj14(cru) == limpo


def test_valor_e_data():
    assert f.valor_br("70000,00") == Decimal("70000.00")
    assert f.valor_br("1.234,56") == Decimal("1234.56")
    assert f.valor_br("8520.00") == Decimal("8520.00")
    assert f.data_br("08/06/2026") == date(2026, 6, 8)
    assert f.data_br("2026-04-27") == date(2026, 4, 27)


def test_assinatura_nao_depende_da_ordem():
    assert f.assinatura(["b", "a"]) == f.assinatura(["a", "b"])
    assert f.assinatura(["a"]) != f.assinatura(["a", "b"])


# --- gravação ----------------------------------------------------------------
class _Cur:
    def __init__(self, tem_antigo=False):
        self.sql, self.tem = [], tem_antigo

    def execute(self, sql, params=None):
        self.sql.append(sql)

    def fetchone(self):
        return (1,) if self.tem else None


def test_ano_de_mg_vazio_onde_havia_pagamento_nao_apaga(monkeypatch):
    import psycopg2.extras
    monkeypatch.setattr(psycopg2.extras, "execute_values", lambda *a, **k: None)
    cur = _Cur(tem_antigo=True)
    n, recusados = f.troca(cur, "MG", ("ano", 2026), {1}, [], "ft", vazio_e_valido=False)
    assert recusados == ["1"] and not any("DELETE" in s for s in cur.sql)


def test_mes_do_rs_vazio_e_resposta_valida(monkeypatch):
    import psycopg2.extras
    monkeypatch.setattr(psycopg2.extras, "execute_values", lambda *a, **k: None)
    cur = _Cur(tem_antigo=True)
    n, recusados = f.troca(cur, "RS", ("mes", 2026, 6), {3}, [], "z", vazio_e_valido=True)
    assert recusados == [] and any("DELETE" in s and "mes = %s" in s for s in cur.sql)


def test_migrations_registradas():
    from services.startup import MIGRATION_FILES
    fim = MIGRATION_FILES.index("add_auditoria_imutavel.sql")
    assert MIGRATION_FILES.index("add_feas_estadual.sql") < fim
    assert MIGRATION_FILES.index("add_tela_feas.sql") < fim
    sql = (Path(__file__).parents[1] / "migrations" / "add_feas_estadual.sql").read_text(encoding="utf-8")
    bloco = sql.split("CREATE TABLE IF NOT EXISTS feas_pagamento")[1].split(");")[0]
    for c in ("municipio_id", "uf", "ano", "mes", "data", "documento", "favorecido_cnpj",
              "favorecido_nome", "unidade", "acao", "modalidade", "valor", "arquivo"):
        assert f"\n    {c} " in bloco


# --- a conta da tela -----------------------------------------------------------
def _p(d, valor, acao="4431 PISO MINEIRO DE ASSISTENCIA SOCIAL", cnpj=FMAS_MS):
    return {"ano": d.year, "mes": d.month, "data": d, "documento": "1", "favorecido_cnpj": cnpj,
            "favorecido_nome": None, "acao": acao, "modalidade": None, "valor": Decimal(str(valor))}


def test_piso_mineiro_parado_ha_mais_de_60_dias_e_atraso():
    pg = [_p(date(2026, 4, 27), 25560), _p(date(2026, 6, 12), 8520)]
    r = montar(pagamentos=pg, cnpj_prefeitura=PREF_MS, uf="MG", hoje=date(2026, 9, 26))
    assert r["atrasadas"] == ["4431 PISO MINEIRO DE ASSISTENCIA SOCIAL"]
    assert r["totais"]["ano"] == 34080.0 and r["totais"]["fundo_ano"] == 34080.0
    r = montar(pagamentos=pg + [_p(date(2026, 9, 21), 8520)], cnpj_prefeitura=PREF_MS, uf="MG",
               hoje=date(2026, 9, 26))
    assert r["atrasadas"] == []


def test_mesma_acao_com_grafias_diferentes_e_uma_so():
    """Santa Maria 2025: "197501022 COFINANCIAMENTO..." e "197501022 Cofinanciamento..."."""
    pg = [_p(date(2025, 12, 30), 100, "197501022 COFINANCIAMENTO UNIFICADO - PISO GAUCHO", FMAS_SM),
          _p(date(2026, 6, 16), 25000, "197501022 Cofinanciamento Unificado - Piso Gaucho", FMAS_SM)]
    r = montar(pagamentos=pg, cnpj_prefeitura=PREF_SM, uf="RS", hoje=date(2026, 9, 26))
    assert len(r["acoes"]) == 1
    assert r["acoes"][0]["acao"] == "197501022 Cofinanciamento Unificado - Piso Gaucho"
    assert {p["acao"] for p in r["pagamentos"]} == {r["acoes"][0]["acao"]}


def test_rs_nao_tem_atraso_e_separa_fundo_de_prefeitura():
    pg = [_p(date(2026, 1, 5), 25000, "197501022 Cofinanciamento Unificado - Piso Gaucho", FMAS_SM),
          _p(date(2025, 11, 5), 70000, "807901003 Aquisicao de Veiculos", PREF_SM)]
    r = montar(pagamentos=pg, cnpj_prefeitura=PREF_SM, uf="RS", hoje=date(2026, 9, 26))
    assert r["atrasadas"] == []
    assert r["totais"]["fundo_ano"] == 25000.0 and r["totais"]["prefeitura_ano"] == 0.0
    assert r["totais"]["ano_anterior"] == 70000.0
    assert r["pagamentos"][0]["destino"] == "fundo"
