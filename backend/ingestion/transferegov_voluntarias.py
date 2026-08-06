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


def _propostas_sem_historico(municipio_id: int) -> set:
    """Retorna numero_proposta das que AINDA NAO tem Historico de Comunicacoes.
    Usado para priorizar: cada rodada gasta o orcamento nas pendentes primeiro,
    entao o conjunto converge em alguns dias em vez de recapturar sempre as mesmas."""
    try:
        import psycopg2
        url = os.getenv("DATABASE_URL_SYNC", "").replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        conn = psycopg2.connect(url); cur = conn.cursor()
        cur.execute(
            "SELECT numero_proposta FROM transferegov_propostas "
            "WHERE municipio_id=%s AND historico_atualizado_em IS NULL",
            (municipio_id,)
        )
        out = {r[0] for r in cur.fetchall()}
        cur.close(); conn.close()
        return out
    except Exception:
        return set()


def _propostas_ops_obs_frescas(municipio_id: int, max_age_days: int = 3) -> set:
    """numero_proposta cujo ops_obs/obras foi checado ha menos de max_age_days.
    Usado p/ PULAR a re-navegacao no cron: cada instrumento e navegado no portal
    (~caro); sem skip, TODOS os ~3161 re-navegam toda rodada. Com skip, so os
    novos/vencidos navegam. Se a coluna ainda nao existe (migration nao rodou),
    o except devolve set() vazio -> tudo navega (fallback seguro)."""
    try:
        import psycopg2
        url = os.getenv("DATABASE_URL_SYNC", "").replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        conn = psycopg2.connect(url); cur = conn.cursor()
        cur.execute(
            "SELECT numero_proposta FROM transferegov_propostas "
            "WHERE municipio_id=%s AND ops_obs_atualizado_em IS NOT NULL "
            "AND ops_obs_atualizado_em > NOW() - make_interval(days => %s)",
            (municipio_id, max_age_days)
        )
        out = {r[0] for r in cur.fetchall()}
        cur.close(); conn.close()
        return out
    except Exception:
        return set()


