"""
Startup tasks executadas no boot do FastAPI.

Roda migrations idempotentes ao subir o backend, garantindo que:
- Tabelas existem (mesmo apos reset do DB)
- Seeds institucionais (Comissao da Saude, Bancada MG, etc.) estao populados
- Indices estao criados

Cada migration e rodada via psycopg2 raw - usa SYNC para nao bloquear o
event loop async no caso de demora. Falha em uma migration nao impede o
boot (logs warning).
"""
import os
import logging
from pathlib import Path

logger = logging.getLogger("startup")

MIGRATION_FILES = [
    # Tabelas core
    "add_audit_and_user_cols.sql",
    "add_service_tokens.sql",
    # Fix +30 anos SIGCON-MG (idempotente)
    "fix_sigcon_year_offset.sql",
    # Fix mojibake UTF-8 (PrestaÃ§Ã£o -> Prestação)
    "fix_mojibake_utf8.sql",
    # UNIQUE INDEX nr_sigcon total (preciso pra ON CONFLICT no UPSERT)
    "fix_unique_nrsigcon_full.sql",
    # nr_proposta + nr_plano_trabalho + qt_alteracoes + dt_assinatura (SIGCON view)
    "add_nr_proposta_estadual.sql",
    # Tabela emendas_estaduais (SIGCON Pesquisar Emendas Por Convenente)
    "add_emendas_estaduais.sql",
    # Refactor lean (2026-05): drop tabelas das features removidas
    "drop_lean_tables.sql",
]


def run_migrations_full():
    """Inclui migrations longas - usar so manual via SSH ou cron."""
    import os, logging
    from pathlib import Path
    extras = ["dedupe_convenios_unique.sql"]
    sync_url = os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
    if not sync_url: return
    import psycopg2
    base = Path(__file__).parent.parent / "migrations"
    for f in extras:
        path = base / f
        if not path.exists(): continue
        try:
            with psycopg2.connect(sync_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(path.read_text(encoding="utf-8"))
                conn.commit()
            print(f"[STARTUP_FULL] {f}: OK", flush=True)
        except Exception as e:
            print(f"[STARTUP_FULL] {f}: {e}", flush=True)


def _log(msg: str):
    """Log + print (garante visibilidade nos logs Railway)."""
    print(f"[STARTUP] {msg}", flush=True)
    logger.warning(msg)


def run_migrations():
    """Roda todas as migrations SQL na ordem. Idempotente.

    Usa advisory lock pra garantir que so 1 worker rode (uvicorn --workers 2
    inicializaria 2 boots paralelos, criando deadlocks em DDL)."""
    sync_url = os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
    if not sync_url:
        _log("DATABASE_URL_SYNC nao configurada - pulando migrations")
        return

    try:
        import psycopg2
    except ImportError:
        _log("psycopg2 nao instalado - pulando migrations")
        return

    # Tenta pegar advisory lock - se outro worker ja tem, pula
    try:
        with psycopg2.connect(sync_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(987654321)")
                got_lock = cur.fetchone()[0]
            conn.commit()
        if not got_lock:
            _log("Outro worker rodando migrations - pulando")
            return
    except Exception as e:
        _log(f"Falha ao adquirir lock - tentando sem: {e}")

    base = Path(__file__).parent.parent / "migrations"
    if not base.exists():
        _log(f"Pasta migrations nao encontrada: {base}")
        return

    rodadas = 0
    for fname in MIGRATION_FILES:
        path = base / fname
        if not path.exists():
            _log(f"  Migration ausente: {fname}")
            continue
        try:
            with psycopg2.connect(sync_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(path.read_text(encoding="utf-8"))
                conn.commit()
            rodadas += 1
            _log(f"  Migration OK: {fname}")
        except Exception as e:
            # Erros tipicos: tabela ja existe, coluna ja adicionada - sao seguros
            msg = str(e)[:200]
            if any(k in msg.lower() for k in ["already exists", "duplicate", "ja existe"]):
                _log(f"  Migration {fname}: ja aplicada (skip)")
            else:
                _log(f"  Migration {fname} falhou: {msg}")

    _log(f"Startup migrations: {rodadas}/{len(MIGRATION_FILES)} executadas")
