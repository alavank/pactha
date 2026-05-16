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

    # Filtro municipio (best effort; nao bloqueia se PF nao expor select normal)
    try:
        await page.evaluate("""(target) => {
            const sel = document.getElementById('frmListaPlanosDeTrabalho:selMunicipio_input');
            if (sel) {
                sel.value = target;
                sel.dispatchEvent(new Event('change', {bubbles: true}));
            }
        }""", municipio_nome)
        await page.wait_for_timeout(1500)
    except Exception:
        pass

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


async def _scrape_detalhes(page, max_planos: int = 100) -> dict:
    """Para cada linha visivel na tabela de pesquisa unificada, clica no link
    do Plano/Proposta e captura campos da pagina de detalhe.

    Retorna: {nr_proposta_or_plano: {responsaveis, proposta_vigencia, ...}}
    NAO recarrega a tabela entre iteracoes - usa o botao "Retornar para
    Pesquisa Proposta" pra voltar mantendo o state.
    """
    out: dict = {}
    # Selector amplo: cmdLinkPropostaResult, cmdLinkPlanoResult, cmdLinkInstrumento, cmdLinkConvenio
    LINK_SELECTOR = (
        'a[id*="cmdLinkPropostaResult"], a[id*="cmdLinkPlanoResult"], '
        'a[id*="cmdLinkInstrumento"], a[id*="cmdLinkConvenio"], '
        'a[id*="cmdLinkSiafi"]'
    )
    n_links = await page.locator(LINK_SELECTOR).count()
    logger.info(f"  Detalhe: {n_links} links cmdLink na tabela")
    if n_links == 0:
        return out

    iter_count = min(n_links, max_planos)
    for idx in range(iter_count):
        try:
            # Re-busca o locator a cada iteracao (DOM muda apos voltar)
            links = page.locator(LINK_SELECTOR)
            cur_count = await links.count()
            if idx >= cur_count:
                logger.warning(f"  Detalhe iter {idx}: locator sem links suficientes ({cur_count})")
                break
            link = links.nth(idx)
            # Pega texto antes de clicar pra usar como key (eh o nr_proposta ou nr_plano)
            link_text = (await link.text_content() or "").strip()
            await link.click(timeout=15000)
            # Espera carregar a pagina de detalhe (PrimeFaces AJAX) - guard pra body null
            await page.wait_for_function("""() => {
                if (!document.body) return false;
                const t = document.body.innerText || "";
                return t.includes('Responsável(is)') || t.includes('Responsavel(is)')
                    || t.includes('Fase-Etapa-Status') || t.includes('Fase-Etapa')
                    || t.includes('Vigência Atual') || t.includes('Vigencia Atual');
            }""", timeout=25000)
            await page.wait_for_timeout(800)
            data = await page.evaluate(PARSE_DETALHE_JS)
            if data and (data.get("responsaveis") or data.get("fase_etapa_status")):
                key = data.get("nr_proposta_detalhe") or data.get("nr_plano_detalhe") or link_text
                out[key] = data
                logger.info(f"    [{idx+1}/{iter_count}] {key}: resp={data.get('responsaveis','-')[:30]} fase={data.get('fase_etapa_status','-')[:40]}")
            # Volta pra pesquisa
            try:
                btn_voltar = page.locator(
                    'a:has-text("Retornar para Pesquisa"), button:has-text("Retornar"), '
                    'a:has-text("Voltar"), button:has-text("Voltar")'
                ).first
                if await btn_voltar.count() > 0:
                    await btn_voltar.click(timeout=10000)
                    await page.wait_for_function("""() => {
                        const tb = document.querySelector('tbody[id$=\"dtTblExibeListaPlanosDeTrabalho_data\"]');
                        return tb && tb.querySelectorAll(':scope > tr:not(.ui-datatable-empty-message)').length > 0;
                    }""", timeout=30000)
                    await page.wait_for_timeout(1500)
                else:
                    # Fallback: navigate + re-search
                    await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(5000)
                    await page.click('button[id="frmListaPlanosDeTrabalho:cmdBtnPesquisarListaPlanosDeTrabalho"]')
                    await page.wait_for_function("""() => {
                        const tb = document.querySelector('tbody[id$=\"dtTblExibeListaPlanosDeTrabalho_data\"]');
                        return tb && tb.querySelectorAll(':scope > tr:not(.ui-datatable-empty-message)').length > 0;
                    }""", timeout=60000)
                    await page.wait_for_timeout(2000)
            except Exception as e:
                logger.warning(f"  Falha ao voltar pra pesquisa: {e}")
                break
        except Exception as e:
            logger.warning(f"  Detalhe iter {idx} falhou: {str(e)[:120]}")
            # Tenta restaurar navegando direto
            try:
                await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(5000)
                await page.click('button[id="frmListaPlanosDeTrabalho:cmdBtnPesquisarListaPlanosDeTrabalho"]')
                await page.wait_for_function("""() => {
                    const tb = document.querySelector('tbody[id$=\"dtTblExibeListaPlanosDeTrabalho_data\"]');
                    return tb && tb.querySelectorAll(':scope > tr:not(.ui-datatable-empty-message)').length > 0;
                }""", timeout=60000)
                await page.wait_for_timeout(2000)
            except Exception as e2:
                logger.error(f"  Restore falhou: {e2}")
                break
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
        "Valor Dotacao Complementar": "valor_dotacao_complementar",
        "Proposta de Vigencia": "proposta_vigencia",
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
    await page.goto(LOGIN_URL, timeout=60000, wait_until="networkidle")
    await page.fill('input[id="frmLogin:iptTxtUsuario"]', cpf)
    await page.fill('input[id="frmLogin:iptTxtSenha"]', senha)
    await page.click('button[id="frmLogin:j_idt28"]')
    await page.wait_for_timeout(8000)
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

    mun_map = _municipio_id_lookup()
    logger.info(f"Credenciais SIGCON-MG: {len(creds)}, municipios DB: {len(mun_map)}")

    all_records = []  # [(municipio_db_id, dict)] convenios
    all_emendas = []  # [(municipio_db_id, dict)] emendas estaduais
    anos_emendas = list(range(2022, datetime.now().year + 1))  # 2022..ano atual
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--ignore-certificate-errors"])
        try:
            for cred in creds:
                logger.info(f"\n=== Login: {cred['municipio_nome']} (CPF={cred['cpf'][:4]}***) ===")
                ctx = await browser.new_context(
                    ignore_https_errors=True,
                    accept_downloads=True,
                    user_agent="Mozilla/5.0 (Windows NT 10.0) Chrome/131 Safari/537.36",
                )
                page = await ctx.new_page()
                try:
                    await _login(page, cred["cpf"], cred["senha"])
                    # 1) Convenios (Pesquisa Unificada)
                    rows = await _scrape_municipio(page, _norm(cred["municipio_nome"]))
                    # 1b) Detalhes (Responsavel, Proposta Vigencia, Valor Dot Compl,
                    # Fase-Etapa-Status, Setor, Data Criacao) - click-through em cada plano
                    detalhes: dict = {}
                    try:
                        detalhes = await _scrape_detalhes(page, max_planos=100)
                    except Exception as e:
                        logger.warning(f"  Detalhes failed: {e}")
                    # Merge detalhes nas rows (key = nr_proposta OR nr_plano)
                    for r in rows:
                        det = detalhes.get(r.get("nr_proposta")) or detalhes.get(r.get("nr_plano"))
                        if det:
                            # Adiciona campos novos sem sobrescrever os ja parseados da tabela
                            for k, v in det.items():
                                if v and not r.get(k):
                                    r[k] = v
                        all_records.append((cred["municipio_id"], r))
                    # 2) Emendas (Emendas / Pesquisar Por Convenente)
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

    # === Snapshot pre-UPSERT pra detectar deltas (notificacoes push) ===
    # Mapeia nr_sigcon -> (situacao, valor) ANTES do upsert
    pre_snapshot: dict = {}
    keys_check = [r.get("nr_siafi") or r.get("nr_plano") or r.get("nr_proposta") for _, r in all_records]
    keys_check = [k for k in keys_check if k]
    if keys_check:
        cur.execute(
            "SELECT nr_sigcon, situacao, valor_concedente, id FROM convenios_estadual WHERE nr_sigcon = ANY(%s)",
            (keys_check,)
        )
        for nr, sit, val, _id in cur.fetchall():
            pre_snapshot[nr] = {"situacao": sit, "valor": float(val) if val else None, "id": _id}

    notif_payload = []  # acumula notificacoes a inserir depois
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
        try:
            cur.execute("""
                INSERT INTO convenios_estadual (
                    nr_sigcon, nr_siafi, municipio_id, orgao_concedente,
                    convenente_nome, objeto, situacao,
                    valor_concedente, valor_total, valor_repassado,
                    raw_data, tp_instrumento,
                    nr_plano_trabalho, ano, dt_publicacao
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                ON CONFLICT (nr_sigcon) DO UPDATE SET
                    situacao = EXCLUDED.situacao,
                    valor_concedente = COALESCE(EXCLUDED.valor_concedente, convenios_estadual.valor_concedente),
                    valor_total = COALESCE(EXCLUDED.valor_total, convenios_estadual.valor_total),
                    valor_repassado = COALESCE(EXCLUDED.valor_repassado, convenios_estadual.valor_repassado),
                    convenente_nome = COALESCE(EXCLUDED.convenente_nome, convenios_estadual.convenente_nome),
                    nr_plano_trabalho = COALESCE(EXCLUDED.nr_plano_trabalho, convenios_estadual.nr_plano_trabalho),
                    ano = COALESCE(EXCLUDED.ano, convenios_estadual.ano),
                    dt_publicacao = COALESCE(EXCLUDED.dt_publicacao, convenios_estadual.dt_publicacao),
                    raw_data = convenios_estadual.raw_data || EXCLUDED.raw_data,
                    updated_at = NOW()
                RETURNING (xmax = 0) AS is_insert
            """, (
                nr_sigcon[:80],
                rec.get("nr_siafi") or None,
                mun_id,
                rec.get("orgao"),
                rec.get("convenente"),
                rec.get("objeto"),
                sit_label,
                valor,  # valor_concedente (lido pelo front como valor_repasse)
                valor,  # valor_total
                valor,  # valor_repassado
                json.dumps({**rec, "_source": "sigcon_scraper"}, ensure_ascii=False, default=str),
                rec.get("tipo"),
                rec.get("nr_plano") or None,
                ano,
                dt_pub_proxy,
            ))
            row = cur.fetchone()
            is_insert = bool(row and row[0])
            if is_insert:
                inserted += 1
                # NOTIF: novo convenio descoberto
                notif_payload.append({
                    "tipo": "sigcon_novo",
                    "municipio_id": mun_id,
                    "nr_sigcon": nr_sigcon[:80],
                    "titulo": f"Novo convenio: {(rec.get('orgao') or '?')} - {(rec.get('objeto') or '?')[:60]}",
                    "mensagem": f"Valor: {valor or 0:,.2f} | Status: {sit_label}",
                    "severidade": "success",
                    "payload": {"nr_proposta": rec.get("nr_proposta"), "nr_plano": rec.get("nr_plano"),
                                "valor": valor, "status": sit_label, "tipo": rec.get("tipo")},
                })
            else:
                updated += 1
                # NOTIF: status mudou ou valor mudou?
                prev = pre_snapshot.get(nr_sigcon[:80])
                if prev:
                    if prev.get("situacao") and sit_label and prev["situacao"] != sit_label:
                        notif_payload.append({
                            "tipo": "sigcon_status",
                            "municipio_id": mun_id,
                            "nr_sigcon": nr_sigcon[:80],
                            "titulo": f"Status mudou: {prev['situacao']} -> {sit_label}",
                            "mensagem": f"{(rec.get('orgao') or '?')} - {(rec.get('objeto') or '?')[:60]}",
                            "severidade": "warning",
                            "payload": {"old": prev["situacao"], "new": sit_label},
                        })
                    if valor and prev.get("valor") and abs(valor - prev["valor"]) > 0.01:
                        notif_payload.append({
                            "tipo": "sigcon_valor",
                            "municipio_id": mun_id,
                            "nr_sigcon": nr_sigcon[:80],
                            "titulo": f"Valor atualizado: R$ {prev['valor']:,.2f} -> R$ {valor:,.2f}",
                            "mensagem": f"{(rec.get('orgao') or '?')} - {(rec.get('objeto') or '?')[:60]}",
                            "severidade": "info",
                            "payload": {"old": prev["valor"], "new": valor},
                        })
        except Exception as e:
            logger.warning(f"  Erro UPSERT {nr_sigcon}: {str(e)[:200]}")
            conn.rollback()
            continue

    # Insere notificacoes em batch
    if notif_payload:
        # Resolve convenio_estadual_id pra cada notif
        cur.execute(
            "SELECT nr_sigcon, id FROM convenios_estadual WHERE nr_sigcon = ANY(%s)",
            ([n["nr_sigcon"] for n in notif_payload],)
        )
        sigcon_to_id = {nr: _id for nr, _id in cur.fetchall()}
        for n in notif_payload:
            try:
                cur.execute("""
                    INSERT INTO notificacoes (tipo, municipio_id, convenio_estadual_id,
                                              titulo, mensagem, severidade, payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                """, (
                    n["tipo"], n["municipio_id"], sigcon_to_id.get(n["nr_sigcon"]),
                    n["titulo"][:300], n["mensagem"][:500], n["severidade"],
                    json.dumps(n["payload"], default=str),
                ))
            except Exception as e:
                logger.warning(f"  Notif falhou: {e}")
                conn.rollback()
        logger.info(f"\n  Notificacoes geradas: {len(notif_payload)} (novos+status+valor mudou)")

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
            if row and row[0]:
                em_inserted += 1
            else:
                em_updated += 1
        except Exception as e:
            logger.warning(f"  Erro UPSERT emenda {nr_ind}: {str(e)[:200]}")
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
