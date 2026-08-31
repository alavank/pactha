"""SIGCON: a lista de alteracoes deixa de ser reduzida a uma, e o aviso do
portal deixa de ser gravado como status de prestacao de contas.

Os dois achados sao da auditoria de Araujos (30/08/2026), conferidos contra o
que o Estado publica em dados abertos.
"""
import os

import pytest

from ingestion.sigcon_scraper import _pc_forma

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRAPER = os.path.join(RAIZ, "ingestion", "sigcon_scraper.py")
MIGRATION = os.path.join(RAIZ, "migrations", "limpa_prestacao_contas_nao_informado.sql")


# --- o aviso do portal nao e um status ---------------------------------------

def test_o_aviso_do_portal_nao_vira_status():
    """A tela imprime este texto no lugar onde o status apareceria. Medido: 6 dos
    13 convenios de Araujos com a secao lida traziam a FRASE gravada, com SEI e
    data nulos — todos de 2025/2026, recem-assinados."""
    for aviso in ("STATUS DE PRESTAÇÃO DE CONTAS NÃO INFORMADO",
                  "Status de prestação de contas não informado",
                  "STATUS DE PRESTACAO DE CONTAS NAO INFORMADO"):
        assert _pc_forma("prestacao_contas_status", aviso) is None, aviso


def test_os_status_REAIS_continuam_passando():
    """⚠️ Os cinco valores que a producao mostrou funcionando. Se a regra nova
    engolir qualquer um deles, ela trocou um defeito por outro pior."""
    for real in ("Prestação de contas aprovada",
                 "Prestação de contas aprovada com ressalvas",
                 "Aguardando análise da prestação de contas final",
                 "Prestação de contas em análise técnica",
                 "Prestação de contas enviada"):
        assert _pc_forma("prestacao_contas_status", real) == real


def test_a_regra_exige_as_DUAS_palavras():
    """"nao informado" sozinho nao basta: um status legitimo poderia conte-lo.
    A frase do portal tem 'status' E 'informado', e e isso que a distingue."""
    assert _pc_forma("prestacao_contas_status", "Valor não informado pelo órgão") \
        == "Valor não informado pelo órgão"


def test_o_resto_da_validacao_de_forma_segue_de_pe():
    """Nao-regressao dos guardas que ja existiam: rotulo de botao e CPF fora."""
    assert _pc_forma("prestacao_contas_sei", "Cancelar Histórico Status") is None
    assert _pc_forma("prestacao_contas_sei", "030.725.676-62") is None
    assert _pc_forma("prestacao_contas_sei", "1300.01.0008895/2025-20") == "1300.01.0008895/2025-20"
    assert _pc_forma("prestacao_contas_data", "04/12/2025") == "04/12/2025"


# --- a lista de alteracoes ----------------------------------------------------

def test_a_lista_de_alteracoes_e_guardada_inteira():
    """⚠️ Antes, a datatable era reduzida a UM registro (a linha de data mais
    recente) e as outras sumiam. Medido: nos 18 convenios de Araujos casados com
    o portal, o Estado publica 9 alteracoes e a plataforma guardava 4. No 9223438
    havia PRORROGACAO DE OFICIO, ADEQUACAO DO CONVENIO e outra prorrogacao —
    sobrava so a ultima, e a adequacao (de OUTRO tipo) nao existia em lugar
    nenhum."""
    src = open(SCRAPER, encoding="utf-8").read()
    assert '"alteracoes"' in src, "a lista nao esta sendo montada"
    assert 'out["alteracoes"] = alteracoes' in src


def test_os_campos_escalares_da_ultima_ficam():
    """A tela e o RM ja leem os seis campos `ultima_alteracao_*`. A lista entra
    AO LADO deles — trocar a forma de leitura seria outra mudanca, com outro
    risco."""
    src = open(SCRAPER, encoding="utf-8").read()
    for c in ("nr_controle", "tipo", "situacao", "data", "titulo", "usuario"):
        assert f'"ultima_alteracao_{c}"' in src


# --- a migration --------------------------------------------------------------

def test_a_migration_exige_as_duas_palavras_e_nao_precisa_de_unaccent():
    """⚠️ "STATUS" e "INFORMADO" nao tem acento, entao ILIKE basta — `unaccent`
    exige extensao e nao esta instalada em todos os tenants.

    ⚠️ A contagem roda sobre o SQL SEM COMENTARIO: a justificativa acima do
    codigo cita as mesmas palavras, e contar o arquivo inteiro acusaria a propria
    documentacao do conserto. Ja tropecei nisso duas vezes hoje."""
    sql = "\n".join(l for l in open(MIGRATION, encoding="utf-8").read().splitlines()
                    if not l.lstrip().startswith("--"))
    assert "unaccent" not in sql
    assert sql.count("ILIKE") == 2
    assert "'%status%'" in sql and "'%informado%'" in sql
    assert "raw_data - 'prestacao_contas_status'" in sql


def test_a_migration_esta_na_lista_que_o_boot_executa():
    from services.startup import MIGRATION_FILES
    assert "limpa_prestacao_contas_nao_informado.sql" in MIGRATION_FILES


def test_o_sql_da_migration_e_valido_para_o_postgres():
    pglast = pytest.importorskip("pglast", reason="pglast ausente — checagem PULADA")
    pglast.parse_sql(open(MIGRATION, encoding="utf-8").read())
