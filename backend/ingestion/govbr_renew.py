"""Auto-RECONEXAO da sessao gov.br/SICONV — SEM login, SEM reCAPTCHA.

Ideia: ha DUAS camadas de sessao:
  - SSO gov.br (acesso.gov.br)  -> cookies Govbrid/Session_Gov_Br_Prod/...
  - SICONV/JEE (discricionarias) -> JSESSIONID (derivado do SSO via SAML)

O keep-alive antigo (httpx) so resetava o JEE e NAO conseguia refazer o SAML
(precisa de JS). Aqui, num browser real (Playwright), navegamos a entrada do
discricionarias: isso dispara o SAML, que -> bate no SSO (mantendo o SSO QUENTE)
-> se o SSO ainda e valido, volta com nova assertion -> NOVO JSESSIONID JEE.
Ou seja, RE-DERIVAMOS a sessao a cada ciclo, sem login. Salvamos os cookies
frescos no Cofre. Enquanto o SSO viver, a conexao se mantem sozinha.

So quando o SSO expira de vez (teto duro do gov.br) e que cai em /idp/ e ai
retorna 'needs_recapture' — NAO tentamos login (tem reCAPTCHA, nao automatizamos).

Roda como cron (Dockerfile.scraper, Playwright) a cada ~10min.
Uso: COFRE_KEY=... DATABASE_URL_SYNC=... python ingestion/govbr_renew.py
"""
from __future__ import annotations
import os
import sys
import json
import asyncio
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
from services import crypto

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("govbr_renew")

# Entrada autenticada do discricionarias — dispara o SAML (round-trip no SSO).
ENTRY = ("https://discricionarias.transferegov.sistema.gov.br/voluntarias/ForwardAction.do"
         "?modulo=Principal&path=/MostraPrincipalConsultarProposta.do")

# Entrada do /private/ das mandatarias (projeto-basico). E um SP gov.br SEPARADO:
# o SSO re-derivado nao o cobre, entao ele expira por INATIVIDADE se ninguem o
# consulta. A captura da extensao estabelece a sessao dele; para NAO precisar de
# re-captura, o keepalive abaixo navega esta pagina com frequencia (< timeout de
# idle do JEE, ~20-30min) e re-salva os cookies -> mantem o /private/ vivo
# "sempre consultando". Os cookies mandatarias entram no jar (filtro pega
# 'transferegov'). Se ja tiver caido no login, navegar aqui NAO revive (login tem
# reCAPTCHA) -> vira 'private_dead' e o monitor de frescor acusa.
PRIVATE_ENTRY = ("https://mandatarias.transferegov.sistema.gov.br/"
                 "projeto-basico/private/index.jsf")

# Modulo "Execucao Convenente > Processo de Execucao" (ListarLicitacoes). Assim
# como o /private/, e um SP SAML SEPARADO: a sessao dele expira por inatividade e
# o govbr-renew (que so reaquece o discricionarias) NAO a mantinha — por isso a
# situacao da licitacao (processo_execucao) parava de ser capturada horas apos a
# captura. Navegar esta URL no keepalive reseta o idle desse SP e re-salva os
# cookies -> mantem `TgHttpEnrich.processo_execucao_lista` funcionando. Se ja
# caiu no login (idp), navegar aqui NAO revive (precisa re-captura), igual ao
# /private/.
EXEC_ENTRY = ("https://discricionarias.transferegov.sistema.gov.br/"
              "voluntarias/execucao/ListarLicitacoes/ListarLicitacoes.do?destino=ListarLicitacoes")

# Subdominios p/ repovoar JSESSIONIDs frescos + manter o SSO quente.
SUBDOMINIOS = [
    ENTRY,
    "https://parcerias.transferegov.sistema.gov.br/ep-atos-prep-web/home",
    "https://cadastro.transferegov.sistema.gov.br/ep-cadastro-web/home",
    PRIVATE_ENTRY,
]


def _sync_url() -> str:
    return (os.getenv("DATABASE_URL_SYNC", "")
            .replace("&channel_binding=require", "")
            .replace("?channel_binding=require", ""))


