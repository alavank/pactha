"""
TCE-RS pelo portal — os testes travam as armadilhas que corrompem dado em
silêncio, não a mecânica do parser.

Todas foram medidas contra `portal.tce.rs.gov.br` em 03/09/2026:

  (a) A REMESSA "LicitaCon WEB" É CARGA DO TCE, NÃO ENTREGA DO MUNICÍPIO. Nove
      órgãos de oito tipos, mesmo período, mesma data e mesmo horário. A fixture
      guarda o mês em que Nova Palma tem as duas coisas — quatro remessas do
      e-Validador (datas espalhadas por agosto: envio real) e uma WEB (08/09
      05:19, igual à de todo mundo). Um teste que confundisse as duas colocaria
      "entregue em dia" numa tela sem que ninguém tenha entregue nada.

  (b) `tp_situacao` E `origem` SÃO OBRIGATÓRIOS, E OS VALORES SÃO A/E/ALL E
      WEB/VAL/ALL. Com valor inventado o endpoint responde 200 e lista vazia —
      foi o que fez o reconhecimento de 03/09 concluir que ele não servia.

  (c) A LISTA NÃO TEM VALOR; SÓ O DETALHE TEM. Montar a linha sem detalhe tem de
      deixar o valor NULO, nunca zero: zero afirma que a prefeitura contratou de
      graça.

  (d) A PENDÊNCIA DE DETALHE PRECISA FECHAR. Se a versão gravada não for
      exatamente a que a próxima rodada compara, o coletor rebusca o mesmo
      contrato todas as noites, para sempre, sem nunca avançar na fila.

  (e) A PLANILHA ORÇAMENTÁRIA NÃO VAI PARA O BANCO — são 217 itens e 148 KB numa
      obra só, em cinco tenants, para nunca ser lida.

  (f) OS DOIS PERCENTUAIS DE EXECUÇÃO DIVERGEM (90,6% financeiro contra 0,0%
      físico na mesma obra) e não podem ser trocados um pelo outro.

Rodar:
    python -m pytest backend/tests/test_tce_rs_portal.py -v
"""
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from ingestion.tce_rs_portal import (
    _CHAVE, _contrato_da_obra, _dt, _pagina_tudo, _pendentes_de_detalhe,
    _raw_enxuto, _tp_documento, contratos, licitacoes, linha_contrato,
    linha_licitacao, linha_obra, linha_recurso, linha_remessa,
    orgaos_do_municipio,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _fx(nome):
    return json.loads((FIXTURES / nome).read_text(encoding="utf-8"))


ORGAOS = _fx("tce_rs_portal_orgaos.json")
LICITACOES = _fx("tce_rs_portal_licitacoes.json")
CONTRATOS = _fx("tce_rs_portal_contratos.json")
CONTRATO_DET = _fx("tce_rs_portal_contrato_detalhe.json")
REMESSAS = _fx("tce_rs_portal_remessas.json")
OBRAS = _fx("tce_rs_portal_obras.json")
OBRA_DET = _fx("tce_rs_portal_obra_detalhe.json")


class ClienteFalso:
    """Devolve o que se mandar e guarda os parâmetros de cada chamada."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.chamadas.append((url, dict(params or {})))
        corpo = self.respostas.pop(0) if self.respostas else []

        class R:
            status_code = 200

            @staticmethod
            def json():
                return corpo

        return R()


# ---------------------------------------------------------------------------
# (a) A remessa WEB é do Tribunal, não do município
# ---------------------------------------------------------------------------
def test_a_remessa_web_e_a_do_evalidador_nao_se_confundem():
    """O mês em que Nova Palma tem as duas: quatro envios reais e uma carga.

    ⚠️ É o teste que impede a tela de dizer "entregou em dia" olhando a data
    errada. O tipo tem de sobreviver intacto até a linha do banco."""
    linhas = [linha_remessa(1, r) for r in REMESSAS]
    web = [x for x in linhas if x["tipo"] == "LicitaCon WEB"]
    validador = [x for x in linhas if "Validador" in x["tipo"]]

    assert len(web) == 1, "a carga mensal do TCE é uma só"
    assert len(validador) == 4, "os envios do órgão são quatro"

    # A carga do TCE chega no mês SEGUINTE ao período; os envios do órgão, dentro
    # do próprio mês. É essa diferença que distingue as duas naturezas.
    assert web[0]["dt"].month == 9 and web[0]["periodo"] == 8
    assert all(v["dt"].month == 8 for v in validador)


def test_a_remessa_guarda_o_responsavel_com_o_typo_da_fonte():
    """`NOME_REPONSAVEL_ORGAO` — sem o 'S'. Ler o nome correto devolve NULL."""
    linha = linha_remessa(1, REMESSAS[-1])
    assert linha["resp"], "o responsável não pode sumir por causa do typo"
    assert linha["rve"], "sem RVE a remessa não tem identidade e o UPSERT colide"


def test_remessa_sem_rve_nao_quebra_a_chave():
    """RVE ausente vira '-' em vez de NULL: a coluna é NOT NULL na chave."""
    assert linha_remessa(1, {"CD_ORGAO": "53100", "ANO_EXERCICIO": 2026,
                             "PERIODO_MES": 1})["rve"] == "-"


# ---------------------------------------------------------------------------
# (b) Os parâmetros obrigatórios, com os valores que a fonte aceita
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("funcao", [licitacoes, contratos])
def test_lista_pede_todas_as_situacoes_e_todas_as_origens(funcao):
    cli = ClienteFalso([[]])
    funcao(cli, "53100")
    _, params = cli.chamadas[0]
    assert params["tp_situacao"] == "ALL"
    assert params["origem"] == "ALL"
    assert params["cd_orgao"] == "53100"


def test_paginacao_para_quando_a_pagina_vem_incompleta():
    cheia = [{"x": i} for i in range(1000)]
    cli = ClienteFalso([cheia, [{"x": "ultimo"}]])
    fora = _pagina_tudo(cli, "licitacon.contratos", cd_orgao="53100")
    assert len(fora) == 1001
    assert len(cli.chamadas) == 2
    assert cli.chamadas[1][1]["offset"] == 1000


def test_orgao_inexistente_devolve_vazio_sem_explodir():
    """⚠️ HTTP 200 com `[]` é a resposta da fonte para órgão que não existe.

    Vazio não é erro — mas quem chama precisa saber que é vazio, e não receber
    uma exceção que o log leria como falha de rede."""
    assert _pagina_tudo(ClienteFalso([[]]), "licitacon.contratos",
                        cd_orgao="99999") == []


# ---------------------------------------------------------------------------
# O de-para oficial: a Câmara não é o cliente
# ---------------------------------------------------------------------------
def test_depara_escolhe_a_prefeitura_e_nao_a_camara():
    cli = ClienteFalso([ORGAOS])
    achado = orgaos_do_municipio(cli, "4313102")
    assert achado["executivo"]["CD_ORGAO"] == "53100"
    assert achado["executivo"]["NOME"].startswith("PM DE")
    # A Câmara (53101) existe, tem código próprio e fica FORA da coleta — mas
    # aparece em "outros", para a decisão de incluí-la ser tomada, não esquecida.
    assert any(o["CD_ORGAO"] == "53101" for o in achado["outros"])


def test_depara_traz_as_autarquias_do_municipio_maior():
    achado = orgaos_do_municipio(ClienteFalso([ORGAOS]), "4316907")
    assert achado["executivo"]["CD_ORGAO"] == "56900"
    nomes = {o["CD_ORGAO"] for o in achado["outros"]}
    assert "56901" in nomes, "a Câmara de Santa Maria"
    assert len(nomes) >= 3, "IPLAN, IPASSP e o consórcio também são do município"


def test_depara_de_municipio_sem_orgao_devolve_none_em_vez_de_chutar():
    achado = orgaos_do_municipio(ClienteFalso([ORGAOS]), "3106200")  # BH/MG
    assert achado["executivo"] is None
    assert achado["outros"] == []


# ---------------------------------------------------------------------------
# (c) Valor: só no detalhe, e vazio continua vazio
# ---------------------------------------------------------------------------
def test_contrato_sem_detalhe_fica_com_valor_nulo_e_nao_zero():
    linha = linha_contrato(1, "PM DE NOVA PALMA", CONTRATOS[0])
    assert linha["vl"] is None, "zero afirmaria que contratou de graça"
    assert linha["vl_atual"] is None
    assert linha["nr_doc"] is None and linha["contratado"] is None
    # O que a lista TEM continua vindo.
    assert linha["obj"] and linha["ds_sit"] and linha["ano"]


def test_contrato_com_detalhe_traz_os_dois_valores_separados():
    linha = linha_contrato(1, None, CONTRATOS[0], CONTRATO_DET)
    assert linha["vl"] == CONTRATO_DET["VALOR_INICIAL"]
    assert linha["vl_atual"] == CONTRATO_DET["VALOR_ATUAL"]
    assert linha["contratado"] == CONTRATO_DET["CONTRATADO"]
    assert linha["dt_ass"] == date(2026, 8, 31)


def test_licitacao_nao_tem_valor_em_lugar_nenhum_desta_api():
    """⚠️ Nem na lista (15 campos) nem no detalhe (27). `vl_licitacao` e
    `vl_homologado` só existem no CKAN — e por isso o UPSERT daqui NÃO menciona
    esses dois campos, para não apagar o que o outro coletor tenha gravado."""
    from ingestion.tce_rs_portal import _SQL_LIC
    assert "vl_licitacao" not in _SQL_LIC
    assert "vl_homologado" not in _SQL_LIC
    assert set(LICITACOES[0]) & {"VL_LICITACAO", "VL_HOMOLOGADO"} == set()


def test_documento_do_contratado_sai_do_tamanho():
    assert _tp_documento("94573169000184") == "J"
    assert _tp_documento("12345678901") == "F"
    assert _tp_documento("123") is None, "chutar o tipo é pior que deixar nulo"
    assert _tp_documento(None) is None


# ---------------------------------------------------------------------------
# (d) A fila de detalhe tem de esvaziar
# ---------------------------------------------------------------------------
def test_pendencia_de_detalhe_fecha_depois_de_buscada():
    """⚠️ O teste que impede o laço eterno.

    A versão gravada é a `DATA_ATUALIZACAO` da LISTA. Se a comparação usasse a
    do detalhe e as duas divergissem, todo contrato voltaria à fila toda noite."""
    lista = CONTRATOS
    versoes = {}
    pendentes = _pendentes_de_detalhe(lista, versoes, "contratos")
    assert len(pendentes) == len(lista), "sem detalhe nenhum, tudo é pendência"

    # Simula a gravação: `detalhe_da_versao` recebe o que `linha_contrato` põe
    # em "versao" quando há detalhe.
    for r in lista:
        linha = linha_contrato(1, None, r, CONTRATO_DET)
        versoes[_CHAVE["contratos"](r)] = linha["versao"]

    assert _pendentes_de_detalhe(lista, versoes, "contratos") == []


def test_contrato_que_mudou_na_fonte_volta_para_a_fila():
    r = dict(CONTRATOS[0])
    versoes = {_CHAVE["contratos"](r): _dt(r["DATA_ATUALIZACAO"])}
    assert _pendentes_de_detalhe([r], versoes, "contratos") == []

    r["DATA_ATUALIZACAO"] = "2026-09-02 10:00:00"
    assert _pendentes_de_detalhe([r], versoes, "contratos") == [r]


def test_em_andamento_vem_antes_na_fila():
    """O contrato vigente é o que o gestor precisa hoje; se o orçamento acabar
    no meio, é ele que já tem de estar pronto."""
    encerrado = {"NR_CONTRATO": 1, "ANO_CONTRATO": 2026, "TP_INSTRUMENTO": "C",
                 "TP_SITUACAO_CONTRATO": "E", "DATA_ATUALIZACAO": "2026-01-01 00:00:00"}
    vigente = {"NR_CONTRATO": 2, "ANO_CONTRATO": 2016, "TP_INSTRUMENTO": "C",
               "TP_SITUACAO_CONTRATO": "A", "DATA_ATUALIZACAO": "2026-01-01 00:00:00"}
    fila = _pendentes_de_detalhe([encerrado, vigente], {}, "contratos")
    assert fila[0] is vigente, "vigente de 2016 vem antes de encerrado de 2026"


def test_licitacao_tem_seu_proprio_campo_de_situacao():
    """⚠️ Contrato usa `TP_SITUACAO_CONTRATO`; licitação usa `TP_SITUACAO`.
    Ler o campo errado põe toda a fila na mesma prioridade, em silêncio."""
    andando = {"NR_LICITACAO": 9, "ANO_LICITACAO": 2020,
               "CD_TIPO_MODALIDADE": "PRE", "TP_SITUACAO": "A",
               "DATA_ATUALIZACAO": "2026-01-01 00:00:00"}
    fechada = {"NR_LICITACAO": 8, "ANO_LICITACAO": 2026,
               "CD_TIPO_MODALIDADE": "PRE", "TP_SITUACAO": "E",
               "DATA_ATUALIZACAO": "2026-01-01 00:00:00"}
    assert _pendentes_de_detalhe([fechada, andando], {}, "licitacoes")[0] is andando


def test_chave_separa_contrato_de_ata_do_mesmo_numero():
    """O número é sequencial POR TIPO: existe contrato 15 e ata 15 no mesmo ano."""
    contrato = {"NR_CONTRATO": 15, "ANO_CONTRATO": 2026, "TP_INSTRUMENTO": "C"}
    ata = {"NR_CONTRATO": 15, "ANO_CONTRATO": 2026, "TP_INSTRUMENTO": "ARP"}
    assert _CHAVE["contratos"](contrato) != _CHAVE["contratos"](ata)


def test_chave_separa_modalidades_do_mesmo_numero():
    pregao = {"NR_LICITACAO": 36, "ANO_LICITACAO": 2023, "CD_TIPO_MODALIDADE": "PRP"}
    dispensa = {"NR_LICITACAO": 36, "ANO_LICITACAO": 2023, "CD_TIPO_MODALIDADE": "PRD"}
    assert _CHAVE["licitacoes"](pregao) != _CHAVE["licitacoes"](dispensa)


# ---------------------------------------------------------------------------
# (e) e (f) A obra
# ---------------------------------------------------------------------------
def test_planilha_orcamentaria_nao_vai_para_o_raw():
    """⚠️ 217 itens e 148 KB por obra, em cinco bancos, para nunca serem lidos.

    O que fica é a CONTAGEM — que responde "a planilha foi enviada?" sem
    carregar a planilha."""
    enxuto = _raw_enxuto(OBRA_DET)
    for lote in enxuto["PLANILHA_CONTRATUAL_LOTES"]:
        assert "PLANILHA_CONTRATUAL_ITENS" not in lote
        assert lote["QT_ITENS_PLANILHA"] >= 0
    assert len(json.dumps(enxuto)) < len(json.dumps(OBRA_DET))
    # E o que importa continua lá.
    assert enxuto["ORIGEM_RECURSOS"]


def test_os_dois_percentuais_sao_gravados_separados():
    """Na obra 436: financeiro 90,6% e físico 0,0. O órgão mede o pagamento e
    não alimenta o avanço físico — trocar um pelo outro inventa execução."""
    linha = linha_obra(1, OBRAS[0], OBRA_DET)
    assert linha["pc_fin"] == pytest.approx(90.629546)
    assert linha["pc_exec"] == 0.0
    assert linha["pc_fin"] != linha["pc_exec"]


def test_obra_sem_detalhe_nao_inventa_medicao():
    linha = linha_obra(1, OBRAS[0])
    assert linha["qt_med"] is None, "None é 'não perguntei'; 0 seria 'não mediu'"
    assert linha["vl_medido"] is None
    assert linha["raw"] is None
    assert linha["obj"], "o que a lista tem continua vindo"


def test_obra_liga_no_contrato_pelo_texto():
    """⚠️ O Queryon manda 'Contrato 122/2024' como TEXTO, não como os três campos
    da chave. Sem essa conversão a obra não encontra o contrato que a pagou.

    A fixture é o par real: a obra 436 da lista e o detalhe da mesma 436."""
    assert OBRAS[0]["ID_OBRA"] == OBRA_DET["ID_OBRA"] == 436
    linha = linha_obra(1, OBRAS[0], OBRA_DET)
    assert (linha["nr_con"], linha["ano_con"], linha["tp_inst"]) == (122, 2024, "C")
    assert _contrato_da_obra({"DS_CONTRATO": "Contrato 27/2024"}) == (27, 2024, "C")


def test_elo_com_o_contrato_prefere_nulo_a_chute():
    for ds in ("", "sem numero", "Contrato /", "Contrato 12/99999"):
        assert _contrato_da_obra({"DS_CONTRATO": ds})[1] is None, ds
    # Instrumento que não é contrato fica sem código em vez de virar 'C'.
    assert _contrato_da_obra({"DS_CONTRATO": "Ata 5/2025"}) == (5, 2025, None)


def test_origem_do_recurso_e_o_elo_com_o_convenio():
    """A razão de existir de toda a coleta de obras: a obra 436 declara ao
    próprio Tribunal que foi paga por convênio federal do MIDR."""
    recursos = OBRA_DET["ORIGEM_RECURSOS"]
    linha = linha_recurso(1, 436, recursos[0])
    assert linha["cod"] == "FDL"
    assert "Federal" in linha["ds_tp"]
    assert linha["vl"] > 0
    assert linha["convenio"], "o número do convênio/processo é o elo"
    assert linha["data"] == date(2025, 7, 30)


def test_contrapartida_le_o_typo_da_fonte():
    """`VL_CONTRATAPARTIDA` — com o 'TA' no meio. É assim que a fonte manda."""
    assert linha_recurso(1, 1, {"VL_CONTRATAPARTIDA": 1234.5})["contrapartida"] == 1234.5
    assert linha_recurso(1, 1, {"VL_CONTRAPARTIDA": 999})["contrapartida"] is None


# ---------------------------------------------------------------------------
# Conversores
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bruto,esperado", [
    ("2026-08-31 15:09:50", datetime(2026, 8, 31, 15, 9, 50)),
    ("2026-08-31", datetime(2026, 8, 31)),
    ("", None), (None, None), ("nao e data", None),
])
def test_data_hora(bruto, esperado):
    assert _dt(bruto) == esperado


def test_acento_sobrevive_da_fixture_a_linha():
    """A API serve UTF-8 correto (`Content-Type: charset=UTF-8`, bytes c3 a9). O
    console do Windows renderiza isso como caixinha e o mojibake como se
    estivesse certo — quem confere pelo terminal conclui o oposto da verdade."""
    objeto = linha_licitacao(1, None, LICITACOES[0])["obj"]
    assert "Ã" not in objeto, "mojibake: leram UTF-8 como latin-1"
    assert any(c in objeto for c in "áéíóúâêôãõçÁÉÍÓÚÂÊÔÃÕÇ"), objeto
