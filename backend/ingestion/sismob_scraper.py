"""
Scraper SISMOB (Sistema de Monitoramento de Obras de Saude).
Portal: https://sismobcidadao.saude.gov.br
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ingestion.scraper_base import ScraperBase, cli
from ingestion.fns_scraper import parse_money_br


class SISMOBScraper(ScraperBase):
    automation_key = "sismob"
    name = "SISMOB Scraper"

    async def collect(self, credential: dict) -> list[dict]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return []

        cpf = credential.get("usuario")
        senha = credential.get("senha")
        if not cpf or not senha:
            return []

        items = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await (await browser.new_context()).new_page()

            # Login gov.br SSO igual FNS
            await page.goto("https://sismobcidadao.saude.gov.br", timeout=30_000)
            try:
                await page.click("text=Entrar com gov.br", timeout=5_000)
                await page.fill("input[name='accountId']", cpf, timeout=30_000)
                await page.click("button[type='submit']")
                await page.wait_for_selector("input[name='password']", timeout=30_000)
                await page.fill("input[name='password']", senha)
                await page.click("button[type='submit']")
                await page.wait_for_url("https://sismobcidadao.saude.gov.br/**", timeout=30_000)
            except Exception:
                pass

            # Coleta obras
            try:
                await page.wait_for_selector("table tbody tr", timeout=15_000)
                rows = await page.query_selector_all("table tbody tr")
                for r in rows:
                    cells = await r.query_selector_all("td")
                    if len(cells) < 5:
                        continue
                    texts = [(await c.inner_text()).strip() for c in cells]
                    items.append({
                        "nr_proposta": texts[0] if len(texts) > 0 else "",
                        "objeto": texts[1] if len(texts) > 1 else "",
                        "tipo_programa": texts[2] if len(texts) > 2 else "Obra Saude",
                        "valor": parse_money_br(texts[3] if len(texts) > 3 else "0"),
                        "situacao": texts[4] if len(texts) > 4 else "",
                        "ano": datetime.now().year,
                        "fonte": "SISMOB",
                        "orgao_concedente": "Min. Saude - SISMOB",
                    })
            except Exception:
                pass

            await browser.close()
        return items


if __name__ == "__main__":
    cli(SISMOBScraper)
