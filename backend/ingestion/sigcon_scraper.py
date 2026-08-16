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
import time
import unicodedata
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger("sigcon_scraper")

# DEADLINE DA RODADA, visivel para os loops longos DENTRO de uma credencial.
#
# Ate 10/08/2026 o orcamento era checado num lugar so: no topo de `_scrape_one`,
# ou seja ENTRE credenciais. Uma credencial pesada atravessava a janela inteira e
# era morta pelo `timeout` externo (medido: rodada de 2042s contra teto de 2040s,
# exit 124) — perdendo o que estava em voo e sem carimbar. E o mesmo bug ja
# corrigido no transferegov_voluntarias; aqui as caudas sao tres: a paginacao da
# listagem, o loop de detalhes e a paginacao dentro de cada ano de emendas.
#
# Vive no modulo (mesmo padrao de _HIST_ORC no transferegov) para nao mudar a
# assinatura de funcoes chamadas em varios pontos. main() preenche; os loops leem.
_SIG_DEADLINE: dict = {"t": None}


def _sig_estourou() -> bool:
    """True quando o orcamento da rodada acabou. Os loops longos consultam isto
    para parar LIMPO (o que ja foi lido fica gravado) em vez de tomar SIGKILL."""
    t = _SIG_DEADLINE.get("t")
    return t is not None and time.monotonic() >= t

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
        # Cauda 1/3: paginacao da listagem. Sem este corte, um municipio com
        # muitas paginas atravessa o orcamento inteiro (ver _SIG_DEADLINE).
        if _sig_estourou():
            logger.info(f"  [orcamento] {municipio_nome}: paginacao cortada na pag {page_n} "
                        f"— {len(all_rows)} linhas ficam gravadas")
            break
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


async def _scrape_indicacoes(page) -> dict | None:
    """Le a INDICACAO parlamentar do convenio: nr_indicacao, saldo, valor utilizado.

    Expande a secao 'INFORMAÇÕES DE REPASSE DE RECURSOS' (accordion PrimeFaces,
    header com id estavel prefixado accPnlPropostaPlanoTrabalho:tab...) e le duas
    datatables ja presentes no DOM apos o expand (nao precisa clicar 'Visualizar
    Indicacoes'):
      - dtTblIndicacaoRecursosEmenda_data      -> Saldo, Valor Utilizado (agregado)
      - dtTblIndicacaoRecursosEmendaModal_data -> Nome, Indicacao(numero), Status
    Estrutura confirmada por captura do DOM logado (16/08/2026).

    SEMPRE try/except -> None: NAO pode propagar (o loop de detalhe aborta em 6
    falhas seguidas). Custa +1 clique/AJAX por convenio -> ligado por env
    SIGCON_INDICACOES=1 e cortado pelo orcamento (_sig_estourou)."""
    try:
        clicked = await page.evaluate(r"""() => {
            const h=[...document.querySelectorAll('[id^="accPnlPropostaPlanoTrabalho:tab"][id$="_head"]')]
                    .find(e=>/repasse de recursos/i.test(e.innerText||''));
            if(!h) return false;
            if(h.getAttribute('aria-expanded')!=='true') (h.querySelector('a')||h).click();
            return true;
        }""")
        if not clicked:
            return None
        await page.wait_for_timeout(2500)
        data = await page.evaluate(r"""() => {
            const tbById=(sfx)=>{for(const tb of document.querySelectorAll('tbody[id$="_data"]')){if(tb.id.includes(sfx))return tb;}return null;};
            const parse=(tb)=>{
                if(!tb) return {cab:[],rows:[]};
                const tbl=tb.closest('table');
                const cab=tbl?[...tbl.querySelectorAll('thead th')].map(t=>(t.innerText||'').trim()):[];
                const rows=[...tb.querySelectorAll('tr')].map(tr=>[...tr.querySelectorAll('td')].map(td=>(td.innerText||'').trim())).filter(r=>r.some(c=>c));
                return {cab, rows};
            };
            return {agg:parse(tbById('dtTblIndicacaoRecursosEmenda_data')),
                    ind:parse(tbById('dtTblIndicacaoRecursosEmendaModal_data'))};
        }""")
        agg = data.get("agg") or {"cab": [], "rows": []}
        ind = data.get("ind") or {"cab": [], "rows": []}
        # ignora "Nenhum Registro Encontrado."
        agg_rows = [r for r in agg["rows"] if not (len(r) == 1 and "nenhum" in (r[0] or "").lower())]
        ind_rows = [r for r in ind["rows"] if not (len(r) == 1 and "nenhum" in (r[0] or "").lower())]
        if not agg_rows and not ind_rows:
            return None

        def col(cab, *frags):
            for i, h in enumerate(cab):
                hl = (h or "").lower()
                if any(f in hl for f in frags):
                    return i
            return None

        out: dict = {}
        if agg_rows:
            r = agg_rows[0]
            ci_sal = col(agg["cab"], "saldo")
            ci_val = col(agg["cab"], "valor utilizado")
            if ci_sal is not None and ci_sal < len(r):
                out["indic_saldo_str"] = r[ci_sal]
            if ci_val is not None and ci_val < len(r):
                out["indic_valor_utilizado_str"] = r[ci_val]
        if ind_rows:
            ci_num = col(ind["cab"], "indica")   # coluna "Indicação"
            ci_nom = col(ind["cab"], "respons")
            ci_sta = col(ind["cab"], "status")
            r = ind_rows[0]
            if ci_num is not None and ci_num < len(r):
                out["nr_indicacao"] = (r[ci_num] or "").strip() or None
            if ci_nom is not None and ci_nom < len(r):
                out["indic_nome_responsavel"] = (r[ci_nom] or "").strip() or None
            if ci_sta is not None and ci_sta < len(r):
                out["indic_status"] = (r[ci_sta] or "").strip() or None
            out["indicacoes"] = [
                {"nr_indicacao": (rr[ci_num].strip() if ci_num is not None and ci_num < len(rr) else None),
                 "nome_responsavel": (rr[ci_nom].strip() if ci_nom is not None and ci_nom < len(rr) else None),
                 "status": (rr[ci_sta].strip() if ci_sta is not None and ci_sta < len(rr) else None)}
                for rr in ind_rows
            ]
        return out or None
    except Exception:
        return None


