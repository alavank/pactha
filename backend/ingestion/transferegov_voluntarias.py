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


def _clean(s):
    """Remove o caractere de substituicao U+FFFD que o portal TransfereGov as
    vezes serve no lugar de acentos (corrompido na origem, irrecuperavel)."""
    if not isinstance(s, str):
        return s
    return s.replace("�", "").replace("  ", " ").strip()


def _money(s):
    """Converte 'R$ 1.234.567,89' (pt-BR) em float. Retorna None se vazio/invalido."""
    if not s:
        return None
    import re as _re
    cleaned = _re.sub(r"[^\d,.-]", "", str(s))      # remove 'R$', espacos, etc
    cleaned = cleaned.replace(".", "").replace(",", ".")  # milhar . -> nada; decimal , -> .
    try:
        v = float(cleaned)
        return v if v != 0 else None
    except ValueError:
        return None


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

    # Extrai a grid (maior tabela) + links de paginacao displaytag (d-XXXX-p=N).
    # A consulta rapida mostra 20 itens/pagina -> precisamos visitar TODAS as paginas.
    grid_js = """() => {
        const tables=[...document.querySelectorAll('table')];
        let best=null,max=0;
        for(const t of tables){const r=t.querySelectorAll('tr');if(r.length>max){max=r.length;best=t;}}
        let rows=[];
        if(best){
            rows=[...best.querySelectorAll('tr')].slice(1).map(tr=>{
                const tds=[...tr.querySelectorAll('td')].map(c=>c.innerText.trim());
                const a=tr.querySelector('td a');
                return {cols: tds, href: a ? a.href : null};
            }).filter(r=>r.cols.length>=6);
        }
        const links=[];
        document.querySelectorAll('a').forEach(a=>{
            const t=(a.innerText||'').trim();
            if(/^\\d+$/.test(t) && /-p=\\d/.test(a.href||'')) links.push({num: parseInt(t,10), href: a.href});
        });
        return {rows, links};
    }"""

    all_rows = []
    page_links = {}      # num -> href (displaytag mostra janela de paginas)
    visited = set()
    res = await page.evaluate(grid_js)
    visited.add(1)
    all_rows.extend(res["rows"])
    for l in res["links"]:
        page_links.setdefault(l["num"], l["href"])
    safety = 0
    while safety < 100:
        safety += 1
        pending = [n for n in sorted(page_links) if n not in visited]
        if not pending:
            break
        n = pending[0]
        try:
            await page.goto(page_links[n], timeout=40000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2500)
            res = await page.evaluate(grid_js)
            all_rows.extend(res["rows"])
            for l in res["links"]:
                page_links.setdefault(l["num"], l["href"])
        except Exception as e:
            logger.warning(f"  {mun['nome']}: pagina {n} falhou: {str(e)[:80]}")
        visited.add(n)

    propostas = []
    seen_num = set()
    for row in all_rows:
        num = _clean(row["cols"][0])
        if not num or num in seen_num:
            continue
        seen_num.add(num)
        propostas.append({
            "numero_proposta": num,
            "situacao": _clean(row["cols"][1]),
            "orgao": _clean(row["cols"][2]),
            "proponente": _clean(row["cols"][3]),
            "possui_parecer": _clean(row["cols"][4]),
            "identificacao": _clean(row["cols"][5]),
            "_detalhe_url": row["href"],
        })
    logger.info(f"  {mun['nome']}: {len(visited)} pagina(s) -> {len(propostas)} propostas")

    # Enriquece cada proposta com o detalhe (Dados da Proposta)
    for prop in propostas:
        url = prop.pop("_detalhe_url", None)
        if not url:
            continue
        try:
            await page.goto(url, timeout=40000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2500)
            det = await _extrai_detalhe(page)
            # Limpa U+FFFD de chaves e valores
            prop["detalhe"] = {
                _clean(k): (_clean(v) if isinstance(v, str)
                            else [_clean(x) for x in v] if isinstance(v, list) else v)
                for k, v in (det or {}).items()
            }
        except Exception as e:
            logger.warning(f"    detalhe {prop['numero_proposta']}: {str(e)[:80]}")
    return propostas


