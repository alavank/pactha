"""Repasses do Fundo Estadual de Saúde do RS (`ingestion/fes_rs.py`).

O recorte em `fixtures/fes_rs_planilhas.json` é REAL (planilhas de setembro e
fevereiro/2026 baixadas em 24/09/2026 — ver o `_fonte` dele): Nova Palma, Santa
Maria, Guaíba e duas linhas de Aceguá. Os números conferidos aqui são os que o dono
mediu na fonte, e o que a tela mostra sai da mesma conta (`resumo_fes_rs`).
"""
import json
import os
from datetime import date, datetime
from decimal import Decimal

import pytest

from ingestion import fes_rs
from services.municipios_rs_codigo_estadual import CODIGO_ESTADUAL_PARA_IBGE

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "fes_rs_planilhas.json")
NOVA_PALMA = {"id": 1, "nome": "Nova Palma", "ibge": "4313102"}
SANTA_MARIA = {"id": 2, "nome": "Santa Maria", "ibge": "4316907"}
GUAIBA = {"id": 3, "nome": "Guaíba", "ibge": "4309308"}


def _grade(nome):
    with open(FIX, encoding="utf-8") as f:
        return json.load(f)[nome]


def _setembro():
    return fes_rs.ler_grade(_grade("setembro_2026"), 2026, 9)


def _regs(pl, alvos):
    cod_para_alvo, sem = fes_rs.codigos_dos_alvos(alvos)
    assert not sem
    fundos = fes_rs.fundos_por_municipio(
        [ln for ln in pl.linhas if ln["cod_municipio"] in cod_para_alvo])
    return fes_rs.registros(pl, cod_para_alvo, fundos)


def _soma(regs, mid, fundo, campo="valor_pago", **filtro):
    return sum((r[campo] for r in regs if r["municipio_id"] == mid
                and r["fundo_municipal"] is fundo
                and all(r[k] == v for k, v in filtro.items())), Decimal(0))


# ---------------------------------------------------------------------------
# A página
# ---------------------------------------------------------------------------
HTML = """
<a href="/upload/arquivos/202609/24074153-geral-pagos-em-setembro-programas-municipais-e-incentivos-2026-fesgeral.xls" download="">
<a href="/upload/arquivos/202609/24074231-geral-pagos-em-marco-programas-municipais-e-incentivos-2026-fesgeral.xls" download="">
<a href="/upload/arquivos/202609/24074244-geral-pagos-em-janeiro-programas-municipais-e-incentivos-2026-fesgeral.xls" download="">
<a href="/upload/arquivos/202602/11082111-geral-pagos-em-janeiro-programas-municipais-e-incentivos-2026-fesgeral.xls" download="">
<a href="/upload/arquivos/202601/08133300-geral-pagos-em-dezembro-programas-municipais-e-incentivos-2025-fesgeral.xls" download="">
<a href="/upload/arquivos/202609/21082015-geral-pagamentos-programas-municipais-2026-fesf.xls">
"""


def test_links_leem_o_mes_do_nome_e_o_mais_novo_vem_primeiro():
    links = fes_rs.links_da_pagina(HTML)
    assert set(links) == {(2026, 9), (2026, 3), (2026, 1), (2025, 12)}
    # Armadilha 2: janeiro aparece duas vezes; o antigo (fev) dá 404 e vai por último.
    jan = links[(2026, 1)]
    assert [pub for _, pub in jan] == [datetime(2026, 9, 24, 7, 42, 44),
                                       datetime(2026, 2, 11, 8, 21, 11)]
    assert jan[0][0].startswith("https://saude.rs.gov.br/upload/arquivos/202609/24074244-")


def test_o_arquivo_anual_incompleto_nao_entra():
    """Armadilha 9: o `-fesf.xls` anual não tem MAC nem hospitais."""
    assert all("fesf.xls" not in u for v in fes_rs.links_da_pagina(HTML).values() for u, _ in v)


# ---------------------------------------------------------------------------
# A planilha
# ---------------------------------------------------------------------------
def test_le_o_recorte_real_de_setembro():
    pl = _setembro()
    assert len(pl.linhas) == 18 + 103 + 2
    assert pl.total_pago == sum((ln["valor_pago"] for ln in pl.linhas), Decimal(0))
    # Serial do Excel -> data. (O arquivo inteiro vai até 23/09; o recorte, 22/09.)
    assert pl.pago_ate == date(2026, 9, 22)
    np_ = [ln for ln in pl.linhas if ln["cod_municipio"] == 83]
    assert len(np_) == 18
    assert {ln["data_pagamento"] for ln in np_} <= {date(2026, 9, d) for d in range(1, 24)}


