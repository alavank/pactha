"""
Scraper FNS - Fundo Nacional de Saude.
Le credenciais via Service Token (Cofre PACTA).

Estrategia em 2 etapas:
1. Listar pagamentos por ano (tabela com proposta, programa, valor, situacao)
2. Para cada proposta, abrir o detalhe e raspar o parlamentar autor da indicacao.
   No portal FNS (consultafns.saude.gov.br) o parlamentar aparece dentro da
   tela "Detalhamento da Proposta" - campo "Indicador" ou "Parlamentar autor".

A captura de parlamentar e o gap maior do RM Bom Despacho: ~30 das 73
propostas sao FNS (PAP/MAC/Custeio).
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


def extract_parlamentar(texto: str) -> str | None:
    """Extrai nome do parlamentar de um trecho de texto livre."""
    if not texto:
        return None
    t = re.sub(r"\s+", " ", texto).strip()
    # Padroes encontrados no FNS:
    # "Indicador: DEPUTADO LUIS TIBE"
    # "Parlamentar autor: COMISSAO DA SAUDE"
    # "Autor da Emenda: BANCADA DE MINAS GERAIS"
    # "Indicacao parlamentar: Newton Cardoso Jr"
    PATS = [
        r"(?:Indicador|Parlamentar autor|Autor da Emenda|Indica[cç][aã]o parlamentar|Parlamentar)[:\s]+([^\n;|]+)",
        r"(?:DEPUTAD[OA]|SENADOR[A]?)\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ\s\.]{4,60})",
        r"BANCADA\s+(?:DE\s+|DO\s+)?(MINAS GERAIS|EBPM|NORDESTE|MG)",
        r"(COMISS[AÃ]O\s+DA?\s+(?:SA[UÚ]DE|EDUCA[CÇ][AÃ]O|EXTERIOR))",
        r"BLOCO\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ\s]{4,40})",
        r"RELATOR\s+GERAL",
    ]
    for pat in PATS:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            nome = (m.group(1) if m.lastindex else m.group(0)).strip()
            # Limpar prefixos
            nome = re.sub(r"^(DEPUTAD[OA]|SENADOR[A]?|SR\.?|SRA\.?)\s+", "", nome, flags=re.IGNORECASE)
            nome = nome.rstrip(".,;:")
            if 3 <= len(nome) <= 80:
                return nome.upper()
    # Fallback: se aparece "Programa" como indicador, e indicacao programatica
    if re.search(r"\b(Programa|Programatic[ao])\b", t, re.IGNORECASE):
        return "Programa"
    return None


class FNSScraper(ScraperBase):
    automation_key = "fns"
    name = "FNS Scraper"
    uses_govbr = True

    async def collect(self, credential: dict) -> list[dict]:
        """Login no FNS + listagem de pagamentos + detalhe de cada proposta
        para capturar parlamentar autor."""
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

            # 1. Login via gov.br
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

            # 2. Coletar listagem de pagamentos por ano + detalhe parlamentar
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

                        nr_prop = texts[0] if texts else ""

                        # Best-effort: parlamentar pode estar em coluna extra
                        parl = None
                        for t in texts[5:]:
                            parl = extract_parlamentar(t)
                            if parl: break

                        # Se nao achou na linha, abrir o detalhe da proposta
                        if not parl and nr_prop:
                            parl = await self._fetch_parlamentar_detail(page, nr_prop)

                        items.append({
                            "nr_proposta": nr_prop,
                            "programa": texts[1] if len(texts) > 1 else "",
                            "competencia": texts[2] if len(texts) > 2 else "",
                            "valor": parse_money_br(texts[3] if len(texts) > 3 else "0"),
                            "situacao": texts[4] if len(texts) > 4 else "Pago",
                            "ano": ano,
                            "fonte": "FNS",
                            "orgao_concedente": "Min. Saude - FNS",
                            "parlamentar_nome": parl,
                        })
                except Exception as e:
                    print(f"  Falha ano {ano}: {e}")
                    continue

            await browser.close()
        return items

    async def _fetch_parlamentar_detail(self, page, nr_proposta: str) -> str | None:
        """Abre tela de detalhe da proposta e raspa o parlamentar autor.
        Tenta varias URLs/seletores comuns no portal FNS.
        """
        if not nr_proposta:
            return None
        try:
            # Tentar URL direta primeiro
            for url_pat in [
                f"https://consultafns.saude.gov.br/proposta/{nr_proposta}",
                f"https://consultafns.saude.gov.br/proposta?nr={nr_proposta}",
                f"https://consultafns.saude.gov.br/detalhamento?nr_proposta={nr_proposta}",
            ]:
                try:
                    resp = await page.goto(url_pat, timeout=15_000, wait_until="domcontentloaded")
                    if resp and resp.status < 400:
                        body = await page.inner_text("body")
                        parl = extract_parlamentar(body)
                        if parl:
                            return parl
                except Exception:
                    continue
        except Exception:
            return None
        return None


if __name__ == "__main__":
    cli(FNSScraper)
