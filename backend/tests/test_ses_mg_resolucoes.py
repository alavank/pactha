"""Pagamentos da SES-MG por Resolução (fundo a fundo estadual da saúde de MG).

As fixtures são respostas REAIS do painel pagamentoderesolucoes.saude.mg.gov.br de
24/09/2026, recortadas (o <meta> com o byte 0x94 do Windows-1252 ficou de propósito):
Monte Sião 2026 inteiro (26 pagamentos orçamentários, 8 de restos a pagar), três
linhas de Divinópolis (o Fundo e dois consórcios), a tabela vazia que um nome fora
da lista devolve, o formulário com a lista inteira de municípios e a data da
última atualização da página inicial.
"""
import pathlib
from datetime import date, datetime
from decimal import Decimal

import httpx
import pytest

from ingestion import acordofes_ingest as af
from ingestion import ses_mg_resolucoes as sm
from services import ses_mg_fundo as sf

FIX = pathlib.Path(__file__).parent / "fixtures" / "ses_mg"
MONTE_SIAO = {"id": 7, "nome": "Monte Sião", "ibge": "3143401", "cnpj": "22646525000131"}
FMS_MONTE_SIAO = "11875540000135"


def _pagina(nome: str) -> str:
    return sm.decodifica((FIX / nome).read_bytes())


def _orc() -> list[dict]:
    return sm.ler_tabela(_pagina("orcamentario_monte_siao_2026.html"), "orcamentario")


def _restos() -> list[dict]:
    return sm.ler_tabela(_pagina("restos_monte_siao_2026.html"), "restos")


def _soma(linhas, **filtro) -> Decimal:
    return sum((x["valor"] for x in linhas if all(x[k] == v for k, v in filtro.items())),
               Decimal("0"))


# ── página e formulário ─────────────────────────────────────────────────────

def test_a_pagina_mistura_codificacoes_e_decodificar_estrito_explode():
    bruto = (FIX / "orcamentario_monte_siao_2026.html").read_bytes()
    with pytest.raises(UnicodeDecodeError):
        bruto.decode("utf-8")
    assert "FUNDO MUNICIPAL DE SAUDE DE MONTE SIAO" in sm.decodifica(bruto)


def test_token_csrf_e_lista_de_municipios_do_formulario():
    pagina = _pagina("formulario_recorte.html")
    assert sm.token_csrf(pagina) == "5Op2ROBbfxB7ibASIyzwSL9HkRvIT5d7Iw8Hhuzz"
    opcoes = sm.opcoes_municipio(pagina)
    assert len(opcoes) == 854 and "MONTE SIAO" in opcoes
    assert "PINGO-D'AGUA" in opcoes                      # vem como &#039; no HTML


@pytest.mark.parametrize("nome, ibge, esperado", [
    ("Monte Sião", "3143401", "MONTE SIAO"),
    ("Araújos", "3103900", "ARAUJOS"),
    ("Brazópolis", "3108909", "BRASOPOLIS"),              # grafia própria do formulário
    ("São Tomé das Letras", "3165206", "SAO THOME DAS LETRAS"),
    ("Pingo-d'Água", "3150539", "PINGO-D'AGUA"),
    ("Pingo d Água", "3150539", "PINGO-D'AGUA"),          # casamento por letras
    ("Monte Sião do Norte", "9999999", None),             # fora da lista: não consulta
])
def test_nome_no_formulario(nome, ibge, esperado):
    opcoes = sm.opcoes_municipio(_pagina("formulario_recorte.html"))
    assert sm.nome_no_formulario(nome, ibge, opcoes) == esperado


def test_data_da_ultima_atualizacao_da_pagina_inicial():
    assert sm.atualizado_em(_pagina("inicial_recorte.html")) == datetime(2026, 9, 24, 7, 0, 15)
    assert sm.atualizado_em("<html>sem data</html>") is None


# ── a tabela ─────────────────────────────────────────────────────────────────

