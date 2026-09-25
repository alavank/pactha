"""Smoke test da coleta — §22 da auditoria. NÃO ESCREVE DADO REAL.

O que um smoke faz aqui (e o que NÃO faz):

- FAZ: importa cada coletor tocado pela auditoria + `status_coleta`. Importar já
  é um teste — pega erro de sintaxe, import quebrado, e os DOIS estilos de import
  do `status_coleta` (pacote vs script). E prova que NENHUM módulo abre banco ou
  rede no import: o conftest aponta DATABASE_URL para um host que não existe, então
  um `connect()` no nível do módulo estouraria aqui.
- FAZ: confere o CONTRATO de `status_coleta` — toda função devolve `(status, erro)`
  com status no vocabulário do watchdog.
- NÃO FAZ: chamar `ingest()`/`run()`/`backfill()`. Essas funções baixam ZIPs de
  ~200 MB e escrevem no Postgres do tenant. Rodá-las aqui seria coleta real, não
  smoke — o §22 pede o oposto. O comportamento delas é coberto, com banco FALSO,
  em test_correcoes_auditoria.py.
"""
import importlib
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/d")
os.environ.setdefault("JWT_SECRET", "x")
os.environ.setdefault("BI_MODULE", "1")

# módulo -> nome do entry point que o cron/Scheduled Task chama.
COLETORES = {
    "ingestion.simec_par": "run",
    "ingestion.cauc_ingest": "ingest",
    "ingestion.acordofes_ingest": "ingest",
    "ingestion.sigcon_ckan_backfill": "backfill",
    "ingestion.segov_pagamentos": "ingest",
    "ingestion.cge_despesa_ob": "ingest",
    "ingestion.consulta_popular_rs": "ingest",
    "ingestion.cofin_ses_go": "ingest",
    "ingestion.siconv_federal_ingest": "ingest",
    "ingestion.siconv_emenda_backfill": "backfill_parlamentar",
    "ingestion.transparencia_mg": None,   # entry varia; só o import importa aqui
    "ingestion.tce_rs": None,
    "ingestion.tce_rs_portal": None,
    "ingestion.tce_pr": "ingest",
    "ingestion.dou_federal": "ingest",
    "ingestion.cgu_convenios": "ingest",
    "ingestion.cgu_transferencias": "ingest",
    "ingestion.convenios_pr": "ingest",
    "ingestion.convenios_to": "ingest",
    "ingestion.emendas_mg": "ingest",
    "ingestion.ses_mg_resolucoes": "ingest",
    "ingestion.fns_saldo": "ingest",
    "ingestion.regularidade_pr": "ingest",
    "ingestion.emendas_estaduais": None,
    "ingestion.watchdog_coleta": "main",
}

STATUS_VALIDOS = {"success", "partial", "error"}


def test_smoke_coletores_importam_sem_efeito_colateral():
    """Import de cada coletor não pode falhar nem abrir banco/rede. Se algum
    conectasse no import, o DATABASE_URL falso do conftest faria explodir aqui."""
    for mod_name, entry in COLETORES.items():
        mod = importlib.import_module(mod_name)
        if entry:
            fn = getattr(mod, entry, None)
            assert callable(fn), f"{mod_name}.{entry} deveria ser chamável (entry do cron)"


def test_smoke_status_coleta_contrato():
    """Toda função pura devolve (status, erro) com status no vocabulário certo,
    sem tocar banco. Uma amostra por fonte — o detalhe da regra é comportamento
    em test_correcoes_auditoria.py."""
    from ingestion import status_coleta as st
    amostras = [
        st.simec_par(3, 0), st.simec_par(3, 3),
        st.cauc(60, 60), st.cauc(0, 60),
        st.acordofes(100, 10), st.acordofes(0, 0),
        st.sigcon_ckan(50, 40, True), st.sigcon_ckan(50, 0, True),
        st.segov_pagamentos(10, 10, 50, 40), st.segov_pagamentos(0, 0, 50, 0),
        st.cge_despesa_ob(6, 6, 30, 28), st.cge_despesa_ob(6, 6, 30, 0), st.cge_despesa_ob(5, 6, 30, 28),
        st.siconv_federal(1_000_000, 900_000), st.siconv_federal(0, 10),
        st.por_falhas(10, 0, "x"), st.por_falhas(10, 3, "x"),
    ]
    for status, erro in amostras:
        assert status in STATUS_VALIDOS, f"status fora do vocabulário: {status!r}"
        # success nunca carrega motivo de erro; partial/error sempre carregam.
        assert (erro is None) == (status == "success")


def test_smoke_status_coleta_import_nos_dois_estilos():
    """`from ingestion import status_coleta` (pytest/pacote) e `import
    status_coleta` (script solto no diretório) precisam ambos resolver."""
    import sys
    m1 = importlib.import_module("ingestion.status_coleta")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ingestion"))
    try:
        m2 = importlib.import_module("status_coleta")
    finally:
        sys.path.pop(0)
    assert callable(m1.siconv_federal) and callable(m2.siconv_federal)
