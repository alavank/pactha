"""O relatório de Parlamentares no MODELO DA PLANILHA do cliente — a LÓGICA
(`services/relatorio_parlamentares.py`), sem banco e sem PDF (24/09/2026).

O modelo é `EmendasNikolasFerreiraBomDespacho.xlsx` (aba "Emendas por
categoria"), lido com openpyxl. As duas linhas dele são a referência
INDEPENDENTE destes testes — os textos esperados abaixo foram copiados da
planilha, não do código:

    SAÚDE           BOM DESPACHO | 2025 | Incremento MAC | Ministério da Saúde |
                    450.000,00 | Proposta: 36000679587202500 |
                    Pagamento realizado em 18/11/2025.
    INFRAESTRUTURA  BOM DESPACHO | 2024 | Reforma da quadra esportiva – Rua Padre
                    João, 274, bairro de Fátima (Transferência especial –
                    Investimento) | Ministério da Fazenda | 400.000,00 |
                    Plano de Ação: 09032024-070446 |
                    Pagamento realizado em 13/12/2024. ...

As regras de ÁREA usam, além disso, a CAPTURA REAL da API da Transferência
Especial (`fixtures/te_especiais_arvore.json`): as finalidades dos planos 67457
e 91573 e o órgão de cada programa.
"""
import pytest

from services.relatorio_parlamentares import (
    GRUPO_NAO_RECURSO, GRUPO_SEM_INSTRUMENTO, OUTROS, area_por_funcoes, area_por_orgao,
    fmt_valor, linha_estadual, linha_fns, linha_pac, linha_voluntaria, linhas_do_detalhe,
    ministerio_siafi, montar_bloco, pares_de_funcao,
)
from tests.test_te_arvore import PLANO_67457, PLANO_91573, _arvore

# ---------------------------------------------------------------------------
# As duas linhas do MODELO, no formato que `detalhe_core` devolve
# ---------------------------------------------------------------------------
FNS_MODELO = {
    "id": 1, "municipio_id": 7, "municipio_nome": "Bom Despacho",
    "numero": "36000679587202500", "objeto": "INCREMENTO MAC - MAC — Proc 25000.1",
    "situacao": "PROPOSTA PAGA", "valor_total": 450000.0, "orgao": "MS - FNS",
    "ano": 2025, "vl_pago": 450000.0, "vl_pagar": 0.0, "data_pagamento": "18/11/2025",
    # O `coTipoProposta` como a fonte grava (caixa alta): o "Incremento MAC" do
    # modelo tem de sair da padronização, não da fixture.
    "tipo_proposta": "INCREMENTO MAC", "tipo_recurso": "MAC", "fonte": "fns",
}
TE_MODELO = {
    "id": 70446, "municipio_id": 7, "municipio_nome": "Bom Despacho",
    "codigo": "09032024-070446", "emenda": "202437080004", "situacao": "CIENTE",
    "objeto": "27-Desporto e Lazer / 812-Desporto Comunitário",
    "valor_total": 400000.0, "valor_custeio": 0.0, "valor_investimento": 400000.0,
    "execucao": "Pago", "execucao_estado": "pago", "execucao_consultada": True,
    "valor_pago": 400000.0, "dt_ultimo_pagamento": "13/12/2024", "ano": 2024,
    "orgao_programa": "Ministério da Fazenda",
    "relatorio_gestao": ("Relatório de gestão final: Disponibilizado em 30/12/2025; "
                         "nenhuma análise registrada."),
    "objetos_executor": ["Reforma da quadra esportiva – Rua Padre João, 274, bairro de Fátima"],
    "funcoes": [[27, 812]], "fonte": "plano_acao",
}


def _det(**kw):
    base = {"sigcon": [], "voluntarias": [], "emendas": [], "plano_acao": [], "pac": [],
            "fns": [], "emendas_federais": []}
    base.update(kw)
    return base


