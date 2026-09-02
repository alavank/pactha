"""Keep-alive server-side da sessao gov.br/TransfereGov (discricionarias).

PROBLEMA: o JSESSIONID do SICONV (discricionarias.transferegov) morre em
~20-30min de inatividade. Hoje so a extensao Chrome mantinha viva — mas exige
o Chrome aberto. Este servico faz o keep-alive NO SERVIDOR, 24/7, sem depender
do navegador do usuario.

COMO FUNCIONA:
1. A cada ciclo (~8min, abaixo do timeout do JEE), le os cookies gov.br mais
   frescos do Cofre (automation_key='govbr').
2. Faz GET autenticado numa URL leve do discricionarias.
   - HTTP 200 + conteudo autenticado  -> sessao VIVA: reseta o idle timer,
     re-salva os cookies (que podem ter rotacionado) de volta no Cofre.
   - Redireciona p/ idp/login          -> sessao MORTA: loga aviso (precisa
     re-captura via extensao). Continua tentando — assim que o usuario
     re-capturar, o keep-alive volta a manter viva.
3. Repete pra sempre (loop). Deploy como servico Railway de longa duracao.

LIMITE HONESTO: o gov.br SSO pode ter um teto duro de sessao (ex: 8-24h) por
seguranca. Mesmo com keep-alive, pode exigir re-login periodico. Mas estende
de ~20min para horas/dia — re-captura passa a ser rara, nao a cada 20min.

Uso:
    COFRE_KEY=... DATABASE_URL_SYNC=... python ingestion/govbr_keepalive.py
    # opcional: KEEPALIVE_INTERVAL_SEC (default 480)
"""
from __future__ import annotations
import os
import sys
import json
import time
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import psycopg2
from services import crypto

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("govbr_keepalive")

INTERVAL = int(os.getenv("KEEPALIVE_INTERVAL_SEC", "480"))  # 8 min

# URL autenticada leve do discricionarias (consulta de proposta — exige login).
# Se redirecionar p/ idp/login, a sessao morreu.
KEEPALIVE_URLS = [
    "https://discricionarias.transferegov.sistema.gov.br/voluntarias/ConsultarProposta/"
    "ResultadoConsultaPropostaListaInternet.do?Item=item1&method=consultarProposta",
    "https://parcerias.transferegov.sistema.gov.br/ep-atos-prep-web/home",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}


def _sync_url() -> str:
    return (os.getenv("DATABASE_URL_SYNC", "")
            .replace("&channel_binding=require", "")
            .replace("?channel_binding=require", ""))


