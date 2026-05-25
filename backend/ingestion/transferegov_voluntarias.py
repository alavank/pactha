"""Scraper TransfereGov - Transferencias Voluntarias (SICONV/Discricionarias).

Fonte: portal voluntarias via ACESSO LIVRE (guest), sem login gov.br.
Ponto de entrada que estabelece sessao de visitante:
  /voluntarias/ForwardAction.do?modulo=Principal&path=/MostraPrincipalConsultarProposta.do&Usr=guest&Pwd=guest

O fluxo passa por SAML auto-submit (forms com onload=submit), que SO funciona
em browser real -> por isso Playwright (igual SIGCON). httpx puro nao resolve
porque o IdP exige JS.

Para cada municipio PACTA:
  1. Entra via guest
  2. Consulta Rapida: seleciona UF + Municipio (match por nome normalizado)
  3. Clica Consultar
  4. Extrai a grid (Numero, Situacao, Orgao, Proponente, Parecer, CNPJ)
  5. UPSERT em transferegov_propostas

Roda no service com Chromium (Dockerfile.scraper). Local: requer playwright install.
"""
import asyncio
import json
import logging
import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tg_voluntarias")

ENTRY = ("https://discricionarias.transferegov.sistema.gov.br/voluntarias/ForwardAction.do"
         "?modulo=Principal&path=/MostraPrincipalConsultarProposta.do&Usr=guest&Pwd=guest")


def _norm(s: str) -> str:
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFKD", s.upper()) if not unicodedata.combining(c)).strip()


def _municipios_pacta() -> list[dict]:
    import psycopg2
    url = os.getenv("DATABASE_URL_SYNC", "")
    url = url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    conn = psycopg2.connect(url)
    cur = conn.cursor()
    cur.execute("SELECT id, nome, uf FROM municipios WHERE active = true ORDER BY nome")
    out = [{"id": r[0], "nome": r[1], "uf": r[2]} for r in cur.fetchall()]
    cur.close(); conn.close()
    return out


async def _scrape_municipio(page, mun: dict, _retry: int = 0) -> list[dict]:
    """Consulta rapida por UF + Municipio, retorna lista de propostas."""
    await page.goto(ENTRY, timeout=60000, wait_until="domcontentloaded")
    await page.wait_for_timeout(6000 + _retry * 4000)  # SAML auto-submits (mais tempo no retry)

    # Seleciona UF (com retry se a sessao SAML nao estabeleceu)
    try:
        await page.wait_for_selector("select[name=ufAcessoLivre]", timeout=12000)
        await page.select_option("select[name=ufAcessoLivre]", mun["uf"], timeout=10000)
    except Exception:
        if _retry < 2:
            logger.warning(f"  {mun['nome']}: select UF ausente, retry {_retry+1}")
            return await _scrape_municipio(page, mun, _retry + 1)
        logger.warning(f"  {mun['nome']}: select UF nao encontrado apos retries (sessao falhou)")
        return []
    await page.wait_for_timeout(3500)  # carrega municipios via ajax

    # Match municipio por nome normalizado
    muns = await page.evaluate(
        "() => [...document.querySelector('select[name=municipioAcessoLivre]').options]"
        ".map(o => ({v: o.value, t: o.text}))"
    )
    alvo = [m for m in muns if _norm(m["t"]) == _norm(mun["nome"])]
    if not alvo:
        logger.warning(f"  {mun['nome']}: nao encontrado no select ({len(muns)} municipios)")
        return []
    await page.select_option("select[name=municipioAcessoLivre]", alvo[0]["v"])
    await page.wait_for_timeout(1500)

    # Clica Consultar (consulta rapida)
    await page.evaluate("""() => {
        const btns = [...document.querySelectorAll('input[type=button],button,input[type=submit],a')];
        const c = btns.find(b => (b.value||b.innerText||'').trim().toLowerCase()==='consultar');
        if (c) c.click();
    }""")
    await page.wait_for_timeout(9000)

    # Extrai a grid (maior tabela)
    grid = await page.evaluate("""() => {
        const tables=[...document.querySelectorAll('table')];
        let best=null,max=0;
        for(const t of tables){const r=t.querySelectorAll('tr');if(r.length>max){max=r.length;best=t;}}
        if(!best)return[];
        const trs=[...best.querySelectorAll('tr')];
        const head=[...trs[0].querySelectorAll('th,td')].map(c=>c.innerText.trim());
        return trs.slice(1).map(tr=>{
            const tds=[...tr.querySelectorAll('td')].map(c=>c.innerText.trim());
            return tds;
        }).filter(r=>r.length>=6);
    }""")
    propostas = []
    for row in grid:
        propostas.append({
            "numero_proposta": row[0],
            "situacao": row[1],
            "orgao": row[2],
            "proponente": row[3],
            "possui_parecer": row[4],
            "identificacao": row[5],
        })
    return propostas


def _upsert(mun_id: int, propostas: list[dict]):
    import psycopg2
    url = os.getenv("DATABASE_URL_SYNC", "")
    url = url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    conn = psycopg2.connect(url); cur = conn.cursor()
    ins = 0
    for p in propostas:
        if not p.get("numero_proposta"):
            continue
        cur.execute("""
            INSERT INTO transferegov_propostas
                (municipio_id, numero_proposta, situacao, orgao, proponente,
                 possui_parecer, identificacao, raw_data, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,NOW())
            ON CONFLICT (municipio_id, numero_proposta) DO UPDATE SET
                situacao=EXCLUDED.situacao, orgao=EXCLUDED.orgao,
                proponente=EXCLUDED.proponente, possui_parecer=EXCLUDED.possui_parecer,
                identificacao=EXCLUDED.identificacao, raw_data=EXCLUDED.raw_data,
                updated_at=NOW()
        """, (mun_id, p["numero_proposta"][:20], p["situacao"][:300], p["orgao"][:300],
              p["proponente"][:300], p["possui_parecer"][:10], p["identificacao"][:30],
              json.dumps(p, ensure_ascii=False)))
        ins += 1
    conn.commit(); cur.close(); conn.close()
    return ins


async def run():
    from playwright.async_api import async_playwright
    municipios = _municipios_pacta()
    logger.info(f"=== TransfereGov Voluntarias: {len(municipios)} municipios ===")
    total = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--ignore-certificate-errors", "--no-sandbox"])
        ctx = await browser.new_context(ignore_https_errors=True, user_agent="Mozilla/5.0 Chrome/131")
        page = await ctx.new_page()
        for mun in municipios:
            try:
                props = await _scrape_municipio(page, mun)
                n = _upsert(mun["id"], props)
                logger.info(f"  {mun['nome']}: {len(props)} propostas -> {n} upsert")
                total += n
            except Exception as e:
                logger.error(f"  {mun['nome']}: ERRO {str(e)[:200]}")
        await browser.close()
    logger.info(f"=== Finalizado: {total} propostas ===")
    # Log de ingestao
    try:
        import psycopg2
        url = os.getenv("DATABASE_URL_SYNC", "").replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        conn = psycopg2.connect(url); cur = conn.cursor()
        cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, finished_at) "
                    "VALUES ('transferegov_voluntarias','success',%s,NOW())", (total,))
        conn.commit(); cur.close(); conn.close()
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(run())