def test_o_modelo_da_planilha_sai_igual():
    b = montar_bloco("Nikolas Ferreira", _det(fns=[FNS_MODELO], plano_acao=[TE_MODELO]),
                     "BOM DESPACHO")
    assert b["titulo"] == "RECURSOS PAGOS BOM DESPACHO – EMENDAS INDICADAS POR NIKOLAS FERREIRA"
    assert [a["area"] for a in b["areas"]] == ["SAÚDE", "INFRAESTRUTURA"]
    assert [a["subtotal"] for a in b["areas"]] == [450000.0, 400000.0]
    assert b["total"] == 850000.0
    assert b["fora"] == []

    (fns,), (te,) = b["areas"][0]["linhas"], b["areas"][1]["linhas"]
    assert (fns["municipio"], fns["ano"], fns["recurso"], fns["ministerio"],
            fmt_valor(fns["valor"]), fns["referencias"], fns["situacao"]) == (
        "BOM DESPACHO", 2025, "Incremento MAC", "Ministério da Saúde", "450.000,00",
        ["Proposta: 36000679587202500"], "Pagamento realizado em 18/11/2025.")
    assert (te["municipio"], te["ano"], te["recurso"], te["ministerio"],
            fmt_valor(te["valor"]), te["referencias"]) == (
        "BOM DESPACHO", 2024,
        "Reforma da quadra esportiva – Rua Padre João, 274, bairro de Fátima "
        "(Transferência especial – Investimento)",
        "Ministério da Fazenda", "400.000,00", ["Plano de Ação: 09032024-070446"])
    # O modelo escreve "Aguardando análise do relatório de gestão."; a fonte não
    # tem esse estado — a frase diz o que ela diz (ver execucao_te).
    assert te["situacao"].startswith("Pagamento realizado em 13/12/2024. Relatório de gestão final")


# ---------------------------------------------------------------------------
# "PAGOS" só com tudo pago
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("det", [
    _det(fns=[FNS_MODELO], plano_acao=[dict(TE_MODELO, execucao_estado="pago_parte",
                                            valor_pago=100000.0)]),
    _det(fns=[dict(FNS_MODELO, vl_pagar=50000.0)], plano_acao=[TE_MODELO]),
    _det(plano_acao=[dict(TE_MODELO, execucao_estado="nao_consultada")]),
    _det(fns=[FNS_MODELO], sigcon=[{"municipio_id": 7, "municipio_nome": "Bom Despacho",
                                    "numero": "1", "valor_total": 10.0, "situacao": "Concluído"}]),
    # tudo pago na conta, mas há emenda FORA do total: não se afirma "pagos"
    _det(fns=[FNS_MODELO], emendas_federais=[{"municipio_id": 7, "codigo_emenda": "202511110001",
                                              "valor_total": 1.0}]),
    _det(),
])
def test_pagos_so_com_tudo_pago(det):
    b = montar_bloco("Fulano", det, "BOM DESPACHO")
    assert b["titulo"] == "RECURSOS PARA BOM DESPACHO – EMENDAS INDICADAS POR FULANO"
    assert b["todas_pagas"] is False


def test_sem_municipio_o_titulo_diz_todos():
    b = montar_bloco("Fulano", _det(fns=[FNS_MODELO]), "TODOS OS MUNICÍPIOS")
    assert b["titulo"] == "RECURSOS PAGOS TODOS OS MUNICÍPIOS – EMENDAS INDICADAS POR FULANO"


# ---------------------------------------------------------------------------
# NÃO CONTAR O MESMO DINHEIRO DUAS VEZES
# ---------------------------------------------------------------------------
CONV = {"id": 5, "municipio_id": 7, "municipio_nome": "Bom Despacho", "numero": "1301234",
        "objeto": "PAVIMENTACAO DE VIAS", "situacao": "EM EXECUCAO", "valor_total": 500000.0,
        "orgao": "SECRETARIA DE ESTADO DE INFRAESTRUTURA", "ano": 2024,
        "indicacoes": ["2024/123"], "fonte": "sigcon"}
IND = {"id": 9, "municipio_id": 7, "municipio_nome": "Bom Despacho", "nr_indicacao": "2024/123",
       "ano": 2024, "beneficiario": "MUNICIPIO DE BOM DESPACHO", "tipo_atendimento": "Obras",
       "valor_indicacao": 500000.0, "status_indicacao": "Convênio celebrado",
       "uo_sigla": "SEINFRA", "valor_pago": None, "fonte": "emenda"}


