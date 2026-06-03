"""Renova a sessao gov.br no Cofre via login programatico.

Fluxo:
  1. Carrega CPF+senha do Cofre (automation_key='govbr', formato texto)
  2. Abre Chromium com stealth + cookies SSO antigas (pra re-aproveitar
     'Govbrid' que lembra do CPF)
  3. Navega ate parcerias.transferegov + clica 'Entrar com gov.br'
  4. Preenche CPF, Continuar, Senha, Entrar
  5. Aguarda redirect para a area autenticada do TransfereGov
  6. Visita cada subdominio para gerar JSESSIONID
  7. Coleta TODAS as cookies, sobrescreve a sessao no Cofre (id=12 / mun=6)
"""
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

import psycopg2
from services import crypto

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("renovar_govbr")


URL_PARCERIAS_HOME = "https://parcerias.transferegov.sistema.gov.br/ep-atos-prep-web/home"

# Subdominios autenticados a visitar pra popular cookies
SUBDOMINIOS_TG = [
    "https://cadastro.transferegov.sistema.gov.br/ep-cadastro-web/home",
    "https://parcerias.transferegov.sistema.gov.br/ep-atos-prep-web/home",
    "https://especiais.transferegov.sistema.gov.br/transferencia-especial/programa/consulta",
    "https://fundos.transferegov.sistema.gov.br/transferencia/programa/consulta",
    "https://ted.transferegov.sistema.gov.br/ted/programa/consulta",
    "https://discricionarias.transferegov.sistema.gov.br/voluntarias/ForwardAction.do"
    "?modulo=Principal&path=/MostraPrincipalConsultarProposta.do",
]


def _load_credentials():
    """Carrega (cpf, senha) do Cofre. CPF/senha estao no automation_key=govbr
    formato texto curto (id=16). Tambem retorna cookies antigos (id=12) p/
    reuso do 'Govbrid' que lembra do CPF."""
    url = (os.getenv("DATABASE_URL_SYNC", "")
           .replace("&channel_binding=require", "")
           .replace("?channel_binding=require", ""))
    conn = psycopg2.connect(url); cur = conn.cursor()
    cur.execute(
        "SELECT id, municipio_id, usuario, senha_hash, length(senha_hash) "
        "FROM cofre_senhas WHERE automation_key='govbr' ORDER BY updated_at DESC"
    )
    rows = cur.fetchall()
    cred = None
    sess_id = None
    sess_mun = None
    sess_cookies = None
    for rid, mid, usr, enc, lh in rows:
        dec = crypto.decrypt(enc) or ""
        if dec.startswith("{"):
            # cookies antigas
            try:
                sess_id = rid; sess_mun = mid
                sess_cookies = json.loads(dec).get("cookies", [])
            except Exception:
                pass
        elif dec and 6 <= len(dec) <= 100:
            cred = (usr, dec, rid, mid)  # cpf, senha, id, mun
    cur.close(); conn.close()
    return cred, sess_id, sess_mun, sess_cookies


def _to_pw_cookies(cookies):
    out = []
    for c in cookies:
        n, v = c.get("name"), c.get("value")
        if not n or v is None:
            continue
        ck = {"name": n, "value": v, "path": c.get("path") or "/",
              "secure": bool(c.get("secure")), "httpOnly": bool(c.get("httpOnly"))}
        if c.get("domain"):
            ck["domain"] = c["domain"]
        if c.get("sameSite"):
            ck["sameSite"] = {"no_restriction":"None","lax":"Lax","strict":"Strict",
                              "None":"None","Lax":"Lax","Strict":"Strict"}.get(c["sameSite"], "Lax")
        if c.get("expirationDate"):
            try: ck["expires"] = float(c["expirationDate"])
            except: pass
        out.append(ck)
    return out


