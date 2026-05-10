"""
Scraper para o portal FNS (Fundo Nacional de Saude).

Estrategia:
1. Login em consultafns.saude.gov.br via gov.br SSO (CPF + senha)
2. Navega para Consultas > Pagamentos > Por Municipio
3. Filtra por IBGE de cada municipio + competencia
4. Captura tabela de propostas/parcelas pagas
5. Faz upsert em convenios_federal com fonte='FNS'

Requisitos:
- Playwright instalado (pip install playwright && playwright install chromium)
- Credenciais via env: FNS_CPF, FNS_SENHA
- Rodado via GitHub Actions (Vercel nao suporta Playwright)

NOTA: Este e o esqueleto base. A logica precisa ser ajustada apos
inspecionar o portal real (seletores, fluxo gov.br SSO podem variar).
"""
import os
import sys
import asyncio
import re
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, text
from config import get_settings

FNS_BASE_URL = "https://consultafns.saude.gov.br"
TIMEOUT_MS = 30_000


def _get_db_engine():
    settings = get_settings()
    sync_url = settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", "")
    return create_engine(sync_url)


def parse_money_br(s: str) -> Decimal:
    """'R$ 1.234.567,89' -> Decimal('1234567.89')"""
    if not s:
        return Decimal("0")
    s = re.sub(r"[^\d,.-]", "", s).replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return Decimal("0")


async def fns_login(page, cpf: str, senha: str):
    """Realiza login via gov.br no FNS."""
    await page.goto(FNS_BASE_URL, timeout=TIMEOUT_MS)
    # FNS redireciona para gov.br SSO - botao "Entrar com gov.br"
    try:
        await page.click("text=Entrar com gov.br", timeout=5_000)
    except Exception:
        # Se ja esta na pagina de login direto
        pass

    # Login gov.br: CPF -> Continuar -> Senha
    await page.fill("input[name='accountId']", cpf, timeout=TIMEOUT_MS)
    await page.click("button[type='submit']")
    await page.wait_for_selector("input[name='password']", timeout=TIMEOUT_MS)
    await page.fill("input[name='password']", senha)
    await page.click("button[type='submit']")
    # Aguarda volta ao FNS apos SSO
    await page.wait_for_url(f"{FNS_BASE_URL}/**", timeout=TIMEOUT_MS)


async def coletar_pagamentos(page, ibge: str, ano_inicio: int, ano_fim: int):
    """Coleta pagamentos de um municipio no periodo informado.

    Retorna lista de dicts com:
      nr_proposta, programa, competencia, valor, situacao, parcela
    """
    # Path tipico FNS: Consultas Publicas > Pagamentos > Por Beneficiario
    # Cada portal tem variacao. Aqui um esqueleto generico.
    url = f"{FNS_BASE_URL}/pagamentos?ibge={ibge}&anoInicio={ano_inicio}&anoFim={ano_fim}"
    await page.goto(url, timeout=TIMEOUT_MS)
    await page.wait_for_selector("table", timeout=TIMEOUT_MS)

    # Extrai linhas da tabela
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
            "valor": parse_money_br(texts[4] if len(texts) > 4 else "0"),
            "situacao": texts[5] if len(texts) > 5 else "Pago",
        })
    return pagamentos


def upsert_convenio_fns(conn, mun_id: int, p: dict):
    """Insere ou atualiza convenio_federal a partir de pagamento FNS."""
    nr = p.get("nr_proposta") or f"FNS-{p.get('programa','')}-{p.get('competencia','')}"
    nr = nr.strip()[:50] or f"FNS-{mun_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    ano = None
    comp = p.get("competencia") or ""
    m = re.search(r"(20\d{2})", comp)
    if m:
        ano = int(m.group(1))

    conn.execute(text("""
        INSERT INTO convenios_federal (
            nr_convenio, municipio_id, orgao_concedente, objeto,
            situacao, valor_repasse, ano, programa,
            tipo_programa, fonte, dt_desembolso, raw_data, updated_at
        ) VALUES (
            :nr, :mun, 'Min. Saude - FNS', :obj,
            :sit, :val, :ano, :prog,
            :tipo, 'FNS', :dt, :raw, NOW()
        )
        ON CONFLICT (nr_convenio) DO UPDATE SET
            valor_repasse = EXCLUDED.valor_repasse,
            situacao = EXCLUDED.situacao,
            dt_desembolso = EXCLUDED.dt_desembolso,
            raw_data = EXCLUDED.raw_data,
            updated_at = NOW()
    """), {
        "nr": nr,
        "mun": mun_id,
        "obj": p.get("programa", ""),
        "sit": p.get("situacao", "Pago"),
        "val": float(p.get("valor", 0) or 0),
        "ano": ano,
        "prog": p.get("programa", ""),
        "tipo": "PAP" if "PAP" in (p.get("programa", "") or "").upper()
                else ("MAC" if "MAC" in (p.get("programa", "") or "").upper() else None),
        "dt": None,
        "raw": str(p),
    })


async def run():
    cpf = os.getenv("FNS_CPF")
    senha = os.getenv("FNS_SENHA")
    if not cpf or not senha:
        print("ERRO: FNS_CPF e FNS_SENHA nao configurados")
        print("Configure como GitHub Secrets antes de rodar.")
        sys.exit(1)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("ERRO: Playwright nao instalado. Rode: pip install playwright && playwright install chromium")
        sys.exit(1)

    engine = _get_db_engine()

    # Buscar municipios ativos
    with engine.connect() as conn:
        muns = conn.execute(text(
            "SELECT id, nome, ibge_code FROM municipios WHERE active=true AND ibge_code IS NOT NULL"
        )).fetchall()

    print(f"=== FNS Scraper - {len(muns)} municipios ===")
    ano_inicio = 2022
    ano_fim = datetime.now().year

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            await fns_login(page, cpf, senha)
            print("  Login FNS OK")
        except Exception as e:
            print(f"  ERRO no login: {e}")
            await browser.close()
            sys.exit(1)

        total_inseridos = 0
        for mid, nome, ibge in muns:
            try:
                pagamentos = await coletar_pagamentos(page, ibge, ano_inicio, ano_fim)
                print(f"  {nome} (IBGE {ibge}): {len(pagamentos)} pagamentos")
                with engine.begin() as conn:
                    for p in pagamentos:
                        upsert_convenio_fns(conn, mid, p)
                        total_inseridos += 1
            except Exception as e:
                print(f"  {nome}: ERRO - {e}")
                continue

        await browser.close()

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO ingestion_log (source, status, records_inserted, finished_at)
            VALUES ('fns_scraper', 'success', :n, NOW())
        """), {"n": total_inseridos})

    print(f"\n  Total upsert FNS: {total_inseridos}")


if __name__ == "__main__":
    asyncio.run(run())