def test_indicacao_estadual_executada_por_convenio_do_bloco_nao_soma_duas_vezes():
    b = montar_bloco("Fulano", _det(sigcon=[CONV], emendas=[IND]), "BOM DESPACHO")
    linhas = [l for a in b["areas"] for l in a["linhas"]]
    assert len(linhas) == 1 and linhas[0]["fonte"] == "sigcon"
    assert linhas[0]["referencias"] == ["Convênio: 1301234", "Indicação: 2024/123"]
    assert b["total"] == 500000.0


def test_indicacao_sem_convenio_no_bloco_continua_sua():
    """Sem o convênio no bloco, a indicação é o único registro do dinheiro — não
    pode sumir junto com a duplicata."""
    outro_mun = dict(CONV, municipio_id=8)          # mesmo nº, OUTRO município
    b = montar_bloco("Fulano", _det(sigcon=[outro_mun], emendas=[IND]), "X")
    fontes = sorted(l["fonte"] for a in b["areas"] for l in a["linhas"])
    assert fontes == ["emenda", "sigcon"]
    assert b["total"] == 1000000.0


# Achado 3 da revisão do 248361f — o caso real: Araújos, convênio 002567/2026 da
# SEAPA, R$ 0,00, "Cadastramento" (o mesmo que o RM já tirava: `_em_cadastramento`).
CONV_CADASTRO = {"id": 11, "municipio_id": 7, "municipio_nome": "Araújos",
                 "numero": "002567/2026", "objeto": "AQUISICAO DE TRATOR",
                 "situacao": "Cadastramento", "valor_total": 0.0, "orgao": "SEAPA",
                 "ano": 2026, "indicacoes": ["2026/77"], "fonte": "sigcon"}
IND_SEAPA = {"id": 12, "municipio_id": 7, "municipio_nome": "Araújos", "nr_indicacao": "2026/77",
             "ano": 2026, "beneficiario": "MUNICIPIO DE ARAUJOS",
             "tipo_atendimento": "Equipamentos", "valor_indicacao": 300000.0,
             "status_indicacao": "Aguardando celebração", "uo_sigla": "SEAPA",
             "valor_pago": None, "fonte": "emenda"}


@pytest.mark.parametrize("conv,fora", [
    (CONV_CADASTRO, True),                                          # o caso real: R$ 0
    (dict(CONV_CADASTRO, valor_total=300000.0), True),              # cadastramento com valor
    (dict(CONV_CADASTRO, situacao="RESCINDIDO", valor_total=300000.0), True),
    (dict(CONV_CADASTRO, situacao="CANCELADO", valor_total=300000.0), True),
    (dict(CONV_CADASTRO, situacao="EM EXECUCAO", valor_total=0.0), False),  # vivo, sem valor
])
def test_convenio_que_nao_conta_com_valor_nao_apaga_a_indicacao(conv, fora):
    """Só o convênio que fica no total E tem valor toma o lugar da indicação. Os
    outros apareciam, e a indicação — o único registro do dinheiro — sumia."""
    b = montar_bloco("Fulano", _det(sigcon=[conv], emendas=[IND_SEAPA]), "ARAÚJOS")
    no_total = [l for a in b["areas"] for l in a["linhas"]]
    (ind,) = [l for l in no_total if l["fonte"] == "emenda"]
    assert ind["valor"] == 300000.0 and b["total"] == 300000.0
    de_fora = [l for g in b["fora"] for l in g["linhas"]]
    (c,) = [l for l in no_total + de_fora if l["fonte"] == "sigcon"]
    assert (c in de_fora) is fora
    # o convênio que não venceu não carrega a indicação nas referências
    assert c["referencias"] == ["Convênio: 002567/2026"]


