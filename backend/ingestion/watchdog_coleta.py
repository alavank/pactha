"""Watchdog da saude da coleta -- torna VISIVEL o que hoje e silencioso.

MOTIVACAO (incidente de 2026-07-23): um scraper do TransfereGov ficou pendurado
por 4h49m sem que ninguem soubesse. O `ingestion_log` so grava DEPOIS que a
execucao termina (sempre com finished_at preenchido), entao uma execucao travada
nao aparece em lugar nenhum -- nem no log, nem no painel. E fontes que pararam de
atualizar (o SIGCON ficou 26h sem ingerir) tambem passavam despercebidas.

Este cron roda a cada ~30 min e detecta DUAS condicoes que hoje ninguem ve:

  1. SCRAPER TRAVADO: um processo `ingestion/*.py` ou um `chrome-headless-shell`
     vivo ha mais tempo que o teto (o reaper ja mata, mas aqui a gente ALERTA
     antes/alem disso -- defesa em profundidade).
  2. FONTE PARADA: uma fonte cujo ultimo `success` no ingestion_log e mais velho
     que o esperado para a frequencia dela (ex.: sigcon deveria rodar 4x/dia;
     se o ultimo sucesso tem >18h, algo travou).

Alerta vai para o Telegram (chat em WATCHDOG_CHAT_ID ou TELEGRAM_CHAT_ID) se
configurado; senao, so loga (o log ja e melhor que o nada de hoje). Nunca falha
o processo por causa do alerta.

Anti-spam: nao repete o mesmo alerta dentro de WATCHDOG_COOLDOWN_MIN (default
180 min) -- estado guardado na tabela watchdog_alertas.

Uso: python -m ingestion.watchdog_coleta
"""
import logging
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("watchdog_coleta")

# Idade maxima esperada do ultimo SUCCESS por fonte, em horas. Fontes fora deste
# mapa nao sao cobradas por frescor (so entram na deteccao de processo travado).
# Derivado das Scheduled Tasks reais + folga.
FRESCOR_HORAS = {
    "sigcon_scraper": 18,            # roda 4x/dia -> 6h; 18h = 3 janelas perdidas
    "transferegov_opendata": 30,     # 1x/dia -> 24h + folga
    "transferegov_voluntarias": 30,
    "transferegov_pac": 30,
    "fns": 30,                       # 1x/dia
    "cauc": 12,
    "acordofes": 12,
    "simec_par": 12,
    "siconv_convenio_backfill": 30,
    "sismob": 30,                    # 1x/dia (auto-throttle no proprio ingest)
}

# Acima desta idade (segundos) um processo de ingestao/Chromium e considerado
# travado. Alinhado ao teto dos crons (timeout -k 30 3000 = 50 min) + margem.
IDADE_TRAVADO_S = int(os.getenv("WATCHDOG_MAX_PROC_S", "3900") or "3900")


def _db_url() -> str:
    return (os.getenv("DATABASE_URL_SYNC", "")
            .replace("&channel_binding=require", "").replace("?channel_binding=require", ""))


def _instancia() -> str:
    return os.getenv("INSTANCE_SLUG") or os.getenv("HOSTNAME") or "pactha"


# --------------------------------------------------------------- deteccao ---

def _fontes_paradas(cur) -> list[dict]:
    """Fontes cujo ultimo SUCCESS e mais velho que o limite da fonte."""
    cur.execute("""
        SELECT source, max(finished_at) AS ultimo
        FROM ingestion_log
        WHERE status = 'success'
        GROUP BY source
    """)
    achados = []
    for source, ultimo in cur.fetchall():
        limite_h = FRESCOR_HORAS.get(source)
        if limite_h is None or ultimo is None:
            continue
        cur.execute("SELECT EXTRACT(EPOCH FROM (now() - %s)) / 3600.0", (ultimo,))
        idade_h = float(cur.fetchone()[0])
        if idade_h > limite_h:
            achados.append({
                "tipo": "fonte_parada",
                "chave": source,
                "detalhe": f"ultimo sucesso ha {idade_h:.1f}h (limite {limite_h}h)",
            })
    # Fontes ESPERADAS que nunca tiveram sucesso nenhum tambem contam.
    cur.execute("SELECT DISTINCT source FROM ingestion_log WHERE status = 'success'")
    com_sucesso = {r[0] for r in cur.fetchall()}
    for source in FRESCOR_HORAS:
        if source not in com_sucesso:
            achados.append({
                "tipo": "fonte_parada",
                "chave": source,
                "detalhe": "nenhum sucesso registrado ainda",
            })
    return achados


