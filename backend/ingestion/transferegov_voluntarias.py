"""Scraper TransfereGov - Transferencias Voluntarias (SICONV/Discricionarias).

Fonte: portal voluntarias via ACESSO LIVRE (guest), sem login gov.br.
Ponto de entrada que estabelece sessao de visitante:
  /voluntarias/ForwardAction.do?modulo=Principal&path=/MostraPrincipalConsultarProposta.do&Usr=guest&Pwd=guest

O fluxo passa por SAML auto-submit (forms com onload=submit), que SO funciona
em browser real -> por isso Playwright (igual SIGCON). httpx puro nao resolve
porque o IdP exige JS.

Para cada municipio PACTHA:
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
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tg_voluntarias")

ENTRY = ("https://discricionarias.transferegov.sistema.gov.br/voluntarias/ForwardAction.do"
         "?modulo=Principal&path=/MostraPrincipalConsultarProposta.do&Usr=guest&Pwd=guest")

# Entrada AUTENTICADA (sem Usr=guest): mesma tela de consulta, mas os detalhes
# resultantes sao a versao logada — com o botao "Detalhar Clausula Suspensiva/
# Liminar Judicial" e os campos gated (parlamentar). O guest NAO renderiza esse
# botao (TagFuncionalidade resultado='false'). Por isso, quando ha sessao viva,
# a LISTAGEM tambem precisa rodar autenticada (nao so o detalhe).
ENTRY_AUTH = ("https://discricionarias.transferegov.sistema.gov.br/voluntarias/ForwardAction.do"
              "?modulo=Principal&path=/MostraPrincipalConsultarProposta.do")


def _jwt_minutos_restantes(cookies: list[dict]) -> float:
    """Retorna minutos restantes do JWT user-id (parcerias.transferegov).
    Retorna -inf se nao houver user-id ou nao decodificar.
    Retorna 0 se ja expirou."""
    import base64
    import json as _json
    import time
    uid = next((c for c in cookies if c.get("name") == "user-id"), None)
    if not uid:
        return float("-inf")
    token = uid.get("value", "")
    parts = token.split(".")
    if len(parts) < 2:
        return float("-inf")
    try:
        pb = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = _json.loads(base64.urlsafe_b64decode(pb))
        exp = payload.get("exp")
        if exp:
            return (exp - time.time()) / 60
    except Exception:
        pass
    return float("-inf")


def _propostas_ja_enriquecidas(municipio_id: int) -> set:
    """Retorna numero_proposta das que JA tem parlamentar OU sit_det.
    Permite priorizar as pendentes quando rodando com janela curta de auth."""
    try:
        import psycopg2
        url = os.getenv("DATABASE_URL_SYNC", "").replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        conn = psycopg2.connect(url); cur = conn.cursor()
        cur.execute(
            "SELECT numero_proposta FROM transferegov_propostas "
            "WHERE municipio_id=%s AND (parlamentar IS NOT NULL OR situacao_contratacao_detalhe IS NOT NULL)",
            (municipio_id,)
        )
        out = {r[0] for r in cur.fetchall()}
        cur.close(); conn.close()
        return out
    except Exception:
        return set()


def _load_session_cookies(automation_key: str) -> list[dict] | None:
    """Carrega cookies do Cofre p/ uma chave de automacao (best-effort)."""
    try:
        import psycopg2
        from services import crypto
        url = os.getenv("DATABASE_URL_SYNC", "")
        url = url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        conn = psycopg2.connect(url)
        cur = conn.cursor()
        cur.execute(
            "SELECT senha_hash FROM cofre_senhas "
            "WHERE automation_key=%s AND length(senha_hash) > 1000 "
            "ORDER BY updated_at DESC LIMIT 1",
            (automation_key,),
        )
        row = cur.fetchone()
        cur.close(); conn.close()
        if not row:
            return None
        dec = crypto.decrypt(row[0])
        if not dec or not dec.startswith("{"):
            return None
        data = json.loads(dec)
        out = []
        for c in data.get("cookies", []):
            n, v = c.get("name"), c.get("value")
            if not n or v is None:
                continue
            ck = {
                "name": n, "value": v, "path": c.get("path") or "/",
                "secure": bool(c.get("secure")), "httpOnly": bool(c.get("httpOnly")),
            }
            if c.get("domain"):
                ck["domain"] = c["domain"]
            ss = c.get("sameSite")
            if ss:
                ck["sameSite"] = {"no_restriction": "None", "lax": "Lax", "strict": "Strict",
                                  "None": "None", "Lax": "Lax", "Strict": "Strict"}.get(ss, "Lax")
            exp = c.get("expirationDate")
            if exp:
                try:
                    ck["expires"] = float(exp)
                except (TypeError, ValueError):
                    pass
            out.append(ck)
        return out or None
    except Exception as e:
        logger.warning(f"_load_session_cookies({automation_key}): ignorando ({e})")
        return None


def _load_govbr_cookies() -> list[dict] | None:
    """Carrega cookies das DUAS sessoes (govbr + siconv_legado) consolidadas.
    govbr = cookies de parcerias.transferegov + SSO gov.br
    siconv_legado = cookies de discricionarias.transferegov (JSESSIONID p/
                    acessar Cláusula Suspensiva e demais campos gated do SICONV antigo)
    Retorna lista consolidada (deduplicada por nome+dominio)."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for key in ("govbr", "siconv_legado"):
        cks = _load_session_cookies(key)
        if not cks:
            continue
        for c in cks:
            sig = (c.get("name", ""), c.get("domain", ""))
            if sig in seen:
                continue
            seen.add(sig)
            out.append(c)
        logger.info(f"  cofre[{key}]: {len(cks)} cookies carregados")
    return out or None


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


