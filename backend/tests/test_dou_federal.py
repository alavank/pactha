"""DOU federal (`ingestion/dou_federal.py`) — as armadilhas medidas em 22/09/2026.

Os textos abaixo são recortes REAIS das páginas lidas naquele dia (Nova Palma/RS
em 60 dias, Santa Maria/RS em 14). O que se protege, na ordem do cabeçalho do
coletor: nome não é chave; a cidade não é a prefeitura; a busca pagina por
cursor; página sem o bloco de resultados é falha, não zero.
"""
import json

import httpx
import pytest

from ingestion import dou_federal as d

NOVA_PALMA = {"id": 1, "nome": "Nova Palma", "uf": "RS", "ibge": "4313102",
              "cnpj": "88488358000156"}
SANTA_MARIA = {"id": 2, "nome": "Santa Maria", "uf": "RS", "ibge": "4316907",
               "cnpj": "88488366000100"}

# O que a lista nacional do IBGE diz desses nomes (medido: Nova Palma 1, Santa
# Maria 2 — RS e RN).
TRAVA_NP = {"antes": [], "depois": [], "unico": True}
TRAVA_SM = {"antes": [], "depois": ["DO HERVAL", "DO SALTO", "DA BOA VISTA"],
            "unico": False}


def _ev(texto, alvo, trava=None, orgao=None):
    p = d.padroes(alvo, trava)
    r = d.evidencia_no_texto(d.normaliza(texto), p,
                             d.normaliza(orgao) if orgao else None)
    return r[0] if r else None


# ---------------------------------------------------------------------------
# normaliza: a posição no texto normalizado é a posição no original
# ---------------------------------------------------------------------------
def test_normaliza_preserva_o_comprimento():
    s = "Portaria nº 3.006 — Município de São João/RS ½ çÃO"
    n = d.normaliza(s)
    assert len(n) == len(s)
    assert "MUNICIPIO DE SAO JOAO/RS" in n
    assert n.index("SAO JOAO") == s.index("São João")


# ---------------------------------------------------------------------------
# Armadilha 1: nome não é chave
# ---------------------------------------------------------------------------
def test_portaria_com_municipio_e_uf_entra():
    t = ("Autoriza a transferência de recursos ao município de Nova Palma/RS, para "
         "execução de ações de Proteção e Defesa Civil.")
    assert _ev(t, NOVA_PALMA, TRAVA_NP) == "municipio"


def test_naturalizacao_com_sobrenome_nao_entra():
    """Portaria MJSP 6.972 (31/08/2026): filha de BENEDICTA NOVA PALMA."""
    t = ("natural da Bolívia, nascida em 31 de março de 1980, filha de EMIGDIO "
         "OCANA NEGRETE e de BENEDICTA NOVA PALMA, residente no estado de São Paulo")
    assert _ev(t, NOVA_PALMA, TRAVA_NP) is None


def test_empresa_com_o_nome_nao_entra():
    """Despachos da ANEEL: "Nova Palma Energia Ltda", "Usina Hidroelétrica Nova
    Palma Ltda." — sem UF colada, sem "Município de"."""
    t = ("Interessado: Nova Palma Energia Ltda, CNPJ nº 89.889.604/0001-44. "
         "Usina Hidroelétrica Nova Palma Ltda. - Nova Palma, concessionárias")
    assert _ev(t, NOVA_PALMA, TRAVA_NP) is None


def test_outro_municipio_que_comeca_com_o_nome_nao_entra():
    assert _ev("em favor do Município de Santa Maria do Herval/RS", SANTA_MARIA,
               TRAVA_SM) is None
    assert _ev("ações no município de Santa Maria de Jetibá - ES", SANTA_MARIA,
               TRAVA_SM) is None


def test_outro_estado_nao_entra():
    assert _ev("Região Administrativa de Santa Maria/DF", SANTA_MARIA, TRAVA_SM) is None
    assert _ev("ao Município de Santa Maria/RN", SANTA_MARIA, TRAVA_SM) is None


def test_municipio_do_mesmo_estado_que_termina_no_nome_e_barrado():
    """Alvo hipotético "Palma"/RS: "Nova Palma/RS" é outro município."""
    palma = {"id": 9, "nome": "Palma", "uf": "RS", "ibge": "", "cnpj": ""}
    trava = {"antes": ["NOVA"], "depois": ["SOLA"], "unico": True}
    assert _ev("ao Município de Nova Palma/RS", palma, trava) is None
    assert _ev("ao Município de Palma/RS", palma, trava) == "municipio"
    # e sem UF: "Município de Palma Sola" é Palma Sola/SC
    assert _ev("MUNICIPIO DE PALMA SOLA", palma, trava) is None