def _processos_travados() -> list[dict]:
    """Processos de ingestao / Chromium vivos ha mais que IDADE_TRAVADO_S.

    Le a arvore de processos do PROPRIO container (o watchdog roda como um
    `docker exec` no worker, entao ve os processos dos scrapers). Best-effort:
    se ps/pgrep faltarem, retorna vazio sem quebrar."""
    achados = []
    try:
        # etimes = segundos de vida; args = linha de comando
        out = subprocess.run(
            ["ps", "-eo", "etimes,args"],
            capture_output=True, text=True, timeout=15,
        ).stdout
    except Exception as e:
        logger.debug(f"  ps indisponivel: {e}")
        return achados

    for linha in out.splitlines()[1:]:
        linha = linha.strip()
        if not linha:
            continue
        parte = linha.split(None, 1)
        if len(parte) != 2:
            continue
        try:
            idade = int(parte[0])
        except ValueError:
            continue
        cmd = parte[1]
        eh_ingestao = "ingestion/" in cmd or "ingestion." in cmd
        eh_chrome = "chrome-headless-shell" in cmd or "ms-playwright" in cmd
        if (eh_ingestao or eh_chrome) and idade > IDADE_TRAVADO_S:
            achados.append({
                "tipo": "processo_travado",
                "chave": cmd[:60],
                "detalhe": f"vivo ha {idade // 60} min (teto {IDADE_TRAVADO_S // 60} min)",
            })
    return achados


# --------------------------------------------------------------- anti-spam --

def _garante_tabela(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS watchdog_alertas (
            tipo         VARCHAR(30)  NOT NULL,
            chave        VARCHAR(120) NOT NULL,
            ultimo_envio TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (tipo, chave)
        )
    """)


def _deve_alertar(cur, tipo: str, chave: str, cooldown_min: int) -> bool:
    """True se este alerta nao foi enviado dentro do cooldown. Registra o envio."""
    cur.execute(
        "SELECT EXTRACT(EPOCH FROM (now() - ultimo_envio)) / 60.0 "
        "FROM watchdog_alertas WHERE tipo = %s AND chave = %s",
        (tipo, chave))
    row = cur.fetchone()
    if row is not None and float(row[0]) < cooldown_min:
        return False
    cur.execute(
        "INSERT INTO watchdog_alertas (tipo, chave, ultimo_envio) VALUES (%s, %s, now()) "
        "ON CONFLICT (tipo, chave) DO UPDATE SET ultimo_envio = now()",
        (tipo, chave))
    return True


# --------------------------------------------------------------- envio ------

def _alerta(mensagem: str) -> None:
    """Envia ao Telegram se configurado; sempre loga."""
    logger.warning(f"ALERTA: {mensagem}")
    chat = (os.getenv("WATCHDOG_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not chat or not token:
        logger.info("  (Telegram nao configurado -- alerta so no log)")
        return
    try:
        import asyncio
        from services.telegram import send_message
        asyncio.run(send_message(chat, mensagem))
    except Exception as e:
        logger.warning(f"  falha ao enviar Telegram: {e}")


def main() -> None:
    import psycopg2
    url = _db_url()
    if not url:
        logger.error("DATABASE_URL_SYNC ausente")
        return
    cooldown = int(os.getenv("WATCHDOG_COOLDOWN_MIN", "180") or "180")
    inst = _instancia()

    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        _garante_tabela(cur)
        conn.commit()

        achados = _fontes_paradas(cur) + _processos_travados()
        if not achados:
            logger.info("coleta saudavel: nenhuma fonte parada, nenhum processo travado")
            return

        enviados = 0
        for a in achados:
            if _deve_alertar(cur, a["tipo"], a["chave"], cooldown):
                conn.commit()
                icone = "\U0001F534" if a["tipo"] == "processo_travado" else "\U0001F7E0"
                titulo = "processo travado" if a["tipo"] == "processo_travado" else "fonte parada"
                _alerta(f"{icone} *PACTHA {inst}* — {titulo}\n`{a['chave']}`\n{a['detalhe']}")
                enviados += 1
            else:
                logger.info(f"  (em cooldown, nao reenviado): {a['tipo']} {a['chave']}")
        logger.info(f"watchdog: {len(achados)} achado(s), {enviados} alerta(s) enviado(s)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