async def _goto_with_retry(page, url: str, max_retries: int = 3, base_delay: float = 0.5,
                           timeout: int = 30000) -> bool:
    """goto() com backoff exponencial. True=sucesso, False=falhou.
    Nao retenta 404/403 (erro permanente). Recupera de 'connection closed',
    'ERR_NAME_NOT_RESOLVED' e timeouts transitorios."""
    import random
    for attempt in range(max_retries):
        try:
            await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            return True
        except Exception as e:
            es = str(e).lower()
            if "404" in es or "403" in es or "not found" in es:
                return False
            if attempt < max_retries - 1:
                await asyncio.sleep(base_delay * (2 ** attempt) + random.uniform(0, 0.4))
            else:
                logger.warning(f"    goto {url[:55]} falhou {max_retries}x: {str(e)[:60]}")
                return False
    return False


async def _scrape_municipio(page, mun: dict, _retry: int = 0, is_auth: bool = False,
                            page_auth=None) -> list[dict]:
    """Consulta por UF + Municipio, retorna lista de propostas COM detalhe.

    page      = pagina GUEST (sem cookies) p/ listagem+detalhe via Acesso Livre.
                A listagem SO funciona em guest: com cookies de sessao, o
                ForwardAction redireciona p/ a consulta do convenente (sem o
                form ufAcessoLivre) e a listagem falha.
    page_auth = pagina AUTENTICADA (com cookies gov.br) p/ abrir o INSTRUMENTO
                e capturar o detalhe da Clausula Suspensiva (motivo + data).
                None = sem sessao -> captura so o status, sem motivo/data.
    is_auth   = mantido por compat; nao altera mais a entrada (sempre guest).
    """
    entry = ENTRY  # listagem SEMPRE via Acesso Livre (guest)
    await page.goto(entry, timeout=60000, wait_until="domcontentloaded")
    await page.wait_for_timeout(6000 + _retry * 4000)  # SAML auto-submits (mais tempo no retry)

    # Seleciona UF (com retry se a sessao SAML nao estabeleceu)
    try:
        await page.wait_for_selector("select[name=ufAcessoLivre]", timeout=12000)
        await page.select_option("select[name=ufAcessoLivre]", mun["uf"], timeout=10000)
    except Exception:
        if _retry < 2:
            logger.warning(f"  {mun['nome']}: select UF ausente, retry {_retry+1}")
            return await _scrape_municipio(page, mun, _retry + 1, is_auth=is_auth,
                                           page_auth=page_auth)
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
    grid_js = r"""() => {
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
        const denude = s => (s||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase();
        const links=[];
        let prox=null;
        document.querySelectorAll('a').forEach(a=>{
            const raw=(a.innerText||'').trim();
            const href=a.href||'';
            // links NUMERICOS da janela: tem -p= E -g= (ex ...-p=3&-g=3)
            if(/^\d+$/.test(raw) && /-p=\d+/.test(href)) links.push({num: parseInt(raw,10), href});
            // link "Prox" (proxima janela): so tem -g= (SEM -p=). Desliza a janela.
            const t=denude(raw);
            if((t.indexOf('prox')===0 || t==='>' || t==='>>' || t.indexOf('seguinte')>=0 || t.indexOf('next')>=0)
               && /-g=\d+/.test(href)) prox=href;
        });
        // info "Pagina X de Y (Z item(s))" p/ validar avanco e saber a ultima pagina
        let info=null;
        document.querySelectorAll('.pagelinks').forEach(b=>{
            const mm=denude(b.innerText).match(/pagina\s+(\d+)\s+de\s+(\d+)\s*\((\d+)/);
            if(mm) info={cur:+mm[1], total:+mm[2], items:+mm[3]};
        });
        return {rows, links, prox, info};
    }"""

    all_rows = []
    res = await page.evaluate(grid_js)
    all_rows.extend(res["rows"])

    # Paginacao SEM TETO. O displaytag mostra so uma JANELA fixa de numeros
    # (ex 1-10) e NAO desliza clicando nos numeros. Para ir alem, ha o link
    # "[Prox]" (proxima janela), que usa APENAS -g=<pag> (SEM -p=) e recarrega
    # a grid deslizando a janela (10 -> 11..16). Estrategia:
    #   - dentro da janela: navega pelo link NUMERICO de cur+1 (tem -p= & -g=);
    #   - na borda da janela: usa o link "[Prox]" (so -g=).
    # Valida o avanco pelo banner "Pagina X de Y" e re-tenta se a grid vier
    # vazia (carga incompleta). Para na ultima pagina (cur == total).
    def _key(r):
        return _clean(r["cols"][0]) if r.get("cols") else ""
    seen_keys = {_key(r) for r in res["rows"] if _key(r)}
    total = (res.get("info") or {}).get("total")
    cur = 1
    paginas = 1
    tried = set()
    while (total is None or cur < total) and paginas < 2000:
        nxt = next((l["href"] for l in res.get("links", []) if l["num"] == cur + 1), None)
        if not nxt:
            nxt = res.get("prox")  # borda da janela -> desliza via [Prox] (so -g=)
        if not nxt or nxt in tried:
            break  # ultima pagina (nem cur+1 numerico nem [Prox])
        tried.add(nxt)
        # navega com retry: as vezes a grid vem vazia/incompleta (recarrega)
        loaded = False
        for attempt in range(3):
            try:
                await page.goto(nxt, timeout=40000, wait_until="domcontentloaded")
            except Exception as e:
                logger.warning(f"  {mun['nome']}: goto pagina {cur + 1} falhou: {str(e)[:70]}")
                await page.wait_for_timeout(1500)
                continue
            await page.wait_for_timeout(2500 + attempt * 1500)
            res = await page.evaluate(grid_js)
            info = res.get("info") or {}
            # ok se veio linha(s) E a pagina reportada avancou p/ cur+1 (ou sem info)
            if res["rows"] and (not info or info.get("cur") == cur + 1):
                loaded = True
                break
        if not loaded:
            logger.warning(f"  {mun['nome']}: pagina {cur + 1} nao carregou (grid vazia/errada), parando em {len(all_rows)} linhas")
            break
        novos = 0
        for r in res["rows"]:
            k = _key(r)
            if k and k not in seen_keys:
                seen_keys.add(k); novos += 1
        all_rows.extend(res["rows"])
        cur += 1
        paginas += 1
        if novos == 0:
            break  # nada novo -> fim (evita loop se algo repetir)

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
    logger.info(f"  {mun['nome']}: {paginas} pagina(s) -> {len(propostas)} propostas")

    # Enriquece cada proposta com o detalhe (Dados da Proposta).
    # Listagem e detalhe rodam na MESMA page (mesma sessao). Quando is_auth,
    # os links de detalhe sao logados → renderizam o botao Detalhar Clausula
    # Suspensiva + campos gated (parlamentar).
    # OTIMIZACAO: quando auth, prioriza propostas SEM enrich (janela curta).
    detail_page = page
    if page_auth is not None:
        try:
            _ja_enriquecidos = _propostas_ja_enriquecidas(mun["id"])
            propostas.sort(key=lambda p: 0 if p["numero_proposta"] not in _ja_enriquecidos else 1)
            n_pend = sum(1 for p in propostas if p["numero_proposta"] not in _ja_enriquecidos)
            logger.info(f"  {mun['nome']}: {n_pend} propostas SEM enrich serao priorizadas")
        except Exception:
            pass
    _tot = len(propostas)
    _enr = 0
    for _i, prop in enumerate(propostas, 1):
        if _i % 10 == 0:
            logger.info(f"    {mun['nome']}: detalhe {_i}/{_tot} (enriquecidos: {_enr})")
        url = prop.pop("_detalhe_url", None)
        if not url:
            continue
        # Guarda o idProposta (da URL) -> casa com o open data siconv_emenda p/
        # backfill do parlamentar sem precisar do arquivo nacional de 199 MB.
        _idp = _id_proposta_from_url(url)
        if _idp:
            prop["id_proposta_siconv"] = _idp
        try:
            if not await _goto_with_retry(detail_page, url):
                continue
            await detail_page.wait_for_timeout(1800)
            det = await _extrai_detalhe(detail_page)
            # Tenta capturar parlamentar (best-effort via texto livre na tela)
            try:
                parl = await _extrai_parlamentar(detail_page)
                if parl:
                    det["_parlamentar"] = parl
            except Exception:
                pass
            det.pop("_situacao_det_url", None)
            det.pop("_situacao_det_label", None)
            # Limpa U+FFFD de chaves e valores
            prop["detalhe"] = {
                _clean(k): (_clean(v) if isinstance(v, str)
                            else [_clean(x) for x in v] if isinstance(v, list) else v)
                for k, v in (det or {}).items()
            }
            # Detalhe da Clausula Suspensiva / Liminar Judicial (motivo + data
            # prevista). So existe quando a Situacao de Contratacao e clausula/
            # liminar E ha sessao autenticada com acesso ao instrumento. O botao
            # NAO fica na pagina da proposta — fica no INSTRUMENTO. Por isso
            # navegamos proposta->instrumento->Detalhar na page_auth (cookies).
            _sit = (prop["detalhe"].get("Situação de Contratação Atual")
                    or prop.get("situacao") or "")
            if page_auth is not None and _RE_CLAUSULA.search(_sit):
                _idp = _id_proposta_from_url(url)
                if _idp:
                    try:
                        sd = await _extrai_clausula_via_instrumento(page_auth, _idp)
                        if sd:
                            prop["detalhe"]["_situacao_detalhe"] = {
                                _clean(k): _clean(v) if isinstance(v, str) else v
                                for k, v in sd.items()
                            }
                    except Exception as e:
                        logger.warning(f"    clausula {prop['numero_proposta']}: {str(e)[:90]}")
            if det.get("_parlamentar") or prop["detalhe"].get("_situacao_detalhe"):
                _enr += 1
        except Exception as e:
            logger.warning(f"    detalhe {prop['numero_proposta']}: {str(e)[:80]}")
    logger.info(f"  {mun['nome']}: enrich concluido — {_enr}/{_tot} propostas enriquecidas")
    return propostas


