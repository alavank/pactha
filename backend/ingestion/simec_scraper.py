"""
Scraper SIMEC/PAR (Educacao - FNDE).
Portal: https://simec.mec.gov.br

Estrategia (apos inspecao do portal real):
1. GET https://simec.mec.gov.br/login.php (form com nudoc=CPF e senha)
2. POST com credenciais
3. Apos login, acessa modulo PAR: https://simec.mec.gov.br/par/
4. Coleta termos/sub-acoes/obras do municipio
"""
import os
import sys
import re
import asyncio
import logging
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ingestion.scraper_base import ScraperBase, cli

logger = logging.getLogger("simec")


def parse_money_br(s: str) -> float:
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", s).replace(".", "").replace(",", ".")
    try:
        return float(Decimal(s))
    except Exception:
        return 0.0


class SIMECScraper(ScraperBase):
    automation_key = "simec"
    name = "SIMEC/PAR Scraper"
    uses_govbr = True  # SIMEC usa gov.br SSO

    async def collect(self, credential: dict) -> list[dict]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("playwright nao instalado")
            return []

        cpf = (credential.get("usuario") or "").strip()
        senha = credential.get("senha") or ""
        if not cpf or not senha:
            logger.warning("Credencial SIMEC sem usuario/senha")
            return []

        from ingestion.stealth_helper import (
            create_stealth_browser_context, human_type, human_click, human_wait,
        )

        items = []
        async with async_playwright() as pw:
            browser, ctx = await create_stealth_browser_context(pw)
            page = await ctx.new_page()

            # 1. Login via gov.br SSO com STEALTH + comportamento humanizado
            try:
                await page.goto("https://simec.mec.gov.br/login.php", timeout=30_000)
                await page.wait_for_load_state("networkidle", timeout=10_000)
                await human_wait(1.5, 3.0)

                # Click humanizado no botao gov.br
                clicked = False
                for sel in ['a:has-text("gov.br")', 'a[href*="acesso.gov.br"]']:
                    try:
                        await human_click(page, sel)
                        clicked = True
                        logger.info(f"  Click gov.br via {sel}")
                        break
                    except Exception:
                        continue
                if not clicked:
                    raise RuntimeError("Botao gov.br nao encontrado")

                await page.wait_for_url(lambda u: "acesso.gov.br" in u, timeout=20_000)
                await page.wait_for_load_state("networkidle", timeout=10_000)
                await human_wait(2, 4)
                logger.info(f"  Redirecionado: {page.url}")

                # Digitacao humana do CPF
                await human_type(page, 'input#accountId', cpf)
                logger.info(f"  CPF digitado humanizado")
                await human_wait(0.5, 1.5)

                # Click humanizado em Continuar
                await human_click(page, 'button[type="submit"]')
                await human_wait(3, 5)

                # Caso aparece "Como deseja entrar?" -> escolher senha
                try:
                    await human_click(page, 'a:has-text("senha"), button:has-text("senha")')
                    await human_wait(2, 4)
                except Exception:
                    pass

                # Digitar senha
                await human_type(page, 'input[name="password"]', senha)
                logger.info(f"  Senha digitada humanizado")
                await human_wait(0.5, 1.5)

                await human_click(page, 'button[type="submit"]')

                # Aguardar volta ao SIMEC apos SSO
                await page.wait_for_url(lambda u: "simec.mec.gov.br" in u, timeout=30_000)
                await page.wait_for_load_state("networkidle", timeout=15_000)
                logger.info(f"  Login OK - URL: {page.url}")
            except Exception as e:
                logger.error(f"Falha no login SIMEC via gov.br: {e}")
                await browser.close()
                return []

            # 2. Acessar modulo PAR
            try:
                await page.goto("https://simec.mec.gov.br/par/", timeout=30_000)
                await page.wait_for_load_state("networkidle", timeout=20_000)
            except Exception as e:
                logger.warning(f"Falha acessando /par/: {e}")

            # 3. Coletar dados visiveis em qualquer tabela da pagina
            # Estrategia generica: capturar TODAS as tabelas com rows
            try:
                tables = await page.query_selector_all("table")
                logger.info(f"  {len(tables)} tabelas encontradas")
                for table in tables:
                    rows = await table.query_selector_all("tbody tr")
                    if len(rows) < 1:
                        continue
                    for r in rows:
                        cells = await r.query_selector_all("td")
                        if len(cells) < 3:
                            continue
                        texts = []
                        for c in cells[:8]:
                            t = (await c.inner_text()).strip()
                            texts.append(t)
                        # Heuristica: linha com valor R$ provavelmente tem dados
                        valor = 0
                        valor_cell = None
                        for t in texts:
                            if "R$" in t or re.search(r"\d[.,]\d{2}\s*$", t):
                                valor = parse_money_br(t)
                                if valor > 0:
                                    valor_cell = t
                                    break
                        if valor <= 0:
                            continue
                        items.append({
                            "nr_proposta": texts[0][:50] if texts else "",
                            "programa": "PAR/SIMEC",
                            "objeto": " | ".join(texts[:4])[:500],
                            "valor": valor,
                            "situacao": texts[-1] if len(texts) > 4 else "Em analise",
                            "ano": datetime.now().year,
                            "fonte": "SIMEC",
                            "orgao_concedente": "Min. Educacao - FNDE",
                        })
            except Exception as e:
                logger.error(f"Erro extraindo tabelas: {e}")

            # 4. Print HTML para diagnostico (se nada coletado)
            if not items:
                try:
                    txt = (await page.inner_text("body"))[:2000]
                    logger.info(f"  Pagina apos login (primeiros 2k chars):\n{txt}")
                except Exception:
                    pass

            await browser.close()
        logger.info(f"  SIMEC coletou {len(items)} items")
        return items


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    cli(SIMECScraper)
