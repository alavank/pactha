"""
Scraper Estrutura SUAS (Assistencia Social - MDS).
Portal: https://estruturasuas.mds.gov.br
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ingestion.scraper_base import ScraperBase, cli
from ingestion.fns_scraper import parse_money_br


class SUASScraper(ScraperBase):
    automation_key = "suas"
    name = "Estrutura SUAS Scraper"
    uses_govbr = True

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

            await page.goto("https://estruturasuas.mds.gov.br/login", timeout=30_000)
            try:
                await page.fill("input[name='cpf']", cpf, timeout=30_000)
                await page.fill("input[name='senha']", senha)
                await page.click("button[type='submit']")
                await page.wait_for_load_state("networkidle", timeout=30_000)
            except Exception:
                # SUAS pode ter SSO gov.br em alguns casos
                try:
                    await page.click("text=Entrar com gov.br")
                    await page.fill("input[name='accountId']", cpf)
                    await page.click("button[type='submit']")
                    await page.fill("input[name='password']", senha)
                    await page.click("button[type='submit']")
                except Exception:
                    pass

            # Coleta convenios/CRAS/CREAS
            try:
                await page.wait_for_selector("table tbody tr", timeout=15_000)
                rows = await page.query_selector_all("table tbody tr")
                for r in rows:
                    cells = await r.query_selector_all("td")
                    if len(cells) < 4:
                        continue
                    texts = [(await c.inner_text()).strip() for c in cells]
                    items.append({
                        "nr_proposta": texts[0] if len(texts) > 0 else "",
                        "objeto": texts[1] if len(texts) > 1 else "Estrutura SUAS",
                        "tipo_programa": "CRAS/CREAS/Centro POP",
                        "valor": parse_money_br(texts[2] if len(texts) > 2 else "0"),
                        "situacao": texts[3] if len(texts) > 3 else "",
                        "ano": datetime.now().year,
                        "fonte": "SUAS",
                        "orgao_concedente": "Min. Desenvolvimento Social - SUAS",
                    })
            except Exception:
                pass

            await browser.close()
        return items


if __name__ == "__main__":
    cli(SUASScraper)