def test_estado_por_extenso():
    t = ("serviço de radiodifusão comunitária no Município de Nova Palma, Estado do "
         "Rio Grande do Sul.")
    assert _ev(t, NOVA_PALMA, TRAVA_NP) == "municipio"


def test_prefeitura_sem_uf_so_com_nome_unico():
    """Despacho ANM (28/07/2026): "PREFEITURA MUNICIPAL DE NOVA PALMA", sem UF.
    Vale para Nova Palma (única no Brasil) e NÃO para Santa Maria (RS e RN)."""
    assert _ev("810.946/2025 - PREFEITURA MUNICIPAL DE NOVA PALMA 810.944/2025",
               NOVA_PALMA, TRAVA_NP) == "municipio"
    assert _ev("810.946/2025 - PREFEITURA MUNICIPAL DE SANTA MARIA 810.944/2025",
               SANTA_MARIA, TRAVA_SM) is None
    # sem a lista do IBGE (falha na rodada), a regra fica desligada
    assert _ev("PREFEITURA MUNICIPAL DE NOVA PALMA", NOVA_PALMA, None) is None


# ---------------------------------------------------------------------------
# IBGE e CNPJ
# ---------------------------------------------------------------------------
def test_tabela_do_ms_com_ibge_de_6_digitos():
    """Portaria GM/MS 12.122 (PSE): "RS 431310 NOVA PALMA 100,00%"."""
    t = ("RS 431308 NOVA PÁDUA 100,00% R$ 7.676,00 R$ 759,35 R$ 8.435,35 RS 431310 "
         "NOVA PALMA 100,00% R$ 7.676,00 R$ 1.771,83 R$ 9.447,83")
    assert _ev(t, NOVA_PALMA, TRAVA_NP) == "ibge"


def test_ibge_de_6_digitos_sozinho_nao_basta():
    """Seis dígitos aparecem em número de processo; só valem colados ao nome."""
    assert _ev("Processo nº 431310/2024 arquivado.", NOVA_PALMA, TRAVA_NP) is None


def test_ibge_de_7_digitos_basta():
    """FUNDEB (Portaria Interministerial MEC/MF 11) e o protocolo da Defesa Civil."""
    assert _ev("RS NOVA PALMA 4313102 15.780,26", NOVA_PALMA, TRAVA_NP) == "ibge"
    assert _ev("Protocolo nº REC-RS-4313102-20240508-01", NOVA_PALMA, TRAVA_NP) == "ibge"
    assert _ev("código 43131020", NOVA_PALMA, TRAVA_NP) is None


def test_cnpj_formatado_ou_nao():
    assert _ev("Convenente: CNPJ 88.488.358/0001-56", NOVA_PALMA, TRAVA_NP) == "cnpj"
    assert _ev("CNPJ 88488358000156", NOVA_PALMA, TRAVA_NP) == "cnpj"


# ---------------------------------------------------------------------------
# Armadilhas 8 e 9: quem publicou, e cidade x município
# ---------------------------------------------------------------------------
def test_ato_publicado_pela_prefeitura():
    org = "Prefeituras/Estado do Rio Grande do Sul/Prefeitura Municipal de Santa Maria"
    assert _ev("Santa Maria, 17 de setembro de 2026.", SANTA_MARIA, TRAVA_SM,
               org) == "orgao"


def test_orgao_de_outro_municipio_com_o_mesmo_comeco():
    org = "Prefeituras/Estado de Minas Gerais/PREFEITURA MUNICIPAL DE SANTA MARIA DO SALTO"
    assert _ev("Santa Maria do Salto, 1º de setembro.", SANTA_MARIA, TRAVA_SM,
               org) is None
    org_rn = "Prefeituras/Estado do Rio Grande do Norte/Prefeitura Municipal de Santa Maria"
    assert _ev("texto sem citação", SANTA_MARIA, TRAVA_SM, org_rn) is None


def test_endereco_e_cidade_nao_municipio():
    t = ("prédios e áreas da UFSM, Campi de Santa Maria/RS, Frederico Westphalen/RS "
         "e Cachoeira do Sul/RS")
    assert _ev(t, SANTA_MARIA, TRAVA_SM) == "cidade"