def test_monte_siao_2026_os_numeros_medidos():
    linhas = _orc()
    assert len(linhas) == 26
    assert _soma(linhas) == Decimal("4440015.08")
    assert _soma(linhas, categoria="ordinario") == Decimal("431951.08")
    assert _soma(linhas, categoria="emenda") == Decimal("4008064.00")
    assert _soma(linhas, cod_upg="560") == Decimal("290992.79")          # incentivo APS
    assert _soma(linhas, cod_upg="599") == Decimal("68399.53")           # CBAF
    assert _soma(linhas, cod_upg="558") == Decimal("36508.41")           # promoção
    assert _soma(linhas, cod_upg="813") + _soma(linhas, cod_upg="594") == Decimal("36050.35")
    assert {x["cnpj_credor"] for x in linhas} == {FMS_MONTE_SIAO}
    assert max(x["data_pagamento"] for x in linhas) == date(2026, 9, 9)
    x = linhas[0]
    assert (x["id_fonte"], x["num_ob"], x["num_empenho"], x["data_pagamento"]) == (
        36515946, "2261", "250", date(2026, 3, 25))
    assert (x["banco"], x["agencia"], x["conta"], x["resolucao"]) == (
        "1", "2791X", "170518", "10900/2026")
    assert x["valor"] == Decimal("104743.50") and x["ano_empenho"] is None


def test_restos_a_pagar_a_resolucao_antiga_paga_em_2026():
    linhas = _restos()
    assert len(linhas) == 8
    assert _soma(linhas) == Decimal("427662.80")
    assert {(x["ano_empenho"], x["num_empenho"], x["resolucao"]) for x in linhas} == {
        (2019, "5813", "6949/2019")}
    x = linhas[0]
    assert x["data_pagamento"] == date(2026, 2, 23) and x["valor"] == Decimal("81418.67")
    assert x["valor_nao_processado"] == Decimal("81418.67") and x["valor_processado"] == 0
    assert x["num_ob"] is None                            # a fonte não publica o documento
    assert x["cnpj_credor"] == FMS_MONTE_SIAO             # vinha pontuado


def test_nome_fora_da_lista_devolve_tabela_vazia_e_isso_nao_e_erro_de_layout():
    """Armadilha 1: o 200 vazio é indistinguível de "nada pago" — por isso o nome é
    conferido na lista ANTES do POST, e não depois."""
    assert sm.ler_tabela(_pagina("orcamentario_nome_inexistente.html"), "orcamentario") == []


def test_layout_diferente_recusa_a_resposta_inteira():
    restos = _pagina("restos_monte_siao_2026.html")
    with pytest.raises(sm.LayoutMudou):                   # a página de restos lida como a outra
        sm.ler_tabela(restos, "orcamentario")
    with pytest.raises(sm.LayoutMudou):
        sm.ler_tabela("<html><body>manutenção</body></html>", "orcamentario")
    orc = _pagina("orcamentario_monte_siao_2026.html")
    cortada = orc[:orc.index("</tr>", orc.index("<tbody>")) - 40] + "</tbody></table>"
    with pytest.raises(sm.LayoutMudou):
        sm.ler_tabela(cortada, "orcamentario")
    sem_coluna = orc.replace("Razão Social</th>", "Credor</th>")
    with pytest.raises(sm.LayoutMudou):
        sm.ler_tabela(sem_coluna, "orcamentario")


@pytest.mark.parametrize("cod, nome, esperado", [
    ("666", "ATENDIMENTO A DEMANDAS DOS MUNICÍPIOS E ENTIDADES - INVESTIMENTO", "emenda"),
    ("675", "ATENDIMENTO A DEMANDAS DOS MUNICÍPIOS E ENTIDADES - CUSTEIO", "emenda"),
    ("999", "EMENDAS PARLAMENTARES SES - CUSTEIO", "emenda"),     # código novo, nome do dropdown
    ("650", "PAGAMENTOS RELATIVOS À EMENDAS PARLAMENTARES FEDERAIS.", "emenda_federal"),
    ("948", "REPASSE DE RECOMPOSIÇÃO DO ACORDO FES", "acordo_fes"),
    ("560", "REPASSES DE INCENTIVOS FINANCEIROS PARA FINANCIAMENTO ESTADUAL DA APS.", "ordinario"),
    ("630", "TRANSF. MUNIC.REF. PROGRAMA MONITORAMENTO DAS AÇÕES VIGILANCIA  SAÚDE", "ordinario"),
])
def test_emenda_ou_ordinario_pela_upg(cod, nome, esperado):
    assert sm.categoria(cod, nome) == esperado


