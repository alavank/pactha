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

# Modulo "Execucao Concedente > Notas de Empenho". ⚠️ NAO E O MESMO SP DO
# `EXEC_ENTRY` ACIMA, ao contrario do que o comentario dele supunha: ele mora sob
# /voluntarias/PRESTACAO/ (e nao /execucao/) e tem idle PROPRIO.
#
# MEDIDO EM PRODUCAO (Freitas, 25/08/2026), e e o que separa os dois:
#   keepalive .......... execucao=vivo, de 10 em 10 minutos, sem falhar
#   projeto basico ..... 0 falhas   (mora em /execucao/ -> coberto)
#   notas de empenho ... 115 falhas (mora em /prestacao/ -> NUNCA tocado)
# Ou seja: a sessao que o keepalive mantinha viva nao era a que as NEs usam, e
# elas morriam por inatividade algumas horas depois de cada captura — com o log
# dizendo "sessao do SP fria?", que estava certo mas apontava para o SP errado.
#
# Navegar esta URL reseta o idle DESSE SP e re-salva os cookies. Se ja caiu no
# login (idp), navegar aqui NAO revive — precisa re-captura, igual aos outros.
PRESTACAO_ENTRY = ("https://discricionarias.transferegov.sistema.gov.br/"
                   "voluntarias/prestacao/_proposta/empenho/"
                   "listarEmpenhosNovoSiafi.jsf?destino=ManterEmpenhoNovoSiafi")

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
        # ⚠️ `municipio_id IS NULL` SEPARA A SESSAO DA CREDENCIAL, e sem isso o
        # renovador le a linha errada. A sessao gov.br e do OPERADOR e vale
        # cross-mun, entao a extensao a grava em escopo de instancia; uma linha
        # COM municipio e a credencial daquela prefeitura (CPF + senha).
        #
        # Em 02/09 isso apareceu em producao no freitas: a extensao antiga
        # mandava `municipio_id`, e a captura — que casa por
        # (automation_key, municipio_id) — gravou o blob de sessao POR CIMA da
        # senha da credencial do IBGE 3103900. Aquela linha passou a satisfazer
        # `length(senha_hash) > 1000` e, como o keepalive re-salva nela a cada
        # ciclo, o `updated_at` dela ficava sempre a frente: a captura nova era
        # gravada e IGNORADA. O sintoma so apareceria na proxima recuperacao —
        # recapturar e continuar sem sessao, sem erro em lugar nenhum.
        cur.execute("SELECT id, senha_hash FROM cofre_senhas "
                    "WHERE automation_key='govbr' AND length(senha_hash) > 1000 "
                    "AND municipio_id IS NULL "
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


SOURCE_SESSAO = "govbr_sessao"
# MUDA-OU-VENCE. O keepalive roda de 10 em 10 minutos = 144 linhas por dia. O
# painel de ingestao mostra as ~80 linhas mais recentes; 144/dia apagariam o
# historico de TODAS as outras fontes. Grava so quando o estado MUDA ou quando a
# ultima linha ja venceu — em regime saudavel, ~24 linhas/dia.
HEARTBEAT_MIN = int(os.getenv("GOVBR_LOG_HEARTBEAT_MIN", "50") or "50")


def _status_sessao(private_ok: bool, exec_ok: bool, prest_ok: bool) -> tuple:
    """(status, vivos, frase) no vocabulario que o frescor JA entende.

    ⚠️ 'success' | 'parcial' | 'erro', e nao 'alive'/'vivo'. Inventar vocabulario
    aqui obrigaria a mexer no `freshness` e no `watchdog` — o custo de um nome
    bonito seria dois lugares a mais para errar.

    ⚠️ OS TRES SPs CONTAM SEPARADO. Foi exatamente por `execucao` e `prestacao`
    aparecerem como um so que as NEs morriam em silencio com o keepalive
    dizendo "execucao=vivo"."""
    vivos = sum((bool(private_ok), bool(exec_ok), bool(prest_ok)))
    frase = (f"private={'vivo' if private_ok else 'CAIU'}, "
             f"execucao={'vivo' if exec_ok else 'CAIU'}, "
             f"prestacao={'vivo' if prest_ok else 'CAIU'}")
    if vivos == 3:
        return "success", vivos, frase
    if vivos == 0:
        return "erro", vivos, frase
    return "parcial", vivos, frase


def _registra_sessao(private_ok: bool, exec_ok: bool, prest_ok: bool) -> None:
    """Grava a saude da sessao gov.br em `ingestion_log`.

    ⚠️ POR QUE ISTO PRECISOU EXISTIR: a saude da sessao so vivia no LOG DO
    CONTAINER, que e efemero. "Ha quantas horas a sessao esta viva ou morta" era
    uma pergunta sem resposta possivel no banco — e a auditoria mediu a sessao
    morta 297,5h de 720h (41%) sem que nada no produto dissesse isso.

    ⚠️ `cofre_senhas.updated_at` NAO servia de sinal: o keepalive re-salva os
    cookies mesmo quando a navegacao caiu no idp, entao o carimbo subia com a
    sessao morta.

    Best-effort de verdade: qualquer falha aqui e engolida. Este e um registro de
    OBSERVACAO — derrubar o keepalive por causa dele seria trocar a coleta pela
    contabilidade da coleta."""
    status, vivos, frase = _status_sessao(private_ok, exec_ok, prest_ok)
    try:
        conn = psycopg2.connect(_sync_url())
        with conn, conn.cursor() as cur:
            cur.execute(
                "SELECT status, finished_at FROM ingestion_log "
                "WHERE source = %s ORDER BY id DESC LIMIT 1", (SOURCE_SESSAO,))
            ult = cur.fetchone()
            if ult and ult[0] == status and ult[1] is not None:
                cur.execute("SELECT EXTRACT(epoch FROM (now() - %s)) / 60", (ult[1],))
                if (cur.fetchone()[0] or 0) < HEARTBEAT_MIN:
                    conn.close()
                    return          # mesmo estado e ainda dentro da janela
            cur.execute(
                "INSERT INTO ingestion_log (source, status, records_inserted, "
                "error_message, started_at, finished_at) "
                "VALUES (%s, %s, %s, %s, NOW(), NOW())",
                (SOURCE_SESSAO, status, vivos, frase if status != "success" else None))
        conn.close()
    except Exception as e:
        log.info(f"registro da sessao nao gravado ({str(e)[:70]}) — keepalive segue")


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
        # 4) prestacao (Notas de Empenho): SP SEPARADO do de cima, com idle
        #    proprio — ver o comentario de PRESTACAO_ENTRY. Sem esta navegacao a
        #    coleta de NEs morria horas depois da captura enquanto o keepalive
        #    reportava `execucao=vivo`, o que fazia o sintoma parecer outra coisa.
        prest_ok = False
        try:
            await page.goto(PRESTACAO_ENTRY, timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            pu = (page.url or "").lower()
            prest_ok = "idp/" not in pu and "sso.acesso" not in pu
        except Exception as e:
            log.warning(f"keepalive prestacao: {str(e)[:80]}")
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
    # ⚠️ `prestacao` sai no log SEPARADO de `execucao`, e nao somado a ele: sao
    # SPs diferentes, e foi exatamente por eles aparecerem como um so que as NEs
    # morriam em silencio com o keepalive dizendo "execucao=vivo".
    _sps = (f"execucao={'vivo' if exec_ok else 'CAIU'}, "
            f"prestacao={'vivo' if prest_ok else 'CAIU'}")
    _registra_sessao(private_ok, exec_ok, prest_ok)
    if private_ok:
        log.info(f"keepalive OK — /private/ vivo, {_sps}, "
                 f"{len(relevant)} cookies re-salvos")
        return "alive"
    log.warning(f"keepalive — /private/ CAIU (idp/login), {_sps}. "
                "Precisa re-captura pela extensao.")
    return "private_dead"


if __name__ == "__main__":
    import sys
    modo = sys.argv[1] if len(sys.argv) > 1 else "renew"
    print(asyncio.run(keepalive() if modo == "keepalive" else renew()))