async def _scrape_alteracoes(page) -> dict | None:
    """Ultima alteracao do convenio (secao 'ALTERAÇÕES DO CONVÊNIO'):
    nr_controle, tipo, situacao, data, titulo, usuario. None se nao houver / erro.

    Datatable dtTblListaAlteracaoConvenio_data (id estavel), colunas mapeadas por
    CABECALHO. Estrutura confirmada por captura do DOM logado (16/08/2026):
    [Nº Controle, Tipo, Situação, Data Cadastro, Título Alteração, Usuário, Ações].
    Escolhe a linha de MAIOR Data Cadastro (a mais recente) — nao confia na ordem.

    SEMPRE try/except -> None (nao propaga; o loop de detalhe aborta em 6 falhas).
    Ligado por env SIGCON_INDICACOES=1, cortado pelo orcamento (_sig_estourou)."""
    import re as _re
    try:
        clicked = await page.evaluate(r"""() => {
            const h=[...document.querySelectorAll('[id^="accPnlPropostaPlanoTrabalho:tab"][id$="_head"]')]
                    .find(e=>/altera[cç][aã]o|altera..es do conv/i.test(e.innerText||''));
            if(!h) return false;
            if(h.getAttribute('aria-expanded')!=='true') (h.querySelector('a')||h).click();
            return true;
        }""")
        if not clicked:
            return None
        await page.wait_for_timeout(2500)
        data = await page.evaluate(r"""() => {
            let tb=null;
            for(const t of document.querySelectorAll('tbody[id$="_data"]')){if(t.id.includes('dtTblListaAlteracaoConvenio_data')){tb=t;break;}}
            if(!tb) return null;
            const tbl=tb.closest('table');
            const cab=tbl?[...tbl.querySelectorAll('thead th')].map(t=>(t.innerText||'').trim()):[];
            const rows=[...tb.querySelectorAll('tr')].map(tr=>[...tr.querySelectorAll('td')].map(td=>(td.innerText||'').trim())).filter(r=>r.some(c=>c));
            return {cab, rows};
        }""")
        if not data or not data.get("rows"):
            return None
        rows = [r for r in data["rows"] if not (len(r) == 1 and "nenhum" in (r[0] or "").lower())]
        if not rows:
            return None
        cab = data.get("cab") or []

        def col(*frags):
            for i, h in enumerate(cab):
                hl = (h or "").lower()
                if any(f in hl for f in frags):
                    return i
            return None

        ci_ctrl, ci_tipo, ci_sit = col("controle"), col("tipo"), col("situa")
        ci_data, ci_tit, ci_usu = col("data"), col("tulo", "titulo"), col("usu")

        def g(r, i):
            return (r[i].strip() if (i is not None and i < len(r)) else None) or None

        def keydata(r):
            v = g(r, ci_data) or ""
            m = _re.search(r"(\d{2})/(\d{2})/(\d{4})", v)
            return (m.group(3) + m.group(2) + m.group(1)) if m else ""

        r0 = max(rows, key=keydata) if ci_data is not None else rows[0]
        out = {
            "ultima_alteracao_nr_controle": g(r0, ci_ctrl),
            "ultima_alteracao_tipo": g(r0, ci_tipo),
            "ultima_alteracao_situacao": g(r0, ci_sit),
            "ultima_alteracao_data": g(r0, ci_data),
            "ultima_alteracao_titulo": g(r0, ci_tit),
            "ultima_alteracao_usuario": g(r0, ci_usu),
        }
        return out if any(out.values()) else None
    except Exception:
        return None


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
        # Cauda 2/3: loop de detalhes. Cada registro custa varios segundos (clique
        # via DOM + re-estabelecimento da grade); sem corte, uma credencial com
        # muitos planos come a rodada toda.
        if _sig_estourou():
            logger.info(f"  [orcamento] detalhes cortados em {idx}/{iter_count} "
                        f"— {len(out)} ja capturados ficam gravados")
            break
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
            # EXTRAS por env SIGCON_INDICACOES=1 (default off): expande as secoes
            # de accordion e le a INDICACAO parlamentar (nr_indicacao/saldo/valor)
            # e a ULTIMA ALTERACAO. Cada helper e try/except->None (nao propaga) e
            # so roda se ainda ha orcamento. Os campos entram no `data` e fluem
            # para raw_data (merge no upsert), sem tocar no INSERT posicional.
            if data and (os.getenv("SIGCON_INDICACOES", "0") or "0").strip() == "1" and not _sig_estourou():
                _ind = await _scrape_indicacoes(page)
                if _ind:
                    data.update(_ind)
                _alt = await _scrape_alteracoes(page)
                if _alt:
                    data.update(_alt)
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
        # O corte da paginacao interna so sai de UM ano; sem este, o laco seguiria
        # para o proximo ano e o orcamento nao seria respeitado de fato.
        if _sig_estourou():
            logger.info(f"  [orcamento] emendas interrompidas antes do ano {ano}")
            break
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
            # Cauda 3/3: paginacao dentro de cada ano de emendas. Como o laco
            # externo ja percorre varios anos, sem corte aqui o custo e
            # (anos x paginas) e nao ha teto nenhum.
            if _sig_estourou():
                logger.info(f"  [orcamento] emendas cortadas no ano {ano} pag {page_n}")
                break
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