def test_csrf_vencido_renova_o_token_e_repete_uma_vez():
    formulario = (FIX / "formulario_recorte.html").read_bytes()
    tabela = (FIX / "orcamentario_monte_siao_2026.html").read_bytes()
    chamadas = []

    def responde(req: httpx.Request) -> httpx.Response:
        chamadas.append(req.method)
        if req.method == "GET":
            return httpx.Response(200, content=formulario)
        if chamadas.count("POST") == 1:
            return httpx.Response(419, content=b"Page Expired")
        assert b"_token=5Op2ROBbfxB7ibASIyzwSL9HkRvIT5d7Iw8Hhuzz" in req.content
        assert b"dsc_municipio=MONTE+SIAO" in req.content
        return httpx.Response(200, content=tabela)

    with httpx.Client(transport=httpx.MockTransport(responde)) as c:
        form = sm.Formulario(c)
        linhas = form.consultar("orcamentario", "MONTE SIAO", 2026)
    assert len(linhas) == 26 and chamadas == ["GET", "POST", "GET", "POST"]


# ── a conferência do CNPJ (armadilha 3) ──────────────────────────────────────

def _cadastro(ibge, natureza):
    return {"ibge": ibge, "natureza_codigo": natureza}


def test_credor_conferido_pela_prefeitura_pelo_fns_e_pela_receita():
    conf = sm.ConfereCredor(fns={7: {"99999999000199"}}, cadastro={
        FMS_MONTE_SIAO: _cadastro("3143401", 1333),       # Fundo Público Municipal
        "20059618000134": _cadastro("3143401", 1210),     # consórcio sediado lá
        "11111111000111": _cadastro("3103900", 1333),     # fundo de OUTRO município
    })
    assert conf("22646525000131", MONTE_SIAO) == (True, "prefeitura")
    assert conf("22646525000212", MONTE_SIAO) == (True, "prefeitura")    # filial, mesma raiz
    assert conf("99999999000199", MONTE_SIAO) == (True, "fns")
    assert conf(FMS_MONTE_SIAO, MONTE_SIAO) == (True, "receita")
    assert conf("20059618000134", MONTE_SIAO) == (False, None)
    assert conf("11111111000111", MONTE_SIAO) == (False, None)
    assert conf("***456789**", MONTE_SIAO) == (False, None)               # CPF mascarado
    assert conf("55555555000155", MONTE_SIAO) == (None, None)             # sem cadastro


def test_credor_desconhecido_consulta_a_receita_uma_vez_e_guarda():
    consultas = []

    def consultar(cnpj):
        consultas.append(cnpj)
        return {"cnpj": cnpj, "ibge": "3143401", "natureza_codigo": 1333}

    sm.PAUSA_S, pausa = 0, sm.PAUSA_S
    try:
        conf = sm.ConfereCredor(fns={}, cadastro={}, consultar=consultar)
        assert conf(FMS_MONTE_SIAO, MONTE_SIAO) == (True, "receita")
        assert conf(FMS_MONTE_SIAO, MONTE_SIAO) == (True, "receita")
    finally:
        sm.PAUSA_S = pausa
    assert consultas == [FMS_MONTE_SIAO] and len(conf.novos) == 1


