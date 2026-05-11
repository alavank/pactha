"""
Scraper SIMEC/PAR (Educacao - FNDE).
Portal: https://simec.mec.gov.br/par/

NOTA: SIMEC nao expoe API publica. Login via CPF+senha.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ingestion.scraper_base import ScraperBase, cli
from ingestion.fns_scraper import parse_money_br


class SIMECScraper(ScraperBase):
    automation_key = "simec"
    name = "SIMEC/PAR Scraper"

    async def collect(self, credential: dict) -> list[dict]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            print("ERRO: pip install playwright")
            return []

        cpf = credential.get("usuario")
        senha = credential.get("senha")
        if not cpf or not senha:
            return []

        items = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await (await browser.new_context()).new_page()

            await page.goto("https://simec.mec.gov.br/login.php", timeout=30_000)
            await page.fill("input[name='dado']", cpf)
            await page.fill("input[name='senha']", senha)
            await page.click("button[type='submit']")
            await page.wait_for_load_state("networkidle", timeout=30_000)

            # Acessa modulo PAR
            await page.goto("https://simec.mec.gov.br/par/", timeout=30_000)

            # Coleta lista de termos/sub-acoes do PAR (UF/Municipio = vinculo do CPF)
            try:
                await page.wait_for_selector("table.listagem tr", timeout=15_000)
                rows = await page.query_selector_all("table.listagem tbody tr")
                for r in rows:
                    cells = await r.query_selector_all("td")
                    if len(cells) < 4:
                        continue
                    texts = [(await c.inner_text()).strip() for c in cells]
                    items.append({
                        "nr_proposta": texts[0] if len(texts) > 0 else "",
                        "programa": texts[1] if len(texts) > 1 else "PAR/SIMEC",
                        "objeto": texts[2] if len(texts) > 2 else "",
                        "valor": parse_money_br(texts[3] if len(texts) > 3 else "0"),
                        "situacao": texts[4] if len(texts) > 4 else "Em analise",
                        "ano": datetime.now().year,
                        "fonte": "SIMEC",
                        "orgao_concedente": "Min. Educacao - FNDE",
                    })
            except Exception:
                pass

            await browser.close()
        return items


if __name__ == "__main__":
    cli(SIMECScraper)
