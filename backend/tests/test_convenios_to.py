"""Convênios do Estado do TO (TRANSFERE.TO) — armadilhas medidas contra a fonte em 23/09/2026.

As fixtures são páginas REAIS de `VisualizarConvenio.aspx`, com os bytes como a fonte
os manda (a mistura UTF-8 + Latin-1 intacta; só o CRLF virou LF):
  1200 — Prefeitura de Crixás do Tocantins: OB + contrapartida (valor = Estado + contrapartida)
   104 — Fundo Municipal de Saúde de Axixá: 2ª emenda, OBs > "valor do convênio"
   180 — "FMS DE SÃO SALVADOR DO TOCANTINS": a sigla do fundo
   100 — instituto (entidade), sem programação financeira
"""
import json
import pathlib
from decimal import Decimal

import httpx
import pytest

from ingestion import convenios_to as c

FIX = pathlib.Path(__file__).parent / "fixtures" / "transfere_to"


def _det(i: int) -> dict:
    return c.ler_detalhe(c.decodifica((FIX / f"{i}.html").read_bytes()), i)


# Recorte do catálogo do IBGE (normalizado) que os testes precisam.
CATALOGO = c.apelidos([
    "CRIXAS DO TOCANTINS", "AXIXA DO TOCANTINS", "SAO SALVADOR DO TOCANTINS",
    "NATIVIDADE", "SAO VALERIO DA NATIVIDADE", "CHAPADA DA NATIVIDADE",
    "PALMAS", "MARIANOPOLIS DO TOCANTINS", "PINDORAMA DO TOCANTINS",
    "SAO MIGUEL DO TOCANTINS", "SAO MIGUEL",  # hipotético: a base já é outro município
])


def test_pagina_mistura_utf8_e_latin1_e_as_duas_saem_legiveis():
    d = _det(1200)
    assert d["acao"].startswith("4336 - FOMENTO À PRODUÇÃO")          # topo, UTF-8
    tipos = [p["tipo"] for p in d["programacao_financeira"]]
    assert "NOTA DE LIQUIDAÇÃO" in tipos and "ORDEM BANCÁRIA" in tipos  # grade, Latin-1
    assert "�" not in json.dumps(d, default=str, ensure_ascii=False)


def test_campos_da_prefeitura_com_ob_e_contrapartida():
    d = _det(1200)
    assert d["numero"] == "77010.000036/2023"
    assert d["cnpj"] == "01612821000141"
    assert d["convenente"] == "PREFEITURA MUNICIPAL DE CRIXAS DO TOCANTINS"
    assert d["orgao"] == "SECRETARIA DA CULTURA"
    assert d["situacao"] == "PRESTAÇÃO DE CONTAS EM ANÁLISE"
    assert str(d["vig_ini"]) == "2023-03-28" and str(d["vig_fim"]) == "2023-12-31"
    # Armadilha 4: o valor publicado é Estado (a OB) + contrapartida depositada.
    assert d["valor"] == Decimal("135000.00")
    assert d["repassado"] == Decimal("100000.00")
    assert d["contrapartidas"][0]["valor"] == "35000.00"
    assert str(d["dt_empenho"]) == "2023-03-24" and str(d["dt_desembolso"]) == "2023-04-17"
    assert str(d["assinatura"]) == "2023-03-28"


def test_repassado_passa_do_valor_original_quando_ha_segunda_emenda():
    d = _det(104)
    assert d["valor"] == Decimal("120000.00")
    assert d["repassado"] == Decimal("121125.00")       # 50.000 + 70.000 + 1.125


def test_assinatura_e_a_da_celebracao_nao_a_do_aditivo():
    """Id 104: celebrado em 10-11/12/2020, aditivos assinados em 11/2022 e 12/2022."""
    d = _det(104)
    assert str(d["assinatura"]) == "2020-12-11"
    assert c.registro(d, 1)["ano"] == 2020


@pytest.mark.parametrize("datas,esperado", [
    ([], None),
    (["2023-03-17"], "2023-03-17"),
    (["2023-03-17", "2023-03-28"], "2023-03-28"),               # o par da celebração
    (["2020-10-01", "2023-01-24"], "2020-10-01"),               # par incompleto
    (["2022-06-29", "2022-06-29", "2023-11-28", "2024-03-27"], "2022-06-29"),
])
def test_data_da_celebracao(datas, esperado):
    from datetime import date
    r = c.data_da_celebracao([date.fromisoformat(x) for x in datas])
    assert (str(r) if r else None) == esperado


def test_sem_programacao_financeira_o_repassado_e_zero_afirmado():
    d = _det(100)
    assert d["programacao_financeira"] == []
    assert d["repassado"] == Decimal("0")


def test_pagina_que_nao_e_de_convenio_devolve_none():
    assert c.ler_detalhe("<html><body>Erro</body></html>", 1) is None