def test_divinopolis_consorcio_nao_e_o_municipio_e_o_cnpj_que_perdeu_o_zero():
    linhas = sm.ler_tabela(_pagina("orcamentario_divinopolis_2026_recorte.html"), "orcamentario")
    docs = {x["cnpj_credor"] for x in linhas}
    assert docs == {"19166979000109", "20059618000134",
                    "00639952000150"}                    # CISVI veio com 12 dígitos
    divinopolis = {"id": 9, "nome": "Divinópolis", "ibge": "3122306", "cnpj": "18291351000164"}
    conf = sm.ConfereCredor(fns={}, cadastro={
        "19166979000109": _cadastro("3122306", 1333),
        "20059618000134": _cadastro("3122306", 1210),
        "00639952000150": _cadastro("3122306", 3999),
    })
    assert sm.confere_fatia(linhas, divinopolis, conf) == []
    assert {x["cnpj_credor"] for x in linhas if x["do_municipio"]} == {"19166979000109"}


def test_fatia_com_credor_sem_cadastro_nao_pode_ser_gravada():
    linhas = _orc()
    conf = sm.ConfereCredor(fns={}, cadastro={})          # Receita fora do ar
    assert sm.confere_fatia(linhas, dict(MONTE_SIAO, cnpj=None), conf) == [FMS_MONTE_SIAO]


# ── rodada, gravação e idempotência ──────────────────────────────────────────

def test_anos_da_rodada():
    set_2026 = date(2026, 9, 24)
    assert sm.anos_da_rodada(set_2026, set()) == [2026, 2025]
    lidos = {("orcamentario", 2025), ("restos", 2025), ("orcamentario", 2024)}
    assert sm.anos_da_rodada(set_2026, lidos) == [2026, 2024]    # 2024 sem os restos
    assert sm.anos_da_rodada(date(2026, 2, 10), set()) == [2026, 2025, 2024]
    tudo = {(t, a) for t in ("orcamentario", "restos") for a in range(2019, 2026)}
    assert sm.anos_da_rodada(set_2026, tudo) == [2026]


class _Cur:
    def __init__(self, falha_em: str | None = None):
        self.sql, self.falha_em = [], falha_em

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if self.falha_em and s.startswith(self.falha_em):
            raise RuntimeError("tabela não existe")
        self.sql.append((s, params))


@pytest.fixture
def batch_direto(monkeypatch):
    import psycopg2.extras
    monkeypatch.setattr(psycopg2.extras, "execute_batch",
                        lambda cur, sql, seq, page_size=100: [cur.execute(sql, p) for p in seq])
    monkeypatch.setattr(af, "execute_values",
                        lambda cur, sql, seq: cur.execute(sql, list(seq)))


def _conferidas(linhas):
    conf = sm.ConfereCredor(fns={}, cadastro={FMS_MONTE_SIAO: _cadastro("3143401", 1333)})
    assert sm.confere_fatia(linhas, MONTE_SIAO, conf) == []
    return linhas


def test_grava_troca_a_fatia_inteira_e_repetir_da_o_mesmo(batch_direto):
    linhas = _conferidas(_orc())
    rodadas = []
    for _ in range(2):
        cur = _Cur()
        assert sm.grava_fatia(cur, 7, "orcamentario", 2026, linhas, "MONTE SIAO",
                              datetime(2026, 9, 24, 7, 0, 15), antes=26) is None
        rodadas.append(cur.sql)
    assert rodadas[0] == rodadas[1]
    sql = rodadas[0]
    assert sql[0] == ("DELETE FROM ses_mg_pagamentos WHERE municipio_id = %s AND tipo = %s "
                      "AND ano_pagamento = %s", (7, "orcamentario", 2026))
    ins = [p for s, p in sql if s.startswith("INSERT INTO ses_mg_pagamentos")]
    assert len(ins) == 26 and all(p["do_municipio"] for p in ins)
    assert {p["ano_empenho"] for p in ins} == {2026}      # orçamentário = empenho do ano
    cob = [p for s, p in sql if s.startswith("INSERT INTO ses_mg_cobertura")]
    assert cob == [(7, "orcamentario", 2026, "MONTE SIAO", 26, Decimal("4440015.08"),
                    datetime(2026, 9, 24, 7, 0, 15))]