def test_convenio_em_cadastramento_fica_fora_do_total_e_o_cadastrado_nao():
    (l,) = linhas_do_detalhe(_det(sigcon=[dict(CONV_CADASTRO, valor_total=10.0)]))
    assert l["fora"] == GRUPO_NAO_RECURSO
    # "CONVÊNIO CADASTRADO" é o celebrado do backfill do CKAN — a palavra
    # inteira do RM (`_em_cadastramento`), não a substring "cadastr".
    (l,) = linhas_do_detalhe(_det(sigcon=[dict(CONV_CADASTRO, situacao="CONVENIO CADASTRADO",
                                               valor_total=10.0)]))
    assert l["fora"] is None


def test_selecao_do_pac_que_virou_a_voluntaria_nao_se_repete():
    vol = {"municipio_id": 7, "municipio_nome": "Bom Despacho", "numero_proposta": "034595/2025",
           "objeto": "CONSTRUCAO DE UBS", "situacao": "Em execução", "valor_global": 900000.0,
           "orgao": "MINISTERIO DA SAUDE", "pac_origem": "36000004633/2025", "fonte": "voluntaria"}
    pac = {"municipio_id": 7, "municipio_nome": "Bom Despacho",
           "numero_proposta": "36000004633/2025 ", "programa": "Novo PAC Saúde",
           "situacao": "Selecionada", "valor_total": 900000.0, "fonte": "pac"}
    b = montar_bloco("Fulano", _det(voluntarias=[vol], pac=[pac]), "X")
    linhas = [l for a in b["areas"] for l in a["linhas"]]
    assert [l["fonte"] for l in linhas] == ["voluntaria"]
    assert "Novo PAC: 36000004633/2025" in linhas[0]["referencias"]
    assert b["total"] == 900000.0 and b["fora"] == []


def test_carteira_cgu_sem_instrumento_fica_fora_do_total():
    """A emenda da carteira que sobrou do desconto de `detalhe_core` pode ser o
    MESMO dinheiro da proposta do FNS — que não foi casada pelo nº da emenda
    nesta base. Fica numa seção própria, e o total geral não muda com ela."""
    carteira = {"municipio_id": 7, "municipio_nome": "Bom Despacho",
                "codigo_emenda": "202537080010", "ano": 2025, "orgao_siafi": "36000",
                "beneficiario_nome": "FUNDO MUNICIPAL DE SAUDE", "valor_total": 450000.0}
    sem = montar_bloco("Fulano", _det(fns=[FNS_MODELO]), "X")
    com = montar_bloco("Fulano", _det(fns=[FNS_MODELO], emendas_federais=[carteira]), "X")
    assert com["total"] == sem["total"] == 450000.0
    (g,) = com["fora"]
    assert g["grupo"] == GRUPO_SEM_INSTRUMENTO and g["soma"] == 450000.0
    assert g["linhas"][0]["ministerio"] == "Ministério da Saúde"
    assert g["linhas"][0]["referencias"] == ["Emenda: 202537080010"]


@pytest.mark.parametrize("fonte,item", [
    ("pac", {"numero_proposta": "56000000001/2025", "situacao": "Não Selecionada",
             "valor_total": 10.0}),
    ("plano_acao", dict(TE_MODELO, situacao="IMPEDIDO")),
    ("voluntarias", {"numero_proposta": "1/2024", "situacao": "Proposta/Plano de Trabalho Rejeitados",
                     "valor_global": 10.0, "orgao": "MINISTERIO DAS CIDADES"}),
    ("sigcon", {"numero": "2", "situacao": "CANCELADO", "valor_total": 10.0}),
    ("emendas", {"nr_indicacao": "9", "status_indicacao": "Cancelada", "valor_indicacao": 10.0}),
])
def test_o_que_nao_e_recurso_aparece_mas_fora_do_total(fonte, item):
    b = montar_bloco("Fulano", _det(**{fonte: [dict(item, municipio_id=7)]}), "X")
    assert b["total"] is None and b["areas"] == []
    assert [g["grupo"] for g in b["fora"]] == [GRUPO_NAO_RECURSO]


