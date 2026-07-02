"""
SIGCON-MG scraper via Playwright (portal autenticado).

Usa credencial municipal (CPF + senha de gestor de Convenente cadastrado pela
prefeitura) para acessar a Pesquisa Unificada de Propostas/Planos/Convenios em:

  https://www.convenios.mg.gov.br/sigconv2/pages/GerirPropostaDePlanoDeTrabalho/pesquisaUnificada.jsf

O usuario logado SO ENXERGA convenios em que sua entidade (ex: MUNICIPIO DE ARAUJOS)
e Convenente. Por isso eh necessaria UMA credencial POR municipio alvo.

Pra cada credencial cadastrada no cofre com sistema='SIGCON-MG':
- Login + fecha modal CAGEC
- Pesquisa unificada (Todos os tipos)
- Download CSV (encoding latin-1)
- UPSERT em convenios_estadual com nr_sigcon = nr_siafi (quando existir)
  ou chave sintetica SIGCON-PORTAL-{municipio}-{idx}

Limite CKAN bulk era 27 -> com scraper expandido cobertura aumenta substancialmente
para todos os anos visiveis ao Convenente.

Cron: rodar manualmente ou via tier 'monthly' (run_all.py).
"""
import asyncio
import io
import json
import logging
import os
import sys
import unicodedata
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger("sigcon_scraper")

LOGIN_URL = "https://www.convenios.mg.gov.br/sigconv2/public/pages/login.jsf"
SEARCH_URL = "https://www.convenios.mg.gov.br/sigconv2/pages/GerirPropostaDePlanoDeTrabalho/pesquisaUnificada.jsf"
EMENDAS_URL = "https://www.convenios.mg.gov.br/sigconv2/pages/EmendaParlamentar/pesquisarEmendasPorConvenente.jsf"

# Mapeia status SIGCON pra "Em vigor" / "Encerrado" / etc
STATUS_MAP = {
    "VIGENTE": "Em vigor",
    "PLANO AUTORIZADO": "Plano Autorizado",
    "ENCERRADO": "Encerrado",
    "CANCELADA": "Cancelado",
    "CADASTRAMENTO": "Cadastramento",
    "ANALISE - CHECKLIST DE CELEBRACAO": "Analise Celebracao",
    "ANALISE TECNICA": "Analise Tecnica",
    "PREENCHIMENTO DE CHECKLIST": "Preenchimento Checklist",
}


def _norm(s: str) -> str:
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFKD", s.upper()) if not unicodedata.combining(c))


def _parse_money(s: str) -> Optional[float]:
    if not s or not s.strip():
        return None
    # "R$ 1.000.000,00" -> 1000000.00
    s = s.replace("R$", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(s: str):
    """Primeira data DD/MM/YYYY na string -> datetime.date (ou None)."""
    import re as _re
    from datetime import date as _date
    if not s:
        return None
    m = _re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(s))
    if not m:
        return None
    try:
        return _date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except (ValueError, TypeError):
        return None


def _parse_vigencia_range(s: str):
    """'10/06/2026 a 08/06/2028' -> (date inicio, date fim). 1a e ultima data."""
    import re as _re
    from datetime import date as _date
    if not s:
        return (None, None)
    ds = _re.findall(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(s))
    def _mk(t):
        try:
            return _date(int(t[2]), int(t[1]), int(t[0]))
        except (ValueError, TypeError):
            return None
    ini = _mk(ds[0]) if ds else None
    fim = _mk(ds[-1]) if len(ds) > 1 else None
    return (ini, fim)


PARSE_TABLE_JS = r"""
() => {
    const tbody = document.querySelector('tbody[id$="dtTblExibeListaPlanosDeTrabalho_data"]');
    if (!tbody) return {error: 'no plans tbody'};
    const trs = Array.from(tbody.querySelectorAll(':scope > tr'))
        .filter(tr => !tr.classList.contains('ui-datatable-empty-message'));
    const rows = trs.map(tr => Array.from(tr.children).map(td => td.innerText.trim().replace(/\n+/g, ' | ')));
    // Tambem retorna paginacao
    const pagInfo = (document.body.innerText.match(/P[aá]gina\s+\d+\s+de\s+\d+/i) || [''])[0];
    return {count: rows.length, rows: rows, pag: pagInfo};
}
"""