async def _extrai_situacao_detalhe(page) -> dict:
    """Pagina de detalhe da Situacao de Contratacao Atual (qualquer tipo).
    Captura todos os pares label:valor de forma generica, ignorando linhas
    de cabecalho/rodape e celulas vazias. Funciona para Clausula Suspensiva,
    Liminar Judicial, Pendencia etc."""
    return await page.evaluate("""() => {
        const out = {};
        document.querySelectorAll('tr').forEach(tr => {
            const tds = [...tr.querySelectorAll('td,th')].map(c => c.innerText.trim());
            if (tds.length === 2) {
                const k = tds[0]; const v = tds[1];
                if (k && v && k.length < 80 && v.length < 600 && !out[k]) out[k] = v;
            } else if (tds.length === 4) {
                for (const i of [0, 2]) {
                    const k = tds[i]; const v = tds[i + 1];
                    if (k && v && k.length < 80 && v.length < 600 && !out[k]) out[k] = v;
                }
            }
        });
        return out;
    }""")


_RE_CLAUSULA = re.compile(r"cl[áa]usula|suspensiv|liminar", re.I)

# Botao "Detalhar Clausula Suspensiva/Liminar Judicial" na tela do INSTRUMENTO
# (EditarDadosProposta.do). E um submit Struts (setaAcao(...)), gated pela
# funcionalidade EXECUCAO_DETALHAR_CLAUSULA_SUSPENSIVA -> so renderiza logado.
_CLAUSULA_BTN_SELECTORS = [
    "css=input[name='editarDadosPropostaDetalharPropostaDetalharClausulaSuspensivaForm']",
    "css=input[onclick*='DetalharClausulaSuspensiva' i]",
    "css=input[onclick*='ClausulaSuspensiva' i], a[onclick*='ClausulaSuspensiva' i]",
    "xpath=//input[contains(@value,'etalhar') and (contains(@value,'láusula') "
    "or contains(@value,'uspensiva') or contains(@value,'iminar'))]",
]


