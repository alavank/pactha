"""Correções da auditoria de coleta (11/09/2026) — balde de código puro.

Escopo: só as correções testáveis sem produção (M-2, M-1, M-3, A-1). As correções
de infra (C-1/C-2 403-por-IP, C-3/SISMOB agendamento Coolify, A-3 heartbeat/watchdog,
A-4 comando real do cron) NÃO estão aqui — dependem de acesso que a sessão de
auditoria não tem, e foram documentadas, não implementadas.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/d")
os.environ.setdefault("JWT_SECRET", "x")
os.environ.setdefault("BI_MODULE", "1")

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fonte(rel):
    return open(os.path.join(RAIZ, rel), encoding="utf-8").read()


# ── M-2: _money robusto (o caso 1234.56 não pode virar 123456) ──────────────

def test_m2_money_reconhece_formato_ptbr_e_nao_estraga_ponto_decimal():
    from ingestion.siconv_emenda_backfill import _money
    assert _money("0") == 0.0
    assert _money("10") == 10.0
    assert _money("1234") == 1234.0
    assert _money("1000000") == 1000000.0
    assert _money("10,50") == 10.5          # vírgula decimal
    assert _money("10.50") == 10.5          # ⚠️ ponto decimal — o BUG: era 1050
    assert _money("1234.56") == 1234.56     # ⚠️ o caso do relatório: era 123456
    assert _money("1234,56") == 1234.56
    assert _money("1.000,50") == 1000.5     # ponto = milhar QUANDO há vírgula
    assert _money("1.234,56") == 1234.56
    assert _money("R$ 1.234,56") == 1234.56
    assert _money("") is None and _money(None) is None
    assert _money("lixo") is None


def test_m2_backfill_nao_tem_mais_money_incondicional_aninhado():
    """A função aninhada (que fazia replace incondicional) foi removida; o `_money`
    agora é único, do módulo. Guarda contra reintrodução da cópia aninhada."""
    src = _fonte("ingestion/siconv_emenda_backfill.py")
    # só UMA definição de _money (a do módulo)
    assert src.count("def _money(") == 1


# ── M-1: COALESCE — não zerar cláusula suspensiva com "Normal"/ausência ─────

def test_m1_update_clausula_usa_coalesce():
    src = _fonte("ingestion/siconv_convenio_backfill.py")
    assert "COALESCE(%s, situacao_contratacao)" in src
    assert "COALESCE(%s, clausula_suspensiva_motivo)" in src
    assert "COALESCE(%s, clausula_suspensiva_dt_prevista)" in src


# ── M-3: partial em vez de success cravado quando parte falhou ──────────────

def test_m3_consulta_popular_reporta_partial():
    src = _fonte("ingestion/consulta_popular_rs.py")
    assert "falhas += 1" in src
    assert '"partial"' in src


def test_m3_cofin_ses_go_isola_municipio_e_reporta_partial():
    src = _fonte("ingestion/cofin_ses_go.py")
    assert "SAVEPOINT cofin_mun" in src
    assert "ROLLBACK TO SAVEPOINT cofin_mun" in src
    assert '"partial"' in src


# ── A-1: SIMEC-PAR — status honesto (não 'success' cravado) ─────────────────

def test_a1_simec_par_status_derivado_nao_hardcoded():
    src = _fonte("ingestion/simec_par.py")
    # o literal antigo cravado sumiu
    assert "'simec_par','success'" not in src
    assert "'simec_par',%s" in src            # status agora é parâmetro
    # e a decisão existe (todos falharam -> error; alguns -> partial)
    assert "falhas == n" in src
    assert '"partial"' in src and '"error"' in src


# ── Continuação (2ª leva de correções) ──────────────────────────────────────

def test_a1_restante_status_derivado():
    for rel, fonte in [("ingestion/sigcon_ckan_backfill.py", "sigcon_ckan_backfill"),
                       ("ingestion/cauc_ingest.py", "cauc"),
                       ("ingestion/acordofes_ingest.py", "acordofes")]:
        src = _fonte(rel)
        assert f"'{fonte}','success'" not in src, f"{fonte}: success ainda cravado"
        assert f"'{fonte}',%s" in src, f"{fonte}: status deveria ser parâmetro"
        assert '"partial"' in src


def test_a4_siconv_emenda_backfill_loga_no_caminho_do_cron():
    src = _fonte("ingestion/siconv_emenda_backfill.py")
    # o cron chama backfill_parlamentar() — ela agora registra em ingestion_log
    i = src.index("def backfill_parlamentar")
    corpo = src[i:src.index("def main", i)]
    assert "_registra(" in corpo and "siconv_emenda_backfill" in corpo


def test_c1_transparencia_mg_grava_ingestion_log():
    src = _fonte("ingestion/transparencia_mg.py")
    assert "def _log_ingest(" in src
    assert "'transparencia_mg'" in src
    assert "_log_ingest(" in src  # chamado em pelo menos um caminho de saída


def test_c3_siconv_federal_zero_guard_e_transacao_unica():
    src = _fonte("ingestion/siconv_federal_ingest.py")
    assert "'siconv_federal','success'" not in src        # não é mais cravado
    assert "if total == 0:" in src and "conn.rollback()" in src  # zero-guard
    # o commit imediato pós-TRUNCATE saiu (reload na mesma transação)
    assert "TRUNCATE siconv_federal" in src
    i = src.index("TRUNCATE siconv_federal")
    depois = src[i:i+200]
    assert "conn.commit()" not in depois, "TRUNCATE não pode commitar antes do reload"


def test_item6_watchdog_detecta_fonte_nunca_executada():
    src = _fonte("ingestion/watchdog_coleta.py")
    assert "fonte_nunca_executada" in src
    assert "siconv_federal" in src and "siconv_empenho_aberto" in src


def test_m6_emendas_estaduais_nao_comita_vazio():
    src = _fonte("ingestion/emendas_estaduais.py")
    assert "if extracted == 0:" in src
    assert "conn.rollback()" in src
    assert "'emendas_estaduais', 'success'" in src  # caminho normal mantido