def test_municipio_como_endereco_de_empresa_e_cidade():
    """Farmácia Popular (08/09/2026): "localizada no Município de Monte Sião - MG"."""
    monte_siao = {"id": 3, "nome": "Monte Sião", "uf": "MG", "ibge": "3143401", "cnpj": ""}
    t = ("DEFERE o cancelamento da participação da empresa DROGA MINAS SUL LTDA, "
         "inscrita no CNPJ sob o nº 12.466.656/0001-83, localizada no Município de "
         "Monte Sião - MG, no Programa Farmácia Popular")
    assert _ev(t, monte_siao, TRAVA_NP) == "cidade"
    # sem UF, com nome único, o endereço não vira citação nenhuma
    assert _ev("empresa sediada no Município de Nova Palma", NOVA_PALMA, TRAVA_NP) is None


def test_municipio_ganha_da_cidade_no_mesmo_texto():
    t = ("Campus de Santa Maria/RS ... transferência de recursos ao Município de "
         "Santa Maria/RS, para execução")
    assert _ev(t, SANTA_MARIA, TRAVA_SM) == "municipio"


def test_ordem_das_evidencias():
    assert d.EVIDENCIAS == ("orgao", "ibge", "cnpj", "municipio", "cidade")


def test_trecho_recorta_com_a_grafia_original():
    t = "x " * 400 + "ao Município de Nova Palma/RS, para execução" + " y" * 400
    cit = d.avaliar(t, [dict(NOVA_PALMA, padroes=d.padroes(NOVA_PALMA, TRAVA_NP))])
    assert len(cit) == 1
    assert "Município de Nova Palma/RS" in cit[0]["trecho"]
    assert cit[0]["trecho"].startswith("… ") and cit[0]["trecho"].endswith(" …")


# ---------------------------------------------------------------------------
# Categoria
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("titulo,ementa,tipo,texto,esperado", [
    ("PORTARIA Nº 2.598", "Autoriza a transferência de recursos ao município de "
     "Nova Palma/RS, para execução de ações de Proteção e Defesa Civil.",
     "Portaria", None, "repasse"),
    ("PORTARIA GM/MS Nº 12.122", "Habilita municípios e Distrito Federal ao "
     "recebimento do incentivo financeiro do PSE.", "Portaria", None, "habilitacao"),
    ("PORTARIA INTERMINISTERIAL MEC/MF Nº 11", "Altera a Portaria que estabelece as "
     "estimativas, os valores e os cronogramas de desembolso das complementações da "
     "União ao FUNDEB", "Portaria Interministerial", None, "repasse"),
    ("PORTARIA Nº 2.753", None, "Portaria",
     "PORTARIA Nº 2.753 A UNIÃO, por intermédio do MINISTÉRIO ... resolve: Art. 1º "
     "Prorrogar o prazo de execução das ações de Proteção e Defesa Civil no "
     "município de Nova Palma/RS até 27/02/2027.", "prazo"),
    ("EXTRATO DE CONTRATO", None, "Extrato de Contrato",
     "Contrato de Repasse nº 7AAEUD/2026, firmado pelo MUNICÍPIO DE NOVA PALMA-RS",
     "convenio"),
    ("PORTARIA Nº 100", "Reconhece a situação de emergência no Município de X/RS",
     "Portaria", None, "emergencia"),
    ("AVISO DE LICITAÇÃO", None, "Aviso de Licitação", "Pregão eletrônico nº 90/2026",
     "licitacao"),
    ("DECRETO LEGISLATIVO Nº 358", "Aprova o ato que renova a autorização de "
     "radiodifusão comunitária", "Decreto Legislativo", None, "outros"),
])
def test_categoria(titulo, ementa, tipo, texto, esperado):
    assert d.categoria(titulo, ementa, tipo, texto) == esperado


def test_categorias_de_captacao_existem_na_tela():
    from routers.dou_federal import CATEGORIAS
    assert set(d.CATEGORIAS_CAPTACAO) <= set(CATEGORIAS)
    assert {c for c, _ in d._REGRAS} | {"outros"} == set(CATEGORIAS)


# ---------------------------------------------------------------------------
# Armadilhas 3 e 5: paginação por cursor; página sem bloco é falha
# ---------------------------------------------------------------------------
def _pagina(itens, total_paginas=1):
    return (
        '<script id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params" '
        'type="application/json">' + json.dumps({"jsonArray": itens}) + "</script>"
        f"<script>var request = {{ currentPage : 1, totalPages : {total_paginas}, "
        "delta : 75 }</script>")


def test_pagina_sem_o_bloco_e_falha_e_nao_zero():
    with pytest.raises(d.BuscaFalhou):
        d.ler_resultados("<html><body>Manutenção</body></html>")
    assert d.ler_resultados(_pagina([])) == ([], 1)


