"""Scraper Selecao PAC / Novo PAC (TransfereGov, Acesso Livre guest).

Fonte: discricionarias.transferegov.../voluntarias/propostapac/listarPropostaPac.jsf
Fluxo: sessao guest (mesmo ENTRY das voluntarias) -> pagina PAC -> filtra por
CNPJ do Proponente (prefeitura) -> Consultar -> pagina a grid -> detalhe ->
UPSERT em transferegov_pac.

O CNPJ da prefeitura vem das voluntarias ja coletadas (transferegov_propostas.
identificacao); se o municipio ainda nao tem CNPJ conhecido, pula (loga).

Uso: python -m ingestion.transferegov_pac [municipio_id]   (sem id = todos ativos)
Roda no Dockerfile.scraper (Chromium). DATABASE_URL_SYNC obrigatorio.
"""
import asyncio
import json
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tg_pac")

from ingestion.transferegov_voluntarias import ENTRY, _clean, _money, _norm  # noqa: E402

PAC_URL = "https://discricionarias.transferegov.sistema.gov.br/voluntarias/propostapac/listarPropostaPac.jsf"


def _db_url() -> str:
    return (os.getenv("DATABASE_URL_SYNC", "")
            .replace("&channel_binding=require", "").replace("?channel_binding=require", ""))


def _municipios(municipio_id=None) -> list[dict]:
    import psycopg2
    conn = psycopg2.connect(_db_url()); cur = conn.cursor()
    if municipio_id:
        cur.execute("SELECT id, nome, uf FROM municipios WHERE id=%s", (int(municipio_id),))
    else:
        cur.execute("SELECT id, nome, uf FROM municipios WHERE active=true ORDER BY nome")
    muns = [{"id": r[0], "nome": r[1], "uf": r[2]} for r in cur.fetchall()]
    # CNPJ da prefeitura (proponente) — mais frequente nas voluntarias
    for m in muns:
        cur.execute("""SELECT identificacao FROM transferegov_propostas
                       WHERE municipio_id=%s AND identificacao ~ '^[0-9]'
                       GROUP BY identificacao ORDER BY count(*) DESC LIMIT 1""", (m["id"],))
        row = cur.fetchone()
        m["cnpj"] = (row[0].strip() if row and row[0] else None)
    cur.close(); conn.close()
    return muns


# grid_js: extrai rows (cols + href de detalhe), links numericos e "proxima"
GRID_JS = r"""() => {
    const tables=[...document.querySelectorAll('table')];
    let best=null,max=0;
    for(const t of tables){const r=t.querySelectorAll('tr').length;if(r>max){max=r;best=t;}}
    let rows=[];
    if(best){
        rows=[...best.querySelectorAll('tr')].slice(1).map(tr=>{
            const tds=[...tr.querySelectorAll('td')].map(c=>c.innerText.trim());
            const a=tr.querySelector('td a[href]');
            return {cols:tds, href:(a && /Proposta/i.test(a.href))?a.href:null};
        }).filter(r=>r.cols.length>=5 && /\d{6,}\/\d{4}/.test(r.cols[0]||''));
    }
    const denude=s=>(s||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase();
    const links=[]; let prox=null;
    document.querySelectorAll('a').forEach(a=>{
        const raw=(a.innerText||'').trim(); const href=a.href||'';
        if(/^\d+$/.test(raw) && /-p=\d+/.test(href)) links.push({num:parseInt(raw,10), href});
        const t=denude(raw);
        if((t.indexOf('prox')===0||t==='>'||t==='>>') && /-g=\d+/.test(href)) prox=href;
    });
    let info=null;
    document.querySelectorAll('.pagelinks').forEach(b=>{
        const mm=denude(b.innerText).match(/pagina\s+(\d+)\s+de\s+(\d+)/);
        if(mm) info={cur:+mm[1], total:+mm[2]};
    });
    return {rows, links, prox, info};
}"""