async def _scrape_municipio(page, municipio_nome: str) -> list[dict]:
    """Faz pesquisa unificada e parseia tabela HTML diretamente.

    A tabela tem colunas:
    [0] expander | [1] Nº Proposta | [2] Nº Plano | [3] Nº Instrumento |
    [4] Instrumento (text) | [5] SIAFI | [6] Tipo | [7] Concedente | [8] Convenente |
    [9] Municipio | [10] Valor | [11] Titulo | [12] Status | [13] Conta | [14] Remessa | [15] Acao
    """
    await page.goto(SEARCH_URL, timeout=60000, wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)

    # Filtro municipio — e um PrimeFaces selectonemenu com ~854 opcoes cujo
    # VALUE e o codigo IBGE (NAO o nome). O codigo antigo fazia sel.value=NOME,
    # que nunca casava → filtro ficava no default (Araujos). Aqui buscamos a
    # opcao pelo TEXTO normalizado e setamos o VALUE correto + sincronizamos
    # o label do widget PrimeFaces.
    matched = await page.evaluate("""(target) => {
        const norm = (s) => (s||'').toUpperCase()
            .normalize('NFKD').replace(/[\\u0300-\\u036f]/g,'').trim();
        const sel = document.getElementById('frmListaPlanosDeTrabalho:selMunicipio_input');
        if (!sel) return 'no_select';
        const t = norm(target);
        let opt = [...sel.options].find(o => norm(o.text) === t);
        if (!opt) opt = [...sel.options].find(o => norm(o.text).startsWith(t));
        if (!opt) opt = [...sel.options].find(o => norm(o.text).includes(t));
        if (!opt) return 'no_match';
        sel.value = opt.value;
        sel.dispatchEvent(new Event('change', {bubbles: true}));
        const label = document.getElementById('frmListaPlanosDeTrabalho:selMunicipio_label');
        if (label) label.textContent = opt.text;
        return 'ok:' + opt.value + ':' + opt.text;
    }""", municipio_nome)
    logger.info(f"    filtro municipio {municipio_nome}: {matched}")
    await page.wait_for_timeout(1800)

    # Pesquisar
    await page.click('button[id="frmListaPlanosDeTrabalho:cmdBtnPesquisarListaPlanosDeTrabalho"]')
    # Espera tabela popular (nao soh vazio)
    try:
        await page.wait_for_function("""() => {
            const tb = document.querySelector('tbody[id$="dtTblExibeListaPlanosDeTrabalho_data"]');
            if (!tb) return false;
            const tr = tb.querySelector(':scope > tr');
            return tr && !tr.classList.contains('ui-datatable-empty-message');
        }""", timeout=90000)
    except Exception:
        logger.warning(f"  Tabela nao carregou apos pesquisa de {municipio_nome}")
        return []

    all_rows = []
    page_n = 1
    while True:
        await page.wait_for_timeout(2000)
        data = await page.evaluate(PARSE_TABLE_JS)
        rows = data.get("rows", [])
        logger.info(f"  Pag {page_n} ({data.get('pag','')}): {len(rows)} linhas")
        for r in rows:
            # Padding pra evitar IndexError
            cells = r + [""] * (16 - len(r))
            nr_proposta = cells[1].strip()
            nr_plano = cells[2].strip()
            nr_instrumento = cells[3].strip()
            siafi = cells[5].strip() if cells[5] != "ui-button" else ""
            tipo = cells[6].strip()
            orgao = cells[7].strip()
            convenente = cells[8].strip()
            mun = cells[9].strip()
            valor = _parse_money(cells[10])
            objeto = cells[11].strip()
            status = cells[12].strip()
            # Extrai ano do numero "/YYYY"
            import re
            ano = None
            for fld in (nr_plano, nr_proposta, nr_instrumento):
                m = re.search(r"/(\d{4})$", fld)
                if m:
                    ano = int(m.group(1))
                    break
            all_rows.append({
                "nr_proposta": nr_proposta,
                "nr_plano": nr_plano,
                "nr_instrumento": nr_instrumento,
                "nr_siafi": siafi or None,
                "tipo": tipo,
                "orgao": orgao,
                "convenente": convenente,
                "municipio": mun,
                "valor_repasse": valor,
                "objeto": objeto,
                "status": status,
                "ano": ano,
            })
        # Tenta proxima pagina
        next_btn = page.locator('a.ui-paginator-next:not(.ui-state-disabled)').first
        if await next_btn.count() == 0:
            break
        try:
            await next_btn.click(timeout=10000)
            await page.wait_for_timeout(5000)
            page_n += 1
            if page_n > 50:  # safety
                break
        except Exception as e:
            logger.warning(f"  Paginacao parou em {page_n}: {e}")
            break

    logger.info(f"  Total parsed: {len(all_rows)} convenios para {municipio_nome}")
    return all_rows


LINK_SELECTOR_DET = (
    'a[id*="cmdLinkPropostaResult"], a[id*="cmdLinkPlanoResult"], '
    'a[id*="cmdLinkInstrumento"], a[id*="cmdLinkConvenio"], '
    'a[id*="cmdLinkSiafi"]'
)


