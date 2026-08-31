"""O backfill do CKAN deixa de ser UPDATE-only e passa a INSERIR o que falta.

Ate 30/08/2026 este coletor baixava, a cada 6 horas, o dataset com TODOS os
convenios do municipio, atualizava so as linhas que a tabela ja tinha, e
descartava o resto. Medido em Araujos: o Estado publica 63 convenios da
prefeitura e a plataforma tinha 18 — faltavam 45, R$ 4.465.654,15, e 23 deles ja
tinham repasse do Estado.

Os fixtures aqui sao csv.gz montados em memoria no formato REAL do
dados.mg.gov.br: latin-1, delimitador ';' e BOM UTF-8 no primeiro cabecalho.
"""
import gzip
import io
import json

import pytest

from ingestion.sigcon_ckan_backfill import (_SQL_INSERT, _fato_por_convenio,
                                            _linhas, _situacao_por_convenio)


def _gz(cabecalho: list[str], linhas: list[list[str]]) -> bytes:
    """csv.gz como o Estado publica: latin-1, ';' e BOM UTF-8 no 1o cabecalho."""
    buf = io.StringIO()
    buf.write(";".join(cabecalho) + "\n")
    for l in linhas:
        buf.write(";".join(str(c) for c in l) + "\n")
    bruto = buf.getvalue().encode("utf-8")
    # o BOM chega ao arquivo como bytes UTF-8; lido em latin-1 vira 'ï»¿'
    return gzip.compress(b"\xef\xbb\xbf" + bruto[0:0] + bruto)


# --- o BOM ------------------------------------------------------------------

def test_o_BOM_nao_engole_a_primeira_coluna():
    """⚠️ O arquivo e UTF-8 COM BOM lido como latin-1, entao a primeira coluna
    chega 'ï»¿id_situacao'. Sem limpar, todo .get() dessa coluna devolve None e o
    casamento sai VAZIO — sem erro nenhum. Eu reproduzi esse engano durante a
    auditoria, e foi por isso que este teste existe."""
    gz = _gz(["id_situacao", "fl_versao", "nome"], [["3", "1", "VIGENTE"]])
    linha = next(iter(_linhas(gz)))
    assert linha["id_situacao"] == "3", "o BOM ficou colado no nome da coluna"
    assert linha["nome"] == "VIGENTE"


# --- situacao ---------------------------------------------------------------

_SIT = _gz(["id_situacao", "fl_versao", "nome"],
           [["1", "1", "CONVENIO CADASTRADO"], ["2", "1", "CANCELADO"],
            ["3", "1", "VIGENTE"], ["4", "1", "ENCERRADO"]])


def _tipo(linhas):
    return _gz(["id_tempo", "id_orgao", "id_convenio", "id_municipio", "id_convenente",
                "id_tipo_atendimento", "id_situacao", "ano_particao"], linhas)


def test_a_traducao_da_situacao_e_a_MEDIDA_nos_18_casados():
    """ENCERRADO -> 'Encerrado' (12 de 12) e VIGENTE -> 'Em vigor' (6 de 6),
    conferido convenio a convenio nos que existem nos dois lados."""
    gz = _tipo([["1", "9", "100", "43", "7", "1", "4", "2025"],
                ["1", "9", "200", "43", "7", "1", "3", "2025"],
                ["1", "9", "300", "43", "7", "1", "2", "2025"]])
    s = _situacao_por_convenio(gz, _SIT)
    assert s["100"] == "Encerrado"
    assert s["200"] == "Em vigor"
    assert s["300"] == "Cancelado"


def test_CONVENIO_CADASTRADO_fica_VERBATIM():
    """⚠️ Nao ha UMA linha entre os 18 casados que autorize traduzi-lo. Mapea-lo
    para 'Cadastramento' (que na plataforma significa ANTES da celebracao) seria
    mentira: dos 45 convenios de Araujos com esse rotulo, 23 ja tiveram repasse.
    A palavra do portal e melhor que um palpite meu."""
    gz = _tipo([["1", "9", "400", "43", "7", "1", "1", "2025"]])
    assert _situacao_por_convenio(gz, _SIT)["400"] == "CONVENIO CADASTRADO"


def test_a_situacao_mais_recente_vence():
    """O fato tem uma linha por ano de particao."""
    gz = _tipo([["1", "9", "500", "43", "7", "1", "3", "2023"],
                ["1", "9", "500", "43", "7", "1", "4", "2026"]])
    assert _situacao_por_convenio(gz, _SIT)["500"] == "Encerrado"


# --- fato -------------------------------------------------------------------