def test_busca_segue_o_cursor():
    pedidos = []
    p1 = [{"urlTitle": f"a-{i}", "classPK": str(i), "score": 0,
           "displayDateSortable": "1790046000000"} for i in range(75)]
    p2 = [{"urlTitle": "b-0", "classPK": "900", "score": 0,
           "displayDateSortable": "1789000000000"}]

    def responde(req: httpx.Request):
        pedidos.append(dict(req.url.params))
        corpo = _pagina(p2, 2) if req.url.params.get("newPage") == "2" else _pagina(p1, 2)
        return httpx.Response(200, text=corpo)

    from datetime import date
    with httpx.Client(transport=httpx.MockTransport(responde)) as c:
        todos = d.buscar(c, "Nova Palma", date(2026, 9, 1), date(2026, 9, 22))
    assert len(todos) == 76
    assert pedidos[0]["q"] == '"Nova Palma"'
    assert pedidos[0]["delta"] == "75"
    assert pedidos[0]["publishFrom"] == "01-09-2026"
    # a página 2 leva o cursor do ÚLTIMO item da página 1
    assert pedidos[1]["newPage"] == "2" and pedidos[1]["currentPage"] == "1"
    assert pedidos[1]["id"] == "74"
    assert pedidos[1]["displayDate"] == "1790046000000"


def test_user_agent_nao_e_o_do_httpx():
    """Armadilha 4: o UA padrão do httpx é derrubado sem resposta."""
    assert d.UA["User-Agent"].startswith("Mozilla/5.0")


# ---------------------------------------------------------------------------
# Página do ato
# ---------------------------------------------------------------------------
ATO_HTML = """
<div class="texto-dou"><html><head></head><body>
  <p class="identifica">PORTARIA Nº 3.006, DE 10 DE SETEMBRO DE 2026</p>
  <p class="ementa">Altera o artigo 1º da Portaria n.º 2598, que autorizou
     transferência de recursos ao Município de Nova Palma/RS.</p>
  <p class="dou-paragraph">Art. 1º ...</p>
  <table><tr><td>RS</td><td>431310</td><td>NOVA PALMA</td></tr></table>
  <p class="assina">FULANO</p>
</body></html></div>
<div class="informacao-conteudo-dou"><p>Este conteúdo não substitui</p></div>
"""


def test_ler_ato():
    a = d.ler_ato(ATO_HTML)
    assert a["identifica"] == "PORTARIA Nº 3.006, DE 10 DE SETEMBRO DE 2026"
    assert a["ementa"].startswith("Altera o artigo 1º")
    assert "RS 431310 NOVA PALMA" in " ".join(a["texto"].split())
    assert "não substitui" not in a["texto"]


def test_ato_sem_corpo_e_erro():
    with pytest.raises(ValueError):
        d.ler_ato("<html><body>erro</body></html>")


def test_linha_do_ato():
    hit = {"urlTitle": "portaria-n-3.006-731371992", "classPK": 731371994,
           "pubName": "DO1", "editionNumber": "173", "numberPage": "40",
           "pubDate": "14/09/2026", "artType": "Portaria",
           "hierarchyStr": "Ministério da Integração/SEDEC", "title": "PORTARIA"}
    linha = d.linha_ato(hit, d.ler_ato(ATO_HTML))
    assert str(linha["data_publicacao"]) == "2026-09-14"
    assert linha["class_pk"] == "731371994"
    assert linha["categoria"] == "repasse"


# ---------------------------------------------------------------------------
# Janela
# ---------------------------------------------------------------------------
def test_janela():
    from datetime import date, timedelta
    hoje = date(2026, 9, 22)
    assert d.janela(None, hoje) == hoje - timedelta(days=d.DIAS_INICIAL)
    assert d.janela(date(2026, 9, 21), hoje) == date(2026, 9, 21) - timedelta(
        days=d.DIAS_REVISAO)
    # parado há meses: não volta mais que DIAS_MAX
    assert d.janela(date(2026, 1, 1), hoje) == hoje - timedelta(days=d.DIAS_MAX)


def test_termos_de_busca():
    assert d.termos(NOVA_PALMA) == ["Nova Palma", "4313102", "431310"]


def test_travas_da_lista_nacional():
    cat = [("RS", "NOVA PALMA"), ("RS", "PALMA"), ("SC", "PALMA SOLA"),
           ("RS", "SANTA MARIA"), ("RN", "SANTA MARIA"), ("RS", "SANTA MARIA DO HERVAL")]
    t = d.travas(cat, "RS", "PALMA")
    assert t["antes"] == ["NOVA"] and t["depois"] == ["SOLA"] and t["unico"]
    t = d.travas(cat, "RS", "SANTA MARIA")
    assert not t["unico"] and t["depois"] == ["DO HERVAL"]
    assert d.travas(None, "RS", "PALMA") == {}