def _save_session(municipio_id: int, cookies_pw: list, sistema_label: str = "gov.br - Conta Unica") -> int:
    """Sobrescreve/cria a sessao govbr no Cofre. Formato igual ao bookmarklet."""
    import datetime
    payload = {
        "format": "cookies_full",
        "cookies": cookies_pw,
        "url": "https://parcerias.transferegov.sistema.gov.br/",
        "domain": "parcerias.transferegov.sistema.gov.br",
    }
    enc = crypto.encrypt(json.dumps(payload))
    obs = (f"[SESSION] renovada em {datetime.datetime.now(datetime.timezone.utc).isoformat()} | "
           f"cookies={len(cookies_pw)} | url=https://parcerias.transferegov... | login programatico")
    url = (os.getenv("DATABASE_URL_SYNC", "")
           .replace("&channel_binding=require", "")
           .replace("?channel_binding=require", ""))
    conn = psycopg2.connect(url); cur = conn.cursor()
    # tenta UPDATE existente (qualquer entrada govbr com cookies); senao INSERT
    cur.execute(
        "SELECT id FROM cofre_senhas WHERE automation_key='govbr' "
        "AND length(senha_hash) > 1000 ORDER BY updated_at DESC LIMIT 1"
    )
    row = cur.fetchone()
    if row:
        rid = row[0]
        cur.execute("UPDATE cofre_senhas SET senha_hash=%s, observacao=%s, updated_at=NOW() WHERE id=%s",
                    (enc, obs, rid))
    else:
        cur.execute(
            "INSERT INTO cofre_senhas (municipio_id, sistema, url, usuario, senha_hash, "
            "observacao, categoria, automation_key, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,'Sessao','govbr',NOW()) RETURNING id",
            (municipio_id, f"Sessao {sistema_label.upper()}",
             "https://parcerias.transferegov.sistema.gov.br/",
             "(cookie)", enc, obs)
        )
        rid = cur.fetchone()[0]
    conn.commit(); cur.close(); conn.close()
    return rid