async def _estabelecer_grid(page, tries: int = 3) -> bool:
    """(Re)estabelece a grade da Pesquisa Unificada: goto SEARCH_URL + Pesquisar
    + espera as linhas. Com retries. Retorna True se a grade tem linhas."""
    for t in range(tries):
        try:
            await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=40000)
            await page.wait_for_timeout(2500)
            await page.click('button[id="frmListaPlanosDeTrabalho:cmdBtnPesquisarListaPlanosDeTrabalho"]',
                             timeout=15000)
            await page.wait_for_function("""() => {
                const tb = document.querySelector('tbody[id$="dtTblExibeListaPlanosDeTrabalho_data"]');
                return tb && tb.querySelectorAll(':scope > tr:not(.ui-datatable-empty-message)').length > 0;
            }""", timeout=60000)
            await page.wait_for_timeout(1200)
            return True
        except Exception as e:
            logger.warning(f"  estabelecer_grid try {t+1}/{tries}: {str(e)[:70]}")
            await page.wait_for_timeout(2000)
    return False


async def _scrape_detalhes(page, max_planos: int = 100) -> dict:
    """Para cada linha da Pesquisa Unificada, abre o detalhe e captura os campos.

    RESILIENTE: clique via DOM (el.click() — passa por cima de overlay/scroll do
    PrimeFaces), re-estabelece a grade entre registros, e NUNCA quebra o loop por
    1 falha — pula o registro e segue (aborta so apos muitas falhas seguidas).
    """
    out: dict = {}
    n_links = await page.locator(LINK_SELECTOR_DET).count()
    logger.info(f"  Detalhe: {n_links} links cmdLink na tabela")
    if n_links == 0:
        return out

    iter_count = min(n_links, max_planos)
    falhas_seguidas = 0
    idx = 0
    while idx < iter_count:
        if falhas_seguidas >= 6:
            logger.warning(f"  {falhas_seguidas} falhas seguidas — abortando detalhes (capturados {len(out)})")
            break
        try:
            links = page.locator(LINK_SELECTOR_DET)
            cur_count = await links.count()
            if idx >= cur_count:
                # grade nao restaurada -> tenta restabelecer antes de desistir do idx
                if not await _estabelecer_grid(page):
                    falhas_seguidas += 1
                    idx += 1
                    continue
                links = page.locator(LINK_SELECTOR_DET)
                if idx >= await links.count():
                    idx += 1
                    continue
            link = links.nth(idx)
            link_text = (await link.text_content() or "").strip()
            # Clique via DOM (bypassa overlay/scroll). Fallback: Playwright click.
            try:
                await link.evaluate("el => el.click()")
            except Exception:
                await link.scroll_into_view_if_needed(timeout=4000)
                await link.click(timeout=10000)
            # Espera a pagina de detalhe (PrimeFaces AJAX)
            await page.wait_for_function("""() => {
                if (!document.body) return false;
                const t = document.body.innerText || "";
                return t.includes('Responsável(is)') || t.includes('Responsavel(is)')
                    || t.includes('Fase-Etapa-Status') || t.includes('Fase-Etapa')
                    || t.includes('Vigência Atual') || t.includes('Vigencia Atual');
            }""", timeout=25000)
            await page.wait_for_timeout(700)
            data = await page.evaluate(PARSE_DETALHE_JS)
            if data and (data.get("responsaveis") or data.get("fase_etapa_status")
                         or data.get("dt_assinatura_str") or data.get("valor_contrapartida_atual_str")
                         or data.get("valor_contrapartida_str") or data.get("vigencia_atual_str")):
                key = data.get("nr_proposta_detalhe") or data.get("nr_plano_detalhe") or link_text
                out[key] = data
                logger.info(f"    [{idx+1}/{iter_count}] {key}: resp={data.get('responsaveis','-')[:24]} "
                            f"contrap={data.get('valor_contrapartida_atual_str') or data.get('valor_contrapartida_str','-')} "
                            f"assin={data.get('dt_assinatura_str','-')}")
            falhas_seguidas = 0
            idx += 1
            # Re-estabelece a grade para o proximo registro
            if idx < iter_count and not await _estabelecer_grid(page):
                logger.warning("  nao restabeleceu a grade apos detalhe — tentando seguir")
                falhas_seguidas += 1
        except Exception as e:
            logger.warning(f"  Detalhe iter {idx} falhou: {str(e)[:110]}")
            falhas_seguidas += 1
            idx += 1
            await _estabelecer_grid(page)  # restaura p/ o proximo
    logger.info(f"  Detalhes capturados: {len(out)}")
    return out


