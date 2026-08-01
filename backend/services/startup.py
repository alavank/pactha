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
    # RBAC por tela/municipio (estavam fora da lista -> ausentes em clones novos)
    "add_user_telas.sql",
    "add_user_municipios.sql",
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
    # UNIQUE INDEX em nr_siafi (previne duplicacao scraper+CKAN)
    "add_unique_nr_siafi.sql",
    # Valores monetarios das Voluntarias (valor_global/repasse/contrapartida)
    "add_voluntarias_valores.sql",
    # SIMEC PAR (consulta publica MEC) - dimensoes + liberacoes
    "add_simec_par.sql",
    # Relatorio de Monitoramento (RM) - padrao Freitas
    "add_rm.sql",
    # Voluntarias: situacao contratacao + clausula suspensiva detalhe + parlamentar
    "add_voluntarias_clausula_parlamentar.sql",
    # Voluntarias: detalhe generico da Situacao de Contratacao (qualquer tipo)
    "add_voluntarias_situacao_detalhe.sql",
    # Voluntarias: processo_execucao_qtd (licitacoes do instrumento - Execucao Convenente)
    "add_voluntarias_processo_execucao.sql",
    # Voluntarias: Historico de Comunicacoes + Termos de Notificacao (mandatarias)
    "add_voluntarias_historico_comunicacoes.sql",
    # Voluntarias: OPs/OBs (repasses/desembolsos) + OBRAS (acompanhamento medicao)
    "add_voluntarias_ops_obs_obras.sql",
    # Modulo Gestao Interna (anotacoes + anexos por item)
    "add_gestao_anotacoes.sql",
    # Integracao Telegram (telegram_users + telegram_link_codes)
    "add_telegram.sql",
    # Voluntarias: id_proposta_siconv (casa com open data p/ backfill parlamentar)
    "add_voluntarias_id_proposta_siconv.sql",
    # Log de mudancas de status (trigger) -> aviso no dashboard
    "add_status_changes.sql",
    # Modulo Geracao de Documentos (plano de sustentabilidade etc.)
    "add_documentos.sql",
    # CAUC - regularidade fiscal federal do municipio (dados abertos STN)
    "add_cauc.sql",
    # Acordo FES - divida da saude estadual (SES-MG) com os municipios
    "add_acordofes.sql",
    # Selecao PAC / Novo PAC (TransfereGov guest, por municipio)
    "add_transferegov_pac.sql",
    # Fila de jobs on-demand (ex.: refresh SIGCON disparado pela UI) - Coolify
    "add_scraper_jobs.sql",
    # Acentuacao correta dos rotulos de cidade (convencao "Nome - UF")
    "fix_municipio_acentos.sql",
    # Codigo FNS por municipio (des-hardcoda run_fns_local) - gerido pela Central
    "add_fns_code.sql",
    # Control-plane (Console Alavank): coluna kind em service_tokens
    "add_control_token_kind.sql",
    # SSO tecnico: uso unico REAL do token (compartilhado entre workers)
    "add_sso_used_jti.sql",
    # Painel Executivo do prefeito: push subscriptions + preferencias + dedupe + cache IA
    "add_painel_push.sql",
    # Rodizio de coleta por municipio ("mais desatualizado primeiro"). Mata a
    # starvation alfabetica: antes, a rodada era cortada por volta do 10o de 41
    # municipios e os do fim da lista NUNCA eram atualizados, em silencio.
    "add_scraper_municipio_coleta.sql",
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

    # Schema base (tabelas + seed) antes das migrations incrementais. No Coolify
    # nao existe o passo manual "rodar setup_db.py uma vez"; e idempotente
    # (CREATE TABLE IF NOT EXISTS + INSERT ON CONFLICT DO NOTHING). O seed so roda
    # quando a tabela users esta vazia (evita re-hash/print de senha a cada boot).
    try:
        import setup_db
        setup_db.create_tables()
        # Tabelas modeladas ausentes do setup_db e sem migration CREATE (ex.:
        # cofre_senhas, audit_log): cria a partir dos models SQLAlchemy.
        # checkfirst=True nao toca tabelas ja existentes.
        try:
            import models  # noqa: F401 - registra todos os models em Base.metadata
            from database import Base
            from sqlalchemy import create_engine as _ce
            _eng = _ce(sync_url)
            Base.metadata.create_all(_eng, checkfirst=True)
            _eng.dispose()
            _log("create_all (tabelas modeladas) OK")
        except Exception as e:
            _log(f"create_all falhou: {str(e)[:150]}")
        with psycopg2.connect(sync_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users")
                n_users = cur.fetchone()[0]
            conn.commit()
        if n_users == 0:
            setup_db.seed_data()
            _log("Seed inicial aplicado (users estava vazio)")
        _log("Schema base (setup_db) OK")
    except Exception as e:
        _log(f"setup_db falhou (seguindo assim mesmo): {str(e)[:200]}")

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

    # Bootstrap do control token (Console Alavank), apos as migrations (kind ja existe).
    _bootstrap_control_token(sync_url)


def _bootstrap_control_token(sync_url: str):
    """Se CONTROL_TOKEN_BOOTSTRAP estiver no env e ainda nao houver control token,
    cria um ServiceToken(kind='control', scopes=['control:*']) com o hash do raw.
    Idempotente: nao recria se ja existe um control token. O raw fica so no Console."""
    raw = os.getenv("CONTROL_TOKEN_BOOTSTRAP", "").strip()
    if not raw or len(raw) < 32:
        return
    import json
    import hashlib
    try:
        import psycopg2
    except ImportError:
        return
    th = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    prefix = raw[:12]
    try:
        with psycopg2.connect(sync_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM service_tokens WHERE kind = 'control'")
                if cur.fetchone()[0] == 0:
                    cur.execute(
                        "INSERT INTO service_tokens "
                        "(name, kind, token_hash, token_prefix, scopes, description, active) "
                        "VALUES ('console-alavank', 'control', %s, %s, %s::jsonb, "
                        "'Control-plane token (Console Alavank)', true) "
                        "ON CONFLICT (name) DO NOTHING",
                        (th, prefix, json.dumps(["control:*"])),
                    )
            conn.commit()
        _log("Control token bootstrap: OK (criado ou ja existia)")
    except Exception as e:
        _log(f"Control token bootstrap falhou: {str(e)[:150]}")