FONTE_COLETA = "sigcon"


def _marca_coleta(municipio_id: int, ok: bool, erro: str | None = None,
                  fonte: str = FONTE_COLETA) -> None:
    """Registra que este municipio foi coletado (ou falhou) agora.

    E o que alimenta o rodizio: a proxima rodada ordena por `ultima_coleta_em`
    NULLS FIRST, entao quem acabou de ser coletado vai para o fim da fila e quem
    esta parado ha mais tempo vem primeiro. Best-effort: se a tabela ainda nao
    existir (worker subiu antes da migration da API), apenas ignora -- o scraper
    nao pode quebrar por causa da contabilidade do rodizio.

    `fonte` permite carimbos por DATASET dentro do mesmo run: 'sigcon_emendas'
    registra a coleta de emendas separada da de convenios, porque a falha de
    _scrape_emendas e engolida (warning) e o carimbo compartilhado diria
    "fresco" para a tela de Emendas com o dado congelado — a mesma cegueira do
    incidente do CAGEC de 01/08. O rodizio continua lendo so fonte='sigcon'.
    """
    import psycopg2
    try:
        conn = psycopg2.connect(_sync_dsn())
        try:
            with conn.cursor() as cur:
                if ok:
                    # tentativas=0 TAMBEM no INSERT: `tentativas` significa
                    # "falhas consecutivas", e a 1a coleta boa de um municipio
                    # novo nao e falha nenhuma. Com 1 aqui, o municipio nascia
                    # marcado como 'em falha' para o monitor de staleness ate a
                    # 2a coleta boa (so o ON CONFLICT zerava).
                    cur.execute(
                        "INSERT INTO scraper_municipio_coleta "
                        "(fonte, municipio_id, ultima_coleta_em, tentativas) "
                        "VALUES (%s, %s, now(), 0) "
                        "ON CONFLICT (fonte, municipio_id) DO UPDATE SET "
                        "ultima_coleta_em = now(), tentativas = 0, ultimo_erro = NULL",
                        (fonte, municipio_id),
                    )
                else:
                    # CARIMBA ultima_coleta_em TAMBEM NO ERRO. Antes so o sucesso
                    # carimbava e, como a fila ordena NULLS FIRST, um municipio que
                    # falha login DETERMINISTICAMENTE ficava eternamente em 1o lugar:
                    # abria TODA rodada, queimava ~40s, e empurrava os saudaveis para
                    # fora da janela. Medido na Freitas: 7 municipios nunca coletaram
                    # (Espinosa com 183 tentativas) e seguiam furando a fila todo dia.
                    # Carimbando aqui, a fila vira round-robin honesto; o diagnostico
                    # do problema fica em ultimo_erro/tentativas, nao na ordenacao.
                    cur.execute(
                        "INSERT INTO scraper_municipio_coleta "
                        "(fonte, municipio_id, ultima_coleta_em, ultimo_erro_em, ultimo_erro, tentativas) "
                        "VALUES (%s, %s, now(), now(), %s, 1) "
                        "ON CONFLICT (fonte, municipio_id) DO UPDATE SET "
                        "ultima_coleta_em = now(), "
                        "ultimo_erro_em = now(), ultimo_erro = EXCLUDED.ultimo_erro, "
                        "tentativas = scraper_municipio_coleta.tentativas + 1",
                        (fonte, municipio_id, (erro or "")[:500]),
                    )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.debug(f"  (rodizio nao registrado p/ municipio {municipio_id}: {e})")