def _id_proposta_from_url(url: str) -> str | None:
    """Extrai idProposta=NNN da URL de detalhe (guest) p/ navegar o instrumento."""
    if not url:
        return None
    m = re.search(r"[?&]idProposta=(\d+)", url)
    return m.group(1) if m else None


async def _extrai_clausula_via_instrumento(page_auth, id_proposta: str) -> dict | None:
    """Captura motivo + data prevista da Clausula Suspensiva (ou Liminar).

    FLUXO CONFIRMADO ao vivo (sessao gov.br viva + conta com acesso ao
    instrumento). O botao NAO existe na pagina de detalhe da proposta — fica na
    tela do INSTRUMENTO:
      1) ResultadoDaConsultaDePropostaDetalharProposta.do?idProposta=ID  (seta contexto)
      2) ForwardAction.do ... MostraPrincipalEditarDadosProposta.do      (abre instrumento)
      3) clica 'Detalhar Clausula Suspensiva/Liminar Judicial' (submit Struts setaAcao)
      4) le os pares label:valor de /voluntarias/execucao/DetalharClausulaSuspensiva

    Retorna {'Situacao Atual do Contrato':..., 'Data prevista...':..., 'Motivo...':...}
    ou None (conta sem acesso ao instrumento, ou instrumento sem clausula)."""
    base = "https://discricionarias.transferegov.sistema.gov.br/voluntarias"
    det_url = (f"{base}/ConsultarProposta/ResultadoDaConsultaDePropostaDetalharProposta.do"
               f"?idProposta={id_proposta}&")
    fwd_url = (f"{base}/ForwardAction.do?modulo=Principal"
               f"&path=/MostraPrincipalEditarDadosProposta.do")
    if not await _goto_with_retry(page_auth, det_url, timeout=40000):
        return None
    await page_auth.wait_for_timeout(1500)
    if not await _goto_with_retry(page_auth, fwd_url, timeout=40000):
        return None
    await page_auth.wait_for_timeout(3500)
    btn = None
    for sel in _CLAUSULA_BTN_SELECTORS:
        try:
            cand = page_auth.locator(sel).first
            if await cand.count() > 0:
                btn = cand
                break
        except Exception:
            continue
    if btn is None:
        return None
    try:
        await btn.click(timeout=8000)
        # submit Struts navega na MESMA pagina -> espera a tela de execucao
        try:
            await page_auth.wait_for_url("**/DetalharClausulaSuspensiva**", timeout=15000)
        except Exception:
            try:
                await page_auth.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
        await page_auth.wait_for_timeout(1500)
    except Exception:
        return None
    sd = await _extrai_situacao_detalhe(page_auth)
    return sd or None