def test_o_fato_traz_as_chaves_de_dimensao_e_o_repasse():
    """Sao elas que permitem partir do MUNICIPIO em vez de partir do que a
    plataforma ja conhece — a diferenca entre achar 18 e achar 63."""
    gz = _gz(["id_tempo", "id_orgao", "id_convenio", "id_municipio", "id_convenente",
              "ano_particao", "vr_concede_atual", "vr_emen_parl_atual",
              "vr_interv_atual", "vr_contra_atual", "vr_total_atual",
              "vr_rep_concede_atual"],
             [["1", "42", "900", "43", "3185", "2025", "200000.00", "0.00",
               "0.00", "0.00", "200000.00", "200000.00"]])
    f = _fato_por_convenio(gz)["900"]
    assert f["id_municipio"] == "43"
    assert f["id_convenente"] == "3185"
    assert f["id_orgao"] == "42"
    assert f["repassado"] == 200000.0
    assert f["total"] == 200000.0


def test_o_fato_guarda_a_particao_mais_recente():
    gz = _gz(["id_convenio", "id_municipio", "id_convenente", "id_orgao",
              "ano_particao", "vr_rep_concede_atual", "vr_concede_atual",
              "vr_contra_atual", "vr_total_atual"],
             [["900", "43", "1", "2", "2022", "50000.00", "1", "1", "1"],
              ["900", "43", "1", "2", "2026", "80000.00", "1", "1", "1"]])
    assert _fato_por_convenio(gz)["900"]["repassado"] == 80000.0


# --- o INSERT ---------------------------------------------------------------

def test_o_insert_nunca_sobrescreve_a_tela_logada():
    """⚠️ DO NOTHING, nao DO UPDATE. Quem manda no convenio e a tela do SIGCON;
    este caminho so ACRESCENTA o que ela nao alcanca."""
    assert "DO NOTHING" in _SQL_INSERT
    assert "DO UPDATE" not in _SQL_INSERT


def test_o_conflito_declara_o_predicado_do_indice_PARCIAL():
    """`ux_convenios_estadual_nr_siafi` e UNIQUE PARCIAL (WHERE nr_siafi IS NOT
    NULL AND nr_siafi <> ''). Sem repetir o predicado no ON CONFLICT, o Postgres
    nao infere o indice e devolve 42P10 — a insercao inteira morre."""
    assert "ON CONFLICT (nr_siafi) WHERE nr_siafi IS NOT NULL AND nr_siafi <> ''" in _SQL_INSERT


def test_a_linha_inserida_nasce_com_fonte_SIGCON():
    """Todo consumidor recorta por `fonte ILIKE 'SIGCON%'`. Nascer com outra
    fonte deixaria a linha invisivel para a tela, o RM e o proprio backfill."""
    assert "'SIGCON-MG'" in _SQL_INSERT


def test_o_valor_repassado_entra_no_insert():
    """E o campo que prova que o dinheiro saiu — o motivo de a auditoria ter
    chamado a ausencia desses convenios de grave."""
    assert "valor_repassado" in _SQL_INSERT
    assert "%(repassado)s" in _SQL_INSERT


def test_a_data_de_publicacao_REAL_entra_no_insert():
    """O scraper grava 1o de janeiro como substituto quando nao abre o detalhe.
    A linha que nasce do CKAN ja nasce com a data verdadeira."""
    assert "dt_publicacao" in _SQL_INSERT
    assert "%(dt_pub)s" in _SQL_INSERT


def test_o_sql_do_insert_e_valido_para_o_postgres():
    """Gramatica real. PULA (nao passa) sem pglast."""
    pglast = pytest.importorskip("pglast", reason="pglast ausente — checagem PULADA")
    # os placeholders %(x)s do psycopg2 nao sao SQL; troca por NULL para parsear
    import re
    pglast.parse_sql(re.sub(r"%\([a-z_]+\)s", "NULL", _SQL_INSERT))


def test_a_insercao_nasce_DESLIGADA():
    """⚠️ Ligada, esta etapa insere 2.658 convenios no freitas (R$ 508,5 mi, dos
    quais R$ 305,3 mi ja repassados) em 41 dos 42 municipios — quase o DOBRO das
    2.411 linhas de hoje. Uma mudanca desse tamanho e decisao do dono, nao efeito
    colateral de um merge. `SIGCON_CKAN_INSERT=1` liga por tenant, sem deploy."""
    import inspect

    from ingestion import sigcon_ckan_backfill as m
    src = inspect.getsource(m.backfill)
    assert 'os.getenv("SIGCON_CKAN_INSERT", "0")' in src, "o default voltou a ser ligado"
    assert 'in ("1", "true", "yes")' in src, "a guarda virou opt-out em vez de opt-in"