def _stamp_ops_obs(municipio_id: int, numero_proposta: str) -> None:
    """Carimba ops_obs_atualizado_em=NOW() (checagem feita, MESMO vazia) num UPDATE
    isolado — NAO no INSERT do _upsert — p/ a proposta sair do backlog de ops_obs.
    Marcar tb as vazias e o que evita re-navegar os ~2900 sem ops_obs toda rodada."""
    try:
        import psycopg2
        url = os.getenv("DATABASE_URL_SYNC", "").replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        conn = psycopg2.connect(url); cur = conn.cursor()
        cur.execute(
            "UPDATE transferegov_propostas SET ops_obs_atualizado_em=NOW() "
            "WHERE municipio_id=%s AND numero_proposta=%s",
            (municipio_id, numero_proposta[:20])
        )
        conn.commit(); cur.close(); conn.close()
    except Exception:
        pass


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
    # Aguarda o banner de paginacao (.pagelinks) renderizar. Sem isso, as vezes
    # a 1a leitura pega a grid (20 linhas) ANTES dos controles de paginacao ->
    # o loop nao acha "proxima"/total e para na pagina 1 (subestima o total).
    try:
        await page.wait_for_selector(".pagelinks", timeout=15000)
        await page.wait_for_timeout(1200)
    except Exception:
        pass

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

    # Modo rapido (re-run "carregar todos"): pula o enrich por-proposta (lento,
    # ~2.5s cada). As linhas-base (numero, situacao, orgao, proponente, parecer,
    # CNPJ) sao gravadas mesmo assim; o detalhe (valores/objeto/parlamentar) e
    # preenchido depois pelo cron diario. O detalhe ja existente e preservado
    # (upsert usa COALESCE). Mantemos id_proposta_siconv pois vem so da URL.
    if os.getenv("TG_SKIP_ENRICH") == "1":
        for prop in propostas:
            _u = prop.pop("_detalhe_url", None)
            _idp = _id_proposta_from_url(_u) if _u else None
            if _idp:
                prop["id_proposta_siconv"] = _idp
        logger.info(f"  {mun['nome']}: enrich pulado (TG_SKIP_ENRICH=1) — {len(propostas)} propostas base")
        return propostas

    # Enriquece cada proposta com o detalhe (Dados da Proposta).
    # Listagem e detalhe rodam na MESMA page (mesma sessao). Quando is_auth,
    # os links de detalhe sao logados → renderizam o botao Detalhar Clausula
    # Suspensiva + campos gated (parlamentar).
    # OTIMIZACAO: quando auth, prioriza propostas SEM enrich (janela curta).
    detail_page = page
    # Orçamento de capturas de Histórico por execução. Cada captura navega a área
    # /private/ das mandatárias (~12s); sem teto, as 3152 propostas do Freitas
    # dariam ~10h por rodada — inviável no host de 2 vCPU compartilhado. Com teto
    # + priorização das que ainda não têm histórico, cada rodada avança um naco e
    # o conjunto converge em poucos dias. 0 desliga a captura.
    try:
        _hist_budget = max(0, int(os.getenv("TRANSFEREGOV_HISTORICO_MAX", "15") or "15"))
    except ValueError:
        _hist_budget = 15
    if page_auth is not None:
        try:
            _ja_enriquecidos = _propostas_ja_enriquecidas(mun["id"])
            _sem_hist = _propostas_sem_historico(mun["id"])
            # Ordena por (sem enrich, sem histórico): as duas pendências vêm primeiro.
            propostas.sort(key=lambda p: (
                0 if p["numero_proposta"] not in _ja_enriquecidos else 1,
                0 if p["numero_proposta"] in _sem_hist else 1,
            ))
            n_pend = sum(1 for p in propostas if p["numero_proposta"] not in _ja_enriquecidos)
            n_hist = sum(1 for p in propostas if p["numero_proposta"] in _sem_hist)
            logger.info(f"  {mun['nome']}: {n_pend} propostas SEM enrich serao priorizadas | "
                        f"{n_hist} sem historico (orcamento desta rodada: {_hist_budget})")
        except Exception:
            pass
    # Skip incremental de ops_obs/obras: precomputa quais propostas ja foram
    # checadas recentemente (nao re-navegar). E GUEST, entao independe de page_auth.
    _ops_obs_on = (os.getenv("TG_OPS_OBS", "0") or "0").strip() == "1"
    try:
        _ops_obs_max_age = max(0, int(os.getenv("TG_OPS_OBS_MAX_AGE_DAYS", "3") or "3"))
    except ValueError:
        _ops_obs_max_age = 3
    _ops_obs_frescas = _propostas_ops_obs_frescas(mun["id"], _ops_obs_max_age) if _ops_obs_on else set()
    # ENRICH POR HTTP (TG_HTTP_ENRICH=1): mesmos dados sem Chromium — ~4s por
    # instrumento em vez de ~22s (validado campo-a-campo contra o browser). O
    # cliente e STATEFUL (contexto do convenio no servidor) -> um por municipio,
    # usado sequencialmente. Falha ao criar = segue no browser (fallback).
    _hx = None
    if (os.getenv("TG_HTTP_ENRICH", "0") or "0").strip() == "1":
        try:
            from ingestion.transferegov_http import TgHttpEnrich
            _hx = TgHttpEnrich(_load_govbr_cookies())
            logger.info(f"  {mun['nome']}: enrich via HTTP (sem browser)")
        except Exception as e:
            logger.warning(f"  {mun['nome']}: HTTP enrich indisponivel ({str(e)[:60]}) — usando browser")
            _hx = None
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
            await detail_page.wait_for_timeout(700)  # perf: Struts server-rendered (HTML pronto no domcontentloaded)
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
            # Processo de Execução (Licitações) — SÓ p/ contratação "Normal".
            # Convênio Normal em execução SEM licitação/processo registrado =
            # município parado (flag de monitoramento, destacado igual à cláusula).
            # Funciona em GUEST (detail_page já está no detalhe = contexto setado).
            if _idp and "normal" in _sit.lower():
                try:
                    _qtd = (await asyncio.to_thread(_hx.processo_execucao, _idp)) if _hx \
                        else (await _conta_processo_execucao(detail_page))
                    if _qtd is not None:
                        prop["processo_execucao_qtd"] = _qtd
                except Exception as e:
                    logger.warning(f"    proc.exec {prop['numero_proposta']}: {str(e)[:80]}")
            # OPs/OBs (repasses/desembolsos) e OBRAS (acompanhamento/medicao).
            # Ambas GUEST (nao exigem sessao gov.br), mas cada uma navega o portal
            # por instrumento (~alguns s) — pesado no host burstable. Por isso a
            # coleta e ligada por env TG_OPS_OBS=1, hoje so no siao-worker
            # (ativado so p/ SIAO; os demais tenants nao gastam CPU com isto).
            if _idp and _ops_obs_on and prop["numero_proposta"] not in _ops_obs_frescas:
                try:
                    _oo = (await asyncio.to_thread(_hx.ops_obs, _idp)) if _hx \
                        else (await _extrai_ops_obs(detail_page))
                    if _oo is not None:
                        prop["ops_obs"] = _oo
                except Exception as e:
                    logger.warning(f"    ops_obs {prop['numero_proposta']}: {str(e)[:80]}")
                try:
                    _ob = (await asyncio.to_thread(_hx.obras, _idp)) if _hx \
                        else (await _extrai_obras(detail_page, _idp))
                    if _ob is not None:
                        prop["obras"] = _ob
                except Exception as e:
                    logger.warning(f"    obras {prop['numero_proposta']}: {str(e)[:80]}")
                # Carimba a checagem (mesmo vazia) -> sai do backlog, nao re-navega toda rodada.
                _stamp_ops_obs(mun["id"], prop["numero_proposta"])
            # Historico de Comunicacoes + Termos de Notificacao (Projeto Basico /
            # mandatarias). SO com sessao gov.br viva (area /private/).
            if page_auth is not None and _idp and _hist_budget > 0:
                try:
                    # Debita o orçamento na TENTATIVA, não no sucesso: o custo de
                    # tempo já foi pago mesmo quando a página não devolve dados.
                    _hist_budget -= 1
                    _hc = (await asyncio.to_thread(_hx.historico, _idp)) if _hx \
                        else (await _captura_historico_comunicacoes(page_auth, _idp))
                    if _hc:
                        prop["historico_comunicacoes"] = _hc.get("historico") or []
                        prop["documentos_quadro_resumo"] = _hc.get("documentos") or []
                    if _hc is not None:
                        # Sessao viva e pagina /private/ consultada, MESMO sem eventos:
                        # marca como checada p/ sair do backlog e nao re-consumir o
                        # orcamento toda rodada (senao as propostas vazias represam os
                        # slots e o historico nunca converge). _hc None = sessao
                        # morta/erro de navegacao -> continua pendente p/ nova tentativa.
                        prop["_historico_checado"] = True
                except Exception as e:
                    logger.warning(f"    historico {prop['numero_proposta']}: {str(e)[:80]}")
            if det.get("_parlamentar") or prop["detalhe"].get("_situacao_detalhe"):
                _enr += 1
        except Exception as e:
            logger.warning(f"    detalhe {prop['numero_proposta']}: {str(e)[:80]}")
        # Persiste ESTA proposta ja — nao espera o fim do municipio. Assim o
        # progresso parcial sobrevive a um restart do container no meio da coleta:
        # municipios grandes fecham em pedacos, em vez de reiniciar do zero toda vez.
        try:
            _upsert(mun["id"], [prop])
        except Exception as e:
            logger.warning(f"    upsert incremental {prop['numero_proposta']}: {str(e)[:80]}")
    if _hx is not None:
        _hx.close()
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