async def _extrai_parlamentar(page) -> str | None:
    """Tenta extrair parlamentar/autor da indicacao. Combina abordagens:
      1) Procura em <tr> com 2 ou 4 celulas (label-valor)
      2) Procura em texto livre por varios padroes
      3) Tenta seguir botao 'Histórico de Indicações' / 'Indicações Parlamentares'
         na pagina de detalhe, se aparecer (best-effort, ignora se nao houver)."""
    parl = await page.evaluate("""() => {
        const LABELS = [
            'Autor da Emenda', 'Parlamentar', 'Nome do Autor', 'Indica',
            'Nome do Parlamentar', 'Autor', 'Indicado por',
            'Parlamentar Indicador', 'Beneficiario da Emenda',
        ];
        const cleanVal = (v) => {
            v = (v || '').replace(/\\s+/g, ' ').trim();
            if (!v) return null;
            if (v.length < 5 || v.length > 200) return null;
            // descarta sentinelas e valores nao-nome
            if (/^(numero|data|valor|tipo|sim|n[ãa]o|n[/.]\\s*a|\\-+|0+)$/i.test(v)) return null;
            // descarta datas (DD/MM/YYYY) e numeros puros
            if (/^\\d{1,2}\\/\\d{1,2}\\/\\d{2,4}$/.test(v)) return null;
            if (/^[\\d.,\\s]+$/.test(v)) return null;
            // descarta funcional programatica e codigos longos sem espaco
            if (/^\\d{6,}/.test(v)) return null;
            // exige PELO MENOS 2 palavras com letras (nomes proprios tem nome+sobrenome)
            const palavras = v.split(/\\s+/).filter(w => /[A-Za-zÀ-ú]{2,}/.test(w));
            if (palavras.length < 2) return null;
            // exige pelo menos uma letra maiuscula (nome proprio)
            if (!/[A-ZÀ-Ú]/.test(v)) return null;
            return v;
        };

        // 1) Tabelas label:valor
        const trs = [...document.querySelectorAll('tr')];
        for (const tr of trs) {
            const tds = [...tr.querySelectorAll('td,th')].map(c => c.innerText.trim());
            if (tds.length === 2 && LABELS.some(l => tds[0].toLowerCase().includes(l.toLowerCase()))) {
                const v = cleanVal(tds[1]);
                if (v) return v;
            } else if (tds.length === 4) {
                for (const i of [0, 2]) {
                    if (LABELS.some(l => tds[i].toLowerCase().includes(l.toLowerCase()))) {
                        const v = cleanVal(tds[i+1]);
                        if (v) return v;
                    }
                }
            }
        }

        // 2) Texto livre (regex)
        const txt = document.body.innerText;
        const patterns = [
            /Autor\\s+da\\s+Emenda\\s*[:\\n]\\s*([^\\n]{3,120})/i,
            /Parlamentar(?:\\s+Indicador)?\\s*[:\\n]\\s*([^\\n]{3,120})/i,
            /Nome\\s+do\\s+(?:Autor|Parlamentar)\\s*[:\\n]\\s*([^\\n]{3,120})/i,
            /Indica[çc][ãa]o\\s+Parlamentar\\s*[:\\n]\\s*([^\\n]{3,120})/i,
            /Indicado\\s+por\\s*[:\\n]\\s*([^\\n]{3,120})/i,
            /Benefici[áa]rio\\s+da\\s+Emenda\\s*[:\\n]\\s*([^\\n]{3,120})/i,
        ];
        for (const re of patterns) {
            const m = txt.match(re);
            if (m) {
                const v = cleanVal(m[1]);
                if (v) return v;
            }
        }
        return null;
    }""")
    if parl:
        return parl
    # Fallback: tenta clicar em "Histórico de Indicações" / "Emendas"
    try:
        link = page.locator(
            "xpath=//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'indica')] | "
            "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'emenda')]"
        ).first
        if await link.count() > 0:
            href = await link.get_attribute("href")
            if href and "javascript" not in href.lower():
                cur = page.url
                await page.goto(href, timeout=30000, wait_until="domcontentloaded")
                await page.wait_for_timeout(2500)
                p2 = await page.evaluate("""() => {
                    const trs=[...document.querySelectorAll('tr')];
                    for (const tr of trs) {
                        const tds=[...tr.querySelectorAll('td,th')].map(c=>c.innerText.trim());
                        // procura linha que comece com nome de parlamentar
                        for (const t of tds) {
                            const m = t.match(/(?:Deputad[oa]|Senador[a]?|Vereador[a]?|Dr\\.|Dra\\.)\\s+([A-Z][A-ZÀ-Úa-zà-ú\\s'.-]{4,80})/i);
                            if (m) return m[0].trim();
                        }
                    }
                    return null;
                }""")
                await page.goto(cur, timeout=30000, wait_until="domcontentloaded")
                await page.wait_for_timeout(1500)
                if p2:
                    return p2
    except Exception:
        pass
    return None


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
        // Botao "Detalhar Clausula Suspensiva/Liminar Judicial".
        // Busca na PAGINA INTEIRA (nao so numa linha especifica) qualquer
        // anchor/button cujo onclick/href/texto aponte para o detalhe da
        // CLAUSULA SUSPENSIVA (ou liminar judicial). Ignora "Detalhar" generico
        // de habilitacao etc. Extrai a URL do onclick (location.href='...').
        try {
            const extractUrl = (el) => {
                let url = el.href || '';
                if (!url || url.toLowerCase().startsWith('javascript')) {
                    const oc = el.getAttribute('onclick') || '';
                    // location.href='...'  ou  window.location='...'
                    const m = oc.match(/(?:location\\.href|window\\.location)\\s*=\\s*['"]([^'"]+)['"]/i)
                            || oc.match(/['"]([^'"]*Detalhar[^'"]*)['"]/i);
                    if (m) {
                        url = m[1];
                        if (!url.startsWith('http')) {
                            url = (url.startsWith('/') ? location.origin : location.origin + '/voluntarias/execucao/') + url.replace(/^\\//, '');
                        }
                    }
                }
                return url;
            };
            const isClausula = (s) => /clausula|cláusula|suspensiva|liminar/i.test(s || '');
            const cands = [...document.querySelectorAll('a, input[type="button"], button')];
            let chosen = null;
            // 1) prioridade: onclick/href aponta p/ DetalharClausulaSuspensiva
            for (const el of cands) {
                const oc = (el.getAttribute('onclick') || '') + ' ' + (el.href || '');
                if (/detalharclausulasuspensiva|clausulasuspensiva|liminarjudicial/i.test(oc)) { chosen = el; break; }
            }
            // 2) fallback: texto "Detalhar ... Clausula/Suspensiva/Liminar"
            if (!chosen) {
                for (const el of cands) {
                    const t = (el.value || el.innerText || '').trim();
                    if (/detalhar/i.test(t) && isClausula(t)) { chosen = el; break; }
                }
            }
            // 3) fallback final: dentro de uma linha que mencione contratacao + clausula
            if (!chosen) {
                const row = [...document.querySelectorAll('tr')].find(tr =>
                    isClausula(tr.innerText) && /detalhar/i.test(tr.innerText));
                if (row) chosen = row.querySelector('a, input[type="button"], button');
            }
            if (chosen) {
                const url = extractUrl(chosen);
                const label = (chosen.value || chosen.innerText || '').trim();
                if (url && /detalhar|clausula|suspensiva|liminar/i.test(url + label)) {
                    out['_situacao_det_url'] = url;
                    if (label) out['_situacao_det_label'] = label.slice(0, 80);
                }
            }
        } catch (e) { /* ignore */ }
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
        situacao_contr = g("Situação de Contratação Atual")
        parlamentar = g("_parlamentar")
        # Detalhe generico da situacao de contratacao (qualquer tipo)
        sd = det.get("_situacao_detalhe") if isinstance(det.get("_situacao_detalhe"), dict) else {}
        sit_det_json = sd if sd else None
        # Deriva campos especificos de Clausula Suspensiva quando aplicavel
        cl_dt = None
        cl_motivo = None
        if sd:
            import re as _re
            from datetime import datetime as _dt
            for k, v in sd.items():
                if not isinstance(v, str):
                    continue
                kl = k.lower()
                if ("data" in kl and "prevista" in kl) or ("prazo" in kl):
                    m = _re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", v.strip())
                    if m:
                        try:
                            cl_dt = _dt(int(m.group(3)), int(m.group(2)), int(m.group(1))).date()
                        except (ValueError, TypeError):
                            pass
                elif "motivo" in kl:
                    cl_motivo = v.strip() or None
        cur.execute("""
            INSERT INTO transferegov_propostas
                (municipio_id, numero_proposta, situacao, orgao, proponente,
                 possui_parecer, identificacao, codigo_instrumento, modalidade,
                 situacao_siafi, numero_processo, objeto, programa,
                 dt_inicio_vigencia, dt_fim_vigencia, dt_proposta, dt_assinatura,
                 valor_global, valor_repasse, valor_contrapartida,
                 situacao_contratacao, clausula_suspensiva_dt_prevista,
                 clausula_suspensiva_motivo, parlamentar, situacao_contratacao_detalhe,
                 id_proposta_siconv, detalhe, raw_data, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s::jsonb,NOW())
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
                situacao_contratacao=COALESCE(EXCLUDED.situacao_contratacao, transferegov_propostas.situacao_contratacao),
                clausula_suspensiva_dt_prevista=COALESCE(EXCLUDED.clausula_suspensiva_dt_prevista, transferegov_propostas.clausula_suspensiva_dt_prevista),
                clausula_suspensiva_motivo=COALESCE(EXCLUDED.clausula_suspensiva_motivo, transferegov_propostas.clausula_suspensiva_motivo),
                parlamentar=COALESCE(EXCLUDED.parlamentar, transferegov_propostas.parlamentar),
                situacao_contratacao_detalhe=COALESCE(EXCLUDED.situacao_contratacao_detalhe, transferegov_propostas.situacao_contratacao_detalhe),
                id_proposta_siconv=COALESCE(EXCLUDED.id_proposta_siconv, transferegov_propostas.id_proposta_siconv),
                detalhe=EXCLUDED.detalhe, raw_data=EXCLUDED.raw_data, updated_at=NOW()
        """, (mun_id, p["numero_proposta"][:20], p["situacao"][:300], p["orgao"][:300],
              p["proponente"][:300], p["possui_parecer"][:10], p["identificacao"][:30],
              (codigo_instr or "")[:30] or None, (modalidade or "")[:100] or None,
              (situacao_siafi or "")[:200] or None, (num_processo or "")[:50] or None,
              objeto, (programa or "")[:300] or None,
              (dt_ini_vig or "")[:20] or None, (dt_fim_vig or "")[:20] or None,
              (dt_prop or "")[:20] or None, (dt_assin or "")[:20] or None,
              valor_global, valor_repasse, valor_contrap,
              (situacao_contr or "")[:100] or None, cl_dt, cl_motivo,
              (parlamentar or "")[:200] or None,
              json.dumps(sit_det_json, ensure_ascii=False) if sit_det_json else None,
              (p.get("id_proposta_siconv") or None),
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
        # Contexto GUEST (sem cookies): listagem via Acesso Livre
        ctx_guest = await browser.new_context(ignore_https_errors=True, user_agent="Mozilla/5.0 Chrome/131")
        page_guest = await ctx_guest.new_page()
        # GUEST-ONLY: a Cláusula Suspensiva (situação + motivo + data) agora vem do
        # OPEN DATA (siconv_convenio_backfill), então NÃO usamos mais a sessão
        # autenticada gov.br aqui. Isso elimina a dependência de re-captura
        # (reCAPTCHA) e acelera o scrape (sem navegar o instrumento por proposta).
        govbr_cks = None
        page_auth = None
        if govbr_cks:  # desativado de propósito (guest-only) — bloco abaixo nunca roda
            # Carrega cookies originais (com expiration) para checar validade.
            # Auth do scraper usa principalmente JSESSIONID de discricionarias
            # (capturado quando user faz bookmarklet em /voluntarias/...).
            # user-id JWT do parcerias eh OPCIONAL (so usado pra extracoes
            # adicionais no parcerias). Pula auth APENAS se NAO tiver
            # JSESSIONID de discricionarias E o user-id estiver expirado.
            try:
                import psycopg2 as _pg
                _u = os.getenv("DATABASE_URL_SYNC","").replace("&channel_binding=require","").replace("?channel_binding=require","")
                _c = _pg.connect(_u); _cur = _c.cursor()
                _cur.execute("SELECT senha_hash FROM cofre_senhas WHERE automation_key IN ('govbr','siconv_legado') "
                             "AND length(senha_hash) > 1000 ORDER BY updated_at DESC")
                _all = _cur.fetchall(); _cur.close(); _c.close()
                from services import crypto as _crypto
                has_discric_session = False
                best_jwt_mins = float("-inf")
                for _row in _all:
                    _data = json.loads(_crypto.decrypt(_row[0]))
                    cks = _data.get("cookies", [])
                    if any('discricionarias' in (c.get('domain','') or '') and c.get('name')=='JSESSIONID' for c in cks):
                        has_discric_session = True
                    jm = _jwt_minutos_restantes(cks)
                    if jm > best_jwt_mins: best_jwt_mins = jm
                logger.info(f"  auth status: JSESSIONID-discric={has_discric_session} | user-id JWT={best_jwt_mins:+.1f}min")
                if not has_discric_session and best_jwt_mins <= 1:
                    logger.warning("  sem JSESSIONID e JWT expirado — pulando auth, indo direto guest")
                    govbr_cks = None
            except Exception as e:
                logger.warning(f"  nao validou sessao: {e}")
        if govbr_cks:
            try:
                ctx_auth = await browser.new_context(ignore_https_errors=True, user_agent="Mozilla/5.0 Chrome/131")
                await ctx_auth.add_cookies(govbr_cks)
                page_auth = await ctx_auth.new_page()
                logger.info(f"  contexto AUTH criado com {len(govbr_cks)} cookies SSO")
            except Exception as e:
                logger.warning(f"  falha ao criar contexto AUTH: {e}")
                page_auth = None
        else:
            logger.info("  sem sessao gov.br valida, detalhes em guest")
        for mun in municipios:
            try:
                # Listagem SEMPRE guest (Acesso Livre). Com sessao viva, o
                # detalhe da Clausula Suspensiva (motivo+data) e capturado via
                # page_auth navegando o instrumento. Sem sessao: so o status.
                props = await _scrape_municipio(page_guest, mun, page_auth=page_auth)
                n = _upsert(mun["id"], props)
                logger.info(f"  {mun['nome']}: {len(props)} propostas -> {n} upsert")
                total += n
            except Exception as e:
                logger.error(f"  {mun['nome']}: ERRO {str(e)[:200]}")
        await browser.close()
    logger.info(f"=== Finalizado: {total} propostas ===")
    # Backfill do parlamentar (autor da emenda) via open data SICONV. O scraper
    # ja gravou id_proposta_siconv acima, entao aqui so baixa o arquivo barato
    # (siconv_emenda ~7.6 MB) e casa id->NOME_PARLAMENTAR. Best-effort.
    try:
        from ingestion import siconv_emenda_backfill as _bf
        # SO o passo barato (7.6 MB). O id_proposta_siconv vem do scraper acima;
        # backfill_ids (199 MB) e' so manual/one-time (evita download recorrente
        # por causa de propostas sem link de detalhe). no Railway = sem cache.
        npb = _bf.backfill_parlamentar(use_cache=False)
        logger.info(f"  backfill parlamentar: {npb} linha(s) atualizadas")
    except Exception as e:
        logger.warning(f"  backfill parlamentar falhou: {str(e)[:160]}")
    # Backfill SITUACAO DE CONTRATACAO + CLAUSULA SUSPENSIVA via OPEN DATA
    # (siconv_convenio) — substitui a dependencia da sessao gov.br autenticada.
    # Assim o detalhe da clausula (motivo + data prevista) atualiza sozinho, sem
    # re-captura/reCAPTCHA.
    try:
        from ingestion import siconv_convenio_backfill as _cb
        ncl = _cb.backfill(use_cache=False)
        logger.info(f"  backfill clausula/contratacao: {ncl} linha(s) atualizadas")
    except Exception as e:
        logger.warning(f"  backfill clausula falhou: {str(e)[:160]}")
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


async def run_one(municipio_id: int):
    """Versao test: roda so para um municipio (debug)."""
    from playwright.async_api import async_playwright
    muns = [m for m in _municipios_pacta() if m["id"] == municipio_id]
    if not muns:
        logger.error(f"municipio_id={municipio_id} nao encontrado")
        return
    mun = muns[0]
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--ignore-certificate-errors", "--no-sandbox"])
        ctx_guest = await browser.new_context(ignore_https_errors=True, user_agent="Mozilla/5.0 Chrome/131")
        page_guest = await ctx_guest.new_page()
        govbr_cks = _load_govbr_cookies()
        page_auth = None
        # Auth eh por JSESSIONID de discricionarias (capturado via bookmarklet
        # em /voluntarias/...) OU user-id JWT do parcerias. Pula auth APENAS
        # se nenhum estiver valido.
        if govbr_cks:
            try:
                import psycopg2 as _pg
                _u = os.getenv("DATABASE_URL_SYNC","").replace("&channel_binding=require","").replace("?channel_binding=require","")
                _c = _pg.connect(_u); _cur = _c.cursor()
                _cur.execute("SELECT senha_hash FROM cofre_senhas WHERE automation_key IN ('govbr','siconv_legado') "
                             "AND length(senha_hash) > 1000 ORDER BY updated_at DESC")
                _all = _cur.fetchall(); _cur.close(); _c.close()
                from services import crypto as _crypto
                has_discric_session = False
                best_jwt_mins = float("-inf")
                for _row in _all:
                    _data = json.loads(_crypto.decrypt(_row[0]))
                    cks = _data.get("cookies", [])
                    if any('discricionarias' in (c.get('domain','') or '') and c.get('name')=='JSESSIONID' for c in cks):
                        has_discric_session = True
                    jm = _jwt_minutos_restantes(cks)
                    if jm > best_jwt_mins: best_jwt_mins = jm
                logger.info(f"  auth: JSESSIONID-discric={has_discric_session} | user-id JWT={best_jwt_mins:+.1f}min")
                if not has_discric_session and best_jwt_mins <= 1:
                    logger.warning("  sem JSESSIONID e JWT expirado — pulando auth")
                    govbr_cks = None
            except Exception as e:
                logger.warning(f"  nao validou sessao: {e}")
        if govbr_cks:
            ctx_auth = await browser.new_context(ignore_https_errors=True, user_agent="Mozilla/5.0 Chrome/131")
            await ctx_auth.add_cookies(govbr_cks)
            page_auth = await ctx_auth.new_page()
            logger.info(f"  contexto AUTH criado com {len(govbr_cks)} cookies SSO")
        try:
            props = await _scrape_municipio(page_guest, mun, page_auth=page_auth)
            n = _upsert(mun["id"], props)
            logger.info(f"{mun['nome']}: {len(props)} propostas -> {n} upsert")
            com_parl = sum(1 for p in props if (p.get("detalhe") or {}).get("_parlamentar"))
            com_sit_det = sum(1 for p in props if (p.get("detalhe") or {}).get("_situacao_detalhe"))
            logger.info(f"  ENRICH: parlamentar={com_parl} sit_det={com_sit_det}")
        finally:
            await browser.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        asyncio.run(run_one(int(sys.argv[1])))
    else:
        asyncio.run(run())
