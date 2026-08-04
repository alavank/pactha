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
import time
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
    # Modo Tela do BI: filtro POR USUARIO + links publicos curtos e revogaveis
    "add_bi_tela.sql",
    # CAGEC (regularidade estadual MG). A coleta e publica, por CNPJ, sem
    # credencial — ver routers/cagec.py e ingestion/cagec_scraper.py.
    "add_cagec.sql",
    # separa Prefeitura, Fundo Municipal de Saude e FMAS — cadastros proprios
    "add_cagec_entidades.sql",
    # de quando e o detalhamento do CRC, e o erro do portal quando ele nao sai
    "add_cagec_crc_estado.sql",
    # Tipo do link publicado: TV de parede ('tela') ou app de celular ('mobile')
    "add_bi_tela_link_kind.sql",
    # Historico da IA por usuario, retencao de 30 dias (expurgo automatico)
    "add_ai_historico.sql",
    # SISMOB: obras de saude do MS (API publica, sem login). Tabela propria —
    # obra tem etapa/percentual/empreiteira, que nao cabem em 'convenio'.
    "add_sismob.sql",
    # Base publica nacional do SICONV (dados abertos), usada na consulta por CNPJ.
    # Nasceu ORFA em a53afcc: o commit criou a migration e nao a registrou aqui,
    # entao o runner nunca a executava. Nas instancias antigas a tabela existe
    # porque foi criada a mao; num tenant novo ela simplesmente nao nascia e
    # `routers/transferegov.py` (que consulta sem guarda) devolvia 500. E
    # CREATE TABLE/INDEX IF NOT EXISTS, sem INSERT: inerte onde ja existe.
    "add_siconv_federal.sql",
    # Marca de quiosque no USUARIO (nao no claim do JWT, que o refresh nao
    # repassa). Fecha o link publico de TV no Painel de Indicadores.
    # DEPENDE de add_bi_tela.sql — o backfill le bi_tela_links — por isso vem
    # depois dela nesta lista.
    "add_users_kiosk.sql",
    # Auditoria detalhada: municipio, sessao, resultado, rota, snapshots legiveis
    # e valor-antes/valor-depois. Puramente ADITIVA sobre audit_log — nenhuma
    # coluna existente muda, nenhuma linha antiga e reescrita (o unico UPDATE e
    # o backfill do nome do autor, com guarda `usuario_nome IS NULL`).
    "add_auditoria_detalhada.sql",
    # Incremento 4 — o papel vira ROTULO: `super_admin` e `somente_leitura` no
    # usuario, e o BACKFILL que evita o apagao (todo admin de cliente ganha,
    # explicitamente, as telas e municipios que hoje ele so tem pelo bypass de
    # `role == 'admin'`). DEPENDE de add_user_telas / add_user_municipios (as
    # tabelas que ela preenche) e de add_users_kiosk (le `users.kiosk`), todas
    # acima nesta lista. O backfill so pode rodar UMA VEZ — a propria migration
    # cria `migration_backfills` para isso; ver o cabecalho dela.
    "add_role_vira_rotulo.sql",
    # Incremento 5 — permissao por ACAO (`recurso.acao`) por usuario: a
    # tabela-catalogo (chave estrangeira que mata o typo silencioso), a tabela
    # de concessao e o BACKFILL de compatibilidade (quem tem a tela X ganha
    # X.ver/X.exportar; os verbos de escrita so para quem e admin hoje).
    # DEPENDE de add_role_vira_rotulo.sql — le `users.super_admin` e conta com
    # `migration_backfills`, os dois criados la — por isso vem depois dela.
    # O backfill so pode rodar UMA VEZ; ver o cabecalho da migration.
    "add_permissoes_por_acao.sql",
    # Incremento 6 — ALCANCE por linha (Row-Level), por usuario e por MODULO:
    # a tabela-catalogo dos modulos escopaveis (FK que mata o typo silencioso) e
    # o alcance escolhido por usuario. DEPENDE de add_permissoes_por_acao.sql
    # so por ordem conceitual (a tabela `users` ja existe muito antes).
    # ⚠️ NAO tem backfill, de proposito: ausencia de linha e `todos`, que e o
    # comportamento de hoje — ninguem perde a edicao no deploy. Ver o cabecalho
    # da migration antes de acrescentar qualquer INSERT ali.
    "add_escopo_por_modulo.sql",
    # Incremento 7 — MODELOS de permissao (o "molde"): as tres tabelas
    # (modelo, conteudo, alcance) e a semente dos QUATRO moldes de prefeitura.
    # DEPENDE de add_permissoes_por_acao.sql (le `permissoes_catalogo`, alvo da
    # FK) e de add_escopo_por_modulo.sql (le `escopo_recursos`) — as duas acima
    # nesta lista.
    # ⚠️ A semente CRUZA `migration_backfills`, ao contrario da semente do
    # catalogo de permissoes: molde e dado que o ADMINISTRADOR edita e apaga, e
    # sem a marca o boot seguinte ressuscitaria o molde apagado ontem. Ver o
    # cabecalho da migration antes de mexer no INSERT.
    "add_modelos_de_permissao.sql",
    # ⚠️ SEMPRE A ULTIMA DA LISTA. Instala o append-only da trilha: gatilho que
    # RECUSA UPDATE/DELETE/TRUNCATE em audit_log e cadeia de hash calculada
    # dentro do banco. Toda migration que ainda faz BACKFILL (hoje so
    # add_auditoria_detalhada.sql, que reescreve `usuario_nome`) tem de rodar
    # ANTES — com o gatilho no ar, um UPDATE de backfill quebraria o BOOT.
    # Migration nova que precise reescrever audit_log entra ACIMA desta linha,
    # nunca abaixo.
    "add_auditoria_imutavel.sql",
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