async def _extrai_detalhe(page) -> dict:
    """Objeto/justificativa/valores/qualificacao da pagina de detalhe (label->valor)."""
    return await page.evaluate(r"""() => {
        const out={};
        const nodes=[...document.querySelectorAll('td,label,span,th')];
        const want={'objeto':'objeto','justificativa':'justificativa','qualifica':'qualificacao',
                    'valor repasse':'valor_repasse','valor contrapartida':'valor_contrapartida',
                    'valor total':'valor_total','programa':'programa'};
        const denude=s=>(s||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase().trim();
        for(const n of nodes){
            const t=denude(n.innerText);
            for(const k in want){
                if(t===k || t===k+':'){
                    let val='';
                    const ta=n.parentElement && n.parentElement.querySelector('textarea');
                    if(ta) val=ta.value||ta.innerText;
                    else if(n.nextElementSibling) val=n.nextElementSibling.innerText;
                    if(val && !out[want[k]]) out[want[k]]=val.trim().slice(0,4000);
                }
            }
        }
        return out;
    }""")


async def _scrape_municipio(page, mun: dict) -> list[dict]:
    if not mun.get("cnpj"):
        logger.warning(f"  {mun['nome']}: sem CNPJ conhecido (rode voluntarias antes) — pulando PAC")
        return []
    await page.goto(PAC_URL, timeout=45000, wait_until="domcontentloaded")
    await page.wait_for_timeout(2500)
    # Preenche CNPJ do Proponente (acha pelo texto da linha; fallback posicional)
    ok = await page.evaluate(r"""(cnpj) => {
        for(const i of document.querySelectorAll('input[type=text]')){
            const tr=i.closest('tr'); const txt=((tr?tr.innerText:'')||'').toUpperCase();
            if(txt.includes('CNPJ') && txt.includes('PROPONENTE')){ i.value=cnpj; return true; }
        }
        const f=document.getElementById('formListarPropostaPac:_idJsp35');
        if(f){ f.value=cnpj; return true; } return false;
    }""", mun["cnpj"])
    if not ok:
        logger.warning(f"  {mun['nome']}: campo CNPJ nao encontrado no form PAC"); return []
    await page.evaluate("""() => {
        const b=document.getElementById('formListarPropostaPac:_idJsp55')
          || [...document.querySelectorAll('input[type=submit],button')].find(x=>/consultar/i.test(x.value||x.innerText||''));
        if(b) b.click();
    }""")
    await page.wait_for_timeout(7000)
    try:
        await page.wait_for_selector(".pagelinks, table", timeout=12000)
    except Exception:
        pass

    # Paginacao POSTBACK JSF: os numeros/"Prox" nao sao links GET (-p=), sao
    # postbacks. Clicamos o "Prox" (postback) ate sumir / nao trazer nada novo.
    def _key(r):
        return _clean(r["cols"][0]) if r.get("cols") else ""
    all_rows = []
    seen = set()
    res = await page.evaluate(GRID_JS)
    for r in res["rows"]:
        k = _key(r)
        if k and k not in seen:
            seen.add(k); all_rows.append(r)
    # Paginacao = RichFaces dataScroller (A4J.AJAX.Submit). O "Prox" e um <span>
    # (nao clicavel); os NUMEROS ("2","3"...) sao <a> com onclick A4J. Clicamos o
    # numero da proxima pagina (cur+1) — clique confiavel do Playwright dispara o
    # AJAX que re-renderiza a grid. Para quando nao ha o proximo numero.
    cur = 1
    paginas = 1
    while paginas < 60:
        nxt = page.locator(".pagelinks a", has_text=re.compile(rf"^\s*{cur + 1}\s*,?\s*$"))
        try:
            if await nxt.count() == 0:
                break
            await nxt.first.click(timeout=6000)
        except Exception:
            break
        await page.wait_for_timeout(3000)
        res = await page.evaluate(GRID_JS)
        novos = 0
        for r in res["rows"]:
            k = _key(r)
            if k and k not in seen:
                seen.add(k); all_rows.append(r); novos += 1
        cur += 1
        paginas += 1
        if novos == 0:
            break

    # dedup por numero_proposta
    props = {}
    for row in all_rows:
        c = row["cols"]
        num = _clean(c[0])
        if not num or num in props:
            continue
        prog = _clean(c[1]) if len(c) > 1 else ""
        prog_cod = prog.split(" - ", 1)[0].strip() if " - " in prog else ""
        propo = _clean(c[2]) if len(c) > 2 else ""
        cnpj = ""
        mprop = re.match(r"\s*([\d./-]{14,20})\s*-\s*(.*)", propo)
        if mprop:
            cnpj = mprop.group(1); propo = mprop.group(2).strip()
        props[num] = {
            "numero_proposta": num, "programa": prog, "programa_codigo": prog_cod,
            "proponente": propo, "cnpj": cnpj or mun["cnpj"],
            "situacao": _clean(c[3]) if len(c) > 3 else "",
            "valor_total": _money(c[4]) if len(c) > 4 else None,
            "emenda_parlamentar": (_clean(c[5]) if len(c) > 5 and _clean(c[5]) not in ("-", "") else None),
            "_detalhe_url": row.get("href"),
        }
    logger.info(f"  {mun['nome']}: {paginas} pagina(s) -> {len(props)} propostas PAC")
    # OBS: o detalhe (objeto/justificativa) e postback JSF (href='#'), nao navegavel
    # por GET. Enriquecimento futuro: clicar a linha + "Voltar" por proposta.
    for p in props.values():
        p.pop("_detalhe_url", None)
    return list(props.values())