def _load_govbr() -> tuple[int | None, list | None]:
    """(cofre_id, cookies) da sessao govbr mais recente com cookies."""
    try:
        conn = psycopg2.connect(_sync_url(), connect_timeout=10)
        cur = conn.cursor()
        cur.execute("SELECT id, senha_hash FROM cofre_senhas "
                    "WHERE automation_key='govbr' AND length(senha_hash) > 1000 "
                    "ORDER BY updated_at DESC LIMIT 1")
        row = cur.fetchone()
        cur.close(); conn.close()
        if not row:
            return None, None
        dec = crypto.decrypt(row[1])
        if not dec or not dec.startswith("{"):
            return None, None
        return row[0], json.loads(dec).get("cookies", [])
    except Exception as e:
        log.warning(f"_load_govbr: {e}")
        return None, None


def _to_pw_cookies(cookies: list) -> list:
    out = []
    for c in cookies:
        n, v = c.get("name"), c.get("value")
        if not n or v is None:
            continue
        ck = {"name": n, "value": v, "path": c.get("path") or "/",
              "secure": bool(c.get("secure")), "httpOnly": bool(c.get("httpOnly"))}
        dom = c.get("domain")
        if dom:
            ck["domain"] = dom
        ss = c.get("sameSite")
        if ss:
            ck["sameSite"] = {"no_restriction": "None", "lax": "Lax", "strict": "Strict",
                              "None": "None", "Lax": "Lax", "Strict": "Strict"}.get(ss, "Lax")
        exp = c.get("expirationDate") or c.get("expires")
        if exp and float(exp) > 0:
            try:
                ck["expires"] = float(exp)
            except (TypeError, ValueError):
                pass
        out.append(ck)
    return out


def _from_pw_cookies(cookies: list) -> list:
    """Converte cookies do Playwright p/ o formato de storage do Cofre."""
    out = []
    for c in cookies:
        out.append({
            "name": c.get("name"), "value": c.get("value"),
            "domain": c.get("domain"), "path": c.get("path") or "/",
            "secure": bool(c.get("secure")), "httpOnly": bool(c.get("httpOnly")),
            "sameSite": c.get("sameSite"),
            "expirationDate": c.get("expires") if c.get("expires", -1) and c.get("expires", -1) > 0 else None,
        })
    return out


def _save_cookies(cofre_id: int, cookies_pw: list) -> None:
    """Sobrescreve os cookies da sessao govbr no Cofre (mesma linha id)."""
    payload = {
        "format": "cookies_full",
        "cookies": _from_pw_cookies(cookies_pw),
        "url": "https://discricionarias.transferegov.sistema.gov.br/voluntarias/",
        "domain": "discricionarias.transferegov.sistema.gov.br",
    }
    enc = crypto.encrypt(json.dumps(payload))
    conn = psycopg2.connect(_sync_url(), connect_timeout=10)
    cur = conn.cursor()
    cur.execute("UPDATE cofre_senhas SET senha_hash=%s, updated_at=NOW() WHERE id=%s", (enc, cofre_id))
    conn.commit(); cur.close(); conn.close()


def _is_authenticated(url: str, body: str) -> bool:
    u = (url or "").lower(); b = (body or "").lower()
    if "/idp/" in u or "sso.acesso.gov.br" in u or "identifique-se" in b or "acesso restrito" in b:
        return False
    return "voluntarias" in u and "sair" in b