def _list_credentials() -> list[dict]:
    """Le credenciais SIGCON-MG do cofre, descriptografando.

    ORDEM = MAIS DESATUALIZADO PRIMEIRO (rodizio). Antes a ordem era a que o
    banco devolvia (na pratica alfabetica) e, como a rodada do Freitas nao cabe
    na janela do cron, os municipios do fim da lista NUNCA eram coletados. Com o
    rodizio, uma rodada parcial deixa de ser perda permanente: os que ficaram de
    fora entram na frente na proxima.
    """
    import psycopg2
    from services.crypto import decrypt
    sync_url = os.getenv("DATABASE_URL_SYNC", "")
    sync_url = sync_url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    conn = psycopg2.connect(sync_url)
    cur = conn.cursor()
    # ⭐⭐ TETO DE TENTATIVAS DE LOGIN — ordem do dono (11/08/2026):
    # "nao fique insistindo demais no login e senha nos portais, senao causa
    #  problema e da ban ou algo assim; testa no maximo umas 3 vezes, foi
    #  recusado, ja avisa que eu vejo o que e".
    #
    # ⚠️ E o risco e REAL e ja estava correndo: Piracema e Ribeirao das Neves
    # acumularam 58 tentativas de login cada uma (e Espinosa chegou a 183 antes
    # de sair da carteira). Portal de governo com dezenas de logins falhos da
    # mesma origem bloqueia a CONTA — e ai o municipio para de coletar mesmo
    # depois de a senha ser corrigida.
    #
    # O backoff (1 dia por tentativa, ate 5) ESPACA, mas nunca PARA. Este teto
    # para de vez: passou de 3 recusas de LOGIN, o municipio sai da fila e fica
    # esperando credencial nova.
    #
    # ⚠️ SO CONTA RECUSA DE LOGIN, e a distincao importa: timeout de rede,
    # portal fora do ar ou erro de parsing NAO sao motivo para desistir de um
    # municipio para sempre — esses continuam no rodizio normal, so espacados
    # pelo backoff. O filtro casa o texto que `_marca_coleta` grava quando o
    # formulario nao autentica.
    #
    # O CAMINHO DE VOLTA e automatico e sem SQL: salvar a senha no Cofre zera
    # `tentativas` (routers/cofre.py::_destravar_rodizio), e o municipio volta
    # para a fila na rodada seguinte — na FRENTE, porque `ultima_coleta_em`
    # continua antiga.
    _MAX_LOGIN = max(1, int(os.getenv("SIGCON_MAX_TENTATIVAS_LOGIN", "3") or "3"))
    _SQL_BASE = """
        SELECT cs.id, cs.municipio_id, cs.usuario, cs.senha_hash, m.nome
        FROM cofre_senhas cs
        JOIN municipios m ON m.id = cs.municipio_id
        {join}
        WHERE (cs.sistema ILIKE 'SIGCON%' OR cs.automation_key = 'sigcon')
        {teto}
        {order}
    """
    _TETO = ("AND NOT (COALESCE(sc.tentativas, 0) >= " + str(_MAX_LOGIN) +
             " AND COALESCE(sc.ultimo_erro, '') ILIKE '%login%')")
    try:
        # BACKOFF por falha consecutiva: quem falha login toda rodada (credencial
        # invalida/trocada) e adiado progressivamente — 1 dia por tentativa, ate 5.
        # Sem isso, mesmo com o carimbo no erro, um municipio quebrado volta ao topo
        # da fila em poucas horas e continua roubando janela dos saudaveis. Tambem
        # reduz o risco de lockout no portal por tentativas repetidas (Espinosa ja
        # acumulou 183). `tentativas` zera no primeiro sucesso, entao a punicao some
        # sozinha quando a credencial for corrigida.
        cur.execute(_SQL_BASE.format(
            join=("LEFT JOIN scraper_municipio_coleta sc "
                  "ON sc.municipio_id = cs.municipio_id AND sc.fonte = 'sigcon'"),
            teto=_TETO,
            order=("ORDER BY (COALESCE(sc.ultima_coleta_em, sc.ultimo_erro_em, TIMESTAMPTZ 'epoch') "
                   "          + (LEAST(COALESCE(sc.tentativas,0), 5) * INTERVAL '1 day')) ASC, "
                   "         m.nome"),
        ))
    except Exception:
        # Tabela do rodizio ainda nao migrada: cai no comportamento antigo.
        conn.rollback()
        cur.execute(_SQL_BASE.format(join="", teto="", order="ORDER BY m.nome"))
        logger.warning("  rodizio indisponivel (scraper_municipio_coleta ausente) - ordem alfabetica")
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
    # ⭐ QUEM FICOU DE FORA PELO TETO — parar em silencio seria trocar um
    # problema (risco de bloqueio) por outro (municipio parado sem ninguem
    # saber). O nome sai no log de TODA rodada, e o watchdog transforma isso em
    # alerta agregado.
    try:
        cur.execute(
            "SELECT m.nome, sc.tentativas, sc.ultimo_erro_em::date "
            "FROM scraper_municipio_coleta sc JOIN municipios m ON m.id = sc.municipio_id "
            "WHERE sc.fonte = 'sigcon' AND COALESCE(sc.tentativas,0) >= %s "
            "  AND COALESCE(sc.ultimo_erro, '') ILIKE '%%login%%' "
            "ORDER BY m.nome", (_MAX_LOGIN,))
        parados = cur.fetchall()
        if parados:
            logger.warning(
                "  ⚠️ %d municipio(s) FORA da fila por credencial recusada "
                "(teto de %d tentativas de login, para nao arriscar bloqueio no "
                "portal): %s — corrigir a senha no Cofre religa sozinho",
                len(parados), _MAX_LOGIN,
                "; ".join(f"{n} ({t}x, desde {d})" for n, t, d in parados))
    except Exception:
        conn.rollback()
    conn.close()
    return creds


