"""A data de publicacao SUBSTITUTA (1o de janeiro) sai da coluna da data real.

O coletor do SIGCON gravava `date(ano, 1, 1)` em `dt_publicacao` quando nao
abria o detalhe — declaradamente "NAO eh data exata", so para a ordenacao do
front funcionar. Ela morava na MESMA coluna da data verdadeira e
`ConvenioDetailModal.tsx:202` a imprime como "Data Publicação".

Medido em Araujos (30/08/2026): 15 dos 28 convenios SIGCON tinham 1o de janeiro
gravado. Para os mesmos, o portal publica 30/11/2017, 24/12/2015, 08/05/2015.
"""
import os
import re
from datetime import date

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRAPER = os.path.join(RAIZ, "ingestion", "sigcon_scraper.py")
MIGRATION = os.path.join(RAIZ, "migrations", "limpa_dt_publicacao_substituta.sql")
ROUTER = os.path.join(RAIZ, "routers", "convenios.py")
# ⚠️ A ORDENACAO MUDOU DE ARQUIVO em 03/09/2026 e este teste veio junto. Ela saiu
# de `routers/convenios.py` para `services/convenios_filtro.py:ordem()` porque os
# exports precisam repetir EXATAMENTE a mesma ordem — sem isso as mesmas linhas
# saem embaralhadas no documento, ja que `_sort_key` empata muito e o `sort` do
# Python e estavel, preservando a ordem de chegada. O invariante que este arquivo
# protege nao mudou; so o endereco.
FILTRO = os.path.join(RAIZ, "services", "convenios_filtro.py")


def _codigo(caminho: str, marca: str) -> str:
    """A fonte sem as linhas de comentario — os comentarios CITAM a expressao
    antiga para explicar o defeito, e um `not in` cru acusaria a propria
    documentacao do conserto."""
    return "\n".join(l for l in open(caminho, encoding="utf-8").read().splitlines()
                     if not l.lstrip().startswith(marca))


def test_o_coletor_nao_inventa_mais_a_data():
    src = _codigo(SCRAPER, "#")
    assert "dt_pub_proxy" not in src, "o substituto voltou ao coletor"
    assert "dt_pub = dt_pub_real" in src


def test_sem_data_lida_a_coluna_fica_NULA():
    """NULL diz a verdade — "nao li a data" — e e mais util que uma data que
    parece real e nao e. O upsert usa COALESCE, entao NULL preserva o que ja
    houver em vez de apagar."""
    src = _codigo(SCRAPER, "#")
    assert re.search(r"dt_publicacao\s*=\s*COALESCE\(EXCLUDED\.dt_publicacao", src)


def test_a_migration_so_apaga_o_que_e_exatamente_o_substituto():
    sql = _codigo(MIGRATION, "--")
    assert "dt_publicacao = make_date(ano, 1, 1)" in sql, \
        "sem esta igualdade a migration apagaria data de publicacao legitima"
    assert "fonte ILIKE 'SIGCON%'" in sql, "o FNS nunca usou substituto e nao pode ser tocado"
    assert "SET dt_publicacao = NULL" in sql
    assert sql.count("UPDATE convenios_estadual") == 1


def test_a_migration_esta_na_lista_que_o_boot_executa():
    from services.startup import MIGRATION_FILES
    assert "limpa_dt_publicacao_substituta.sql" in MIGRATION_FILES
    # depois do coletor corrigido nao ha mais linha nova a limpar; roda a cada
    # boot de proposito, como a `limpa_prestacao_contas_sei_lixo.sql`
    assert MIGRATION_FILES.index("limpa_dt_publicacao_substituta.sql") < \
        MIGRATION_FILES.index("add_auditoria_imutavel.sql")


def test_o_sql_da_migration_e_valido_para_o_postgres():
    pglast = pytest.importorskip("pglast", reason="pglast ausente — checagem PULADA")
    pglast.parse_sql(open(MIGRATION, encoding="utf-8").read())


def test_a_ordenacao_nao_regride_sem_o_substituto():
    """⚠️ Este e o teste que impede o conserto de virar um defeito novo. Sem o
    substituto, ordenar so por `dt_publicacao` jogaria 15 dos 28 convenios de
    Araujos para o fim da lista. A queda para 1o de janeiro do `ano` passa a ser
    feita no SQL da ordenacao — onde e criterio de ordem, nao fato exibido."""
    src = _codigo(FILTRO, "#")
    assert "func.make_date(" in src, (
        "a queda para 1o de janeiro sumiu de `convenios_filtro.ordem()` — sem "
        "ela, 15 dos 28 convenios de Araujos voltam para o fim da lista")
    assert re.search(r"func\.coalesce\(\s*ConvenioEstadual\.dt_publicacao", src)
    # E o router tem de continuar usando ESSA ordem, e nao uma propria: duas
    # ordenacoes e como a tela e o documento voltam a discordar.
    assert "filtro.ordem()" in _codigo(ROUTER, "#")


def test_a_ordem_resultante_e_a_mesma_de_antes():
    """Reproduz a chave de ordenacao dos dois mundos e confere que a sequencia
    nao muda para o caso real de Araujos."""
    def antiga(dt_pub_com_substituto):
        return dt_pub_com_substituto

    def nova(dt_pub, ano):
        return dt_pub or date(ano or 1900, 1, 1)

    # tres convenios: um com data real, dois que tinham substituto
    linhas = [("A", date(2017, 11, 30), 2017), ("B", None, 2017), ("C", None, 2015)]
    ordem_nova = [k for k, _, _ in sorted(linhas, key=lambda r: nova(r[1], r[2]), reverse=True)]
    # como era quando o substituto estava gravado na coluna
    antes = [("A", date(2017, 11, 30)), ("B", date(2017, 1, 1)), ("C", date(2015, 1, 1))]
    ordem_antiga = [k for k, _ in sorted(antes, key=lambda r: antiga(r[1]), reverse=True)]
    assert ordem_nova == ordem_antiga == ["A", "B", "C"]