async def renew() -> str:
    """Retorna 'reconnected' | 'needs_recapture' | 'no_session'."""
    cofre_id, cookies = _load_govbr()
    if not cookies:
        log.info("sem sessao govbr no Cofre — aguardando captura via extensao")
        return "no_session"
    log.info(f"cofre id={cofre_id} | {len(cookies)} cookies (re-derivando via SAML, sem login)")
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True,
                                     args=["--ignore-certificate-errors", "--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await br.new_context(ignore_https_errors=True,
                                   user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                                              "Chrome/131.0.0.0 Safari/537.36")
        try:
            await ctx.add_cookies(_to_pw_cookies(cookies))
        except Exception as e:
            log.warning(f"add_cookies: {str(e)[:80]}")
        page = await ctx.new_page()
        try:
            await page.goto(ENTRY, timeout=60000, wait_until="domcontentloaded")
        except Exception as e:
            log.warning(f"goto entry: {str(e)[:80]}")
        await page.wait_for_timeout(8000)  # SAML auto-submit
        body = ""
        try:
            body = await page.evaluate("() => document.body.innerText")
        except Exception:
            pass
        if not _is_authenticated(page.url, body):
            log.warning(f"SSO expirou (caiu em {page.url[:60]}) — precisa RE-CAPTURA "
                        f"(login tem reCAPTCHA, nao automatizavel)")
            await br.close()
            return "needs_recapture"
        # SSO vivo -> re-derivado. Repovoa JSESSIONIDs dos subdominios + mantem SSO quente.
        for sd in SUBDOMINIOS[1:]:
            try:
                await page.goto(sd, timeout=30000, wait_until="domcontentloaded")
                await page.wait_for_timeout(2500)
            except Exception:
                pass
        fresh = await ctx.cookies()
        relevant = [c for c in fresh if any(d in (c.get("domain") or "")
                    for d in ("transferegov", "sso.acesso.gov.br", "gov.br"))]
        await br.close()
        try:
            _save_cookies(cofre_id, relevant)
            log.info(f"RECONECTADO ✓ — {len(relevant)} cookies frescos salvos no Cofre")
        except Exception as e:
            log.error(f"falha ao salvar cookies: {str(e)[:100]}")
            return "needs_recapture"
        return "reconnected"


async def keepalive() -> str:
    """Keep-alive LEVE do /private/ (mandatarias), pensado p/ rodar a cada ~10min.

    So navega o guest (mantem SSO quente) e o /private/ (reseta o idle do JEE),
    re-salvando os cookies. NAO faz o round-trip pesado do renew(). Enquanto rodar
    mais rapido que o timeout de inatividade do /private/, ele NUNCA cai -> sem
    re-captura. Retorna 'alive' | 'private_dead' | 'no_session'.
    """
    cofre_id, cookies = _load_govbr()
    if not cookies:
        log.info("keepalive: sem sessao no Cofre")
        return "no_session"
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True,
                                     args=["--ignore-certificate-errors", "--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await br.new_context(ignore_https_errors=True,
                                   user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                                              "Chrome/131.0.0.0 Safari/537.36")
        try:
            await ctx.add_cookies(_to_pw_cookies(cookies))
        except Exception as e:
            log.warning(f"keepalive add_cookies: {str(e)[:80]}")
        page = await ctx.new_page()
        # 1) guest: mantem o SSO/discricionarias quente (barato)
        try:
            await page.goto(ENTRY, timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(4000)
        except Exception as e:
            log.warning(f"keepalive guest: {str(e)[:80]}")
        # 2) /private/: reseta o idle do JEE das mandatarias
        private_ok = False
        try:
            await page.goto(PRIVATE_ENTRY, timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(4000)
            u = (page.url or "").lower()
            private_ok = "idp/" not in u and "sso.acesso" not in u
        except Exception as e:
            log.warning(f"keepalive private: {str(e)[:80]}")
        # 3) execucao (Processo de Execucao): reseta o idle do SP `execucao`,
        #    mantendo a captura da situacao da licitacao (processo_execucao) viva.
        exec_ok = False
        try:
            await page.goto(EXEC_ENTRY, timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            eu = (page.url or "").lower()
            exec_ok = "idp/" not in eu and "sso.acesso" not in eu
        except Exception as e:
            log.warning(f"keepalive execucao: {str(e)[:80]}")
        fresh = await ctx.cookies()
        relevant = [c for c in fresh if any(d in (c.get("domain") or "")
                    for d in ("transferegov", "sso.acesso.gov.br", "gov.br"))]
        await br.close()
    if not relevant:
        return "private_dead"
    try:
        _save_cookies(cofre_id, relevant)
    except Exception as e:
        log.error(f"keepalive save: {str(e)[:100]}")
    if private_ok:
        log.info(f"keepalive OK — /private/ vivo, execucao={'vivo' if exec_ok else 'CAIU'}, "
                 f"{len(relevant)} cookies re-salvos")
        return "alive"
    log.warning(f"keepalive — /private/ CAIU (idp/login), execucao={'vivo' if exec_ok else 'CAIU'}. "
                "Precisa re-captura pela extensao.")
    return "private_dead"


if __name__ == "__main__":
    import sys
    modo = sys.argv[1] if len(sys.argv) > 1 else "renew"
    print(asyncio.run(keepalive() if modo == "keepalive" else renew()))