def test_fevereiro_tem_uma_coluna_a_mais_e_le_igual():
    grade = _grade("fevereiro_2026")
    assert len(grade[4]) == 37                        # o arquivo real
    pl = fes_rs.ler_grade(grade, 2026, 2)
    assert pl.linhas and all(ln["cod_municipio"] == 83 for ln in pl.linhas)


def test_titulo_de_outro_mes_e_recusado():
    with pytest.raises(ValueError, match="título"):
        fes_rs.ler_grade(_grade("setembro_2026"), 2026, 8)


def test_coluna_obrigatoria_faltando_recusa_o_mes():
    grade = [list(r) for r in _grade("setembro_2026")]
    grade[4][27] = "Valor liquido"                    # renomearam "Valor pago"
    with pytest.raises(ValueError, match="Valor pago"):
        fes_rs.ler_grade(grade, 2026, 9)


def test_sem_totais_e_arquivo_cortado():
    with pytest.raises(ValueError, match="TOTAIS"):
        fes_rs.ler_grade(_grade("setembro_2026")[:-1], 2026, 9)


def test_soma_diferente_do_totais_e_recusada():
    grade = [list(r) for r in _grade("setembro_2026")]
    del grade[20]                                     # uma linha sumiu no caminho
    with pytest.raises(ValueError, match="TOTAIS"):
        fes_rs.ler_grade(grade, 2026, 9)


def test_pagina_de_erro_no_lugar_do_xls_e_recusada():
    with pytest.raises(ValueError, match="não é .xls"):
        fes_rs.ler_planilha(b"<html>Request Rejected</html>", 2026, 9)


# ---------------------------------------------------------------------------
# De-para: código estadual -> IBGE (nunca o nome)
# ---------------------------------------------------------------------------
def test_tabela_de_para_cobre_o_rs_sem_repetir():
    assert len(CODIGO_ESTADUAL_PARA_IBGE) == 497
    ibges = list(CODIGO_ESTADUAL_PARA_IBGE.values())
    assert len(set(ibges)) == len(ibges)
    assert all(str(i).startswith("43") and len(str(i)) == 7 for i in ibges)
    assert CODIGO_ESTADUAL_PARA_IBGE[83] == 4313102      # Nova Palma
    assert CODIGO_ESTADUAL_PARA_IBGE[109] == 4316907     # Santa Maria
    assert CODIGO_ESTADUAL_PARA_IBGE[96] == 4314902      # Porto Alegre


def test_casa_pelo_ibge_e_quem_nao_tem_vira_nota():
    cod, sem = fes_rs.codigos_dos_alvos([NOVA_PALMA, SANTA_MARIA,
                                         {"id": 9, "nome": "Sem IBGE", "ibge": ""}])
    assert {k: v["id"] for k, v in cod.items()} == {83: 1, 109: 2}
    assert sem == ["Sem IBGE (IBGE ?)"]


def test_o_nome_nao_casa_nada():
    """Um município com o NOME de Santa Maria e IBGE de outro lugar não leva as
    linhas de Santa Maria — a lição da Santa Maria do Herval (4316956)."""
    herval = {"id": 7, "nome": "Santa Maria", "ibge": "4316956"}
    regs = _regs(_setembro(), [herval])
    assert all(r["cod_municipio"] != 109 for r in regs)


# ---------------------------------------------------------------------------
# Fundo Municipal × hospitais e entidades
# ---------------------------------------------------------------------------
def test_o_fundo_e_o_credor_da_modalidade_41_pelo_codigo():
    pl = _setembro()
    fundos = fes_rs.fundos_por_municipio(pl.linhas)
    assert fundos[83] == "47373954"                  # FUNDO MUN DE SAUDE DE NOVA PALMA
    assert fundos[109] == "47567813"                 # FUNDO MUN DE SAUDE DE SANTA MARIA


def test_nova_palma_setembro_os_numeros_da_fonte():
    regs = _regs(_setembro(), [NOVA_PALMA])
    assert len(regs) == 18
    assert _soma(regs, 1, True, projeto="PIAPS-PROG INCENT ATENCAO") == Decimal("28673.75")
    assert _soma(regs, 1, True, projeto="COFINANCIAMENTO CAPS") == Decimal("12000")
    assert _soma(regs, 1, True, projeto="REGULACAO ASSISTENCIAL") == Decimal("9113.60")
    # O hospital local recebe DIRETO — e fica fora do fundo.
    assert _soma(regs, 1, False, projeto="ASSISTIR-INCENT HOSP") == Decimal("242460.04")
    assert _soma(regs, 1, False, projeto="ATENCAO MEDIA ALTA COMPLE") == Decimal("153512.06")
    assert _soma(regs, 1, False, projeto="COFINANCIAMENTO AMBULATOR") == Decimal("125000")
    assert {r["credor"] for r in regs if not r["fundo_municipal"]} == {
        "HOSP NOSSA SENHORA DA PIEDADE"}