def test_registro_emendas_sem_repeticao_e_total_sem_concedente():
    r = c.registro(_det(104), 9)
    assert r["nr"] == "TO-104" and r["mid"] == 9 and r["fonte"] == "TRANSFERE-TO"
    assert r["v_conc"] is None and r["v_total"] == Decimal("120000.00")
    raw = json.loads(r["raw"])
    assert raw["nr_instrumento"] == _det(104)["numero"]
    # A fonte lista 010412.00140/2022 duas vezes na grade Origem.
    assert raw["emendas"] == ["010402.00119/2020", "010412.00140/2022"]
    assert raw["url"].endswith("idConvenio=104")


@pytest.mark.parametrize("nome,esperado", [
    ("PREFEITURA MUNICIPAL DE CRIXAS DO TOCANTINS", "CRIXAS DO TOCANTINS"),
    ("FUNDO MUNICIPAL DE SAUDE DE CRIXAS -TOCANTINS", "CRIXAS DO TOCANTINS"),
    ("FUNDO MUNICIPAL DE SAÚDE DE MARIANÓPOLIS", "MARIANOPOLIS DO TOCANTINS"),
    ("FUNDO MUNICIPAL DE SAUDE - PINDORAMA", "PINDORAMA DO TOCANTINS"),
    # O mais longo vence: "NATIVIDADE" também é município.
    ("PREFEITURA MUNICIPAL DE SAO VALERIO DA NATIVIDADE", "SAO VALERIO DA NATIVIDADE"),
    ("FUNDO MUNICIPAL DE SAÚDE DE CHAPADA DA NATIVIDADE", "CHAPADA DA NATIVIDADE"),
    ("PREFEITURA MUNICIPAL DE NATIVIDADE", "NATIVIDADE"),
    # Apelido que colide com outro município não é criado.
    ("PREFEITURA MUNICIPAL DE SAO MIGUEL", "SAO MIGUEL"),
    ("CLUBE RECREATIVO FLAPALMAS", None),                 # palavra inteira
    ("INSTITUTO DE GESTAO E APOIO AOS MUNICIPIOS TOCANTINENSES", None),
])
def test_municipio_pelo_nome(nome, esperado):
    assert c.municipio_do_nome(nome, CATALOGO) == esperado


@pytest.mark.parametrize("nome,esperado", [
    ("PREFEITURA MUNICÍPAL DE BREJINHO DE NAZARÉ", True),
    ("FUNDO MUNICIPAL DE SAÚDE DE PALMAS", True),
    ("FMS DE SÃO SALVADOR DO TOCANTINS", True),
    ("MUNICIPIO DE PALMAS", True),
    ("ASSOCIAÇÃO DE PAIS E AMIGOS DOS EXCEPCIONAIS DE PALMAS", False),
    ("AÇÃO SOCIAL ARQUIDIOCESANA DE PALMAS", False),
    ("FUNDO MUNICIAL DE SAÚDE DE SANTA RITA DO TOCANTINS", True),   # erro da fonte
    ("SECRETARIA MUNICIPAL DE EDUCAÇÃO DE ARAGUAÍNA", True),
    ("CAMARA MUNICIPAL BABACULANDIA", False),                         # não é o Executivo
])
def test_ente_municipal(nome, esperado):
    assert c.e_ente_municipal(nome) is esperado


def test_entidade_nao_casa_por_apelido():
    """O apelido sem "do Tocantins" é para prefeitura/fundo; em entidade ele errava."""
    nome = "ASSOCIAÇÃO DE PRODUTORES RURAIS SÃO MIGUEL ARCANJO - APRUSMA"
    assert c.municipio_do_nome(nome, CATALOGO) == "SAO MIGUEL"          # oficial (hipotético)
    cat = c.apelidos(["SAO MIGUEL DO TOCANTINS"])
    assert c.municipio_do_nome(nome, cat, com_apelidos=False) is None
    ent = {"cnpj": None, "convenente": nome}
    alvos = [{"id": 5, "nome": "São Miguel do Tocantins", "cnpj": None}]
    assert c.classifica(ent, alvos, cat) == (None, False)
    fundo = {"cnpj": None, "convenente": "FUNDO MUNICIPAL DE SAUDE DE SAO MIGUEL"}
    assert c.classifica(fundo, alvos, cat) == (alvos[0], True)


ALVOS = [
    {"id": 1, "nome": "Crixás do Tocantins", "cnpj": "01612821000141"},
    {"id": 2, "nome": "São Salvador do Tocantins", "cnpj": None},
    {"id": 3, "nome": "Palmas", "cnpj": "24851511000185"},
]


def test_classifica_prefeitura_pelo_cnpj_mesmo_sem_catalogo():
    assert c.classifica(_det(1200), ALVOS, None) == (ALVOS[0], True)