def test_fatia_que_tinha_linhas_e_voltou_vazia_nao_apaga(batch_direto):
    cur = _Cur()
    motivo = sm.grava_fatia(cur, 7, "orcamentario", 2026, [], "MONTE SIAO", None, antes=26)
    assert "não apaguei" in motivo and cur.sql == []
    # Nunca lida (antes=None) ou lida vazia: zero é resposta, e grava a cobertura.
    cur = _Cur()
    assert sm.grava_fatia(cur, 7, "restos", 2020, [], "MONTE SIAO", None, antes=None) is None
    assert cur.sql[-1][1][4] == 0


def test_cobertura_so_soma_o_credor_do_municipio(batch_direto):
    linhas = sm.ler_tabela(_pagina("orcamentario_divinopolis_2026_recorte.html"), "orcamentario")
    conf = sm.ConfereCredor(fns={9: {"19166979000109"}}, cadastro={
        "20059618000134": _cadastro("3122306", 1210), "00639952000150": _cadastro("3122306", 3999)})
    divinopolis = {"id": 9, "nome": "Divinópolis", "ibge": "3122306", "cnpj": None}
    sm.confere_fatia(linhas, divinopolis, conf)
    cur = _Cur()
    sm.grava_fatia(cur, 9, "orcamentario", 2026, linhas, "DIVINOPOLIS", None, antes=None)
    fms = sum(x["valor"] for x in linhas if x["cnpj_credor"] == "19166979000109")
    assert cur.sql[-1][1][5] == fms
    assert sum(1 for s, _ in cur.sql if s.startswith("INSERT INTO ses_mg_pagamentos")) == 3


def test_status_da_rodada():
    assert sm.status_da_rodada(4, [], []) == ("success", None)
    assert sm.status_da_rodada(3, ["X restos 2026: HTTPError"], [])[0] == "partial"
    assert sm.status_da_rodada(4, [], ["o painel não atualiza desde 01/09/2026"])[0] == "partial"
    assert sm.status_da_rodada(0, ["formulário"], [])[0] == "error"


def test_tenant_sem_mg_nao_faz_requisicao(monkeypatch):
    """Nos tenants do RS/PR: `success` 0, sem abrir o painel."""
    class Conn:
        def __init__(self): self.cur = _CurAlvos()
        def cursor(self): return self.cur
        def commit(self): pass
        def rollback(self): pass

    class _CurAlvos(_Cur):
        def fetchall(self): return []
        def close(self): pass

    import contextlib
    from ingestion import _resilience
    conn = Conn()
    monkeypatch.setattr(_resilience, "neon_connect", lambda url=None: contextlib.nullcontext(conn))
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: (_ for _ in ()).throw(AssertionError("rede")))
    assert sm.ingest() == 0
    log = [p for s, p in conn.cur.sql if s.startswith("INSERT INTO ingestion_log")]
    assert log == [("ses_mg_resolucoes", "success", 0, None)]


# ── a conta da tela (services/ses_mg_fundo.py) ───────────────────────────────

def _como_do_banco(linhas, tipo):
    return [{**x, "tipo": tipo, "ano_empenho": x["ano_empenho"] or 2026} for x in linhas]


def _indicacao(nr, instrumento, conta, valor):
    return {"nr_indicacao": nr, "autor": "FULANO", "valor_indicacao": valor,
            "valor_pago_segov": 0.0, "instrumento": instrumento, "conta": conta}


