"""
Scraper FNS - usa Service Token + Cofre PACTA (zero credencial em config).

Fluxo seguro:
1. Worker recebe APENAS PACTA_API_URL + PACTA_SERVICE_TOKEN via env
2. Chama GET /api/internal/secrets/fns com X-Service-Token
3. Recebe credenciais cifradas do Cofre, descriptografadas pelo backend
4. Loga em consultafns.saude.gov.br via Playwright (ou httpx) headless
5. Coleta pagamentos por municipio
6. Faz upsert via API publica autenticada (JWT proprio do scraper user)
   OU via DB direto (se mesma rede privada do Neon)

Credenciais NUNCA tocam o filesystem do worker. Vivem so em RAM.
Token e rotacionavel a qualquer momento via /api/admin/service-tokens.
"""
import os
import sys
import asyncio
import re
from datetime import datetime
from decimal import Decimal

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PACTA_API_URL = os.getenv("PACTA_API_URL", "https://pacta-api-production-9c11.up.railway.app/api")
PACTA_SERVICE_TOKEN = os.getenv("PACTA_SERVICE_TOKEN")  # pacta_st_xxx
TIMEOUT_MS = 30_000


def parse_money_br(s: str) -> Decimal:
    if not s:
        return Decimal("0")
    s = re.sub(r"[^\d,.-]", "", s).replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return Decimal("0")


async def fetch_credentials_from_cofre() -> list[dict]:
    """Busca credenciais FNS do Cofre via endpoint interno autenticado."""
    if not PACTA_SERVICE_TOKEN:
        raise RuntimeError(
            "PACTA_SERVICE_TOKEN nao definido. "
            "Crie um Service Token no painel admin com scope 'secret:read:fns' "
            "e configure como env var no worker Railway."
        )
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{PACTA_API_URL}/internal/secrets/fns",
            headers={"X-Service-Token": PACTA_SERVICE_TOKEN},
        )
        r.raise_for_status()
        data = r.json()
        return data.get("secrets", [])


async def fns_login(page, cpf: str, senha: str):
    """Login via gov.br SSO no FNS (selectores reais variam, ajustar apos teste)."""
    await page.goto("https://consultafns.saude.gov.br", timeout=TIMEOUT_MS)
    try:
        await page.click("text=Entrar com gov.br", timeout=5_000)
    except Exception:
        pass
    await page.fill("input[name='accountId']", cpf, timeout=TIMEOUT_MS)
    await page.click("button[type='submit']")
    await page.wait_for_selector("input[name='password']", timeout=TIMEOUT_MS)
    await page.fill("input[name='password']", senha)
    await page.click("button[type='submit']")
    await page.wait_for_url("https://consultafns.saude.gov.br/**", timeout=TIMEOUT_MS)


async def coletar_pagamentos(page, ibge: str, ano_inicio: int, ano_fim: int):
    url = f"https://consultafns.saude.gov.br/pagamentos?ibge={ibge}&anoInicio={ano_inicio}&anoFim={ano_fim}"
    await page.goto(url, timeout=TIMEOUT_MS)
    await page.wait_for_selector("table", timeout=TIMEOUT_MS)
    rows = await page.query_selector_all("table tbody tr")
    pagamentos = []
    for r in rows:
        cells = await r.query_selector_all("td")
        if len(cells) < 5:
            continue
        texts = [(await c.inner_text()).strip() for c in cells]
        pagamentos.append({
            "nr_proposta": texts[0],
            "programa": texts[1],
            "competencia": texts[2],
            "parcela": texts[3] if len(texts) > 3 else "",
            "valor": str(parse_money_br(texts[4] if len(texts) > 4 else "0")),
            "situacao": texts[5] if len(texts) > 5 else "Pago",
        })
    return pagamentos


async def upsert_via_api(municipio_id: int, pagamentos: list[dict]):
    """Envia pagamentos para o backend via endpoint autenticado do scraper.

    Em producao, criar endpoint /api/internal/upsert-fns autenticado pelo
    mesmo Service Token (com scope 'fns:write'). Aqui esboco.
    """
    # TODO: criar endpoint /api/internal/upsert-fns no backend e chamar aqui
    # Por enquanto, log apenas.
    print(f"  [TODO] Upsert {len(pagamentos)} pagamentos para municipio {municipio_id}")


async def run():
    # 1. Buscar credenciais do Cofre
    print("=== FNS Scraper - autenticando via Service Token ===")
    creds = await fetch_credentials_from_cofre()
    if not creds:
        print("Nenhuma credencial FNS cadastrada no Cofre. Cadastre via UI primeiro.")
        sys.exit(0)
    print(f"  {len(creds)} credenciais carregadas (cifradas no DB, decifradas em memoria)")

    # 2. Iniciar Playwright
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("ERRO: pip install playwright && playwright install chromium")
        sys.exit(1)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        for cred in creds:
            cpf = cred.get("usuario")
            senha = cred.get("senha")
            mun_id = cred.get("municipio_id")
            if not cpf or not senha:
                continue
            try:
                print(f"  Login FNS para municipio {mun_id}...")
                await fns_login(page, cpf, senha)
                # Buscar IBGE do municipio (poderia vir do Cofre tambem)
                # Por simplicidade aqui, hardcoded - na pratica buscar do DB
                pagamentos = await coletar_pagamentos(page, "3151206", 2022, datetime.now().year)
                print(f"    {len(pagamentos)} pagamentos coletados")
                await upsert_via_api(mun_id, pagamentos)
            except Exception as e:
                print(f"  ERRO municipio {mun_id}: {e}")

        await browser.close()
    print("FNS scraper finalizado.")


if __name__ == "__main__":
    asyncio.run(run())
