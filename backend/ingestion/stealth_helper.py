"""
Helpers para reduzir deteccao de automacao gov.br/portais governo.
- playwright-stealth: mascara 25+ sinais (webdriver, fingerprint, plugins)
- Random delays humanizados
- Mouse movement
- User agent + viewport realistas
"""
import asyncio
import random
from typing import Optional


REALISTIC_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
]


async def create_stealth_browser_context(playwright):
    """Cria browser + context com TODAS as evasoes disponiveis."""
    from playwright_stealth import Stealth

    # Args do Chromium para esconder flags de automacao
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",  # remove webdriver
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-infobars",
            "--window-size=1366,768",
            "--start-maximized",
            "--disable-extensions",
            "--lang=pt-BR",
        ],
    )

    ua = random.choice(REALISTIC_USER_AGENTS)
    context = await browser.new_context(
        user_agent=ua,
        viewport={"width": 1366, "height": 768},
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        geolocation={"longitude": -46.6333, "latitude": -23.5505},
        permissions=["geolocation"],
        extra_http_headers={
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
        },
    )

    # Aplica stealth a todas as pages do contexto
    stealth = Stealth()
    await stealth.apply_stealth_async(context)

    return browser, context


async def human_type(page, selector: str, text: str):
    """Digita como humano: delay variavel entre teclas."""
    el = await page.wait_for_selector(selector, timeout=15_000, state="visible")
    await el.click()
    await asyncio.sleep(random.uniform(0.3, 0.8))
    for char in text:
        await page.keyboard.type(char, delay=random.randint(60, 150))
    await asyncio.sleep(random.uniform(0.5, 1.2))


async def human_click(page, selector: str):
    """Mouse move humanizado + click."""
    el = await page.wait_for_selector(selector, timeout=10_000, state="visible")
    box = await el.bounding_box()
    if box:
        # Move o mouse em curva ate o elemento
        target_x = box["x"] + box["width"] / 2 + random.uniform(-3, 3)
        target_y = box["y"] + box["height"] / 2 + random.uniform(-3, 3)
        await page.mouse.move(
            random.randint(50, 300),
            random.randint(50, 300),
            steps=random.randint(5, 15),
        )
        await asyncio.sleep(random.uniform(0.1, 0.3))
        await page.mouse.move(target_x, target_y, steps=random.randint(10, 25))
        await asyncio.sleep(random.uniform(0.1, 0.4))
    await el.click()


async def human_wait(min_s: float = 1.0, max_s: float = 3.0):
    """Pausa aleatoria humanizada."""
    await asyncio.sleep(random.uniform(min_s, max_s))
