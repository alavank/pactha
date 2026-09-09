"""Licitações pelo dado aberto — as armadilhas MEDIDAS no dump de 09/09/2026.

Este coletor existe para tirar do login gov.br a pergunta que mais pesa para o
município: *"assinou o convênio e já licitou?"*. Ele erra de três jeitos, e os
três são silenciosos:

  1. **Rótulo sumido.** `MODALIDADE_LICITACAO` vem VAZIA nas duas maiores fatias
     do arquivo — «Cotação Prévia de Preços» (230.911 linhas) e «Dispensa de
     Licitação» (195.654). Quem lê só essa coluna deixa ~40% das contratações
     sem nome na tela, parecendo defeito nosso.
  2. **Valor por duas ordens de grandeza.** 630.998 linhas vêm inteiras ("6300")
     e 339.878 com vírgula decimal ("196,32"); ponto não aparece em nenhuma das
     972.052. Trocar a regra erra por 100x, e valor plausível e errado não é
     percebido depois.
  3. **Zerar quem licitou.** Convênio sem linha no dump vira `qtd = 0` — a
     bandeira "assinou e não licitou". Se isso apagasse uma captura anterior, um
     atraso do arquivo pintaria de parado um município que licitou. É o alarme
     falso mais caro que este produto pode dar.

Rodar:
    python -m pytest backend/tests/test_siconv_licitacao.py -v
"""
import ingestion.siconv_licitacao as lic


def _g(linha: dict):
    """O acessor que o coletor usa, sobre um dicionário de teste."""
    return lambda k: (linha.get(k) or "").strip()


# --------------------------------------------------------------------------
# 1. O rótulo da contratação.
# --------------------------------------------------------------------------

def test_dispensa_pega_o_rotulo_do_tipo_de_processo():
    """Linha real do dump: modalidade vazia, tipo «Dispensa de Licitação»."""
    i = lic.item(_g({"MODALIDADE_LICITACAO": "", "TP_PROCESSO_COMPRA": "Dispensa de Licitação"}))
    assert i["modalidade"] == "Dispensa de Licitação"


def test_pregao_mantem_a_modalidade_quando_ela_existe():
    """Em «Licitação» as duas colunas vêm preenchidas; a específica é a que vale."""
    i = lic.item(_g({"MODALIDADE_LICITACAO": "Pregão", "TP_PROCESSO_COMPRA": "Licitação"}))
    assert i["modalidade"] == "Pregão"
    assert i["tipo_processo"] == "Licitação"


def test_sem_nenhuma_das_duas_fica_none_e_nao_string_vazia():
    """String vazia no JSONB desenha um campo em branco; None a tela sabe omitir."""
    assert lic.item(_g({}))["modalidade"] is None


# --------------------------------------------------------------------------
# 2. O valor.
# --------------------------------------------------------------------------

def test_inteiro_e_reais_inteiros():
    assert lic.valor("6300") == 6300.0
    assert lic.valor("198881") == 198881.0


def test_virgula_e_decimal_e_nao_milhar():
    """"196,32" é cento e noventa e seis reais — não dezenove mil."""
    assert lic.valor("196,32") == 196.32


def test_vazio_e_lixo_viram_none_nunca_zero():
    """Zero é uma afirmação ("a licitação foi de R$ 0"); afirmar isso por falta
    de dado é mentir para baixo, e some no meio de uma soma."""
    assert lic.valor("") is None
    assert lic.valor("   ") is None
    assert lic.valor("R$ mil") is None
    assert lic.valor(None) is None


# --------------------------------------------------------------------------
# 3. O contrato com a tela.
# --------------------------------------------------------------------------

def test_as_seis_chaves_da_tela_logada_continuam_existindo():
    """A tela já desenha este formato desde a captura por login. Renomear uma
    chave aqui apagaria a coluna correspondente sem erro nenhum."""
    i = lic.item(_g({"NR_LICITACAO": "10/2025", "STATUS_LICITACAO": "CONCLUIDO",
                     "SISTEMA_ORIGEM": "Plataforma +Brasil"}))
    for chave in ("numero", "modalidade", "data_publicacao", "situacao",
                  "sistema_origem", "aceite"):
        assert chave in i, chave
    assert i["numero"] == "10/2025"
    assert i["situacao"] == "CONCLUIDO"
    assert i["fonte"] == "dado_aberto"


# --------------------------------------------------------------------------
# 4. O casamento e o BOM.
# --------------------------------------------------------------------------