def test_santa_maria_setembro_os_numeros_da_fonte():
    regs = _regs(_setembro(), [SANTA_MARIA])
    assert len(regs) == 103
    assert _soma(regs, 2, True, projeto="ATENCAO MEDIA ALTA COMPLE") == Decimal("545754.25")
    assert _soma(regs, 2, True, projeto="REDE URG E EMERG-UPAS E P") == Decimal("520000")
    assert _soma(regs, 2, True, projeto="PIAPS-PROG INCENT ATENCAO") == Decimal("366884.84")
    assert _soma(regs, 2, True, projeto="INVERNO GAUCHO ATENCAO ES") == Decimal("310500")
    hucar = sum((r["valor_pago"] for r in regs if r["cod_credor"] == "57333890"
                 and r["projeto"] == "ATENCAO MEDIA ALTA COMPLE"), Decimal(0))
    assert hucar == Decimal("2178996.04")
    casa = sum((r["valor_pago"] for r in regs if r["credor"].startswith("ASSOC FRANCISCANA")
                and r["projeto"] == "ASSISTIR-INCENT HOSP"), Decimal(0))
    assert casa == Decimal("908598.69")


def test_hospital_com_modalidade_41_nao_vira_o_fundo():
    """Guaíba: 'ASSOC HOSPL VILA NOVA' aparece com Fundo a Fundo, mas o fundo é o
    credor com mais linhas nessa modalidade — pelo código (janeiro/2026)."""
    pl = fes_rs.ler_grade(_grade("janeiro_2026"), 2026, 1)
    hosp = [ln for ln in pl.linhas if "VILA NOVA" in ln["credor"]]
    assert any(ln["cod_modalidade"] == "41" for ln in hosp)
    regs = _regs(pl, [GUAIBA])
    assert not any(r["fundo_municipal"] for r in regs if "VILA NOVA" in r["credor"])
    assert {r["credor"] for r in regs if r["fundo_municipal"]} == {"FUNDO MUN DE SAUDE DE GUAIBA"}


def test_aceguá_fora_do_tenant_nao_entra():
    regs = _regs(_setembro(), [NOVA_PALMA, SANTA_MARIA])
    assert {r["cod_municipio"] for r in regs} == {83, 109}


# ---------------------------------------------------------------------------
# Retenções
# ---------------------------------------------------------------------------
def test_tipo_de_retencao():
    assert fes_rs.tipo_retencao("0706", "REST TETO MAC CONASEMS") == "desconto"
    assert fes_rs.tipo_retencao("0455", "MULTAS AUDITORIA DO SUS") == "desconto"
    assert fes_rs.tipo_retencao("0679", "RETENCAO - RECURSO 6") == "desconto"
    assert fes_rs.tipo_retencao("0440", "ISSQN-BASE DE CALCULO-FPE") == "tributo"
    assert fes_rs.tipo_retencao("0539", "IRRF PAGTO FORNECEDORES") == "tributo"
    assert fes_rs.tipo_retencao("0594", "REGULARIZACAO PAG RESP-BLOQUEIOS JUD-SAUDE") == "judicial"
    assert fes_rs.tipo_retencao("0791", "DESC MAC - EMPRÉSTIMOS CONSIGNADOS") == "consignado"
    assert fes_rs.tipo_retencao("9999", "PENHORA JUDICIAL") == "judicial"


def test_retencao_do_fundo_e_linha_propria_com_motivo():
    regs = _regs(_setembro(), [NOVA_PALMA])
    ret = [r for r in regs if r["valor_retido"]]
    assert len(ret) == 1
    r = ret[0]
    assert r["fundo_municipal"] and r["valor_pago"] == 0
    assert r["valor_retido"] == Decimal("395.10")
    assert r["motivo_retencao"] == "REST TETO MAC CONASEMS"
    assert r["tipo_retencao"] == "desconto"
    # Linha sem retenção não guarda o código "0000".
    assert all(x["cod_retencao"] is None for x in regs if not x["valor_retido"])


