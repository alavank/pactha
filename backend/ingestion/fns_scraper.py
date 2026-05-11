"""
Scraper FNS - Fundo Nacional de Saude.
Le credenciais via Service Token (Cofre PACTA).
"""
import os
import sys
import re
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ingestion.scraper_base import ScraperBase, cli


def parse_money_br(s: str) -> float:
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.-]", "", s).replace(".", "").replace(",", ".")
    try:
        return float(Decimal(s))
    except Exception:
        return 0.0


class FNSScraper(ScraperBase):
    automation_key = "fns"
    name = "FNS Scraper"

    async def collect(self, credential: dict) -> list[dict]:
        """Login no FNS via gov.br + coleta pagamentos."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            print("ERRO: pip install playwright && playwright install chromium")
            return []

        cpf = credential.get("usuario")
        senha = credential.get("senha")
        if not cpf or not senha:
            return []

        items = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context()
            page = await ctx.new_page()

            await page.goto("https://consultafns.saude.gov.br", timeout=30_000)
            try:
                await page.click("text=Entrar com gov.br", timeout=5_000)
            except Exception:
                pass

            await page.fill("input[name='accountId']", cpf, timeout=30_000)
            await page.click("button[type='submit']")
            await page.wait_for_selector("input[name='password']", timeout=30_000)
            await page.fill("input[name='password']", senha)
            await page.click("button[type='submit']")
            await page.wait_for_url("https://consultafns.saude.gov.br/**", timeout=30_000)

            # Coleta pagamentos por ano
            for ano in range(2022, datetime.now().year + 1):
                url = f"https://consultafns.saude.gov.br/pagamentos?ano={ano}"
                await page.goto(url, timeout=30_000)
                try:
                    await page.wait_for_selector("table tbody tr", timeout=10_000)
                    rows = await page.query_selector_all("table tbody tr")
                    for r in rows:
                        cells = await r.query_selector_all("td")
                        if len(cells) < 4:
                            continue
                        texts = [(await c.inner_text()).strip() for c in cells]
                        items.append({
                            "nr_proposta": texts[0] if len(texts) > 0 else "",
                            "programa": texts[1] if len(texts) > 1 else "",
                            "competencia": texts[2] if len(texts) > 2 else "",
                            "valor": parse_money_br(texts[3] if len(texts) > 3 else "0"),
                            "situacao": texts[4] if len(texts) > 4 else "Pago",
                            "ano": ano,
                            "fonte": "FNS",
                            "orgao_concedente": "Min. Saude - FNS",
                        })
                except Exception:
                    continue

            await browser.close()
        return items


if __name__ == "__main__":
    cli(FNSScraper)
