"""FNS: o valor PAGO tem coluna propria, e a do PROPOSTO volta a ser so dele.

CASO REAL medido em producao (Araujos, 30/08/2026). Das 43 linhas FNS, 28 estao
pagas por inteiro — ali `vlPago == vlProposta` e o defeito e invisivel. Nas 2
pagas pela metade a coluna trocava de sentido calada:

    FNS-310390-2019-INCREMEN   proposta 500.000,00   pago 400.000,00
    FNS-310390-2026-CUSTEIO_   proposta 800.000,00   pago 200.000,00

A tela mostrava 400.000 e 200.000 como valor total — R$ 700.000,00 de valor
proposto sumindo, com as duas rotuladas "Empenhado".
"""
import os
import re

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLETOR = os.path.join(RAIZ, "ingestion", "run_fns_local.py")
MIGRATION = os.path.join(RAIZ, "migrations", "fix_fns_valor_pago_na_coluna_certa.sql")


def _fonte(caminho: str) -> str:
    return open(caminho, encoding="utf-8").read()


def _so_codigo(caminho: str, marca: str) -> str:
    """A fonte SEM as linhas de comentario.

    ⚠️ Necessario, e a primeira versao destes testes tropecou nisso: os
    comentarios do conserto CITAM a expressao antiga (`vl_pago or vl_prop`) para
    explicar o defeito, entao um `not in` sobre o arquivo inteiro acusava o
    proprio texto que documenta a correcao."""
    return "\n".join(l for l in _fonte(caminho).splitlines()
                     if not l.lstrip().startswith(marca))


# --- a regra, reproduzida como o coletor a escreve -------------------------

def _valores(vl_prop: float, vl_pago: float):
    """Espelha `_normalize`: proposto primeiro, pago em coluna propria."""
    return (vl_prop or vl_pago or None), (vl_pago or None)


def test_pagamento_parcial_nao_encolhe_mais_o_valor_proposto():
    """Os dois casos reais de Araujos, com os numeros do portal."""
    assert _valores(500_000.0, 400_000.0) == (500_000.0, 400_000.0)
    assert _valores(800_000.0, 200_000.0) == (800_000.0, 200_000.0)


def test_a_regra_ANTIGA_produzia_o_numero_errado():
    """Guarda contra reintroducao: `vl_pago or vl_prop` da o pago nas parciais.
    Se alguem reverter a ordem, este teste morre junto com o conserto."""
    def antiga(vl_prop, vl_pago):
        return vl_pago or vl_prop or 0
    assert antiga(500_000.0, 400_000.0) == 400_000.0     # o defeito
    assert _valores(500_000.0, 400_000.0)[0] == 500_000.0  # o conserto


def test_pagamento_integral_nao_muda_de_valor():
    """28 das 43 linhas. A mudanca nao pode mexer nelas."""
    for v in (120_000.0, 57_446.23, 1.0):
        assert _valores(v, v) == (v, v)


def test_sem_valor_proposto_o_pago_ainda_serve_de_total():
    """Nao piorar a linha que so tem o pago: antes ela tinha um total, e
    continua tendo. So que agora o pago tambem aparece na coluna dele."""
    assert _valores(0.0, 90_000.0) == (90_000.0, 90_000.0)


def test_zero_pago_vira_NULL_e_nao_afirmacao():
    """`or None`, nao `or 0`. Zero aqui seria a afirmacao "nada foi pago", e o
    FNS omite `vlPago` tambem quando simplesmente nao informa — a mesma
    disciplina de medido x ausente do resto do repo."""
    assert _valores(300_000.0, 0.0) == (300_000.0, None)


# --- o coletor -------------------------------------------------------------

def test_o_coletor_poe_o_proposto_primeiro():
    src = _so_codigo(COLETOR, "#")
    assert '"valor": vl_prop or vl_pago or None' in src
    assert '"valor_repassado": vl_pago or None' in src
    assert "vl_pago or vl_prop" not in src, "a ordem antiga voltou ao coletor"


def test_o_upsert_grava_a_coluna_nova():
    """De nada adianta calcular o pago se ele nao chega ao banco: a coluna
    precisa estar no INSERT e no DO UPDATE."""
    src = _fonte(COLETOR)
    assert re.search(r"INSERT INTO convenios_estadual.*valor_repassado", src, re.S)
    assert "%(valor_repassado)s" in src
    assert re.search(r"valor_repassado\s*=\s*COALESCE\(EXCLUDED\.valor_repassado", src)


def test_o_arquivo_DEPRECADO_nao_foi_confundido_com_o_coletor():
    """⚠️ `fns_scraper.py` diz 'DEPRECADO — NAO USE' na primeira linha e nao e
    executado por job nenhum. Consertar la nao teria efeito — este teste existe
    porque eu ja tinha apontado o arquivo errado no relatorio da auditoria."""
    dep = _fonte(os.path.join(RAIZ, "ingestion", "fns_scraper.py"))
    assert "DEPRECADO" in dep[:200]


# --- a migration -----------------------------------------------------------

def test_a_migration_esta_na_lista_que_o_boot_executa():
    """Arquivo em migrations/ que nao esta em MIGRATION_FILES nunca roda."""
    from services.startup import MIGRATION_FILES
    assert "fix_fns_valor_pago_na_coluna_certa.sql" in MIGRATION_FILES


def test_a_migration_so_toca_FNS_e_so_o_que_esta_errado():
    sql = _so_codigo(MIGRATION, "--")
    assert sql.count("UPDATE convenios_estadual") == 2
    assert sql.count("fonte = 'FNS'") == 2, "todo UPDATE precisa do recorte por fonte"
    # idempotencia: sem isto o UPDATE reescreve as mesmas linhas a cada boot
    assert sql.count("IS DISTINCT FROM") == 2
    # o cast nao pode derrubar a transacao do arquivo inteiro
    assert sql.count("jsonb_typeof") == 2


def test_o_sql_da_migration_e_valido_para_o_postgres():
    """Gramatica real. PULA (nao passa) sem pglast — checagem que nao roda nao e
    checagem que passou."""
    pglast = pytest.importorskip("pglast", reason="pglast ausente — checagem PULADA")
    pglast.parse_sql(_fonte(MIGRATION))