def _zip_de_teste(linhas: str) -> bytes:
    import io as _io
    import zipfile
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        # UTF-8 com BOM, como o arquivo de verdade (medido nos bytes:
        # EF BB BF + corpo UTF-8). Gerar o fixture em latin-1 esconderia
        # justamente o erro de encoding que este teste precisa pegar.
        z.writestr("siconv_licitacao.csv", linhas.encode("utf-8-sig"))
    return buf.getvalue()


_CAB = ("ID_LICITACAO;NR_CONVENIO;NR_LICITACAO;MODALIDADE_LICITACAO;"
        "TP_PROCESSO_COMPRA;TIPO_LICITACAO;NR_PROCESSO_LICITACAO;"
        "DATA_PUBLICACAO_LICITACAO;DATA_ABERTURA_LICITACAO;"
        "DATA_ENCERRAMENTO_LICITACAO;DATA_HOMOLOGACAO_LICITACAO;STATUS_LICITACAO;"
        "SITUACAO_ACEITE_PROCESSO_EXECU;SISTEMA_ORIGEM;SITUACAO_SISTEMA;"
        "VALOR_LICITACAO;DATA_ANALISE_ACEITE;DATA_ENVIO_ANALISE\n")


def test_o_bom_do_arquivo_nao_estraga_a_primeira_coluna():
    """O CSV real vem com BOM e a primeira coluna sai como `﻿ID_LICITACAO`.
    Sem o strip, o índice do cabeçalho erra e NADA casa — falha total que se
    parece com "nenhum convênio tem licitação"."""
    dados = _zip_de_teste(_CAB + "1;952398;10/2025;;Dispensa de Licitação;;10;;;;30/06/2025;CONCLUIDO;;Plataforma +Brasil;;6300;;\n")
    achados = lic.por_convenio(dados, {"952398"})
    assert list(achados) == ["952398"]
    assert achados["952398"][0]["valor"] == 6300.0


def test_so_traz_os_convenios_pedidos():
    """São 972 mil linhas do Brasil inteiro; trazer o que não é nosso estoura a
    memória do worker e não serve para nada."""
    dados = _zip_de_teste(
        _CAB
        + "1;952398;10/2025;;Dispensa;;10;;;;;CONCLUIDO;;+Brasil;;6300;;\n"
        + "2;111111;1/2020;;Dispensa;;1;;;;;CONCLUIDO;;+Brasil;;100;;\n")
    achados = lic.por_convenio(dados, {"952398"})
    assert set(achados) == {"952398"}


def test_varias_licitacoes_do_mesmo_convenio_viram_lista():
    """`processo_execucao_qtd` é len(lista) — o convênio com três licitações não
    pode virar uma."""
    dados = _zip_de_teste(
        _CAB
        + "1;952398;1;;Dispensa;;1;;;;;CONCLUIDO;;+Brasil;;10;;\n"
        + "2;952398;2;Pregão;Licitação;;2;;;;;CONCLUIDO;;+Brasil;;20;;\n"
        + "3;952398;3;;Inexigibilidade;;3;;;;;EM_ELABORACAO;;+Brasil;;30;;\n")
    achados = lic.por_convenio(dados, {"952398"})
    assert len(achados["952398"]) == 3
    assert [i["modalidade"] for i in achados["952398"]] == [
        "Dispensa", "Pregão", "Inexigibilidade"]


# --------------------------------------------------------------------------
# 5. A fonte nova é VIGIADA desde o primeiro dia.
# --------------------------------------------------------------------------

def test_a_fonte_esta_no_catalogo_do_watchdog():
    """Fonte fora do catálogo morre calada — foi assim que o dado atrás do login
    ficou sete dias parado. Vigia que se adiciona "depois" é o que nunca chega."""
    from ingestion.watchdog_coleta import FRESCOR_HORAS_NACIONAL
    assert FRESCOR_HORAS_NACIONAL["siconv_licitacao"] == 30


def test_a_fonte_aparece_no_monitor_da_central():
    from routers.control import _FONTES_MONITOR
    fontes = {f["key"]: f["sources"] for f in _FONTES_MONITOR}
    assert "siconv_licitacao" in fontes["transferegov_propostas"]


def test_o_resumo_diario_sabe_onde_olhar():
    """Sem entrada no mapa, o alerta das 7h diz que a fonte caiu e não diz onde."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import resumo_coleta
    assert "siconv_licitacao" in resumo_coleta.ONDE_OLHAR