@pytest.mark.parametrize("situacao", [
    "PROPOSTA ARQUIVADA", "Proposta Bloqueada", "PROPOSTA REJEITADA", "Proposta Cancelada",
])
def test_proposta_do_fns_arquivada_ou_bloqueada_fica_fora_do_total(situacao):
    """A regra do RM para o FNS (`_fns_classifica`), e não `_fed_status`, que não
    conhece "arquivad" nem "bloquead" — a ARQUIVADA entrava no total geral."""
    fns = dict(FNS_MODELO, situacao=situacao, vl_pago=0.0, vl_pagar=0.0)
    b = montar_bloco("Fulano", _det(fns=[fns]), "X")
    assert b["total"] is None and b["areas"] == []
    assert [g["grupo"] for g in b["fora"]] == [GRUPO_NAO_RECURSO]


@pytest.mark.parametrize("situacao", ["PROPOSTA ARQUIVADA", "Proposta Bloqueada"])
def test_fns_fora_do_total_com_repasse_diz_o_motivo_e_nao_conta_como_pago(situacao):
    """Revisão de 24/09/2026: ARQUIVADA/BLOQUEADA com vlPago saía só "Pagamento
    realizado em …" — sem o motivo, contradizendo a nota do grupo fora do total."""
    li = linha_fns(dict(FNS_MODELO, situacao=situacao, vl_pago=450000.0, vl_pagar=0.0,
                        data_pagamento="18/11/2025"))
    assert li["fora"] == GRUPO_NAO_RECURSO and li["pago"] is False
    assert li["situacao"].lower().startswith(situacao.lower()[:10])
    assert "Repasse registrado: R$ 450.000,00 em 18/11/2025." in li["situacao"]
    assert not li["situacao"].startswith("Pagamento realizado")


def test_proposta_do_fns_em_analise_continua_no_total():
    fns = dict(FNS_MODELO, situacao="EM ANALISE PELA AREA FINALISTICA", vl_pago=0.0)
    assert linha_fns(fns)["fora"] is None


def test_plano_impedido_diz_por_que_esta_fora():
    (l,) = linhas_do_detalhe(_det(plano_acao=[dict(TE_MODELO, situacao="IMPEDIDO")]))
    assert l["situacao"].startswith("Plano impedido no Transferegov.")


# ---------------------------------------------------------------------------
# ÁREAS — a regra explícita
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("pares,so_inv,area", [
    ([[27, 812]], True, "INFRAESTRUTURA"),     # a quadra do modelo: esporte-OBRA
    ([[27, 812]], False, "ESPORTE E LAZER"),   # esporte com custeio
    ([[10, 301]], False, "SAÚDE"),
    ([[12, 361]], False, "EDUCAÇÃO"),
    ([[8, 244]], False, "ASSISTÊNCIA SOCIAL"),
    ([[15, 451]], False, "INFRAESTRUTURA"),
    ([[26, 782]], False, "INFRAESTRUTURA"),
    ([[20, 608]], False, "AGRICULTURA"),
    ([[6, 182]], False, "SEGURANÇA"),
    ([[13, 392]], False, "CULTURA"),
    ([[23, 695]], False, "TURISMO"),
    ([[23, 691]], False, OUTROS),              # comércio que não é turismo
    ([[4, 122]], False, OUTROS),               # administração: fora da tabela
    ([[15, 451], [27, 812]], True, "INFRAESTRUTURA"),
    ([[6, 182], [27, 812]], False, OUTROS),    # duas áreas: na dúvida, OUTROS
    ([[10, 301], [4, 122]], False, OUTROS),
    ([], False, OUTROS),
])
def test_area_pela_funcao_orcamentaria(pares, so_inv, area):
    assert area_por_funcoes(pares, so_inv) == area


def _funcoes_da_arvore(arv):
    fins = [f for ex in arv["executores"] for f in ex["finalidades"]]
    return ([f["cd_area_politica_publica_tipo_pt"] for f in fins],
            [f["cd_area_politica_publica_pt"] for f in fins])


def test_areas_dos_dois_planos_reais():
    """67457 (Nova Palma): finalidades Defesa Civil + Desporto -> OUTROS.
    91573 (Araújos): Urbanismo / Infraestrutura Urbana -> INFRAESTRUTURA."""
    f, s = _funcoes_da_arvore(_arvore(PLANO_67457))
    assert pares_de_funcao(f, s) == [[6, 182], [27, 812]]
    assert area_por_funcoes(pares_de_funcao(f, s), False) == OUTROS
    f, s = _funcoes_da_arvore(_arvore(PLANO_91573))
    assert area_por_funcoes(pares_de_funcao(f, s), True) == "INFRAESTRUTURA"


