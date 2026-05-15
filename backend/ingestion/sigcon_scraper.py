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

    all_records = []  # [(municipio_db_id, dict)]
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
                    rows = await _scrape_municipio(page, _norm(cred["municipio_nome"]))
                    for r in rows:
                        all_records.append((cred["municipio_id"], r))
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
            if row and row[0]:
                inserted += 1
            else:
                updated += 1
        except Exception as e:
            logger.warning(f"  Erro UPSERT {nr_sigcon}: {str(e)[:200]}")
            conn.rollback()
            continue

    cur.execute(
        "INSERT INTO ingestion_log (source, status, records_inserted, finished_at) "
        "VALUES ('sigcon_scraper', 'success', %s, NOW())",
        (inserted + updated,)
    )
    conn.commit()
    conn.close()

    logger.info(f"\n=== Concluido: {inserted} inseridos, {updated} atualizados (total {inserted+updated}) ===")


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