def test_a_tela_separa_ordinario_emenda_e_restos():
    pgs = (_como_do_banco(_conferidas(_orc()), "orcamentario")
           + _como_do_banco(_conferidas(_restos()), "restos"))
    # Indicações REAIS da SEGOV (CSV de 24/09/2026) de Monte Sião: a 11058/2026 tem
    # 5 indicações, cada uma com a sua conta; a 11049/2026 tem duas de R$ 180 mil.
    inds = [_indicacao("204322", "011058/2026", "26101", 355500.0),
            _indicacao("204509", "011058/2026", "26102", 203626.0),
            _indicacao("197697", "011049/2026", "26098", 180000.0),
            _indicacao("199065", "011049/2026", "26099", 180000.0),
            # duas indicações na MESMA chave: sem chave única, não casa
            _indicacao("1", "11074/2026", "26176", 180000.0),
            _indicacao("2", "11074/2026", "26176", 180000.0)]
    fes = {(FMS_MONTE_SIAO, 2019, "5813"): {"divida_atual": 235174.55, "resolucao": "6949/2019"}}
    r = sf.monta(pgs, inds, fes)
    assert r["ordinario"]["total"] == 431951.08 and r["ordinario"]["n"] == 11
    assert r["ordinario"]["programas"][0]["cod_upg"] == "560"
    assert r["emendas"]["total"] == 4008064.0 and r["emendas"]["n"] == 15
    ligadas = {p["valor"]: p["indicacao"]["nr_indicacao"]
               for p in r["emendas"]["pagamentos"] if p["indicacao"]}
    assert r["emendas"]["ligadas"] == 4
    assert ligadas[355500.0] == "204322" and ligadas[203626.0] == "204509"
    por_conta = {p["conta"]: (p["indicacao"] or {}).get("nr_indicacao")
                 for p in r["emendas"]["pagamentos"]}
    assert por_conta["260983"] == "197697" and por_conta["260991"] == "199065"
    assert por_conta["261769"] is None                    # a chave duplicada não casou
    assert r["restos"]["total"] == pytest.approx(427662.80)
    assert r["restos"]["total_acordo_fes"] == pytest.approx(427662.80)
    assert r["outros_credores"] == []


def test_credor_que_nao_e_o_municipio_fica_fora_de_toda_conta():
    linhas = sm.ler_tabela(_pagina("orcamentario_divinopolis_2026_recorte.html"), "orcamentario")
    for x in linhas:
        x["do_municipio"] = x["cnpj_credor"] == "19166979000109"
    r = sf.monta(_como_do_banco(linhas, "orcamentario"), [], {})
    fora = sum(o["total"] for o in r["outros_credores"])
    dentro = r["ordinario"]["total"] + r["emendas"]["total"]
    assert len(r["outros_credores"]) == 2
    assert dentro + fora == pytest.approx(float(sum(x["valor"] for x in linhas)))


def test_chaves_da_resolucao_e_da_conta():
    assert sm.resolucao_norm("011058/2026") == "11058/2026" == sm.resolucao_norm("11058/2026")
    assert sm.resolucao_norm("N/D") is None
    assert sm.conta_sem_dv("261017") == "26101" and sm.conta_sem_dv("26105X") == "26105"


# ── Acordo FES por empenho ───────────────────────────────────────────────────

def _linha_acordo():
    r = [None] * 26
    r[1], r[2], r[9] = 2019, 5813, "6949/2019"
    r[12], r[19], r[20], r[21], r[22] = 500000, 0, 235174.55, 264825.45, 0
    r[24], r[25] = 11875540000135, "FUNDO MUNICIPAL DE SAUDE DE MONTE SIAO"
    return tuple(r)


def test_acordo_fes_guarda_o_empenho_dos_credores_casados(batch_direto):
    emp = af._empenho(_linha_acordo())
    assert emp[:3] == (2019, "5813", "6949/2019") and emp[5] == 235174.55
    cur = _Cur()
    af._grava_empenhos(cur, [(FMS_MONTE_SIAO, 7)], {FMS_MONTE_SIAO: [emp]})
    s = [x[0] for x in cur.sql]
    assert s[0] == "SAVEPOINT acordofes_empenho" and s[-1] == "RELEASE SAVEPOINT acordofes_empenho"
    ins = [p for q, p in cur.sql if q.startswith("INSERT INTO acordofes_empenho")]
    assert ins == [[(7, FMS_MONTE_SIAO, 2019, "5813", "6949/2019", 500000.0, 0.0,
                     235174.55, 264825.45, 0.0)]]


def test_acordo_fes_sem_a_tabela_nova_nao_perde_o_agregado():
    cur = _Cur(falha_em="TRUNCATE acordofes_empenho")
    af._grava_empenhos(cur, [(FMS_MONTE_SIAO, 7)], {})
    assert cur.sql[-1][0] == "ROLLBACK TO SAVEPOINT acordofes_empenho"