def test_retencao_do_hospital_e_tributo_e_nao_entra_no_fundo():
    regs = _regs(_setembro(), [SANTA_MARIA])
    trib = [r for r in regs if r["tipo_retencao"] == "tributo"]
    assert trib and not any(r["fundo_municipal"] for r in trib)


# ---------------------------------------------------------------------------
# A conta da tela (routers/cofinanciamento.py::resumo_fes_rs)
# ---------------------------------------------------------------------------
def test_resumo_separa_o_fundo_das_entidades():
    from routers.cofinanciamento import resumo_fes_rs

    regs = _regs(_setembro(), [NOVA_PALMA])
    res = resumo_fes_rs(regs)
    f, e = res["fundo"], res["entidades"]
    assert f["credor"] == "FUNDO MUN DE SAUDE DE NOVA PALMA"
    assert f["total_pago"] == pytest.approx(53746.18)
    assert f["total_retido"] == pytest.approx(395.10)
    assert f["programas"][0]["projeto"] == "PIAPS-PROG INCENT ATENCAO"
    assert f["programas"][0]["pago"] == pytest.approx(28673.75)
    assert e["total_pago"] == pytest.approx(543605.83)
    assert [x["credor"] for x in e["itens"]] == ["HOSP NOSSA SENHORA DA PIEDADE"]
    # O total da prefeitura NUNCA inclui o hospital.
    assert f["total_pago"] + e["total_pago"] == pytest.approx(
        float(sum(r["valor_pago"] for r in regs)))
    assert res["meses"] == [{"mes": 9, "pago": pytest.approx(53746.18),
                             "retido": pytest.approx(395.10),
                             "entidades": pytest.approx(543605.83)}]
    assert f["retencoes"][0]["motivo"] == "REST TETO MAC CONASEMS"
    assert f["retido_por_motivo"] == [{"motivo": "REST TETO MAC CONASEMS", "tipo": "desconto",
                                       "valor": pytest.approx(395.10), "n": 1}]


def test_resumo_da_entidade_separa_tributo():
    from routers.cofinanciamento import resumo_fes_rs

    res = resumo_fes_rs(_regs(_setembro(), [SANTA_MARIA]))
    tipos = {t for e in res["entidades"]["itens"] for t in e["retido_por_tipo"]}
    assert "tributo" in tipos
    assert res["fundo"]["total_retido"] == pytest.approx(
        sum(r["valor"] for r in res["fundo"]["retencoes"]))


# ---------------------------------------------------------------------------
# Status da rodada e idempotência
# ---------------------------------------------------------------------------
def test_status_honesto():
    assert fes_rs.status_da_rodada(9, [], [], 0) == ("success", None)
    st, nota = fes_rs.status_da_rodada(9, ["01/2026: HTTP 404"], [], 0)
    assert st == "partial" and "404" in nota
    st, _ = fes_rs.status_da_rodada(2, ["a", "b"], [], 0)
    assert st == "error"
    st, nota = fes_rs.status_da_rodada(9, [], ["X (IBGE 4399999)"], 0)
    assert st == "partial" and "de-para" in nota
    st, nota = fes_rs.status_da_rodada(9, [], [], 30)
    assert st == "partial" and "30 dias" in nota


class _Cur:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split())[:40], params))


def test_grava_mes_apaga_o_mes_dos_municipios_antes_de_inserir(monkeypatch):
    """Armadilha 10: sem chave natural, a carga é apagar + inserir o mês inteiro
    dos municípios do tenant. Rodar duas vezes dá a mesma sequência — e o DELETE
    alcança município que ficou sem linha no mês (a fonte o tirou)."""
    import psycopg2.extras

    inseridos = []
    monkeypatch.setattr(psycopg2.extras, "execute_values",
                        lambda cur, sql, linhas, page_size=0: inseridos.append(len(linhas)))
    pl = _setembro()
    regs = _regs(pl, [NOVA_PALMA, SANTA_MARIA])
    rodadas = []
    for _ in range(2):
        cur = _Cur()
        fes_rs.grava_mes(cur, pl, regs, [1, 2, 5], "u", None, "sha", "v1|x")
        rodadas.append(cur.sql)
    assert rodadas[0] == rodadas[1]
    assert rodadas[0][0][0].startswith("DELETE FROM fes_rs_pagamentos")
    assert rodadas[0][0][1] == (2026, 9, [1, 2, 5])
    assert inseridos == [121, 121]
    assert rodadas[0][1][0].startswith("INSERT INTO fes_rs_arquivos")