# Teto de espera pelo outro worker. Generoso porque a espera real e o tempo das
# migrations do OUTRO worker (segundos), e curto o bastante para nunca pendurar o
# boot: estourou, este worker roda sem o lock — que e exatamente o que ja
# acontecia antes, entao o pior caso e o comportamento antigo.
LOCK_ESPERA_S = 120.0
LOCK_INTERVALO_S = 0.5


def _tomar_lock_migrations(sync_url: str):
    """Pega o advisory lock do boot e DEVOLVE A CONEXAO que o segura.

    Devolve a conexao (quem chamou fecha no fim) ou None — e `None` significa
    "siga sem lock", nunca "pule as migrations". Ver o porque no fim.

    ⚠️ 1. POR QUE DEVOLVER A CONEXAO, E NAO SO UM BOOLEANO. Advisory lock pego com
    `pg_try_advisory_lock` e de SESSAO: vive enquanto a CONEXAO viver e morre com
    ela. A versao anterior tomava o lock dentro de um
    `with psycopg2.connect(...) as conn:` e seguia em frente — mas em psycopg2 o
    `with` de conexao fecha a TRANSACAO, nao a conexao; quem fechava era o coletor
    de lixo, no instante em que a variavel `conn` era reatribuida pelo proximo
    `with psycopg2.connect(...)`, poucas linhas abaixo e ANTES da primeira
    migration. A garantia de "so 1 worker" era ficcao: os dois processos do
    `--workers 2` (Dockerfile.api/Procfile) rodavam a lista inteira em paralelo.
    Ninguem notou porque quase tudo e `IF NOT EXISTS` e o runner engole erro.

    Deixou de ser inofensivo quando entrou comando sem forma idempotente barata
    (`ALTER TABLE ... DROP CONSTRAINT`, em add_auditoria_imutavel.sql): dois
    workers no mesmo arquivo fazem o perdedor da corrida abortar a TRANSACAO
    INTEIRA da migration e registrar "Migration ... falhou" num boot que deu
    certo. O banco fica correto (o vencedor commitou), mas o log passa a acusar
    falha em boot saudavel — e log de migration que grita erro no dia a dia e log
    que ninguem le mais.

    ⚠️ 2. POR QUE ESPERAR EM VEZ DE PULAR. O codigo antigo dizia "outro worker
    rodando - pulando", e pular parece mais rapido. Mas quem pula VOLTA A SERVIR
    ANTES DE O SCHEMA ESTAR PRONTO: no primeiro boot de um tenant novo, o worker 2
    comecaria a responder requisicao contra um banco em que a coluna que ele vai
    consultar ainda nao existe. Esperar o outro terminar e depois rodar a lista de
    novo custa alguns segundos (tudo idempotente, o segundo passe nao faz
    trabalho) e paga por: nenhum worker serve com schema pela metade, e as
    migrations nunca correm em paralelo — some a classe inteira de corrida.

    Espera por SONDAGEM (`pg_try_advisory_lock` em intervalos) e nao com
    `pg_advisory_lock` bloqueante de proposito: sondando, o teto de espera e
    codigo nosso, visivel e testavel, em vez de depender de `lock_timeout` valer
    para lock de advisory nesta versao do servidor.

    `autocommit` porque so precisamos da sessao viva: sem isto a conexao ficaria
    `idle in transaction` durante toda a migration, segurando snapshot a toa."""
    import psycopg2
    conn = None
    try:
        conn = psycopg2.connect(sync_url)
        conn.autocommit = True
        limite = time.monotonic() + LOCK_ESPERA_S
        avisou = False
        while True:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(987654321)")
                if cur.fetchone()[0]:
                    return conn
            if time.monotonic() >= limite:
                _log(f"Outro worker segura o lock ha mais de {LOCK_ESPERA_S:.0f}s "
                     "- rodando as migrations sem ele")
                conn.close()
                return None
            if not avisou:
                _log("Outro worker esta rodando as migrations - esperando ele terminar")
                avisou = True
            time.sleep(LOCK_INTERVALO_S)
    except Exception as e:
        # Falhar em PEGAR o lock nao pode virar "nao rodar as migrations": o boot
        # sem schema e pior que o boot com dois workers concorrendo.
        _log(f"Falha ao adquirir lock - tentando sem: {e}")
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        return None