def _upsert(mun_id: int, props: list[dict]) -> int:
    import psycopg2
    conn = psycopg2.connect(_db_url()); cur = conn.cursor()
    n = 0
    for p in props:
        try:
            cur.execute("""
                INSERT INTO transferegov_pac
                  (municipio_id, numero_proposta, programa, programa_codigo, proponente, cnpj,
                   situacao, valor_repasse, valor_contrapartida, valor_total, emenda_parlamentar,
                   qualificacao, objeto, justificativa, detalhe_url, raw_data, updated_at)
                VALUES (%(m)s,%(numero_proposta)s,%(programa)s,%(programa_codigo)s,%(proponente)s,%(cnpj)s,
                   %(situacao)s,%(valor_repasse)s,%(valor_contrapartida)s,%(valor_total)s,%(emenda_parlamentar)s,
                   %(qualificacao)s,%(objeto)s,%(justificativa)s,%(detalhe_url)s,%(raw)s::jsonb, NOW())
                ON CONFLICT (municipio_id, numero_proposta) DO UPDATE SET
                   programa=EXCLUDED.programa, programa_codigo=EXCLUDED.programa_codigo,
                   proponente=EXCLUDED.proponente, cnpj=EXCLUDED.cnpj, situacao=EXCLUDED.situacao,
                   valor_repasse=COALESCE(EXCLUDED.valor_repasse, transferegov_pac.valor_repasse),
                   valor_contrapartida=COALESCE(EXCLUDED.valor_contrapartida, transferegov_pac.valor_contrapartida),
                   valor_total=COALESCE(EXCLUDED.valor_total, transferegov_pac.valor_total),
                   emenda_parlamentar=EXCLUDED.emenda_parlamentar,
                   qualificacao=COALESCE(EXCLUDED.qualificacao, transferegov_pac.qualificacao),
                   objeto=COALESCE(EXCLUDED.objeto, transferegov_pac.objeto),
                   justificativa=COALESCE(EXCLUDED.justificativa, transferegov_pac.justificativa),
                   detalhe_url=EXCLUDED.detalhe_url, raw_data=EXCLUDED.raw_data, updated_at=NOW()
            """, {**{k: p.get(k) for k in ("numero_proposta", "programa", "programa_codigo", "proponente",
                     "cnpj", "situacao", "valor_repasse", "valor_contrapartida", "valor_total",
                     "emenda_parlamentar", "qualificacao", "objeto", "justificativa", "detalhe_url")},
                  "m": mun_id, "raw": json.dumps(p, ensure_ascii=False)})
            n += 1
        except Exception as e:
            logger.warning(f"upsert {p.get('numero_proposta')}: {str(e)[:80]}"); conn.rollback(); continue
    conn.commit(); cur.close(); conn.close()
    return n


async def run(municipio_id=None):
    from playwright.async_api import async_playwright
    muns = _municipios(municipio_id)
    logger.info(f"=== Selecao PAC: {len(muns)} municipio(s) ===")
    total = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--ignore-certificate-errors", "--no-sandbox"])
        ctx = await browser.new_context(ignore_https_errors=True, user_agent="Mozilla/5.0 Chrome/131")
        page = await ctx.new_page()
        await page.goto(ENTRY, timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(6000)
        for mun in muns:
            try:
                props = await _scrape_municipio(page, mun)
                if props:
                    ins = _upsert(mun["id"], props)
                    logger.info(f"  {mun['nome']}: {ins} PAC upsert")
                    total += ins
            except Exception as e:
                logger.warning(f"  {mun['nome']}: falhou — {str(e)[:100]}")
        await browser.close()
    logger.info(f"=== PAC concluido: {total} propostas ===")
    return total


if __name__ == "__main__":
    mid = int(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(run(mid))