PARSE_DETALHE_JS = r"""
() => {
    // Parseia campos da pagina de detalhe do Plano/Proposta SIGCON
    // Formato observado: "Label:\tValue\n" e "Label:\tValue\tLabel2:\tValue2\n"
    const text = document.body.innerText;
    // Splita em linhas e tenta extrair pares label:value
    const out = {};
    const wanted = {
        "Numero da Proposta": "nr_proposta_detalhe",
        "Numero do Plano de Trabalho": "nr_plano_detalhe",
        "Status": "status_detalhe",
        "Data da Criacao": "data_criacao",
        "Concedente": "concedente_full",
        "Beneficiario": "beneficiario_full",
        "Municipio": "municipio_full",
        "Tipo de Beneficiario": "tipo_beneficiario",
        "Valor Concedente": "valor_concedente_str",
        "Valor Concedente Atual": "valor_concedente_atual_str",
        "Valor Contrapartida": "valor_contrapartida_str",
        "Valor Contrapartida Atual": "valor_contrapartida_atual_str",
        "Valor Dotacao Complementar": "valor_dotacao_complementar",
        "Proposta de Vigencia": "proposta_vigencia",
        "Proposta de Dias de Vigencia": "proposta_dias_vigencia",
        "Data da Assinatura": "dt_assinatura_str",
        "Data de Publicacao": "dt_publicacao_str",
        "Vigencia Atual": "vigencia_atual_str",
        "Dias de Vigencia Atual": "dias_vigencia_atual_str",
        "Dias Restantes de Vigencia": "dias_restantes_str",
        "Quantidade de Alteracoes Concluidas": "qt_alteracoes_str",
        "Responsavel(is)": "responsaveis",
        "Tipo de Instrumento": "tp_instrumento_detalhe",
        "Numero da Transferencia Especial": "nr_te",
        "Fase-Etapa-Status": "fase_etapa_status",
        "Setor": "setor",
        "Titulo": "titulo_detalhe",
    };
    function norm(s) {
        return s.normalize("NFD").replace(/[̀-ͯ]/g, "");
    }
    // Cria regex pra cada label
    const lines = text.split(/\n+/);
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        // Split por tab pra pegar pares
        const parts = line.split(/\t+/);
        for (let j = 0; j < parts.length - 1; j++) {
            const labelRaw = parts[j].trim();
            if (!labelRaw.endsWith(":")) continue;
            const labelClean = norm(labelRaw.replace(/:$/, "").trim());
            const key = wanted[labelClean];
            if (key && !out[key]) {
                let val = (parts[j + 1] || "").trim();
                // Fase-Etapa-Status as vezes vem na proxima linha (multiline)
                if (key === "fase_etapa_status" && !val && i + 1 < lines.length) {
                    val = lines[i + 1].trim();
                }
                out[key] = val;
            }
        }
    }
    return out;
}
"""


PARSE_EMENDAS_JS = r"""
() => {
    // Tabela de emendas: tbody[id$="dataTableEmendasConvenente_data"]
    const tbody = document.querySelector('tbody[id$="dataTableEmendasConvenente_data"]');
    if (!tbody) return {error: 'no emendas tbody'};
    const trs = Array.from(tbody.querySelectorAll(':scope > tr'))
        .filter(tr => !tr.classList.contains('ui-datatable-empty-message'));
    const rows = trs.map(tr => Array.from(tr.children).map(td => td.innerText.trim().replace(/\n+/g, ' | ')));
    const pagInfo = (document.body.innerText.match(/P[aá]gina\s+\d+\s+de\s+\d+/i) || [''])[0];
    return {count: rows.length, rows: rows, pag: pagInfo};
}
"""


async def _scrape_emendas(page, anos: list[int]) -> list[dict]:
    """Coleta emendas parlamentares estaduais para o convenente do usuario.

    Itera ano-a-ano (dropdown anoInciso) e usa convenente default (do usuario logado).
    Tabela de resultado: dataTableEmendasConvenente
    Colunas: [0]Nº Indicacao | [1]Nome do Responsavel | [2]Tipo de Indicacao |
    [3]UO | [4]Sigla UO | [5]CNPJ Beneficiario | [6]Beneficiario |
    [7]Grupo de Despesa | [8]Tipo de Atendimento/Aplicacao | [9]Valor da Indicacao |
    [10]Status da Indicacao
    """
    all_rows = []
    await page.goto(EMENDAS_URL, timeout=60000, wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)

    for ano in anos:
        try:
            await page.evaluate("""(target) => {
                const sel = document.getElementById('frmPesquisaEmendasPorConvenentes:anoInciso_input');
                if (sel) {
                    sel.value = String(target);
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                }
            }""", ano)
            await page.wait_for_timeout(1500)
        except Exception as e:
            logger.warning(f"  set ano {ano} falhou: {e}")
            continue

        try:
            await page.click('button[id="frmPesquisaEmendasPorConvenentes:cmdBtnEnviar"]', timeout=10000)
        except Exception as e:
            logger.warning(f"  click pesquisar emendas {ano} falhou: {e}")
            continue

        # Espera tabela carregar OU mensagem "sem registros"
        try:
            await page.wait_for_function("""() => {
                const tb = document.querySelector('tbody[id$="dataTableEmendasConvenente_data"]');
                if (!tb) return false;
                return tb.querySelectorAll(':scope > tr').length > 0;
            }""", timeout=60000)
        except Exception:
            logger.info(f"  Ano {ano}: tabela nao carregou")
            continue

        await page.wait_for_timeout(2000)
        page_n = 1
        while True:
            data = await page.evaluate(PARSE_EMENDAS_JS)
            rows = data.get("rows", []) or []
            logger.info(f"  Ano {ano} pag {page_n} ({data.get('pag','')}): {len(rows)} emendas")
            for r in rows:
                cells = r + [""] * (12 - len(r))
                rec = {
                    "ano": ano,
                    "nr_indicacao": cells[0].strip(),
                    "nome_responsavel": cells[1].strip(),
                    "tipo_indicacao": cells[2].strip(),
                    "uo_codigo": cells[3].strip(),
                    "uo_sigla": cells[4].strip(),
                    "cnpj_beneficiario": cells[5].strip(),
                    "beneficiario": cells[6].strip(),
                    "grupo_despesa": cells[7].strip(),
                    "tipo_atendimento": cells[8].strip(),
                    "valor_indicacao": _parse_money(cells[9]),
                    "status_indicacao": cells[10].strip(),
                }
                all_rows.append(rec)
            # Proxima pagina
            next_btn = page.locator('a.ui-paginator-next:not(.ui-state-disabled)').first
            if await next_btn.count() == 0:
                break
            try:
                await next_btn.click(timeout=10000)
                await page.wait_for_timeout(4000)
                page_n += 1
                if page_n > 30:
                    break
            except Exception:
                break

    logger.info(f"  Total emendas parsed: {len(all_rows)}")
    return all_rows