def _dt_now():
    """Timestamp UTC (marca quando o historico foi capturado)."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


async def _captura_historico_comunicacoes(page_auth, id_proposta: str) -> dict | None:
    """Captura o Historico numa PAGINA FRESCA do mesmo contexto autenticado.

    A page_auth compartilhada/longeva (reusada em navegacoes guest + Clausula do
    discricionarias) NAO estabelecia a sessao mandatarias /private/ no batch e
    todo _captura devolvia None em silencio (historico travava em 64/3160). Uma
    pagina NOVA no mesmo contexto (mesmos cookies, identica a sonda validada ao
    vivo: retorna eventos de forma confiavel) resolve. Fecha a pagina ao fim;
    fallback = usa a propria page_auth. Ver [[freitas-paridade-piloto]]."""
    try:
        pg = await page_auth.context.new_page()
    except Exception:
        return await _captura_historico_impl(page_auth, id_proposta)
    try:
        return await _captura_historico_impl(pg, id_proposta)
    finally:
        try:
            await pg.close()
        except Exception:
            pass


async def _captura_historico_impl(page_auth, id_proposta: str) -> dict | None:
    """Histórico de Comunicações + Documentos do Quadro Resumo (tela "Documentos
    Orçamentários" / Projeto Básico do TransfereGov **mandatárias**).

    Traz o andamento REAL da análise — eventos com SITUAÇÃO e CONSIDERAÇÕES do
    concedente (ex.: "Emitido Laudo de Análise", "Aceite realizado", parecer) —
    e os Termos de Notificação enviados.

    EXIGE sessão gov.br: a área e /private/ (guest cai no login). Retorna
    {'historico': [...], 'documentos': [...]} com eventos, {} se a página abriu
    autenticada porém SEM eventos (checada), ou None se a sessão caiu no login /
    a navegação falhou (não checada -> continua pendente p/ nova tentativa)."""
    url = ("https://mandatarias.transferegov.sistema.gov.br/projeto-basico/private/"
           f"index.jsf?idProposta={id_proposta}")
    if not await _goto_with_retry(page_auth, url, timeout=45000):
        return None
    await page_auth.wait_for_timeout(4000)
    cur_url = (page_auth.url or "")
    if "idp.transferegov" in cur_url or "sso.acesso.gov.br" in cur_url:
        return None  # sessao gov.br ausente/expirada -> caiu no login
    # PEGADINHA: a tela abre noutra aba e o Historico NAO esta no DOM inicial —
    # ele vive sob a aba "Quadro Resumo" (JSF/AJAX). Confirmado ao vivo: sem o
    # clique temHistorico=false/1 tabela; com o clique, true/4 tabelas.
    for _sel in ("a:has-text('Quadro Resumo')", "span:has-text('Quadro Resumo')",
                 "td:has-text('Quadro Resumo')", "li:has-text('Quadro Resumo')"):
        try:
            _tab = page_auth.locator(_sel).first
            if await _tab.count() > 0:
                await _tab.click(timeout=8000)
                await page_auth.wait_for_timeout(3500)
                break
        except Exception:
            continue
    try:
        data = await page_auth.evaluate("""() => {
            const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
            // Identifica a tabela pela ASSINATURA DO CABECALHO (robusto): buscar
            // pelo titulo nao funciona — "Historico de Comunicacoes" nao e um
            // elemento de texto puro no DOM (confirmado ao vivo).
            const tabelas = [...document.querySelectorAll('table')].map(t => {
                const rows = [...t.querySelectorAll('tr')];
                const heads = rows[0]
                    ? [...rows[0].querySelectorAll('th,td')].map(c => norm(c.textContent))
                    : [];
                return { t, rows, heads, chave: heads.join('|').toLowerCase() };
            });
            const acha = (...res) => {
                for (const x of tabelas) {
                    if (x.rows.length < 2) continue;
                    if (res.every(re => re.test(x.chave))) return x;
                }
                return null;
            };
            const ler = (x) => {
                if (!x) return [];
                const out = [];
                for (const r of x.rows.slice(1)) {
                    const cells = [...r.querySelectorAll('td')].map(c => norm(c.textContent));
                    if (!cells.length || cells.every(c => !c)) continue;
                    const o = {};
                    cells.forEach((c, i) => { o[x.heads[i] || ('col' + i)] = c; });
                    out.push(o);
                }
                return out;
            };
            // Historico: Data/Hora + Evento + Situacao + Consideracoes.
            // (exigir situacao+consideracoes exclui a tabela de "Sistema Externo",
            //  que tambem tem Data/Hora+Evento mas traz Resultado/Mensagem)
            const hist = acha(/data.?\\/?\\s?hora/, /evento/, /situa/, /considera/)
                      || acha(/data.?\\/?\\s?hora/, /evento/, /situa/);
            // Documentos do Quadro Resumo: Descricao + Tipo + Data de Envio
            const docs = acha(/descri/, /tipo/, /data de envio/);
            return { historico: ler(hist), documentos: ler(docs) };
        }""")
    except Exception:
        return None
    if not data:
        return None
    if not (data.get("historico") or data.get("documentos")):
        return {}  # pagina viva e consultada, porem SEM eventos -> checada (nao None)
    return data


async def _le_listagem_licitacoes(page) -> int | None:
    """N licitacoes na tela de Processo de Execucao, ou None se INDETERMINADO.

    None nao e "nenhuma": e "nao consegui ler". Quem chama nao deve gravar 0
    nesse caso — 0 vira o alerta de "contratacao Normal sem processo de
    execucao", e um 0 errado mente para o usuario."""
    try:
        return await page.evaluate("""() => {
            const body = document.body.innerText || '';
            if (/Nenhum registro/i.test(body)) return 0;
            const m = body.match(/\\((\\d+)\\s*ite/i);          // "Pagina X de Y (N item(s))"
            if (m) return parseInt(m[1], 10);
            // tabela cujo CABECALHO tem "Processo de Execucao" + Data/Situacao
            for (const t of document.querySelectorAll('table')) {
                const rows = [...t.querySelectorAll('tr')];
                if (!rows.length) continue;
                const heads = [...rows[0].querySelectorAll('th,td')]
                    .map(c => (c.innerText || '').trim().toLowerCase()).join('|');
                if (heads.includes('processo de execu') &&
                    (heads.includes('data da public') || heads.includes('situa'))) {
                    return rows.slice(1).filter(r =>
                        [...r.querySelectorAll('td')].some(c => (c.innerText || '').trim())).length;
                }
            }
            return null;   // indeterminado
        }""")
    except Exception:
        return None


async def _conta_processo_execucao(page) -> int | None:
    """Conta licitações/processos de execução do instrumento (Execução Convenente
    -> Processo de Execução). FUNCIONA EM GUEST (Acesso Livre) — confirmado ao vivo.

    Pré-condição: `page` já está na tela de DETALHE da proposta (o
    ResultadoDaConsultaDePropostaDetalharProposta.do já setou o contexto do
    convênio). Navega para destino=ListarLicitacoes e lê a listagem.

    Retorna: 0 (Nenhum registro — convênio Normal sem processo iniciado, flag),
    N (nº de registros), ou None se não conseguiu navegar/ler."""
    lic_url = ("https://discricionarias.transferegov.sistema.gov.br/voluntarias/"
               "ForwardAction.do?modulo=proposta&path=/SelecionarConvenio/"
               "SelecionarConvenio.do?destino=ListarLicitacoes")
    if not await _goto_with_retry(page, lic_url, timeout=40000):
        return None
    await page.wait_for_timeout(800)
    if not await page.locator("text=/Listagem de Licita|Processo de Execu/i").count():
        return None  # nao chegou na tela certa
    # A tela JA VEM POPULADA. Le daqui ANTES de qualquer submit.
    #
    # Antes o codigo clicava "Consultar" primeiro, na crenca de que a listagem so
    # populava apos o filtro. E o contrario: o submit DESTROI o resultado (volta
    # uma tela curta, sem a tabela) e a proposta virava 0 licitacoes em silencio.
    # Reproduzido no instrumento 993503 (proposta 011147/2026): a tela traz a
    # licitacao 102026, o submit a some, e gravavamos 0 — o alerta "sem processo
    # de execucao" ficava mentindo para o usuario.
    _lido = await _le_listagem_licitacoes(page)
    if _lido is not None:
        return _lido
    # Indeterminado: ai sim tenta o submit do filtro (fallback).
    try:
        btn = page.locator("input[value='Consultar'], button:has-text('Consultar')").first
        if await btn.count() > 0:
            await btn.click(timeout=8000)
            try:
                await page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            await page.wait_for_timeout(300)  # perf: cushion apos networkidle
    except Exception:
        pass
    try:
        return await page.evaluate("""() => {
            const body = document.body.innerText || '';
            if (/Nenhum registro foi encontrado/i.test(body)) return 0;
            // displaytag: "Página X de Y (N item(s))"
            const m = body.match(/\\((\\d+)\\s*ite/i);
            if (m) return parseInt(m[1], 10);
            // linhas da tabela de resultados (exclui cabecalho)
            const t = document.querySelector('table.dataTable, table.listagem, table#listagem');
            if (t) { const r = t.querySelectorAll('tbody tr'); if (r.length) return r.length; }
            return null; // indeterminado -> NAO assume 0 (evita falso flag)
        }""")
    except Exception:
        return None


def _num_br(s):
    """'R$ 2.800.000,00' -> 2800000.0 ; None se não numérico."""
    if s is None:
        return None
    t = re.sub(r"[^\d,.-]", "", str(s)).replace(".", "").replace(",", ".")
    try:
        return float(t) if t not in ("", "-", ".") else None
    except ValueError:
        return None


async def _extrai_ops_obs(page) -> dict | None:
    """OPs/OBs (Execução Concedente -> OPs/OBs -> Listagem de Repasses). GUEST.

    Pré-condição: `page` está no DETALHE da proposta (contexto do convênio setado).
    Lê o resumo (Valor Total de Repasse / Desembolsado / A Desembolsar / Data do
    último desembolso) e, clicando em 'OPs / OBs GERCOMP Efetuadas', as ordens
    bancárias (NS/OP/OB, valor, situação, data). Retorna dict ou None (sem
    contexto / sessão caiu). {} quando o convênio não tem repasses."""
    rep_url = ("https://discricionarias.transferegov.sistema.gov.br/voluntarias/"
               "ForwardAction.do?modulo=proposta&path=/SelecionarConvenio/"
               "SelecionarConvenio.do?destino=ListarRepasses")
    if not await _goto_with_retry(page, rep_url, timeout=40000):
        return None
    await page.wait_for_timeout(800)
    if "idp.transferegov" in (page.url or ""):
        return None
    if not await page.locator("text=/Listagem de Repasses/i").count():
        return None
    resumo = await page.evaluate("""() => {
        for (const t of document.querySelectorAll('table')) {
            if (/Valor Total de Repasse/i.test(t.innerText || '')) {
                const trs = [...t.querySelectorAll('tr')];
                for (const tr of trs) {
                    const c = [...tr.querySelectorAll('td')].map(x => x.innerText.trim());
                    if (c.length >= 4 && /R\\$/.test(c[0])) return c.slice(0, 4);
                }
            }
        }
        return null;
    }""")
    # _num_br roda em Python (page.evaluate devolve só as strings da tabela)
    out = {}
    if resumo:
        out = {
            "valor_total_repasse": _num_br(resumo[0]),
            "valor_desembolsado": _num_br(resumo[1]),
            "valor_a_desembolsar": _num_br(resumo[2]),
            "data_ultimo_desembolso": (resumo[3] or "").strip() or None,
            "obs": [],
        }
    # GERCOMP -> ordens bancárias detalhadas
    try:
        g = page.locator("input[value*='GERCOMP' i], a:has-text('GERCOMP')").first
        if await g.count():
            await g.click(timeout=8000)
            await page.wait_for_timeout(1200)
            det = await page.evaluate("""() => {
                const res = {resumo: {}, obs: []};
                for (const t of document.querySelectorAll('table')) {
                    const txt = t.innerText || '';
                    if (/Valor Previsto/i.test(txt) && /Valor Desembolsado/i.test(txt) && t.querySelectorAll('tr').length <= 4) {
                        for (const tr of t.querySelectorAll('tr')) {
                            const c = [...tr.querySelectorAll('td')].map(x => x.innerText.trim());
                            if (c.length === 2) res.resumo[c[0]] = c[1];
                        }
                    }
                    if (/N[úu]mero da OB/i.test(txt)) {
                        const rows = [...t.querySelectorAll('tr')];
                        for (const tr of rows) {
                            const c = [...tr.querySelectorAll('td')].map(x => x.innerText.trim());
                            if (c.length >= 10 && /\\dOB\\d|OB\\d/i.test(c[3] || '')) {
                                res.obs.push(c);
                            }
                        }
                    }
                }
                return res;
            }""")
            r = det.get("resumo") or {}
            if not out:
                out = {"obs": []}
            out.setdefault("valor_total_repasse", _num_br(r.get("Valor Previsto")))
            if out.get("valor_desembolsado") is None:
                out["valor_desembolsado"] = _num_br(r.get("Valor Desembolsado"))
            if out.get("valor_a_desembolsar") is None:
                out["valor_a_desembolsar"] = _num_br(r.get("Valor a Desembolsar"))
            for c in det.get("obs") or []:
                out["obs"].append({
                    "numero_interno": c[0], "numero_ns": c[1], "numero_op": c[2],
                    "numero_ob": c[3], "ug_emitente": c[4], "gestao_emitente": c[5],
                    "valor": _num_br(c[6]), "valor_acerto": _num_br(c[7]),
                    "situacao": c[8], "data_emissao_ob": c[9],
                })
    except Exception:
        pass
    return out or {}


async def _extrai_obras(page, id_proposta: str) -> dict | None:
    """OBRAS (Acompanhamento de Obras / medicao). Guest — a sessão Acesso Livre
    da discricionarias vale no medicao. Usa a API JSON /medicao-backend/...:
      - propostas/{id}/contratoslotes  -> lotes/CTEF + submetas
      - proposta/{id}/situacaoParalisacao
      - contratos/{idc}                -> dados do contrato + empresa
      - contratos/{idc}/arts/          -> ART/RRT
    Retorna dict com lotes (ou {} sem obras) ou None se não autenticou."""
    med = "https://medicao.transferegov.sistema.gov.br"
    base = f"{med}/medicao/acompanhamento/proposta/{id_proposta}"
    # A API do medicao exige o TOKEN que o SPA injeta (fetch cru dá 403 "sem
    # perfil"). Então NÃO chamamos a API direto: deixamos o próprio SPA chamar e
    # capturamos as respostas JSON via listener. A sessão Acesso Livre da
    # discricionarias autentica o SPA.
    capt: dict = {}

    async def _on_resp(resp):
        u = resp.url
        if "/medicao-backend/" not in u or "integrations" in u:
            return
        try:
            if "json" in (resp.headers.get("content-type") or ""):
                capt[u.split("/medicao-backend")[-1]] = await resp.json()
        except Exception:
            pass

    page.on("response", _on_resp)
    try:
        try:
            await page.goto(base, timeout=55000, wait_until="networkidle")
        except Exception:
            await page.goto(base, timeout=55000, wait_until="domcontentloaded")
        # perf: poll curto ate o /contratoslotes cair no listener, em vez de sleep
        # cego de 4s — apos networkidle o XHR ja costuma ter chegado (sai em <1s).
        for _ in range(20):
            if any("contratoslotes" in k for k in capt):
                break
            await page.wait_for_timeout(200)
        if "idp.transferegov" in (page.url or ""):
            return None  # sessão Acesso Livre não autenticou o medicao

        def _find(sufixo):
            for k, v in capt.items():
                if k.endswith(sufixo) or sufixo in k:
                    return v
            return None

        cl = _find(f"/propostas/{id_proposta}/contratoslotes")
        if not isinstance(cl, dict):
            return None
        data = cl.get("data") or {}

        # ART/RRT: navega a tela artrrt de cada contrato p/ o SPA disparar /arts/
        for cont in (data.get("contratosLotes") or []):
            if cont.get("tipo") == "C" and cont.get("id"):
                art_url = f"{base}/contrato/{cont['id']}/config/artrrt/listar"
                try:
                    await page.goto(art_url, timeout=45000, wait_until="networkidle")
                    await page.wait_for_timeout(1000)  # perf: cushion apos networkidle
                except Exception:
                    pass
    finally:
        page.remove_listener("response", _on_resp)

    par = capt.get(f"/proposta/{id_proposta}/situacaoParalisacao")
    par_desc = ((par or {}).get("data") or {}).get("descricao") if isinstance(par, dict) else None

    lotes = []
    for cont in (data.get("contratosLotes") or []):
        idc = cont.get("id")
        lote = {
            "tipo": cont.get("tipo"), "numero": cont.get("numero"),
            "id_contrato": idc, "apto_iniciar": cont.get("aptoIniciar"),
            "atrasado": cont.get("atrasado"), "paralisado": cont.get("paralisado"),
            "dias_sem_medicao": cont.get("qtdeDiasSemMedicao"),
            "submetas": [{
                "numero": s.get("numero"), "descricao": s.get("descricao"),
                "situacao": s.get("situacao"), "regime_execucao": s.get("regimeExecucao"),
                "valor": s.get("valorSubmeta"), "valor_realizado": s.get("valorRealizadoAcumulado"),
            } for s in (cont.get("submetas") or [])],
            "contrato": None, "arts": [],
        }
        if cont.get("tipo") == "C" and idc:
            cd = capt.get(f"/contratos/{idc}")
            cdd = (cd or {}).get("data") if isinstance(cd, dict) else None
            if cdd:
                emp = None
                fid = cdd.get("fornecedorId")
                if fid:
                    ed = capt.get(f"/empresas/{fid}")
                    emp = ((ed or {}).get("data") or {}).get("razaoSocial") if isinstance(ed, dict) else None
                # O medicao devolve valorContrato como decimal US ("2562000.00"),
                # NÃO no formato BR — float() direto (nada de _num_br aqui).
                vc = cdd.get("valorContrato")
                try:
                    vc = float(vc) if vc not in (None, "") else None
                except (TypeError, ValueError):
                    vc = None
                lote["contrato"] = {
                    "numero": cdd.get("numeroContrato"), "cnpj": cdd.get("cnpj"),
                    "empresa": emp or cdd.get("nomeConvenente"),
                    "objeto": cdd.get("nomeObjetoContratoFornecimento"),
                    "valor": vc,
                    "dt_assinatura": cdd.get("dtAssinatura"),
                    "dt_inicio_vigencia": cdd.get("dtInicioVigencia"),
                    "dt_fim_vigencia": cdd.get("dtFimVigencia"),
                }
            ar = capt.get(f"/contratos/{idc}/arts/") or capt.get(f"/contratos/{idc}/arts")
            ard = (ar or {}).get("data") if isinstance(ar, dict) else None
            for a in (ard or []):
                lote["arts"].append({
                    "tipo": a.get("tipo"), "numero": a.get("numeroArt") or a.get("numero"),
                    "dt_emissao": a.get("dtEmissao"),
                    "responsavel_tecnico": a.get("nomeResponsavelTecnico") or a.get("responsavelTecnico"),
                    "submetas": a.get("submetas"),
                })
        lotes.append(lote)

    if not lotes:
        return {}
    ti = data.get("tipoInstrumento") or {}
    return {
        "situacao_paralisacao": par_desc,
        "valor_total_submetas": data.get("valorTotalSubmetas"),
        "valor_total_realizado": data.get("valorTotalRealizado"),
        "objeto": ti.get("nomeObjetoContratoRepasse"),
        "lotes": lotes,
    }


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
                 id_proposta_siconv, processo_execucao_qtd,
                 historico_comunicacoes, documentos_quadro_resumo, historico_atualizado_em,
                 ops_obs, obras,
                 detalhe, raw_data, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,NOW())
            ON CONFLICT (municipio_id, numero_proposta) DO UPDATE SET
                situacao=EXCLUDED.situacao, orgao=EXCLUDED.orgao,
                proponente=EXCLUDED.proponente, possui_parecer=EXCLUDED.possui_parecer,
                identificacao=EXCLUDED.identificacao,
                codigo_instrumento=EXCLUDED.codigo_instrumento, modalidade=EXCLUDED.modalidade,
                situacao_siafi=EXCLUDED.situacao_siafi, numero_processo=EXCLUDED.numero_processo,
                objeto=CASE WHEN position(chr(65533) in coalesce(EXCLUDED.objeto,'')) > 0
                            THEN transferegov_propostas.objeto ELSE EXCLUDED.objeto END,
                programa=EXCLUDED.programa,
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
                processo_execucao_qtd=COALESCE(EXCLUDED.processo_execucao_qtd, transferegov_propostas.processo_execucao_qtd),
                historico_comunicacoes=COALESCE(EXCLUDED.historico_comunicacoes, transferegov_propostas.historico_comunicacoes),
                documentos_quadro_resumo=COALESCE(EXCLUDED.documentos_quadro_resumo, transferegov_propostas.documentos_quadro_resumo),
                historico_atualizado_em=COALESCE(EXCLUDED.historico_atualizado_em, transferegov_propostas.historico_atualizado_em),
                ops_obs=COALESCE(EXCLUDED.ops_obs, transferegov_propostas.ops_obs),
                obras=COALESCE(EXCLUDED.obras, transferegov_propostas.obras),
                detalhe=COALESCE(EXCLUDED.detalhe, transferegov_propostas.detalhe),
                raw_data=EXCLUDED.raw_data, updated_at=NOW()
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
              p.get("processo_execucao_qtd"),
              (json.dumps(p["historico_comunicacoes"], ensure_ascii=False)
               if p.get("historico_comunicacoes") else None),
              (json.dumps(p["documentos_quadro_resumo"], ensure_ascii=False)
               if p.get("documentos_quadro_resumo") else None),
              (_dt_now() if (p.get("historico_comunicacoes") or p.get("documentos_quadro_resumo")
                             or p.get("_historico_checado")) else None),
              (json.dumps(p["ops_obs"], ensure_ascii=False) if p.get("ops_obs") else None),
              (json.dumps(p["obras"], ensure_ascii=False) if p.get("obras") else None),
              (json.dumps(det, ensure_ascii=False) if det else None), json.dumps(p, ensure_ascii=False)))
        ins += 1
    conn.commit(); cur.close(); conn.close()
    return ins


