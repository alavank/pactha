"""SIOPS, SIOPE e DigiSUS (ingestion/siops_siope.py + services/saude_educacao.py).

As fixtures em `fixtures/siops_siope/` são respostas REAIS de 24/09/2026,
recortadas (a lista legada e o arquivo do DGMP tiveram o total do rodapé ajustado
ao número de linhas mantidas — é o que o parser confere).
"""
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from ingestion import siops_siope as ss
from services import saude_educacao as se
from services.bi_abas import prazos_dos_itens

FIX = Path(__file__).parent / "fixtures" / "siops_siope"


def _html(nome, enc="utf-8-sig"):
    return (FIX / nome).read_bytes().decode(enc)


def _json(nome):
    return json.loads((FIX / nome).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _sem_espera(monkeypatch):
    monkeypatch.setattr(ss.time, "sleep", lambda *_: None)
    monkeypatch.setattr(ss, "PAUSA_S", 0)


# ---------------------------------------------------------------------------
# 1. msg03 ≠ erro
# ---------------------------------------------------------------------------
MSG03 = (FIX / "siops_api_msg03.json").read_bytes()


def _cliente(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_msg03_e_resposta_e_nao_excecao():
    c = _cliente(lambda req: httpx.Response(404, content=MSG03))
    assert ss.siops_indicadores(c, "314340", 2026, 4) == ("msg03", None)


def test_404_que_nao_e_msg03_levanta():
    c = _cliente(lambda req: httpx.Response(404, json={"status": 404, "error": "Not Found"}))
    with pytest.raises(ss.FonteIndisponivel):
        ss.siops_indicadores(c, "314340", 2026, 4)


def test_500_levanta_depois_das_tentativas():
    chamadas = []

    def h(req):
        chamadas.append(1)
        return httpx.Response(500, text="erro")
    with pytest.raises(ss.FonteIndisponivel):
        ss.siops_indicadores(_cliente(h), "314340", 2026, 4)
    assert len(chamadas) == 3


def test_200_vazio_nao_e_entrega():
    c = _cliente(lambda req: httpx.Response(200, json=[]))
    with pytest.raises(ss.FonteIndisponivel):
        ss.siops_indicadores(c, "314340", 2026, 4)


def test_periodo_vai_na_url_com_o_codigo_do_siops():
    urls = []

    def h(req):
        urls.append(str(req.url))
        return httpx.Response(404, content=MSG03)
    c = _cliente(h)
    for b in range(1, 7):
        ss.siops_indicadores(c, "431310", 2026, b)
    assert [u.rsplit("/", 1)[1] for u in urls] == ["12", "14", "1", "18", "20", "2"]


class _Cur:
    def __init__(self):
        self.linhas = []

    def execute(self, sql, params=None):
        if "saude_educacao_bimestre" in sql:
            self.linhas.append(params)


def _mun(mid, nome, ibge):
    return {"id": mid, "nome": nome, "ibge": ibge, "ibge6": ibge[:6],
            "uf_cod": ibge[:2], "uf": ss.UF_SIGLA[ibge[:2]]}


LEGADO_RS_B4 = (FIX / "siops_homologados_rs_2026_b4.html").read_bytes()
API_OK = (FIX / "siops_api_314340_2026_p1.json").read_bytes()


def _roda_siops(handler, muns, hoje=date(2026, 9, 24), monkeypatch=None):
    # Só o 4º bimestre de 2026: é o caso medido.
    monkeypatch.setattr(ss, "bimestres_encerrados", lambda h: [(2026, 4)])
    cur = _Cur()
    rod = ss._Rodada(cur, dry=False)
    ss._coletar_siops(_cliente(handler), rod, {"43": muns}, {}, hoje)
    return {p["mid"]: p for p in cur.linhas}, rod


def test_lista_legada_prova_a_falta_e_a_api_so_da_o_percentual(monkeypatch):
    pedidos = []

    def h(req):
        pedidos.append(str(req.url))
        if "consmuntransm" in str(req.url):
            return httpx.Response(200, content=LEGADO_RS_B4)
        return httpx.Response(200, content=API_OK)
    np_ = _mun(1, "Nova Palma", "4313102")
    fora = _mun(2, "Santa Maria", "4316907")          # não está na lista recortada
    linhas, rod = _roda_siops(h, [np_, fora], monkeypatch=monkeypatch)
    assert linhas[1]["entregue"] is True
    assert linhas[1]["data"] == date(2026, 9, 23)      # a data vem da lista legada
    assert linhas[1]["pct"] == 24.72
    assert linhas[2]["entregue"] is False
    # A API NÃO é perguntada por quem a lista já provou que não homologou.
    assert not any("/431690/" in u for u in pedidos)
    assert rod.falhas == []


def test_msg03_sem_lista_legada_nao_grava_nao_entregue(monkeypatch):
    def h(req):
        if "consmuntransm" in str(req.url):
            return httpx.Response(503, text="fora do ar")
        return httpx.Response(404, content=MSG03)
    ms = _mun(1, "Monte Sião", "3143401")
    linhas, rod = _roda_siops(h, [ms], hoje=date(2026, 10, 15), monkeypatch=monkeypatch)
    assert linhas == {}                              # "não sei" ≠ "não entregue"
    assert any("sem prova" in f for f in rod.falhas)
    assert any("lista de homologados" in f for f in rod.falhas)


def test_lista_diz_homologado_e_api_msg03_vale_a_lista(monkeypatch):
    def h(req):
        if "consmuntransm" in str(req.url):
            return httpx.Response(200, content=LEGADO_RS_B4)
        return httpx.Response(404, content=MSG03)
    linhas, _ = _roda_siops(h, [_mun(1, "Nova Palma", "4313102")], monkeypatch=monkeypatch)
    assert linhas[1]["entregue"] is True and linhas[1]["pct"] is None


# ---------------------------------------------------------------------------
# 2. Períodos e calendário
# ---------------------------------------------------------------------------
def test_codigos_de_periodo_do_siops():
    assert se.PERIODO_SIOPS == {1: 12, 2: 14, 3: 1, 4: 18, 5: 20, 6: 2}


def test_prazos_dos_bimestres():
    assert [se.prazo_bimestre(2026, b) for b in range(1, 7)] == [
        date(2026, 3, 30), date(2026, 5, 30), date(2026, 7, 30),
        date(2026, 9, 30), date(2026, 11, 30), date(2027, 1, 30)]
    assert se.fim_bimestre(2028, 1) == date(2028, 2, 29)


def test_bimestre_que_a_validade_do_cauc_cobra():
    assert se.bimestre_do_prazo(date(2026, 9, 30)) == (2026, 4)
    assert se.bimestre_do_prazo(date(2027, 1, 30)) == (2026, 6)
    assert se.bimestre_do_prazo(date(2026, 3, 30)) == (2026, 1)


def test_bimestres_encerrados_nao_inclui_o_em_curso():
    enc = se.bimestres_encerrados(date(2026, 9, 24))
    assert (2026, 4) in enc and (2026, 5) not in enc
    assert enc[0] == (2025, 1) and len(enc) == 10


# ---------------------------------------------------------------------------
# 3. Parsers com as respostas reais
# ---------------------------------------------------------------------------
def test_lista_legada_real():
    d = ss.parse_lista_homologados(LEGADO_RS_B4.decode("latin-1"))
    assert d == {"430003": date(2026, 9, 23), "431306": date(2026, 9, 22),
                 "431310": date(2026, 9, 23)}


def test_lista_legada_com_rodape_divergente_e_recusada():
    html = LEGADO_RS_B4.decode("latin-1").replace(
        '<td colspan=3 class="tdcb caixa">3</td>', '<td colspan=3 class="tdcb caixa">4</td>')
    with pytest.raises(ss.FonteIndisponivel):
        ss.parse_lista_homologados(html)


def test_indicador_asps_real_de_monte_siao():
    p = ss.parse_siops_indicadores(json.loads(API_OK))
    assert p["pct"] == 24.72                          # 3º bim/2026, medido
    assert p["numerador"] == 12822183.98 and p["denominador"] == 51862351.57


def test_siope_real_de_nova_palma():
    decl = ss.parse_siope_declaracoes(_json("siope_dados_gerais_rs_2026_b3.json")["value"])
    assert decl["431310"] == {"data": date(2026, 7, 16), "recibo": "444376",
                              "retificadora": False}
    ind = ss.parse_siope_indicadores(_json("siope_indicadores_rs_2026_b3.json")["value"])
    assert ind["431310"]["1.1"]["valor"] == 23.16
    assert ind["431310"]["1.2"]["valor"] == 84.06


def test_filtro_do_siope_vai_com_por_cento_20():
    u = ss._siope_url("Indicadores_Siope", "RS", 2026, 3, filtro="COD_EXIB eq '1.1'")
    assert "COD_EXIB%20eq%20%271.1%27" in u and "+" not in u


def test_dgmp_real_monte_siao_rdqas_nunca_concluidos():
    d = ss.parse_dgmp(_html("dgmp_mg_fase2.xls"))
    itens = {(i["instrumento"], i["ano"]): i["situacao"] for i in d["314340"]}
    assert itens[("PLANO", 2022)] == "Aprovado"
    assert [itens[("RDQA1", a)] for a in (2023, 2024, 2025)] == ["Em Elaboração"] * 3
    assert itens[("RAG", 2025)] == "Aprovado"
    assert len(d["314340"]) == 21
    plano = next(i for i in d["314340"] if i["instrumento"] == "PLANO")
    assert plano["periodo"] == "2022-2025"


def test_dgmp_real_2026_nova_palma_e_juranda():
    rs = ss.parse_dgmp(_html("dgmp_rs_fase9.xls"))
    assert set(rs) == {"431310", "431043"}
    np_ = {(i["instrumento"], i["ano"]): i["situacao"] for i in rs["431310"]}
    assert np_[("RDQA1", 2026)] == "Avaliado" and np_[("RDQA2", 2026)] == "Em Elaboração"
    pr = ss.parse_dgmp(_html("dgmp_pr_fase9.xls"))
    assert "411295" in pr


def test_dgmp_sem_coluna_ibge_e_recusado():
    html = _html("dgmp_mg_fase2.xls").replace("CÓD. IBGE MUNICÍPIO", "COD MUN")
    with pytest.raises(ss.FonteIndisponivel):
        ss.parse_dgmp(html)


def test_dgmp_com_rodape_divergente_e_recusado():
    html = _html("dgmp_rs_fase9.xls")
    i = html.find("<tfoot>")
    html = html[:i] + html[i:].replace(">\n            2\n", ">\n            3\n")
    with pytest.raises(ss.FonteIndisponivel):
        ss.parse_dgmp(html)


# ---------------------------------------------------------------------------
# 4. O alarme falso
# ---------------------------------------------------------------------------
ITENS_CAUC = {"3.2.3": "30/09/26", "3.2.4": "30/09/26", "3.1.2": "30/09/26"}
PESQUISA = date(2026, 7, 31)
HOJE = date(2026, 9, 24)


def _codigos(entregues):
    return sorted(p["codigo"] for p in prazos_dos_itens(
        ITENS_CAUC, PESQUISA, "CAUC", 30, HOJE, entregues=entregues))


def test_sem_entrega_conhecida_os_tres_vencem():
    assert _codigos(None) == ["3.1.2", "3.2.3", "3.2.4"]


def test_bimestre_ja_homologado_nao_vence_mais():
    """Nova Palma/RS, 24/09/2026: 4º bimestre do SIOPS homologado em 23/09 e CAUC
    ainda com 3.2.4 válido até 30/09 — o PACTHA avisava "vence em 6 dias"."""
    assert _codigos({"SIOPS": {(2026, 4)}}) == ["3.1.2", "3.2.3"]
    assert _codigos({"SIOPS": {(2026, 4)}, "SIOPE": {(2026, 4)}}) == ["3.1.2"]


def test_entrega_de_outro_bimestre_nao_apaga_o_aviso():
    assert _codigos({"SIOPS": {(2026, 3)}}) == ["3.1.2", "3.2.3", "3.2.4"]


def test_a_regra_nao_toca_o_cadastro_estadual():
    itens = [{"codigo": "3.2.4", "validade": "30/09/2026", "label": "x", "tipo": "regular"}]
    assert len(prazos_dos_itens(itens, PESQUISA, "CAGEC", 30, HOJE,
                                entregues={"SIOPS": {(2026, 4)}})) == 1


# ---------------------------------------------------------------------------
# 5. O payload da tela
# ---------------------------------------------------------------------------
def _b(sistema, ano, bim, entregue, data=None, pct=None):
    return {"sistema": sistema, "ano": ano, "bimestre": bim, "entregue": entregue,
            "data_entrega": data, "pct_aplicado": pct, "numerador": None,
            "denominador": None, "recibo": None}


def test_juranda_siope_3o_bimestre_atrasado():
    bims = [_b("SIOPE", 2026, 1, True, date(2026, 3, 20), 22.0),
            _b("SIOPE", 2026, 2, True, date(2026, 7, 9), 24.1),
            _b("SIOPE", 2026, 3, False),
            _b("SIOPE", 2026, 4, False)]
    out = se.montar(bims, [], HOJE)
    s = out["sistemas"]["SIOPE"]
    sit = {x["bimestre"]: x["situacao"] for x in s["bimestres"] if x["ano"] == 2026}
    assert sit[3] == "atrasado" and sit[4] == "no_prazo"
    assert sit[2] == "entregue_atrasado"             # 09/07 > prazo de 30/05
    assert out["notas_cauc"]["3.2.3"]["tom"] == "critico"
    assert "3º bimestre/2026" in out["notas_cauc"]["3.2.3"]["texto"]
    assert out["alerta"] is True


def test_percentual_parcial_abaixo_do_minimo_nao_e_vermelho():
    assert se.tom_percentual(13.0, 15.0, 2) == "atencao"
    assert se.tom_percentual(13.0, 15.0, 6) == "critico"
    assert se.tom_percentual(22.2, 15.0, 1) == "ok"


def test_nota_diz_que_a_validade_do_cauc_ja_foi_cumprida():
    bims = [_b("SIOPS", 2026, b, True, date(2026, 2 * b + 1, 20), 20.0) for b in (1, 2, 3)]
    bims.append(_b("SIOPS", 2026, 4, True, date(2026, 9, 23), 19.76))
    out = se.montar(bims, [], HOJE, {"3.2.4": date(2026, 9, 30)})
    n = out["notas_cauc"]["3.2.4"]
    assert n["tom"] == "ok" and "já foi entregue" in n["texto"]
    assert "23/09/2026" in n["texto"]


def test_bimestre_sem_resposta_da_fonte_e_sem_informacao_nao_atraso():
    out = se.montar([_b("SIOPS", 2026, 1, True, date(2026, 3, 2), 18.0)], [], HOJE)
    sit = {(x["ano"], x["bimestre"]): x["situacao"] for x in out["sistemas"]["SIOPS"]["bimestres"]}
    assert sit[(2026, 2)] == "sem_informacao"
    assert out["sistemas"]["SIOPS"]["atrasados"] == []


def test_instrumentos_vencidos_e_conselho():
    linhas = [
        {"instrumento": "RDQA1", "ano": 2025, "periodo": None, "situacao": "Em Elaboração"},
        {"instrumento": "RDQA2", "ano": 2025, "periodo": None,
         "situacao": "Em Análise no Conselho de Saúde"},
        {"instrumento": "RAG", "ano": 2025, "periodo": None, "situacao": "Aprovado"},
        {"instrumento": "PAS", "ano": 2027, "periodo": None, "situacao": "Não Iniciado"},
        {"instrumento": "RDQA2", "ano": 2026, "periodo": None, "situacao": "Em Elaboração"},
    ]
    out = se.montar_instrumentos(linhas, HOJE)
    por = {(i["instrumento"], i["ano"]): i for i in out}
    assert ("PAS", 2027) not in por                    # ano futuro é calendário
    assert por[("RDQA1", 2025)]["vencido"] is True
    assert por[("RDQA2", 2025)]["classe"] == "conselho"
    assert por[("RDQA2", 2025)]["vencido"] is False     # a prefeitura fez a parte dela
    assert por[("RDQA2", 2026)]["vencido"] is False     # vence 30/09/2026
    assert por[("RAG", 2025)]["prazo"] == "2026-03-30"
    assert se.classe_situacao("Situação nova da fonte") == "desconhecido"


def test_status_da_rodada():
    assert ss.status_da_rodada(10, []) == ("success", None)
    st, motivo = ss.status_da_rodada(10, ["SIOPE RS: x"])
    assert st == "partial" and "SIOPE RS" in motivo
    assert ss.status_da_rodada(0, ["tudo caiu"])[0] == "error"