async def _login(page, cpf: str, senha: str):
    # Submit robusto: o id do botao e auto-gerado do JSF (frmLogin:j_idtNN) e
    # VARIA entre sessoes/municipios -> por isso Piracema/Toledo/Perdigao falhavam.
    # Tenta o id conhecido, depois selectors estaveis (type=submit), depois Enter.
    async def _attempt() -> bool:
        await page.goto(LOGIN_URL, timeout=60000, wait_until="networkidle")
        await page.wait_for_selector('input[id="frmLogin:iptTxtSenha"]', timeout=30000)
        await page.fill('input[id="frmLogin:iptTxtUsuario"]', cpf)
        await page.fill('input[id="frmLogin:iptTxtSenha"]', senha)
        submitted = False
        for sel in ('button[id="frmLogin:j_idt28"]',
                    '#frmLogin button[type="submit"]',
                    'button[id^="frmLogin:"][type="submit"]'):
            try:
                await page.click(sel, timeout=6000)
                submitted = True
                break
            except Exception:
                continue
        if not submitted:
            try:
                await page.press('input[id="frmLogin:iptTxtSenha"]', "Enter")
                submitted = True
            except Exception:
                pass
        await page.wait_for_timeout(8000)
        # Sucesso = saiu da tela de login (o campo senha nao existe mais)
        return (await page.locator('input[id="frmLogin:iptTxtSenha"]').count()) == 0

    ok = False
    for tent in range(2):
        try:
            ok = await _attempt()
        except Exception as e:
            logger.warning(f"  login tentativa {tent + 1} falhou: {str(e)[:90]}")
            ok = False
        if ok:
            break
        await page.wait_for_timeout(3000)
    if not ok:
        raise RuntimeError("login SIGCON nao completou (form nao submeteu ou credencial invalida)")

    # Fecha modal CAGEC se aparecer
    for sel in ['#modalBloqueiosIrregularidades .ui-dialog-titlebar-close',
                'a.ui-dialog-titlebar-close']:
        try:
            await page.locator(sel).first.click(timeout=5000)
            await page.wait_for_timeout(1500)
            return
        except Exception:
            pass


def _municipio_id_lookup() -> dict:
    """Retorna {NOME_NORM: municipio_db_id} dos municipios ativos."""
    import psycopg2
    sync_url = os.getenv("DATABASE_URL_SYNC") or ""
    if not sync_url:
        from config import get_settings
        sync_url = get_settings().DATABASE_URL_SYNC or get_settings().DATABASE_URL.replace("+asyncpg", "")
    sync_url = sync_url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    conn = psycopg2.connect(sync_url)
    cur = conn.cursor()
    cur.execute("SELECT id, nome FROM municipios WHERE active=true AND uf='MG'")
    out = {_norm(r[1]): r[0] for r in cur.fetchall()}
    conn.close()
    return out


def _list_credentials() -> list[dict]:
    """Le credenciais SIGCON-MG do cofre, descriptografando."""
    import psycopg2
    from services.crypto import decrypt
    sync_url = os.getenv("DATABASE_URL_SYNC", "")
    sync_url = sync_url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    conn = psycopg2.connect(sync_url)
    cur = conn.cursor()
    cur.execute("""
        SELECT cs.id, cs.municipio_id, cs.usuario, cs.senha_hash, m.nome
        FROM cofre_senhas cs
        JOIN municipios m ON m.id = cs.municipio_id
        WHERE cs.sistema ILIKE 'SIGCON%' OR cs.automation_key = 'sigcon'
    """)
    creds = []
    for r in cur.fetchall():
        senha = decrypt(r[3])
        if senha:
            creds.append({
                "cofre_id": r[0],
                "municipio_id": r[1],
                "municipio_nome": r[4],
                "cpf": r[2],
                "senha": senha,
            })
    conn.close()
    return creds