def test_sem_arvore_as_areas_saem_do_texto_da_listagem():
    txt = PLANO_67457["codigo_descricao_areas_politicas_publicas_plano_acao"]
    assert pares_de_funcao([], [], txt) == [[27, 812], [15, 451], [6, 182], [15, 452],
                                            [20, 608], [26, 782]]
    assert pares_de_funcao(None, None, PLANO_91573[
        "codigo_descricao_areas_politicas_publicas_plano_acao"]) == [[15, 451]]
    assert pares_de_funcao("lixo", 3, "sem numero") == []


@pytest.mark.parametrize("orgao,objeto,area", [
    ("MINISTERIO DA SAUDE", None, "SAÚDE"),
    ("Ministério das Cidades", None, "INFRAESTRUTURA"),
    ("Ministério da Integração e do Desenvolvimento Regional", None, "INFRAESTRUTURA"),
    ("FUNDO NACIONAL DE DESENVOLVIMENTO DA EDUCACAO", None, "EDUCAÇÃO"),
    ("Ministério do Desenvolvimento e Assistência Social", None, "ASSISTÊNCIA SOCIAL"),
    ("MINISTERIO DA AGRICULTURA, PECUARIA E ABASTECIMENTO", None, "AGRICULTURA"),
    ("Ministério da Justiça e Segurança Pública", None, "SEGURANÇA"),
    ("Ministério do Turismo", None, "TURISMO"),
    ("Ministério da Cultura", None, "CULTURA"),
    ("Ministério do Esporte", "Construção de quadra poliesportiva", "INFRAESTRUTURA"),
    ("Ministério do Esporte", "Aquisição de material esportivo", "ESPORTE E LAZER"),
    ("SECRETARIA DE ESTADO DE CULTURA E TURISMO", None, OUTROS),   # duas áreas
    ("Ministério da Cidadania", None, OUTROS),                      # ambíguo
    ("Ministério da Defesa", None, OUTROS),
    ("FES Custeio (SES)", None, "SAÚDE"),                           # siglas de MG
    ("SEGOV -", None, OUTROS),
    ("", None, OUTROS), (None, None, OUTROS),
])
def test_area_pelo_orgao(orgao, objeto, area):
    assert area_por_orgao(orgao, objeto) == area


def test_fns_e_sempre_saude():
    l = linha_fns(dict(FNS_MODELO, tipo_proposta="CUSTEIO PAP"))
    assert l["area"] == "SAÚDE"
    assert l["recurso"] == "Custeio PAP"       # sigla do bloco, não "Custeio pap"


# ---------------------------------------------------------------------------
# SITUAÇÃO ATUAL por extenso — só o medido
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("campos,frase", [
    ({}, "Pagamento realizado em 18/11/2025."),
    ({"data_pagamento": None}, "Pagamento realizado (data não coletada)."),
    ({"vl_pago": 200000.0, "vl_pagar": 250000.0},
     "Pago em parte: R$ 200.000,00 de R$ 450.000,00; último pagamento em 18/11/2025."),
    ({"vl_pago": 0.0, "vl_pagar": 450000.0, "situacao": "EM ANALISE PELA AREA FINALISTICA"},
     "Em analise pela area finalistica."),
    ({"vl_pago": 0.0, "vl_pagar": 0.0, "situacao": None}, "Sem pagamento registrado."),
    ({"vl_pago": None, "vl_pagar": None, "situacao": None}, "Situação da proposta não informada."),
])
def test_situacao_do_fns(campos, frase):
    l = linha_fns(dict(FNS_MODELO, **campos))
    assert l["situacao"] == frase
    assert l["pago"] is frase.startswith("Pagamento realizado")