async def _extrai_detalhe(page) -> dict:
    """Captura todos os pares label:valor + campos do topo da tela Dados da Proposta."""
    return await page.evaluate("""() => {
        const out = {};
        const setKV = (k, v) => { if (k && k.length < 70 && v && !out[k]) out[k] = v.slice(0, 600); };
        // Pares label|valor: linhas com 2 OU 4 celulas (label|valor|label|valor)
        document.querySelectorAll('tr').forEach(tr => {
            const tds = [...tr.querySelectorAll('td,th')];
            if (tds.length === 2) {
                setKV(tds[0].innerText.trim(), tds[1].innerText.trim());
            } else if (tds.length === 4) {
                setKV(tds[0].innerText.trim(), tds[1].innerText.trim());
                setKV(tds[2].innerText.trim(), tds[3].innerText.trim());
            }
        });
        // Campos do topo (Modalidade, Situacao SIAFI, Codigo Instrumento, etc) - layout em divs/spans
        const txt = document.body.innerText;
        const grab = (label) => {
            const re = new RegExp(label + '\\\\s*[:\\\\n]\\\\s*([^\\\\n]{1,120})', 'i');
            const m = txt.match(re);
            return m ? m[1].trim() : null;
        };
        for (const lbl of ['Modalidade','Situação no SIAFI','Código do Instrumento',
                           'Número da Proposta','Número do Processo','Situação de Contratação Atual']) {
            const v = grab(lbl);
            if (v && !out[lbl]) out[lbl] = v;
        }
        // Valores monetarios (Valor Global/Repasse/Contrapartida) - podem estar em
        // tabelas financeiras com layout variado; busca o proximo R$ apos o rotulo.
        const grabMoney = (label) => {
            const re = new RegExp(label + '[\\\\s\\\\S]{0,40}?(R\\\\$\\\\s*[\\\\d.]+,\\\\d{2})', 'i');
            const m = txt.match(re);
            return m ? m[1].trim() : null;
        };
        const moneyLabels = {
            'Valor Global': ['Valor Global do Instrumento','Valor Global'],
            'Valor de Repasse': ['Valor de Repasse da União','Valor de Repasse','Valor do Repasse'],
            'Valor de Contrapartida': ['Valor da Contrapartida','Valor de Contrapartida','Valor Contrapartida'],
        };
        for (const [outKey, variants] of Object.entries(moneyLabels)) {
            for (const lbl of variants) {
                const v = grabMoney(lbl);
                if (v) { out[outKey] = v; break; }
            }
        }
        // Documentos digitalizados (nomes dos PDFs)
        const docs = [];
        document.querySelectorAll('a').forEach(a => {
            const t = (a.innerText||'').trim();
            if (t.toLowerCase().includes('baixar') && a.closest('tr')) {
                const row = a.closest('tr').innerText.replace(/\\s+/g,' ').trim();
                if (row.includes('.pdf') || row.toLowerCase().includes('.pdf')) docs.push(row.slice(0,160));
            }
        });
        if (docs.length) out['_documentos'] = docs;
        // Situacao macro (campo destacado)
        const sitM = txt.match(/Situação\\s*\\n\\s*([^\\n]+)/);
        if (sitM) out['_situacao_macro'] = sitM[1].trim().slice(0,100);
        return out;
    }""")


def _upsert(mun_id: int, propostas: list[dict]):
    import psycopg2
    url = os.getenv("DATABASE_URL_SYNC", "")
    url = url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    conn = psycopg2.connect(url); cur = conn.cursor()
    ins = 0
    for p in propostas:
        if not p.get("numero_proposta"):
            continue
        det = p.get("detalhe") or {}
        def g(*keys):
            for k in keys:
                if det.get(k):
                    return str(det[k])
            return None
        codigo_instr = g("Código do Instrumento")
        modalidade = g("Modalidade")
        situacao_siafi = g("Situação no SIAFI")
        num_processo = g("Número do Processo")
        objeto = g("Objeto do Instrumento")
        programa = g("Programa", "Nome do Programa")
        dt_ini_vig = g("Data Início de Vigência")
        dt_fim_vig = g("Data Término de Vigência Atual", "Data Término de Vigência")
        dt_prop = g("Data da Proposta")
        dt_assin = g("Data Assinatura")
        valor_global = _money(g("Valor Global", "Valor Global do Instrumento"))
        valor_repasse = _money(g("Valor de Repasse", "Valor de Repasse da União", "Valor do Repasse"))
        valor_contrap = _money(g("Valor de Contrapartida", "Valor da Contrapartida"))
        cur.execute("""
            INSERT INTO transferegov_propostas
                (municipio_id, numero_proposta, situacao, orgao, proponente,
                 possui_parecer, identificacao, codigo_instrumento, modalidade,
                 situacao_siafi, numero_processo, objeto, programa,
                 dt_inicio_vigencia, dt_fim_vigencia, dt_proposta, dt_assinatura,
                 valor_global, valor_repasse, valor_contrapartida,
                 detalhe, raw_data, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,NOW())
            ON CONFLICT (municipio_id, numero_proposta) DO UPDATE SET
                situacao=EXCLUDED.situacao, orgao=EXCLUDED.orgao,
                proponente=EXCLUDED.proponente, possui_parecer=EXCLUDED.possui_parecer,
                identificacao=EXCLUDED.identificacao,
                codigo_instrumento=EXCLUDED.codigo_instrumento, modalidade=EXCLUDED.modalidade,
                situacao_siafi=EXCLUDED.situacao_siafi, numero_processo=EXCLUDED.numero_processo,
                objeto=EXCLUDED.objeto, programa=EXCLUDED.programa,
                dt_inicio_vigencia=EXCLUDED.dt_inicio_vigencia, dt_fim_vigencia=EXCLUDED.dt_fim_vigencia,
                dt_proposta=EXCLUDED.dt_proposta, dt_assinatura=EXCLUDED.dt_assinatura,
                valor_global=COALESCE(EXCLUDED.valor_global, transferegov_propostas.valor_global),
                valor_repasse=COALESCE(EXCLUDED.valor_repasse, transferegov_propostas.valor_repasse),
                valor_contrapartida=COALESCE(EXCLUDED.valor_contrapartida, transferegov_propostas.valor_contrapartida),
                detalhe=EXCLUDED.detalhe, raw_data=EXCLUDED.raw_data, updated_at=NOW()
        """, (mun_id, p["numero_proposta"][:20], p["situacao"][:300], p["orgao"][:300],
              p["proponente"][:300], p["possui_parecer"][:10], p["identificacao"][:30],
              (codigo_instr or "")[:30] or None, (modalidade or "")[:100] or None,
              (situacao_siafi or "")[:200] or None, (num_processo or "")[:50] or None,
              objeto, (programa or "")[:300] or None,
              (dt_ini_vig or "")[:20] or None, (dt_fim_vig or "")[:20] or None,
              (dt_prop or "")[:20] or None, (dt_assin or "")[:20] or None,
              valor_global, valor_repasse, valor_contrap,
              json.dumps(det, ensure_ascii=False), json.dumps(p, ensure_ascii=False)))
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