def _load_govbr() -> tuple[int, dict] | tuple[None, None]:
    """Retorna (cofre_id, data) da sessao govbr mais recente com cookies."""
    try:
        conn = psycopg2.connect(_sync_url(), connect_timeout=10)
        cur = conn.cursor()
        # ⚠️ MESMO RECORTE DO `govbr_renew._load_govbr`, e os dois precisam
        # concordar. Se o keepalive escolher uma linha e o renovador outra, o
        # keepalive fica re-salvando cookies numa linha que o renovador nunca le
        # — e, pior, empurrando o `updated_at` dela para a frente, o que faz a
        # linha errada vencer o ORDER BY para sempre. Foi exatamente assim que a
        # captura de 02/09 no freitas foi gravada e ignorada.
        cur.execute(
            "SELECT id, senha_hash FROM cofre_senhas "
            "WHERE automation_key='govbr' AND length(senha_hash) > 1000 "
            "AND municipio_id IS NULL "
            "ORDER BY updated_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        cur.close(); conn.close()
        if not row:
            return None, None
        dec = crypto.decrypt(row[1])
        if not dec or not dec.startswith("{"):
            return None, None
        return row[0], json.loads(dec)
    except Exception as e:
        log.warning(f"_load_govbr: {e}")
        return None, None


def _build_jar(data: dict) -> httpx.Cookies:
    """Monta httpx.Cookies PRESERVANDO o dominio de cada cookie.
    Critico: ha 4 JSESSIONID (discricionarias/mandatarias/fiscalizacao/transfere)
    + SSO. Um dict {name:value} colapsaria todos num so. Aqui mantemos por dominio."""
    jar = httpx.Cookies()
    for c in data.get("cookies", []):
        n, v = c.get("name"), c.get("value")
        if not n or v is None:
            continue
        dom = (c.get("domain") or "").lstrip(".") or "transferegov.sistema.gov.br"
        try:
            jar.set(n, v, domain=dom, path=c.get("path") or "/")
        except Exception:
            pass
    return jar


# URL GATED (exige login) p/ DETECTAR se a sessao esta viva: a area autenticada
# do discricionarias redireciona p/ idp quando a sessao morre. ConsultarProposta
# NAO serve (e publica/guest). Usamos a entrada autenticada do modulo.
AUTH_PROBE_URL = ("https://discricionarias.transferegov.sistema.gov.br/voluntarias/"
                  "ForwardAction.do?modulo=Principal&path=/MostraPrincipalConsultarProposta.do")


def _is_authenticated(resp: httpx.Response) -> bool:
    """True se a sessao AUTENTICADA esta viva. CALIBRADO contra sessao real:
    - viva: AUTH_PROBE_URL responde 200, final em /voluntarias/, body tem 'Sair'.
    - morta: redireciona p/ /idp/ (ou body 'Acesso Restrito'/'Identifique-se').
    OBS: 'Acesso Livre' aparece no header MESMO logado — NAO e marcador de morte."""
    final = str(resp.url).lower()
    if "/idp/" in final or "sso.acesso.gov.br" in final or "/login" in final:
        return False
    body = resp.text.lower()
    if any(m in body for m in ("acesso restrito", "identifique-se", "entrar com gov.br")):
        return False
    # positivo: link "Sair" (do sistema) so existe autenticado, e ficou numa
    # pagina interna do modulo voluntarias
    return resp.status_code == 200 and "voluntarias" in final and "sair" in body


def _mark_alive(cofre_id: int):
    """Marca a sessao como mantida viva (bump updated_at).
    NAO reescreve os cookies: o JSESSIONID JEE nao rotaciona durante a sessao
    (so muda no login), entao os cookies armazenados seguem validos enquanto
    viva. Reescrever per-dominio seria fragil (4 JSESSIONIDs homonimos)."""
    try:
        conn = psycopg2.connect(_sync_url(), connect_timeout=10)
        cur = conn.cursor()
        cur.execute("UPDATE cofre_senhas SET updated_at=NOW() WHERE id=%s", (cofre_id,))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        log.warning(f"_mark_alive: {e}")


_TG_API = "https://api.telegram.org/bot{tok}/sendMessage"
_ALERT_COOLDOWN_H = 6  # nao repete o alerta de sessao morta por X horas


def _alert_session_dead():
    """Avisa via Telegram que a sessao gov.br EXPIROU — no maximo 1x a cada
    _ALERT_COOLDOWN_H horas (dedup persistente em automation_kv, pois cada ciclo
    roda em container efemero). Best-effort: nunca quebra o keep-alive.

    Por que existe: o login gov.br tem reCAPTCHA e NAO pode ser re-feito
    automaticamente. Quando a sessao expira (teto duro do SSO), so a re-captura
    manual resolve — entao o minimo e AVISAR na hora, pra re-captura ser rapida."""
    tok = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not tok:
        return
    try:
        conn = psycopg2.connect(_sync_url(), connect_timeout=10)
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS automation_kv "
                    "(k text PRIMARY KEY, v text, updated_at timestamptz DEFAULT now())")
        cur.execute("SELECT updated_at FROM automation_kv WHERE k='govbr_dead_alert'")
        row = cur.fetchone()
        if row and row[0] and (datetime.now(timezone.utc) - row[0]).total_seconds() < _ALERT_COOLDOWN_H * 3600:
            cur.close(); conn.close(); return  # ja avisou ha pouco
        cur.execute("SELECT chat_id FROM telegram_users")
        chats = [r[0] for r in cur.fetchall()]
        # marca ANTES de enviar (evita repetir se o envio demorar/repetir o ciclo)
        cur.execute("INSERT INTO automation_kv (k,v,updated_at) VALUES ('govbr_dead_alert','dead',now()) "
                    "ON CONFLICT (k) DO UPDATE SET v='dead', updated_at=now()")
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        log.warning(f"_alert dedup: {str(e)[:80]}")
        return
    if not chats:
        log.info("sessao morta mas nenhum chat Telegram registrado p/ avisar")
        return
    msg = ("⚠️ *PACTHA* — a sessão gov.br/TransfereGov *expirou*.\n\n"
           "Os dados *federais* (TransfereGov + cláusula suspensiva) não atualizam "
           "sozinhos até você *recapturar* a sessão pela extensão do navegador.\n\n"
           "_Estadual (SIGCON/Emendas) e Saúde (FNS) seguem atualizando normalmente._")
    sent = 0
    for cid in chats:
        try:
            httpx.post(_TG_API.format(tok=tok),
                       json={"chat_id": cid, "text": msg, "parse_mode": "Markdown",
                             "disable_web_page_preview": True}, timeout=20)
            sent += 1
        except Exception as e:
            log.warning(f"_alert send {cid}: {str(e)[:60]}")
    log.info(f"alerta de sessao morta enviado p/ {sent} chat(s) Telegram")


def _clear_dead_alert():
    """Rearma o alerta quando a sessao volta a ficar viva (apaga o marcador)."""
    try:
        conn = psycopg2.connect(_sync_url(), connect_timeout=10)
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS automation_kv "
                    "(k text PRIMARY KEY, v text, updated_at timestamptz DEFAULT now())")
        cur.execute("DELETE FROM automation_kv WHERE k='govbr_dead_alert'")
        conn.commit(); cur.close(); conn.close()
    except Exception:
        pass


def cycle() -> str:
    """Um ciclo de keep-alive. Retorna 'alive' | 'dead' | 'no_session'."""
    cofre_id, data = _load_govbr()
    if not data:
        log.info("sem sessao govbr no Cofre — aguardando captura via extensao")
        return "no_session"
    jar = _build_jar(data)
    with httpx.Client(cookies=jar, headers=HEADERS, verify=False,
                      follow_redirects=True, timeout=30) as cli:
        # 1) PROBE gated: a sessao esta autenticada?
        try:
            r = cli.get(AUTH_PROBE_URL)
            authed = _is_authenticated(r)
        except Exception as e:
            log.warning(f"probe falhou: {str(e)[:80]}")
            authed = False
        # 2) KEEP-ALIVE: hit nos hosts pra resetar idle timer do JEE
        #    (mesmo se a deteccao for incerta, isso preserva a sessao viva)
        for url in KEEPALIVE_URLS:
            try:
                cli.get(url)
            except Exception:
                pass
        if authed:
            _mark_alive(cofre_id)
            log.info("sessao VIVA ✓ — timer resetado")
            return "alive"
        log.warning("sessao MORTA/guest — precisa re-captura via extensao (gov.br)")
        return "dead"


def main():
    log.info(f"=== govbr keep-alive iniciado (intervalo {INTERVAL}s) ===")
    while True:
        try:
            cycle()
        except Exception as e:
            log.error(f"ciclo falhou: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    # modo --once p/ teste pontual
    if "--once" in sys.argv:
        print(cycle())
    else:
        main()