async def _run():
    from playwright.async_api import async_playwright

    creds = _list_credentials()
    if not creds:
        logger.warning("Nenhuma credencial SIGCON-MG no cofre - cadastre via UI")
        return

    # Filtro opcional: SIGCON_ONLY="Nome1,Nome2" reprocessa so esses municipios
    # (util p/ re-tentar quem falhou no login sem re-scrapear todos). Default = todos.
    _only = os.getenv("SIGCON_ONLY", "").strip()
    if _only:
        _wanted = {_norm(x) for x in _only.split(",") if x.strip()}
        creds = [c for c in creds if _norm(c["municipio_nome"]) in _wanted]
        logger.info(f"SIGCON_ONLY ativo: {[c['municipio_nome'] for c in creds]}")

    mun_map = _municipio_id_lookup()
    logger.info(f"Credenciais SIGCON-MG: {len(creds)}, municipios DB: {len(mun_map)}")

    all_records = []  # [(municipio_db_id, dict)] convenios
    all_emendas = []  # [(municipio_db_id, dict)] emendas estaduais
    anos_emendas = list(range(2022, datetime.now().year + 1))  # 2022..ano atual
    # CONFIRMADO empiricamente: a Pesquisa Unificada do SIGCON-MG eh ESCOPADA
    # ao convenente logado. Mesmo setando o filtro de municipio corretamente
    # (option value = codigo IBGE), o login de Araujos retorna 0 convenios de
    # Piracema/Nova Serrana/etc. Ou seja: cada municipio EXIGE seu proprio login
    # SIGCON (CPF+senha do convenente). Hoje so existe credencial de Araujos no
    # Cofre -> por isso so Araujos tem convenios/parlamentar estaduais.
    # Solucao p/ os demais: cadastrar 1 credencial SIGCON por municipio.
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--ignore-certificate-errors"])
        try:
            for cred in creds:
                logger.info(f"\n=== Login: {cred['municipio_nome']} (CPF={cred['cpf'][:4]}***) ===")
                ctx = await browser.new_context(
                    ignore_https_errors=True, accept_downloads=True,
                    user_agent="Mozilla/5.0 (Windows NT 10.0) Chrome/131 Safari/537.36",
                )
                page = await ctx.new_page()
                try:
                    await _login(page, cred["cpf"], cred["senha"])
                    rows = await _scrape_municipio(page, _norm(cred["municipio_nome"]))
                    detalhes: dict = {}
                    try:
                        detalhes = await _scrape_detalhes(page, max_planos=100)
                    except Exception as e:
                        logger.warning(f"  Detalhes failed: {e}")
                    by_key: dict = {}
                    for r in rows:
                        det = detalhes.get(r.get("nr_proposta")) or detalhes.get(r.get("nr_plano"))
                        if det:
                            for k, v in det.items():
                                if v and not r.get(k):
                                    r[k] = v
                            if det.get("nr_plano_detalhe") and not r.get("nr_plano"):
                                r["nr_plano"] = det["nr_plano_detalhe"]
                        key = r.get("nr_siafi") or r.get("nr_plano") or r.get("nr_proposta")
                        if not key:
                            all_records.append((cred["municipio_id"], r))
                            continue
                        if key in by_key:
                            existing = by_key[key]
                            for k, v in r.items():
                                if v and not existing.get(k):
                                    existing[k] = v
                        else:
                            by_key[key] = r
                    for r in by_key.values():
                        all_records.append((cred["municipio_id"], r))
                    logger.info(f"  {cred['municipio_nome']}: {len(by_key)} convenios")
                    try:
                        emendas = await _scrape_emendas(page, anos_emendas)
                        for e in emendas:
                            all_emendas.append((cred["municipio_id"], e))
                    except Exception as e:
                        logger.warning(f"  Emendas falharam para {cred['municipio_nome']}: {e}")
                except Exception as e:
                    logger.error(f"  Falha {cred['municipio_nome']}: {e}")
                finally:
                    await ctx.close()
        finally:
            await browser.close()

    # UPSERT em convenios_estadual
    import psycopg2
    sync_url = os.getenv("DATABASE_URL_SYNC", "")
    sync_url = sync_url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    conn = psycopg2.connect(sync_url)
    cur = conn.cursor()
    from datetime import date

    inserted = updated = 0
    for mun_id, rec in all_records:
        # nr_sigcon: prioridade SIAFI > Plano > Proposta > sintetica.
        # SIAFI eh o id do convenio "vigente"; Plano/Proposta sao do trackeamento pre-celebracao.
        nr_sigcon = (
            rec.get("nr_siafi")
            or rec.get("nr_plano")
            or rec.get("nr_proposta")
            or f"SIGCON-PORTAL-{mun_id}-{abs(hash(rec.get('objeto') or '')) % 10**8}"
        )
        sit_norm = _norm(rec.get("status") or "")
        sit_label = STATUS_MAP.get(sit_norm, rec.get("status"))
        # dt_publicacao proxy: 1o jan do ano (extraido de "/YYYY" no Plano/Proposta).
        # NAO eh data exata, mas permite ordenacao correta no front (recentes 1o)
        # sem precisar fazer click-through em cada plano.
        ano = rec.get("ano")
        dt_pub_proxy = date(ano, 1, 1) if ano else None
        valor = rec.get("valor_repasse")
        # Campos do detalhe (contrapartida, assinatura, vigencia, alteracoes)
        v_contrap = _parse_money(rec.get("valor_contrapartida_atual_str")
                                 or rec.get("valor_contrapartida_str"))
        dt_assin = _parse_date(rec.get("dt_assinatura_str"))
        dt_pub_real = _parse_date(rec.get("dt_publicacao_str"))
        vig_ini, vig_fim = _parse_vigencia_range(rec.get("vigencia_atual_str"))
        _qa = (rec.get("qt_alteracoes_str") or "").strip()
        qt_alt = int(_qa) if _qa.isdigit() else None
        # valor_total = concedente (repasse) + contrapartida quando houver
        v_total = ((valor or 0) + (v_contrap or 0)) if (valor or v_contrap) else valor
        # dt_publicacao: usa a data real do detalhe se houver, senao o proxy (1o jan)
        dt_pub = dt_pub_real or dt_pub_proxy
        # Conflito de dedupe: prioriza nr_siafi (estavel entre CKAN bulk
        # e scraper Playwright). Se SIAFI presente, usa ON CONFLICT (nr_siafi)
        # pra atualizar o registro existente. Se nao, usa nr_sigcon como fallback.
        nr_siafi = rec.get("nr_siafi") or None
        # IMPORTANTE: o indice unico de nr_siafi e PARCIAL
        # (ux_convenios_estadual_nr_siafi WHERE nr_siafi IS NOT NULL AND <> '').
        # Um "ON CONFLICT (nr_siafi)" simples NAO casa com indice parcial —
        # precisa repetir o predicado. Sem isso, TODO registro com SIAFI
        # falhava silenciosamente (causa real do SIGCON travado ha ~24 dias).
        if nr_siafi:
            conflict_target = "(nr_siafi) WHERE nr_siafi IS NOT NULL AND nr_siafi <> ''"
        else:
            conflict_target = "(nr_sigcon)"
        try:
            # SAVEPOINT por registro: erro em 1 nao descarta os anteriores
            # (antes, conn.rollback() perdia TODO o batch desde o ultimo commit)
            cur.execute("SAVEPOINT sp_conv")
            cur.execute(f"""
                INSERT INTO convenios_estadual (
                    nr_sigcon, nr_siafi, municipio_id, orgao_concedente,
                    convenente_nome, objeto, situacao,
                    valor_concedente, valor_total, valor_repassado, valor_contrapartida,
                    raw_data, tp_instrumento,
                    nr_plano_trabalho, ano, dt_publicacao,
                    dt_assinatura, dt_vigencia_inicial, dt_vigencia_atual,
                    dt_vigencia_final, qt_alteracoes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT {conflict_target} DO UPDATE SET
                    nr_sigcon = COALESCE(convenios_estadual.nr_sigcon, EXCLUDED.nr_sigcon),
                    nr_siafi = COALESCE(convenios_estadual.nr_siafi, EXCLUDED.nr_siafi),
                    situacao = EXCLUDED.situacao,
                    valor_concedente = COALESCE(EXCLUDED.valor_concedente, convenios_estadual.valor_concedente),
                    valor_total = COALESCE(EXCLUDED.valor_total, convenios_estadual.valor_total),
                    valor_repassado = COALESCE(EXCLUDED.valor_repassado, convenios_estadual.valor_repassado),
                    valor_contrapartida = COALESCE(EXCLUDED.valor_contrapartida, convenios_estadual.valor_contrapartida),
                    convenente_nome = COALESCE(EXCLUDED.convenente_nome, convenios_estadual.convenente_nome),
                    nr_plano_trabalho = COALESCE(EXCLUDED.nr_plano_trabalho, convenios_estadual.nr_plano_trabalho),
                    ano = COALESCE(EXCLUDED.ano, convenios_estadual.ano),
                    dt_publicacao = COALESCE(EXCLUDED.dt_publicacao, convenios_estadual.dt_publicacao),
                    dt_assinatura = COALESCE(EXCLUDED.dt_assinatura, convenios_estadual.dt_assinatura),
                    dt_vigencia_inicial = COALESCE(EXCLUDED.dt_vigencia_inicial, convenios_estadual.dt_vigencia_inicial),
                    dt_vigencia_atual = COALESCE(EXCLUDED.dt_vigencia_atual, convenios_estadual.dt_vigencia_atual),
                    dt_vigencia_final = COALESCE(EXCLUDED.dt_vigencia_final, convenios_estadual.dt_vigencia_final),
                    qt_alteracoes = COALESCE(EXCLUDED.qt_alteracoes, convenios_estadual.qt_alteracoes),
                    raw_data = convenios_estadual.raw_data || EXCLUDED.raw_data,
                    updated_at = NOW()
                RETURNING (xmax = 0) AS is_insert
            """, (
                nr_sigcon[:80],
                nr_siafi,
                mun_id,
                rec.get("orgao"),
                rec.get("convenente"),
                rec.get("objeto"),
                sit_label,
                valor,  # valor_concedente (lido pelo front como valor_repasse)
                v_total,  # valor_total = concedente + contrapartida
                None,  # valor_repassado -> preenchido pelo backfill CKAN (ft_convenio)
                v_contrap,  # valor_contrapartida
                json.dumps({**rec, "_source": "sigcon_scraper"}, ensure_ascii=False, default=str),
                rec.get("tipo"),
                rec.get("nr_plano") or None,
                ano,
                dt_pub,
                dt_assin,
                vig_ini,
                vig_fim,  # dt_vigencia_atual = fim da vigencia atual
                vig_fim,  # dt_vigencia_final = mesma (fim atual)
                qt_alt,
            ))
            row = cur.fetchone()
            cur.execute("RELEASE SAVEPOINT sp_conv")
            is_insert = bool(row and row[0])
            if is_insert:
                inserted += 1
            else:
                updated += 1
        except Exception as e:
            logger.warning(f"  Erro UPSERT {nr_sigcon}: {str(e)[:200]}")
            try:
                cur.execute("ROLLBACK TO SAVEPOINT sp_conv")
            except Exception:
                conn.rollback()  # fallback se a conexao inteira caiu
            continue

    cur.execute(
        "INSERT INTO ingestion_log (source, status, records_inserted, finished_at) "
        "VALUES ('sigcon_scraper', 'success', %s, NOW())",
        (inserted + updated,)
    )
    conn.commit()

    # === EMENDAS ESTADUAIS ===
    em_inserted = em_updated = 0
    for mun_id, em in all_emendas:
        nr_ind = em.get("nr_indicacao")
        ano_em = em.get("ano")
        if not nr_ind or not ano_em:
            continue
        try:
            cur.execute("SAVEPOINT sp_em")
            cur.execute("""
                INSERT INTO emendas_estaduais (
                    municipio_id, nr_indicacao, nome_responsavel, tipo_indicacao,
                    uo_codigo, uo_sigla, cnpj_beneficiario, beneficiario,
                    grupo_despesa, tipo_atendimento, valor_indicacao, status_indicacao,
                    ano, raw_data
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (nr_indicacao, ano) DO UPDATE SET
                    nome_responsavel = EXCLUDED.nome_responsavel,
                    tipo_indicacao = EXCLUDED.tipo_indicacao,
                    uo_codigo = EXCLUDED.uo_codigo,
                    uo_sigla = EXCLUDED.uo_sigla,
                    cnpj_beneficiario = EXCLUDED.cnpj_beneficiario,
                    beneficiario = EXCLUDED.beneficiario,
                    grupo_despesa = EXCLUDED.grupo_despesa,
                    tipo_atendimento = EXCLUDED.tipo_atendimento,
                    valor_indicacao = EXCLUDED.valor_indicacao,
                    status_indicacao = EXCLUDED.status_indicacao,
                    raw_data = EXCLUDED.raw_data,
                    updated_at = NOW()
                RETURNING (xmax = 0) AS is_insert
            """, (
                mun_id, nr_ind[:50], em.get("nome_responsavel","")[:300],
                em.get("tipo_indicacao","")[:100],
                em.get("uo_codigo","")[:20], em.get("uo_sigla","")[:50],
                em.get("cnpj_beneficiario","")[:20], em.get("beneficiario","")[:300],
                em.get("grupo_despesa","")[:200], em.get("tipo_atendimento","")[:300],
                em.get("valor_indicacao"), em.get("status_indicacao","")[:50],
                ano_em,
                json.dumps({**em, "_source": "sigcon_scraper"}, ensure_ascii=False, default=str),
            ))
            row = cur.fetchone()
            cur.execute("RELEASE SAVEPOINT sp_em")
            if row and row[0]:
                em_inserted += 1
            else:
                em_updated += 1
        except Exception as e:
            logger.warning(f"  Erro UPSERT emenda {nr_ind}: {str(e)[:200]}")
            try:
                cur.execute("ROLLBACK TO SAVEPOINT sp_em")
            except Exception:
                conn.rollback()
            continue
    conn.commit()
    conn.close()

    logger.info(f"\n=== Convenios: {inserted} inseridos, {updated} atualizados (total {inserted+updated}) ===")
    logger.info(f"=== Emendas estaduais: {em_inserted} inseridas, {em_updated} atualizadas ===")


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