async def renovar(headless: bool = True) -> bool:
    cred, _, sess_mun, old_cookies = _load_credentials()
    if not cred:
        log.error("Sem credenciais CPF+senha no Cofre")
        return False
    cpf, senha, cid, cmun = cred
    log.info(f"Login com CPF={cpf[:3]}***{cpf[-2:]} (cred id={cid})")
    log.info(f"Cookies antigas disponiveis: {len(old_cookies) if old_cookies else 0}")

    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth
    import random as _r

    # Usa profile persistente em ./tmp/chromium_govbr_profile — cookies/storage
    # se acumulam entre runs, dando score reCAPTCHA mais alto.
    profile_dir = Path(__file__).resolve().parent / "_chromium_govbr_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        # launch_persistent_context = browser + context unico, com user_data_dir
        context = await p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
                "--lang=pt-BR",
                "--window-size=1366,768",
            ],
            viewport={"width": 1366, "height": 768},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            extra_http_headers={
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        stealth = Stealth()
        await stealth.apply_stealth_async(context)
        browser = context.browser  # may be None for persistent context
        # injeta cookies antigas (Govbrid persistente ajuda a lembrar do CPF)
        if old_cookies:
            try:
                await context.add_cookies(_to_pw_cookies(old_cookies))
            except Exception as e:
                log.warning(f"falha ao injetar cookies antigas: {e}")
        page = await context.new_page()

        # 1) Vai ao parcerias home
        log.info("1) abrindo parcerias home...")
        await page.goto(URL_PARCERIAS_HOME, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(3000)

        # 2) Clica 'Entrar com gov.br'
        log.info("2) clicando 'Entrar com gov.br'...")
        btn = page.locator(
            "xpath=//button[contains(., 'Entrar')] | //a[contains(., 'Entrar')]"
        ).first
        if await btn.count() == 0:
            log.error("Botao 'Entrar' nao encontrado")
            await browser.close(); return False
        try:
            await btn.click()
        except Exception as e:
            log.warning(f"click falhou: {e}")
        # aguarda redirect ao sso
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)
        log.info(f"  url apos click: {page.url}")

        # Se ja autenticado direto (Govbrid lembrou), pula login
        if "sso.acesso.gov.br" not in page.url and "transferegov.sistema.gov.br" in page.url:
            log.info("  ja autenticado via Govbrid persistente!")
        else:
            # 3) Preenche CPF humanizado e AGUARDA o JS habilitar o botao
            # 'Continuar' (id=enter-account-id) que comeca com disabled='' +
            # class 'loading'. O JS gov.br invoca reCAPTCHA v3 e remove disabled.
            import random
            log.info("3) digitando CPF humanizado...")
            cpf_input = page.locator("input#accountId").first
            await cpf_input.wait_for(state="visible", timeout=15000)
            # foca via click humano (gera UA event)
            box = await cpf_input.bounding_box()
            if box:
                await page.mouse.move(random.randint(50, 300), random.randint(50, 300), steps=10)
                await asyncio.sleep(0.3)
                await page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2, steps=15)
                await asyncio.sleep(0.2)
                await page.mouse.click(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
            await asyncio.sleep(random.uniform(0.5, 1.0))
            for ch in cpf:
                await page.keyboard.type(ch, delay=random.randint(80, 200))
            await asyncio.sleep(random.uniform(1.0, 1.8))
            # Move o mouse pra fora do input (simula intencao de clicar Continuar)
            await page.mouse.move(random.randint(400, 600), random.randint(300, 500), steps=10)
            await asyncio.sleep(random.uniform(0.5, 1.2))

            # Aguarda o botao Continuar ficar HABILITADO (JS validou + recaptcha OK)
            log.info("  aguardando botao Continuar habilitar...")
            try:
                await page.wait_for_function(
                    "() => { const b=document.getElementById('enter-account-id'); "
                    "return b && !b.disabled && !b.classList.contains('loading'); }",
                    timeout=20000
                )
                log.info("  Continuar habilitado!")
            except Exception:
                log.warning("  Continuar nao habilitou em 20s (possivel reCAPTCHA fail)")
                # tenta forcar via remocao do disabled + submit
                await page.evaluate("""() => {
                    const b = document.getElementById('enter-account-id');
                    if (b) { b.disabled = false; b.classList.remove('loading'); }
                }""")

            # Clica Continuar (humanizado)
            log.info("  clicando Continuar...")
            try:
                cont = page.locator("button#enter-account-id").first
                await cont.scroll_into_view_if_needed()
                box = await cont.bounding_box()
                if box:
                    await page.mouse.move(box["x"] + box["width"]/2 + random.uniform(-3, 3),
                                          box["y"] + box["height"]/2 + random.uniform(-3, 3),
                                          steps=random.randint(15, 25))
                    await asyncio.sleep(random.uniform(0.2, 0.4))
                await cont.click(timeout=8000)
            except Exception as e:
                log.warning(f"  click Continuar falhou ({e}); fallback Enter")
                try:
                    await cpf_input.focus()
                    await page.keyboard.press("Enter")
                except Exception:
                    pass
            # aguarda navegacao para tela de senha
            try:
                await page.wait_for_function(
                    "() => document.querySelector('input[type=password]') !== null",
                    timeout=25000
                )
                log.info("  pagina de senha detectada!")
            except Exception:
                pass
            await page.wait_for_timeout(3000)
            log.info(f"  apos continuar: {page.url}")

            # se redirecionar para 'banco/qrcode/certificado' selecionar, escolher senha
            try:
                senha_link = page.locator(
                    "xpath=//a[contains(., 'Senha gov.br')] | //a[contains(., 'sua senha')] | "
                    "//*[contains(text(), 'Sua senha')]"
                ).first
                if await senha_link.count() > 0:
                    log.info("  clicando 'Sua senha' option...")
                    await senha_link.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(2000)
            except Exception:
                pass

            # debug: salva HTML/screenshot apos continuar
            try:
                html = (await page.content())[:8000]
                Path(Path(__file__).resolve().parent / "_renovar_pos_cpf.html").write_text(html, encoding="utf-8")
                await page.screenshot(path=str(Path(__file__).resolve().parent / "_renovar_pos_cpf.png"), full_page=True)
                body_dump = (await page.locator("body").inner_text())[:1000]
                log.info(f"  body apos CPF: {' '.join(body_dump.split())[:500]!r}")
                # lista inputs e links visiveis
                inputs = await page.eval_on_selector_all(
                    "input", "els => els.map(e => ({type:e.type, name:e.name, id:e.id, placeholder:e.placeholder, visible:e.offsetParent!==null}))"
                )
                log.info(f"  inputs encontrados: {inputs[:10]}")
                links = await page.eval_on_selector_all(
                    "a, button", "els => els.filter(e=>e.offsetParent!==null).map(e => (e.innerText||e.value||'').trim().slice(0,60)).filter(t=>t)"
                )
                log.info(f"  links/botoes visiveis: {links[:20]}")
            except Exception as e:
                log.warning(f"debug dump falhou: {e}")

            # 4) Preenche senha
            log.info("4) preenchendo senha...")
            # Tentativa robusta: senha pode estar em iframe (gov.br as vezes usa)
            senha_input = page.locator("input[type='password'], input[name='password'], input#password").first
            try:
                await senha_input.wait_for(state="visible", timeout=15000)
            except Exception:
                # checa iframes
                log.info("  senha nao visivel - tentando iframes")
                frames = page.frames
                log.info(f"  total frames: {len(frames)}")
                achou = False
                for fr in frames:
                    try:
                        loc = fr.locator("input[type='password']").first
                        if await loc.count() > 0:
                            log.info(f"  senha em frame: {fr.url}")
                            senha_input = loc
                            achou = True; break
                    except Exception:
                        pass
                if not achou:
                    log.error("input senha nao achado em nenhum frame")
                    raise
            await senha_input.fill(senha)
            await page.wait_for_timeout(800)
            # clica Entrar
            entrar = page.locator(
                "xpath=//button[contains(., 'Entrar')] | //input[@value='Entrar'] | "
                "//button[@type='submit'] | //input[@type='submit']"
            ).first
            await entrar.click()
            log.info("  aguardando redirect autenticado...")
            try:
                await page.wait_for_url("**parcerias.transferegov.sistema.gov.br**", timeout=40000)
            except Exception:
                # pode ter ido para outro modulo / pode pedir 2FA / etc
                pass
            await page.wait_for_timeout(5000)
            log.info(f"  url final: {page.url}")

        # Check se autenticou
        body = (await page.locator("body").inner_text()).lower()
        if "captcha" in body or "verifica" in body:
            log.error("CAPTCHA ou desafio adicional detectado")
            await page.screenshot(path=str(Path(__file__).resolve().parent / "_renovar_captcha.png"))
            await context.close(); return False
        if "senha" in page.url.lower() or "login" in page.url.lower():
            log.error(f"login falhou — ainda na pagina de login: {page.url}")
            await page.screenshot(path=str(Path(__file__).resolve().parent / "_renovar_loginfail.png"))
            await context.close(); return False

        log.info("LOGIN OK! Visitando subdominios para gerar JSESSIONIDs...")
        for sd in SUBDOMINIOS_TG:
            try:
                await page.goto(sd, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3500)
                log.info(f"  visitado: {sd[:80]} -> {page.url[:80]}")
            except Exception as e:
                log.warning(f"  falha em {sd[:60]}: {str(e)[:80]}")

        # 5) Coleta TODAS as cookies
        final_cookies = await context.cookies()
        log.info(f"Coletadas {len(final_cookies)} cookies ao final")
        # filtra para o que importa (transferegov.* + sso.acesso.gov.br + gov.br)
        domains_interest = ["transferegov", "sso.acesso.gov.br", "gov.br"]
        relevant = [c for c in final_cookies if any(d in (c.get("domain") or "") for d in domains_interest)]
        log.info(f"Cookies relevantes (transferegov/sso/govbr): {len(relevant)}")
        for c in relevant:
            log.info(f"  [{('H' if c.get('httpOnly') else '.')}{('S' if c.get('secure') else '.')}] "
                     f"{c.get('domain','?'):50s} {c.get('name','?')}")

        # 6) Salva no Cofre (no municipio que ja tinha cookies — Piracema)
        target_mun = sess_mun or cmun or 6
        new_id = _save_session(target_mun, relevant)
        log.info(f"Sessao salva: id={new_id} municipio_id={target_mun}")
        await context.close()
        return True


if __name__ == "__main__":
    # Por padrao tenta headless (Railway); flag --visible roda visivel
    visible = "--visible" in sys.argv
    ok = asyncio.run(renovar(headless=not visible))
    sys.exit(0 if ok else 1)
