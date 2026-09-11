"""A-3 (auditoria 11/09) — PREPARADO, AINDA NÃO PLUGADO.

Helper de rastreabilidade para o `ingestion_log` cobrir também o job que MORRE
antes do `finished_at` (hoje a linha só é escrita no fim; run morto pelo timeout/
runner some sem deixar rastro — foi o apagão silencioso de 9 dias do Freitas).

⚠️ NÃO está em uso por nenhum coletor ainda. O rollout (adotar isto onde hoje há
`INSERT INTO ingestion_log` no fim) e a migration `add_ingestion_log_heartbeat.sql`
estão no checklist de produção. Depende de:
  1. registrar a migration em services/startup.py::MIGRATION_FILES;
  2. trocar, coletor a coletor, o INSERT-no-fim por este context manager;
  3. ensinar o watchdog a marcar `running` com heartbeat velho como stale.
Como muda o padrão de escrita de ~29 coletores em 6 bancos, o rollout é gradual e
validado por fonte — por isso vai PREPARADO, não aplicado às cegas.

Padrão de uso pretendido:

    from services.ingest_heartbeat import run_log
    with run_log("fns") as h:
        ...
        h.beat()                       # em laços longos
        ...
        h.finish("success", records=n) # ou 'partial'/'error' + erro

Se o bloco levantar exceção, o __exit__ grava 'error' com a mensagem — nunca fica
sem linha. Se o processo for MORTO (SIGKILL/timeout), a linha fica em 'running' com
heartbeat velho, e o watchdog a converte em stale/error.
"""
from __future__ import annotations

import os
from contextlib import contextmanager


def _conn():
    import psycopg2
    url = (os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL", "").replace("+asyncpg", ""))
    return psycopg2.connect(url.replace("&channel_binding=require", "").replace("?channel_binding=require", ""))


class _Run:
    def __init__(self, conn, row_id: int):
        self._conn = conn
        self._id = row_id
        self._final = False

    def beat(self) -> None:
        """Reseta o heartbeat — chamar dentro de laços longos."""
        try:
            with self._conn.cursor() as c:
                c.execute("UPDATE ingestion_log SET heartbeat_at = NOW() WHERE id = %s", (self._id,))
            self._conn.commit()
        except Exception:
            self._conn.rollback()

    def finish(self, status: str, records: int = 0, erro: str | None = None) -> None:
        try:
            with self._conn.cursor() as c:
                c.execute(
                    "UPDATE ingestion_log SET status=%s, records_inserted=%s, "
                    "error_message=%s, finished_at=NOW(), heartbeat_at=NOW() WHERE id=%s",
                    (status, records, erro, self._id))
            self._conn.commit()
            self._final = True
        except Exception:
            self._conn.rollback()


@contextmanager
def run_log(source: str):
    """Abre uma linha `running` (started_at=NOW) e garante status final.

    Best-effort: se o próprio log falhar, o coletor não cai por isso (mesma
    disciplina dos `_log_ingest` atuais)."""
    conn = _conn()
    row_id = None
    try:
        with conn.cursor() as c:
            c.execute(
                "INSERT INTO ingestion_log (source, status, records_inserted, "
                "started_at, heartbeat_at) VALUES (%s,'running',0,NOW(),NOW()) RETURNING id",
                (source,))
            row_id = c.fetchone()[0]
        conn.commit()
    except Exception:
        conn.rollback()
    run = _Run(conn, row_id) if row_id is not None else None
    try:
        yield run
        if run and not run._final:
            run.finish("success")
    except Exception as e:
        if run and not run._final:
            run.finish("error", 0, str(e)[:400])
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass
