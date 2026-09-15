"""Higiene do detalhe das voluntarias: rotulo que nao e rotulo, modalidade com
o campo seguinte colado, e "medido e vazio" que virava "nunca consultado".

Todos vieram da auditoria de Araujos (30/08/2026), medidos contra os 83 blobs
reais de producao.
"""
import os
import re

from ingestion.transferegov_http import _parece_rotulo
from ingestion.transferegov_voluntarias import _data_br, _primeiro_campo

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOL = os.path.join(RAIZ, "ingestion", "transferegov_voluntarias.py")
HTTP = os.path.join(RAIZ, "ingestion", "transferegov_http.py")


def _codigo(caminho, marca="#"):
    return "\n".join(l for l in open(caminho, encoding="utf-8").read().splitlines()
                     if not l.lstrip().startswith(marca))


# --- rotulo que nao e rotulo --------------------------------------------------

def test_ano_do_cronograma_nao_vira_chave():
    """Caso real, 016886/2021: o detalhe tinha "2021": "R$ 418.471,00" — uma
    linha do CRONOGRAMA achatada como se fosse campo do instrumento."""
    assert _parece_rotulo("2021") is False
    assert _parece_rotulo("2026") is False


def test_nome_de_arquivo_nao_vira_chave():
    """Mesma proposta: "DECLARAÇÃO COMPROVAÇÃO DE CONTRAPARTIDA ARAUJOS
    ASSINADA.pdf": "Baixar Contrapartida" — linha da GRADE DE DOCUMENTOS."""
    assert _parece_rotulo("DECLARAÇÃO COMPROVAÇÃO DE CONTRAPARTIDA ARAUJOS ASSINADA.pdf") is False
    assert _parece_rotulo("anexo.docx") is False
    assert _parece_rotulo("planilha.XLSX") is False


def test_data_e_valor_soltos_nao_viram_chave():
    for lixo in ("31/12/2026", "1.234,56", "  ", "", "12,5%", "-"):
        assert _parece_rotulo(lixo) is False, lixo


def test_os_rotulos_DE_VERDADE_continuam_passando():
    """⚠️ O guarda e uma regra POSITIVA sobre a forma; se ele derrubar um rotulo
    legitimo, troca 224 chaves-lixo por campos perdidos, que e pior."""
    for bom in ("Valor Global", "Data Término de Vigência Atual", "Órgão",
                "Nº do Processo", "Situação", "Opera por OBTV",
                "Código do Pré-Instrumento", "Capacidade Técnica e Gerencial"):
        assert _parece_rotulo(bom) is True, bom


def test_os_dois_leitores_usam_o_MESMO_guarda():
    """O detalhe e escrito por dois caminhos (HTTP e navegador). Guarda em um so
    deixa o outro sujando a mesma coluna."""
    assert "_parece_rotulo(k)" in _codigo(HTTP)
    assert "pareceRotulo(k)" in _codigo(VOL, "//")


# --- modalidade ---------------------------------------------------------------

def test_a_modalidade_perde_o_campo_colado():
    """Medido: 27 de 83 propostas gravaram o par rotulo/valor SEGUINTE colado por
    TAB, e 21 delas com o acento duplamente codificado do pedaco extra."""
    assert _primeiro_campo("Contrato de Repasse\tEnviada para mandatária?\tNÃ£o") \
        == "Contrato de Repasse"
    assert _primeiro_campo("Convênio\tSituação no SIAFI\tEnviado para o SIAFI") == "Convênio"


def test_a_modalidade_limpa_passa_intacta():
    for bom in ("Convênio", "Contrato de Repasse", "Termo de Compromisso",
                "Convênio ou Contrato de Repasse"):
        assert _primeiro_campo(bom) == bom


def test_o_corte_nao_inventa_valor():
    assert _primeiro_campo(None) is None
    assert _primeiro_campo("") is None
    assert _primeiro_campo("\t\t") is None


# --- datas: o mesmo campo colado, e a migration que ele derrubava ---------------

def test_a_data_perde_o_campo_colado():
    """Célula com o par rótulo/valor seguinte colado por TAB: fica só a data. A
    SEGUNDA data do texto é a do campo vizinho e não pode vencer."""
    assert _data_br("06/07/2026\tData Assinatura\t01/07/2026") == "06/07/2026"
    assert _data_br("30/09/2027") == "30/09/2027"


def test_texto_sem_data_vira_None_e_nao_lixo():
    """None faz o COALESCE do upsert preservar o que já está na coluna."""
    for lixo in (None, "", "sem data", "\t\t", "2026"):
        assert _data_br(lixo) is None, lixo


def test_o_coletor_passa_as_quatro_datas_pelo_corte():
    src = _codigo(VOL)
    for rotulo in ("Data Início de Vigência", "Data Término de Vigência Atual",
                   "Data da Proposta", "Data Assinatura"):
        assert re.search(rf'_data_br\(g\("{rotulo}"', src), f"{rotulo} sem _data_br"


def test_a_migration_das_datas_copia_so_a_data_e_cabe_no_varchar20():
    """⚠️ `fix_transferegov_datas_texto.sql` copiava a célula INTEIRA do detalhe
    para colunas VARCHAR(20): com o campo colado, `value too long`, e o arquivo
    (uma transação só) era desfeito a cada boot em Santa Maria — de 17/08 a
    15/09/2026 o reparo das datas trocadas nunca foi aplicado lá."""
    import pglast
    sql = open(os.path.join(RAIZ, "migrations", "fix_transferegov_datas_texto.sql"),
               encoding="utf-8").read()
    pglast.parse_sql(sql)
    codigo = "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("--"))
    sets = re.findall(r"SET\s+(dt_\w+)\s*=\s*(\w+)\(", codigo)
    assert {c for c, _ in sets} == {"dt_inicio_vigencia", "dt_proposta",
                                    "dt_assinatura", "dt_fim_vigencia"}
    assert all(f == "substring" for _, f in sets), sets
    assert codigo.count("from '[0-9]{2}/[0-9]{2}/[0-9]{4}'") == 12


# --- medido e vazio -----------------------------------------------------------

def test_processo_execucao_e_projeto_basico_usam_is_not_None():
    """⚠️ Lista/dict VAZIO e resposta medida ("o portal respondeu: nao ha"), nao
    ausencia. Com truthiness virava NULL e o COALESCE preservava o valor antigo —
    "nao tem" ficava indistinguivel de "nunca consultei".

    Sintoma real em Araujos: 054685/2025 com processo_execucao_qtd = 0 e
    processo_execucao = NULL, duas colunas discordando sobre o mesmo fato.

    Seguro porque nenhum dos dois e pre-semeado: so recebem valor dentro de
    `if ... is not None` (linhas ~999 e ~1030)."""
    src = _codigo(VOL)
    for campo in ("processo_execucao", "projeto_basico"):
        assert re.search(rf'p\.get\("{campo}"\) is not None', src), \
            f"{campo} voltou para truthiness"


def test_o_erro_interno_do_portal_vai_para_o_LOG_e_nao_para_o_retorno():
    """⚠️ Distinguir "nao ha" de "o portal recusou" e legitimo, mas nao pode
    viajar no VALOR DE RETORNO: um dict nao-vazio faria o chamador (`if _hc:`)
    mudar de ramo. O diagnostico vai para o log; o contrato fica igual."""
    src = _codigo(HTTP)
    assert "pagina sem JSF view" in src
    assert "return {}" in src, "o retorno vazio nao pode ter virado dict com marcador"