def test_classifica_fundo_pelo_nome_e_entidade_vai_para_outros():
    assert c.classifica(_det(180), ALVOS, CATALOGO) == (ALVOS[1], True)
    ent = {"cnpj": "99999999000199",
           "convenente": "ASSOCIAÇÃO DE PAIS E AMIGOS DOS EXCEPCIONAIS DE PALMAS"}
    assert c.classifica(ent, ALVOS, CATALOGO) == (ALVOS[2], False)
    # Sem o catálogo, nome não liga nada (a rodada vira partial).
    assert c.classifica(_det(180), ALVOS, None) == (None, False)
    # Município que não é nosso.
    assert c.classifica({"cnpj": None, "convenente": "PREFEITURA MUNICIPAL DE NATIVIDADE"},
                        ALVOS, CATALOGO) == (None, False)


def _transporte(paginas: dict[int, bytes], falha: set[int] = frozenset()):
    def responde(req):
        i = int(req.url.params["idConvenio"])
        if i in falha:
            return httpx.Response(500)
        if i in paginas:
            return httpx.Response(200, content=paginas[i])
        return httpx.Response(302, headers={"Location": "/erro_500.aspx"})
    return httpx.MockTransport(responde)


@pytest.fixture
def varredura_curta(monkeypatch):
    monkeypatch.setattr(c, "ID_MINIMO", 5)
    monkeypatch.setattr(c, "FOLGA", 3)
    monkeypatch.setattr(c, "MINIMO_CONVENIOS", 1)
    monkeypatch.setattr(c, "PAUSA_S", 0)
    monkeypatch.setattr(c.time, "sleep", lambda s: None)


def test_varrer_separa_municipal_de_outros_e_para_depois_da_folga(varredura_curta):
    paginas = {2: (FIX / "1200.html").read_bytes(), 4: (FIX / "180.html").read_bytes(),
               9: (FIX / "100.html").read_bytes()}
    with httpx.Client(transport=_transporte(paginas)) as cl:
        achados, outros, falhas, st = c.varrer(cl, ALVOS, CATALOGO)
    assert sorted(achados) == ["TO-2", "TO-4"]
    assert achados["TO-2"]["mid"] == 1 and achados["TO-4"]["mid"] == 2
    assert outros == {}                 # o instituto não cita município nosso
    assert falhas == []
    # ID_MINIMO=5, último achado 4, folga 3: varre até o 7 — o 9 fica de fora.
    assert st["ids"] == 7 and st["ultimo"] == 4


def test_varrer_com_falha_de_id_e_partial(varredura_curta):
    paginas = {2: (FIX / "1200.html").read_bytes()}
    with httpx.Client(transport=_transporte(paginas, falha={3})) as cl:
        achados, _, falhas, st = c.varrer(cl, ALVOS, CATALOGO)
    assert list(achados) == ["TO-2"]
    assert st["falhas_id"] == 1 and falhas and "sem resposta" in falhas[0]


def test_portal_fora_interrompe_a_rodada(varredura_curta, monkeypatch):
    monkeypatch.setattr(c, "ERROS_SEGUIDOS_MAX", 3)
    with httpx.Client(transport=_transporte({}, falha=set(range(1, 100)))) as cl:
        achados, _, falhas, st = c.varrer(cl, ALVOS, CATALOGO)
    assert achados == {} and st["ids"] == 3 and "portal fora" in falhas[0]


def test_pagina_que_mudou_de_forma_nao_passa_por_sucesso(varredura_curta, monkeypatch):
    """Todo id "sem convênio" (layout novo, 302 para login) = rodada partial, e o
    `completa=False` que vem dela impede de apagar o bloco de entidades."""
    monkeypatch.setattr(c, "MINIMO_CONVENIOS", 2)
    paginas = {2: (FIX / "1200.html").read_bytes(), 3: b"<html>manutencao</html>"}
    with httpx.Client(transport=_transporte(paginas)) as cl:
        _, _, falhas, st = c.varrer(cl, ALVOS, CATALOGO)
    assert st["convenios"] == 1 and falhas and "mudou de forma" in falhas[0]


class _Cur:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))


def test_grava_outros_so_apaga_com_varredura_completa():
    reg = {"mid": 3, "nr": "TO-77", "fonte": c.FONTE}
    cur = _Cur()
    c.grava_outros(cur, {"TO-77": reg}, ALVOS, completa=False)
    assert not any(s.startswith("DELETE") for s, _ in cur.sql)
    cur = _Cur()
    c.grava_outros(cur, {"TO-77": reg}, ALVOS, completa=True)
    apaga = [p for s, p in cur.sql if s.startswith("DELETE")]
    assert apaga == [(c.FONTE, 1, []), (c.FONTE, 2, []), (c.FONTE, 3, ["TO-77"])]
    assert all("convenios_estadual_outros" in s for s, _ in cur.sql)