def _upsert_convenios_batch(cur, records) -> tuple[int, int]:
    """UPSERT de uma leva de convenios estaduais (records=[(mun_id, rec)]).

    SAVEPOINT por registro (1 erro nao descarta os demais). Retorna
    (inseridos, atualizados). Chamado POR MUNICIPIO -> persistencia INCREMENTAL:
    se o scrape for interrompido, o que ja foi coletado permanece no banco
    (antes so gravava no fim: 3h de cron sem escrever 1 linha).
    """
    from datetime import date
    inserted = updated = 0
    for mun_id, rec in records:
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
        nr_prop = (rec.get("nr_proposta") or "").strip() or None
        # ⭐⭐ A CHAVE DE DEDUPE E O NUMERO DA PROPOSTA (11/08/2026).
        #
        # Ate aqui a chave era `nr_sigcon`, que MUDA DE VALOR durante a vida do
        # convenio: enquanto esta em celebracao vale o nº do plano; quando e
        # assinado, passa a valer o nº SIAFI. Chave que muda nao e chave — o
        # upsert nao achava a linha antiga e INSERIA UMA SEGUNDA. Medido no
        # freitas: 6 convenios em duplicata, R$ 1.563.275,67 contados em dobro,
        # e o dono viu na tela "4 convenios" que eram 2.
        #
        # `nr_proposta` nasce no cadastramento, nunca muda e esta preenchido em
        # 100% das linhas (contra 58% do SIAFI). E o unico identificador estavel
        # do ciclo inteiro. Ver migrations/fix_duplicatas_chave_natural.sql.
        #
        # ⚠️ INDICE PARCIAL EXIGE REPETIR O PREDICADO no ON CONFLICT — a mesma
        # armadilha que ja travou o SIGCON por 24 dias, calada, com o nr_siafi.
        if nr_prop:
            conflict_target = ("(municipio_id, nr_proposta) WHERE fonte = 'SIGCON-MG' "
                               "AND nr_proposta IS NOT NULL AND btrim(nr_proposta) <> ''")
        elif nr_siafi:
            conflict_target = "(nr_siafi) WHERE nr_siafi IS NOT NULL AND nr_siafi <> ''"
        else:
            conflict_target = "(nr_sigcon)"
        try:
            # SAVEPOINT por registro: erro em 1 nao descarta os anteriores
            # (antes, conn.rollback() perdia TODO o batch desde o ultimo commit)
            cur.execute("SAVEPOINT sp_conv")
            cur.execute(f"""
                INSERT INTO convenios_estadual (
                    nr_sigcon, nr_siafi, nr_proposta, municipio_id, orgao_concedente,
                    convenente_nome, objeto, situacao,
                    valor_concedente, valor_total, valor_repassado, valor_contrapartida,
                    raw_data, tp_instrumento,
                    nr_plano_trabalho, ano, dt_publicacao,
                    dt_assinatura, dt_vigencia_inicial, dt_vigencia_atual,
                    dt_vigencia_final, qt_alteracoes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT {conflict_target} DO UPDATE SET
                    -- ⭐ `nr_sigcon` e `nr_siafi` PROMOVEM (EXCLUDED vence) em vez
                    -- de congelar: e a linha em celebracao que RECEBE o numero
                    -- SIAFI quando o convenio e assinado. Com o COALESCE
                    -- invertido de antes, o numero novo nunca entrava — e era
                    -- exatamente por isso que nascia uma segunda linha.
                    nr_sigcon = COALESCE(EXCLUDED.nr_sigcon, convenios_estadual.nr_sigcon),
                    nr_siafi = COALESCE(EXCLUDED.nr_siafi, convenios_estadual.nr_siafi),
                    nr_proposta = COALESCE(EXCLUDED.nr_proposta, convenios_estadual.nr_proposta),
                    situacao = EXCLUDED.situacao,
                    valor_concedente = COALESCE(EXCLUDED.valor_concedente, convenios_estadual.valor_concedente),
                    -- ⚠️ valor_total RECOMPUTADO, e nao apenas preservado.
                    -- O COALESCE simples mantinha o total ANTIGO sempre que a
                    -- rodada nao trouxesse total novo — e era exatamente esse o
                    -- caso do defeito: o backfill do CKAN grava o total com so
                    -- a parte do concedente, e a coleta seguinte preenche a
                    -- CONTRAPARTIDA sem refazer a soma. A tela somava
                    -- 7.000.000 + 728.020,41 e exibia 7.000.000, em 258 linhas.
                    -- Sem esta mudanca, a migration que corrige o passado seria
                    -- desfeita pela proxima coleta.
                    -- Se as DUAS parcelas forem desconhecidas, nao ha o que
                    -- somar e o comportamento antigo vale.
                    valor_total = CASE
                        WHEN COALESCE(EXCLUDED.valor_concedente, convenios_estadual.valor_concedente) IS NULL
                         AND COALESCE(EXCLUDED.valor_contrapartida, convenios_estadual.valor_contrapartida) IS NULL
                        THEN COALESCE(EXCLUDED.valor_total, convenios_estadual.valor_total)
                        ELSE COALESCE(EXCLUDED.valor_concedente, convenios_estadual.valor_concedente, 0)
                           + COALESCE(EXCLUDED.valor_contrapartida, convenios_estadual.valor_contrapartida, 0)
                      END,
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
                (nr_prop or "")[:50] or None,
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
                try:
                    cur.connection.rollback()  # fallback se a conexao inteira caiu
                except Exception:
                    pass
            continue
    return inserted, updated


def _upsert_emendas_batch(cur, emendas) -> tuple[int, int]:
    """UPSERT de uma leva de emendas estaduais (emendas=[(mun_id, em)]).

    Mesma politica de SAVEPOINT por registro do _upsert_convenios_batch.
    """
    em_inserted = em_updated = 0
    for mun_id, em in emendas:
        nr_ind = em.get("nr_indicacao")
        ano_em = em.get("ano")
        # ⚠️ `ano` DEIXOU DE SER IDENTIDADE (11/08/2026) e por isso nao barra
        # mais a linha: ele e o ano do FILTRO do dropdown, nao um atributo da
        # indicacao (a tabela de origem nao tem coluna de ano). Enquanto ele
        # esteve na chave unica, a mesma indicacao lida sob dois filtros virava
        # duas linhas — 195 linhas fantasma e R$ 74,7 mi de inflacao no freitas.
        if not nr_ind or not mun_id:
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
                ON CONFLICT (municipio_id, nr_indicacao) DO UPDATE SET
                    -- ⚠️ LEAST e nao EXCLUDED: sem isso, cada passada do laco
                    -- 2022->2026 reescreveria o ano da MESMA linha e o registro
                    -- ficaria oscilando de ano a cada rodada. LEAST fixa no
                    -- primeiro ano em que a fonte reportou a indicacao (o
                    -- correto) e torna o upsert idempotente e independente da
                    -- ordem do laco. LEAST ignora NULL no Postgres.
                    ano = LEAST(emendas_estaduais.ano, EXCLUDED.ano),
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
                mun_id, nr_ind[:50], em.get("nome_responsavel", "")[:300],
                em.get("tipo_indicacao", "")[:100],
                em.get("uo_codigo", "")[:20], em.get("uo_sigla", "")[:50],
                em.get("cnpj_beneficiario", "")[:20], em.get("beneficiario", "")[:300],
                em.get("grupo_despesa", "")[:200], em.get("tipo_atendimento", "")[:300],
                em.get("valor_indicacao"), em.get("status_indicacao", "")[:50],
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
                try:
                    cur.connection.rollback()
                except Exception:
                    pass
            continue
    return em_inserted, em_updated


def _sync_dsn() -> str:
    """DSN psycopg2 (Neon usa channel_binding=require, que psycopg2 nao suporta)."""
    dsn = os.getenv("DATABASE_URL_SYNC", "")
    return dsn.replace("&channel_binding=require", "").replace("?channel_binding=require", "")


async def _scrape_one(browser, cred, anos_emendas, sem, deadline=None):
    """Raspa 1 municipio (login proprio) + PERSISTE com conexao propria.

    Permite rodar municipios EM PARALELO: psycopg2 nao e seguro p/ cursores
    concorrentes na mesma conexao, por isso 1 conexao por tarefa. Isolado:
    falha de 1 municipio nao derruba os outros, e o que ja foi gravado fica
    gravado. Retorna (nome, ins, upd, em_ins, em_upd, ok).

    `deadline` (time.monotonic) e o orcamento da rodada: se ja passou, este
    municipio NAO comeca. Parar por conta propria antes do teto e melhor que ser
    morto pelo `timeout` do cron no meio de um login -- o que ja foi coletado
    fica gravado, o rodizio registra quem faltou e a proxima rodada os prioriza.
    """
    import psycopg2
    nome = cred["municipio_nome"]
    async with sem:
        if deadline is not None and time.monotonic() >= deadline:
            logger.info(f"  [orcamento esgotado] {nome} adiado para a proxima rodada")
            return (nome, 0, 0, 0, 0, None)  # None = nem tentou (nao conta como falha)
        logger.info(f"=== Login: {nome} (CPF={cred['cpf'][:4]}***) ===")
        ctx = await browser.new_context(
            ignore_https_errors=True, accept_downloads=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0) Chrome/131 Safari/537.36",
        )
        page = await ctx.new_page()
        try:
            await _login(page, cred["cpf"], cred["senha"])
            rows = await _scrape_municipio(page, _norm(nome))
            detalhes: dict = {}
            try:
                # Tunavel por env: em maquina apertada da para baixar o teto e
                # cobrir mais municipios por rodada (o rodizio garante que todos
                # sao visitados ao longo das rodadas seguintes).
                try:
                    _max_planos = max(1, int(os.getenv("SIGCON_MAX_PLANOS", "100") or "100"))
                except ValueError:
                    _max_planos = 100
                detalhes = await _scrape_detalhes(page, max_planos=_max_planos)
            except Exception as e:
                logger.warning(f"  Detalhes failed ({nome}): {e}")
            by_key: dict = {}
            mun_records: list = []
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
                    mun_records.append((cred["municipio_id"], r))
                    continue
                if key in by_key:
                    existing = by_key[key]
                    for k, v in r.items():
                        if v and not existing.get(k):
                            existing[k] = v
                else:
                    by_key[key] = r
            mun_records += [(cred["municipio_id"], r) for r in by_key.values()]

            # Emendas ANTES de abrir a conexao — o scrape (login+detalhes+emendas)
            # leva 10-20 min; se a conexao fosse aberta no inicio, ficaria ociosa
            # e o Neon/Postgres a fecharia por idle timeout ("connection already
            # closed"). Abrimos SO AGORA (fresca) p/ gravar rapido e fechar.
            emendas = []
            emendas_erro: str | None = None
            try:
                emendas = await _scrape_emendas(page, anos_emendas)
            except Exception as e:
                logger.warning(f"  Emendas falharam para {nome}: {e}")
                emendas_erro = str(e)

            conn = psycopg2.connect(_sync_dsn())
            try:
                cur = conn.cursor()
                i, u = _upsert_convenios_batch(cur, mun_records)
                conn.commit()
                ei, eu = _upsert_emendas_batch(
                    cur, [(cred["municipio_id"], e) for e in emendas])
                conn.commit()
            finally:
                # Fecha SEMPRE: se um UPSERT estourar no meio, a conexao nao pode
                # ficar pendurada ate o processo morrer.
                try:
                    conn.close()
                except Exception:
                    pass
            logger.info(f"  {nome}: {len(mun_records)} convenios (+{i}/~{u}) | "
                        f"emendas +{ei}/~{eu}")
            _marca_coleta(cred["municipio_id"], ok=True)
            # Carimbo do DATASET de emendas (ver docstring de _marca_coleta):
            # o selo da tela de Emendas responde por ESTA coleta, sem punir a
            # tela de Convenios quando so as emendas quebram (e vice-versa).
            _marca_coleta(cred["municipio_id"], ok=emendas_erro is None,
                          erro=(f"emendas: {emendas_erro[:300]}" if emendas_erro else None),
                          fonte="sigcon_emendas")
            return (nome, i, u, ei, eu, True)
        except Exception as e:
            logger.error(f"  Falha {nome}: {e}")
            _marca_coleta(cred["municipio_id"], ok=False, erro=str(e))
            return (nome, 0, 0, 0, 0, False)
        finally:
            try:
                await ctx.close()
            except Exception:
                pass


async def _run():
    from playwright.async_api import async_playwright

    creds = _list_credentials()
    if not creds:
        logger.warning("Nenhuma credencial SIGCON-MG no cofre - cadastre via UI")
        # Grava a rodada no ingestion_log MESMO sem credencial: sem esta linha,
        # o watchdog acusaria 'nenhum sucesso registrado ainda' para sempre num
        # tenant que simplesmente nao tem SIGCON (ex.: Trust) — e credencial
        # ausente e nota, nao alarme.
        import psycopg2
        try:
            _c0 = psycopg2.connect(_sync_dsn())
            with _c0.cursor() as _cu0:
                _cu0.execute(
                    "INSERT INTO ingestion_log (source, status, records_processed, "
                    "records_inserted, records_updated, error_message, finished_at) "
                    "VALUES ('sigcon_scraper', 'success', 0, 0, 0, "
                    "'sem credenciais SIGCON cadastradas', NOW())")
            _c0.commit(); _c0.close()
        except Exception as e:
            logger.warning(f"  ingestion_log falhou: {str(e)[:120]}")
        return

    # Filtro opcional: SIGCON_ONLY="Nome1,Nome2" reprocessa so esses municipios
    # (util p/ re-tentar quem falhou no login sem re-scrapear todos). Default = todos.
    _only = os.getenv("SIGCON_ONLY", "").strip()
    if _only:
        _wanted = {_norm(x) for x in _only.split(",") if x.strip()}
        creds = [c for c in creds if _norm(c["municipio_nome"]) in _wanted]
        logger.info(f"SIGCON_ONLY ativo: {[c['municipio_nome'] for c in creds]}")

    # LOTE POR RODADA: com a fila ja ordenada por rodizio+backoff, basta cortar os
    # N primeiros. Rodadas curtas e FREQUENTES cobrem a carteira melhor do que
    # poucas rodadas longas — foi o que resolveu o TransfereGov (PR #158): la a
    # rodada unica nunca terminava, e fatiada passou a entregar 41/41 frescos.
    # Aqui o efeito e o mesmo: em vez de 4 janelas/dia que cobrem ~11 municipios,
    # varias janelas menores somam mais cobertura e nenhuma morre no meio.
    # 0 ou vazio = sem corte (comportamento antigo).
    try:
        _lote = max(0, int(os.getenv("SIGCON_LOTE_MUNICIPIOS", "0") or "0"))
    except ValueError:
        _lote = 0
    if _lote and len(creds) > _lote:
        creds = creds[:_lote]
        logger.info(f"LOTE: {len(creds)} municipio(s) desta rodada (mais desatualizados): "
                    f"{[c['municipio_nome'] for c in creds]}")

    mun_map = _municipio_id_lookup()
    logger.info(f"Credenciais SIGCON-MG: {len(creds)}, municipios DB: {len(mun_map)}")

    anos_emendas = list(range(2022, datetime.now().year + 1))  # 2022..ano atual
    # PARALELO + INCREMENTAL: cada municipio roda na sua propria tarefa
    # (_scrape_one), com contexto Playwright e conexao DB proprios; o semaforo
    # limita quantos rodam ao mesmo tempo. A persistencia acontece dentro da
    # tarefa -> uma interrupcao (deploy, timeout do cron, kill) preserva tudo o
    # que ja foi coletado, em vez de perder a rodada inteira.
    # Tunavel por env SIGCON_CONCURRENCY (default 2; 1 = sequencial como antes).
    # Default conservador: o host e uma t3.large (2 vCPU) compartilhada pelos
    # workers dos 3 tenants; cada tarefa sobe um contexto Chromium proprio.
    # Suba para 3+ (valor usado no piloto) se houver folga de CPU/memoria.
    try:
        conc = max(1, int(os.getenv("SIGCON_CONCURRENCY", "2") or "2"))
    except ValueError:
        conc = 2
    conc = min(conc, len(creds))

    # ORCAMENTO DA RODADA. As Scheduled Tasks rodam sob `timeout -k 30 3000`
    # (50 min). Deixar o `timeout` matar significa morrer no meio de um login,
    # possivelmente deixando Chromium para tras. Melhor parar por conta propria
    # ANTES: o que ja foi coletado esta gravado (persistencia e por municipio),
    # o rodizio anota quem faltou, e a proxima rodada comeca por eles.
    # Default 2700s = 45 min, 5 min abaixo do teto externo.
    try:
        budget = max(0, int(os.getenv("SIGCON_BUDGET_SECONDS", "2700") or "2700"))
    except ValueError:
        budget = 2700
    deadline = (time.monotonic() + budget) if budget else None
    # Publica o deadline para os loops longos DENTRO de cada credencial
    # (paginacao da listagem, detalhes, emendas). Antes so `_scrape_one` o
    # enxergava, e uma credencial pesada estourava o teto externo.
    _SIG_DEADLINE["t"] = deadline

    logger.info(
        f"SIGCON: {len(creds)} municipios | concorrencia={conc} | "
        f"orcamento={budget}s | ordem=mais desatualizado primeiro"
    )
    if creds:
        logger.info(f"  primeiros da fila: {[c['municipio_nome'] for c in creds[:5]]}")
    # CONFIRMADO empiricamente: a Pesquisa Unificada do SIGCON-MG eh ESCOPADA
    # ao convenente logado. Mesmo setando o filtro de municipio corretamente
    # (option value = codigo IBGE), o login de Araujos retorna 0 convenios de
    # Piracema/Nova Serrana/etc. Ou seja: cada municipio EXIGE seu proprio login
    # SIGCON (CPF+senha do convenente). Hoje so existe credencial de Araujos no
    # Cofre -> por isso so Araujos tem convenios/parlamentar estaduais.
    # Solucao p/ os demais: cadastrar 1 credencial SIGCON por municipio.
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--ignore-certificate-errors", "--disable-dev-shm-usage"])
        try:
            sem = asyncio.Semaphore(conc)
            raw = await asyncio.gather(
                *[_scrape_one(browser, c, anos_emendas, sem, deadline) for c in creds],
                return_exceptions=True,  # 1 tarefa explodindo nao invalida as demais
            )
        finally:
            await browser.close()

    results = []
    for c, r in zip(creds, raw):
        if isinstance(r, BaseException):
            logger.error(f"  Falha {c['municipio_nome']}: {r}")
            results.append((c["municipio_nome"], 0, 0, 0, 0, False))
        else:
            results.append(r)

    tot_ins = sum(r[1] for r in results)
    tot_upd = sum(r[2] for r in results)
    tot_em_ins = sum(r[3] for r in results)
    tot_em_upd = sum(r[4] for r in results)
    # Tres estados distintos, nao dois: ok / falhou / nem tentou (orcamento).
    # Misturar "adiado" com "falhou" mentiria no relatorio -- adiado e o
    # comportamento CORRETO do rodizio, nao um erro.
    muns_ok = sum(1 for r in results if r[5] is True)
    falhas = [r[0] for r in results if r[5] is False]
    adiados = [r[0] for r in results if r[5] is None]
    if adiados:
        logger.info(
            f"  ORCAMENTO: {len(adiados)} municipio(s) adiado(s) para a proxima "
            f"rodada (entram primeiro no rodizio): {adiados[:10]}"
            + (" ..." if len(adiados) > 10 else "")
        )

    # Status HONESTO, nao 'success' incondicional. Antes, uma rodada em que TODO
    # login falhava (ou sem credencial nenhuma) gravava 'success' e deixava o
    # watchdog e o painel de frescor verdes com a fonte quebrada. Regras:
    #   - >=1 municipio ok -> success (falha pontual de login e NOTA em
    #     error_message, nao alarme: rodizio+backoff ja tratam, e credencial
    #     quebrada nao trava o jogo);
    #   - todos os tentados falharam -> erro (portal fora / bug / sessao);
    #   - nada tentado -> success com nota (sem credencial cadastrada, ou
    #     orcamento esgotado antes do 1o — comportamento correto do rodizio).
    _tentados = muns_ok + len(falhas)
    if _tentados == 0:
        _status = "success"
        # (creds vazio aqui so acontece via filtro SIGCON_ONLY: o caso "cofre
        #  vazio" ja retornou la em cima, com log proprio.)
        _msg = ("SIGCON_ONLY nao casou nenhuma credencial" if not creds
                else f"nenhum municipio tentado nesta rodada ({len(adiados)} adiado(s) pelo orcamento)")
    elif muns_ok == 0:
        _status = "erro"
        _msg = f"todas as {len(falhas)} tentativas falharam: {', '.join(falhas[:8])}"
    else:
        _status = "success"
        _msg = (f"{len(falhas)} falha(s) de login/scrape: {', '.join(falhas[:8])}"
                if falhas else None)

    # Log de ingestao final: conexao PROPRIA e curta (abre, grava, fecha).
    # Nunca reaproveita conexao do scrape — essa ja foi fechada ha muito tempo.
    import psycopg2
    _c = None
    try:
        _c = psycopg2.connect(_sync_dsn())
        _cu = _c.cursor()
        _cu.execute(
            "INSERT INTO ingestion_log (source, status, records_processed, "
            "records_inserted, records_updated, error_message, finished_at) "
            "VALUES ('sigcon_scraper', %s, %s, %s, %s, %s, NOW())",
            (_status, _tentados, tot_ins, tot_upd, _msg),
        )
        _c.commit()
    except Exception as e:
        logger.warning(f"  ingestion_log falhou: {str(e)[:200]}")
    finally:
        if _c is not None:
            try:
                _c.close()
            except Exception:
                pass

    logger.info(f"\n=== Convenios: {tot_ins} inseridos, {tot_upd} atualizados "
                f"(total {tot_ins + tot_upd}) em {muns_ok}/{len(creds)} municipios "
                f"(concorrencia {conc}) ===")
    if falhas:
        logger.warning(f"=== Falharam login/scrape ({len(falhas)}): {falhas} ===")
    logger.info(f"=== Emendas estaduais: {tot_em_ins} inseridas, {tot_em_upd} atualizadas ===")


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