def test_fns_parte_do_autor_paga_em_parte_divide_pela_proposta():
    """A linha tem a PARTE do autor (R$ 250 mil de uma proposta de R$ 450 mil);
    o pagamento é da PROPOSTA — "R$ 200 mil de R$ 250 mil" seria falso."""
    l = linha_fns(dict(FNS_MODELO, valor_total=250000.0, valor_proposta=450000.0,
                       vl_pago=200000.0, vl_pagar=250000.0))
    assert l["valor"] == 250000.0 and l["pago"] is False
    assert l["situacao"] == ("Pago em parte: R$ 200.000,00 de R$ 450.000,00 da proposta; "
                             "último pagamento em 18/11/2025.")


VOL = {"municipio_id": 7, "municipio_nome": "Bom Despacho", "numero_proposta": "034595/2025",
       "codigo_instrumento": "981397", "objeto": "AQUISICAO DE PATRULHA MECANIZADA",
       "situacao": "Em execução", "valor_global": 350000.0,
       "orgao": "MINISTERIO DA AGRICULTURA E PECUARIA", "fonte": "voluntaria"}


@pytest.mark.parametrize("campos,fim,pago", [
    ({"desembolso_consultado": True, "valor_desembolsado": 350000.0,
      "valor_a_desembolsar": 0.0, "dt_ultimo_desembolso": "10/03/2026"},
     "Em execução. Pagamento realizado em 10/03/2026.", True),
    ({"desembolso_consultado": True, "valor_desembolsado": 100000.0,
      "valor_a_desembolsar": 250000.0, "dt_ultimo_desembolso": "10/03/2026"},
     "Em execução. Pago em parte: R$ 100.000,00 de R$ 350.000,00; último pagamento em 10/03/2026.",
     False),
    ({"desembolso_consultado": True, "valor_desembolsado": 0.0, "valor_a_desembolsar": 350000.0},
     "Em execução. Nenhum pagamento registrado.", False),
    # Nunca consultado: nada se diz do dinheiro — nem "sem pagamento", nem R$ 0.
    ({"desembolso_consultado": False}, "Em execução.", False),
])
def test_situacao_da_voluntaria(campos, fim, pago):
    l = linha_voluntaria(dict(VOL, **campos))
    assert l["situacao"] == fim and l["pago"] is pago
    assert l["referencias"] == ["Convênio: 981397", "Proposta: 034595/2025"]
    assert l["ano"] == 2025 and l["area"] == "AGRICULTURA"


@pytest.mark.parametrize("orgao,ministerio", [
    # O formato da voluntária: "CÓDIGO - NOME" (`transferegov_opendata._orgao`).
    ("36000 - MINISTERIO DA SAUDE", "Ministério da Saúde"),
    ("36211 - FUNASA", "Ministério da Saúde"),                  # órgão superior 36000
    ("26298 - FUNDO NACIONAL DE DESENVOLVIMENTO DA EDUCACAO",   # FNDE, autarquia
     "Ministério da Educação"),
    ("56000 - MINISTERIO DAS CIDADES", "Ministério das Cidades"),
    # Código que o mapa não conhece: o NOME como veio (sem o código), nada inventado.
    ("99000 - ORGAO QUE O MAPA NAO CONHECE", "Orgao Que o Mapa Nao Conhece"),
    # Revisão de 24/09/2026: o nome da FONTE vence o do mapa, que não muda com o
    # ano — antes saía "Ministério da Infraestrutura" (extinto em 2023) e
    # "Ministério da Economia" para o que a fonte chamou de Fazenda.
    ("39000 - MINISTERIO DOS TRANSPORTES", "Ministério dos Transportes"),
    ("25000 - MINISTERIO DA FAZENDA", "Ministério da Fazenda"),
    ("55000 - MINISTERIO DA CIDADANIA", "Ministério da Cidadania"),
    # O próprio ministério com o MESMO nome do mapa: o do mapa, que tem os acentos.
    ("53000 - MINISTERIO DA INTEGRACAO E DO DESENVOLVIMENTO REGIONAL",
     "Ministério da Integração e do Desenvolvimento Regional"),
    # Sem código: como antes.
    ("MINISTERIO DA AGRICULTURA E PECUARIA", "Ministerio da Agricultura e Pecuaria"),
    ("", "—"),
])
def test_ministerio_de_origem_da_voluntaria_sem_o_codigo(orgao, ministerio):
    assert linha_voluntaria(dict(VOL, orgao=orgao))["ministerio"] == ministerio


