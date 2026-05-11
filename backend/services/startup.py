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
    "add_plano_trabalho_nf.sql",
    "add_camara_dou_compliance.sql",
    # Seeds (idempotentes)
    "seed_parlamentares_institucionais.sql",
]


def run_migrations():
    """Roda todas as migrations SQL na ordem. Idempotente."""
    sync_url = os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
    if not sync_url:
        logger.warning("DATABASE_URL_SYNC nao configurada - pulando migrations")
        return

    try:
        import psycopg2
    except ImportError:
        logger.warning("psycopg2 nao instalado - pulando migrations")
        return

    base = Path(__file__).parent.parent / "migrations"
    if not base.exists():
        logger.warning(f"Pasta migrations nao encontrada: {base}")
        return

    rodadas = 0
    for fname in MIGRATION_FILES:
        path = base / fname
        if not path.exists():
            continue
        try:
            with psycopg2.connect(sync_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(path.read_text(encoding="utf-8"))
                conn.commit()
            rodadas += 1
            logger.info(f"  Migration OK: {fname}")
        except Exception as e:
            # Erros tipicos: tabela ja existe, coluna ja adicionada - sao seguros
            msg = str(e)[:200]
            if any(k in msg.lower() for k in ["already exists", "duplicate", "ja existe"]):
                logger.info(f"  Migration {fname}: ja aplicada (skip)")
            else:
                logger.warning(f"  Migration {fname} falhou: {msg}")

    logger.info(f"Startup migrations: {rodadas}/{len(MIGRATION_FILES)} executadas")