async def run():
    from playwright.async_api import async_playwright
    municipios = _municipios_pacta()
    logger.info(f"=== TransfereGov Voluntarias: {len(municipios)} municipios ===")

    # CAMADA BASE por DADOS ABERTOS primeiro (HTTP, sem navegador). Preenche a
    # tabela inteira -- valores, situacao, datas, parlamentar, programa -- a
    # partir dos CSVs oficiais. So DEPOIS o navegador entra para a fatia que so
    # existe atras do login (historico de comunicacoes, quadro resumo, processo
    # de execucao). Assim, se o Chromium travar/falhar, a base ja esta completa e
    # atualizada -- em vez do cenario antigo, em que uma falha do navegador
    # deixava TUDO desatualizado. Isolado: um erro aqui nao impede o resto.
    # TG_OPENDATA=0 desliga (volta ao comportamento so-navegador).
    if (os.getenv("TG_OPENDATA", "1") or "1").strip() not in ("0", "false", "no"):
        try:
            from ingestion.transferegov_opendata import run as _open_run
            _open_run()
        except Exception as e:
            logger.warning(f"  camada de dados abertos falhou (segue p/ navegador): {e}")

    total = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--ignore-certificate-errors", "--no-sandbox"])
        ctx_guest = None
        ctx_auth = None
        try:
            # Contexto GUEST (sem cookies): listagem via Acesso Livre
            ctx_guest = await browser.new_context(ignore_https_errors=True, user_agent="Mozilla/5.0 Chrome/131")
            page_guest = await ctx_guest.new_page()
            # A Cláusula Suspensiva vem do OPEN DATA (siconv_convenio_backfill), então
            # por um tempo este run() rodou GUEST-ONLY, com a sessão desligada. Só que
            # o Histórico de Comunicações (add. em 20/07) EXIGE a área /private/: sem
            # sessão ele nunca era capturado pelo cron — apenas por run_one() manual.
            # Com a extensão de captura + govbr_renew (re-deriva via SAML a cada 15min,
            # sem reCAPTCHA), a sessão se mantém sozinha e a coleta pode ser automática.
            # Degrada com segurança: sem sessão válida, cai em guest exatamente como antes.
            # TRANSFEREGOV_AUTH=0 volta ao comportamento guest-only.
            _auth_on = (os.getenv("TRANSFEREGOV_AUTH", "1") or "1").strip() not in ("0", "false", "no")
            govbr_cks = _load_govbr_cookies() if _auth_on else None
            page_auth = None
            if govbr_cks:
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
        finally:
            # Fecha SEMPRE, inclusive em excecao/cancelamento: e este caminho que,
            # sem o finally, deixava Chromium orfao vivo consumindo CPU para sempre.
            for _ctx in (ctx_auth, ctx_guest):
                if _ctx is not None:
                    try:
                        await _ctx.close()
                    except Exception:
                        pass
            try:
                await browser.close()
            except Exception:
                pass
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
    # Selecao PAC / Novo PAC — roda logo apos as voluntarias (usa o CNPJ da
    # prefeitura que as voluntarias acabaram de gravar em transferegov_propostas).
    # Best-effort (browser proprio); nao derruba o cron das voluntarias.
    try:
        from ingestion.transferegov_pac import run as _pac_run
        await _pac_run()
    except Exception as e:
        logger.warning(f"  PAC (apos voluntarias) falhou: {str(e)[:160]}")


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