def run_migrations():
    """Roda todas as migrations SQL na ordem. Idempotente.

    Serializa os workers por advisory lock (uvicorn --workers 2 inicializaria 2
    boots paralelos, criando corrida em DDL). O lock e SEGURADO ate a ultima
    migration — ver `_tomar_lock_migrations` para o porque de isso ser explicito."""
    sync_url = os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
    if not sync_url:
        _log("DATABASE_URL_SYNC nao configurada - pulando migrations")
        return

    try:
        import psycopg2
    except ImportError:
        _log("psycopg2 nao instalado - pulando migrations")
        return

    lock_conn = _tomar_lock_migrations(sync_url)
    try:
        _rodar_migrations(sync_url)
    finally:
        # Solta o lock so DEPOIS da ultima migration (e do bootstrap do token).
        if lock_conn is not None:
            try:
                lock_conn.close()
            except Exception:
                pass


def _rodar_migrations(sync_url: str):
    """O trabalho em si, ja com o lock do boot na mao."""
    import psycopg2

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
    _log_estado_da_trava()

    # Bootstrap do control token (Console Alavank), apos as migrations (kind ja existe).
    _bootstrap_control_token(sync_url)


def _log_estado_da_trava() -> None:
    """⭐ O BOOT DIZ EM QUE MODO A TRAVA ESTA. Uma linha, e ela paga a si mesma.

    `AUTHZ_MODO` e `AUTHZ_REGISTRO` mudam o que o sistema RECUSA, e nao deixavam
    rastro nenhum: para saber se a trava estava ligada era preciso abrir o painel
    do Coolify e ler a variavel — ou seja, a resposta vinha de onde alguem
    DECLAROU o estado, e nao de onde ele vale. As duas coisas divergem no dia em
    que a env e criada e o container nao reinicia.

    E as duas sao FAIL-OPEN por escolha (`AUTHZ_MODO=bloqueiop`, com o dedo
    escorregando no teclado, segue em `aviso`): o valor invalido nao liga a trava
    e tambem nao quebra o boot. Sem esta linha, esse erro de digitacao e
    invisivel — o sistema parece protegido e nao esta, que e a pior das duas
    formas de estar errado.

    Nao levanta: log de diagnostico nao pode ser o que derruba a API."""
    try:
        from services import authz, registro_rotas
        _log(f"Trava de permissao: AUTHZ_MODO={authz.modo()} "
             f"| AUTHZ_REGISTRO={registro_rotas.modo()}")
    except Exception as e:  # pragma: no cover - diagnostico nunca derruba o boot
        _log(f"Trava de permissao: nao foi possivel ler o modo ({str(e)[:80]})")


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