@pytest.mark.parametrize("pago,empenhado,fim,e_pago", [
    (500000.0, 500000.0, "Pago: R$ 500.000,00 (dados da SEGOV de 12/05/2026).", True),
    (100000.0, 500000.0,
     "Pago em parte: R$ 100.000,00 de R$ 500.000,00 (dados da SEGOV de 12/05/2026).", False),
    (0.0, 500000.0, "Empenhado, sem pagamento nos dados da SEGOV de 12/05/2026.", False),
    (0.0, 0.0, "Sem pagamento nos dados da SEGOV de 12/05/2026.", False),
    (None, None, "", False),        # a planilha não trouxe: nada se afirma
])
def test_situacao_da_indicacao_estadual(pago, empenhado, fim, e_pago):
    l = linha_estadual(dict(IND, valor_pago=pago, valor_empenhado=empenhado,
                            execucao_em="2026-05-12"))
    assert l["situacao"] == ("Convênio celebrado. " + fim).strip()
    assert l["pago"] is e_pago
    assert l["area"] == "INFRAESTRUTURA"     # SEINFRA


def test_indicacao_estadual_diz_o_objeto_quando_a_segov_traz():
    """A TE-MG não vira convênio: sem o objeto, a linha dizia só "Obras – Município
    de Bom Despacho". Sem objeto, a linha continua a de antes."""
    com = linha_estadual(dict(IND, objeto="CONSTRUÇÃO DA COBERTURA DA QUADRA POLIESPORTIVA"))
    sem = linha_estadual(IND)
    assert "quadra poliesportiva" in com["recurso"].lower()
    assert "Bom Despacho" in com["recurso"]
    assert sem["recurso"].startswith("Obras")
    assert com["area"] == sem["area"]          # a área continua pela UO/tipo


@pytest.mark.parametrize("uo,tipo,area", [
    ("SES", "Obras", "SAÚDE"),            # a obra da saúde é SAÚDE, não OUTROS
    ("SEE", "Obras", "EDUCAÇÃO"),
    ("SEINFRA", "Obras", "INFRAESTRUTURA"),
    ("SEGOV", "Obras", "INFRAESTRUTURA"),  # a UO não dá área: vale o tipo
    ("", "Obras", "INFRAESTRUTURA"),
    ("SEGOV", "Custeio", OUTROS),
])
def test_area_da_indicacao_estadual_pela_uo_antes_do_tipo(uo, tipo, area):
    assert linha_estadual(dict(IND, uo_sigla=uo, tipo_atendimento=tipo))["area"] == area


def test_pac_ministerio_pelo_codigo_do_programa():
    l = linha_pac({"municipio_id": 7, "numero_proposta": "56000004633/2025",
                   "programa_codigo": "5600020250001", "situacao": "Selecionada",
                   "objeto": "Construção de unidade habitacional", "valor_total": 10.0})
    assert l["ministerio"] == "Ministério das Cidades"
    assert l["area"] == "INFRAESTRUTURA" and l["fora"] is None
    assert l["situacao"] == "Seleção do Novo PAC: Selecionada."
    assert l["pago"] is False                 # seleção não é pagamento


@pytest.mark.parametrize("cod,nome", [
    ("36000", "Ministério da Saúde"), ("56000", "Ministério das Cidades"),
    ("54000", "Ministério do Turismo"), ("81000", "Ministério dos Direitos Humanos e Cidadania"),
    ("20000", "Presidência da República"), ("99999", "Órgão SIAFI 99999"), (None, None),
])
def test_ministerio_pelo_codigo_siafi(cod, nome):
    assert ministerio_siafi(cod) == nome


def test_valor_no_formato_do_modelo():
    assert fmt_valor(450000) == "450.000,00"
    assert fmt_valor(1234567.891) == "1.234.567,89"
    assert fmt_valor(None) == "—"
