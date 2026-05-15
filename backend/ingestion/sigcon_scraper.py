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


async def _scrape_municipio(page, municipio_nome: str) -> list[dict]:
    """Faz pesquisa filtrada (ou nao-filtrada se usuario soh ve seu mun) + download CSV."""
    # Navega para Pesquisa Unificada
    await page.goto(SEARCH_URL, timeout=60000, wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)

    # Tenta selecionar municipio no dropdown PrimeFaces (UI label hidden as vezes)
    try:
        await page.evaluate("""(target) => {
            const sel = document.getElementById('frmListaPlanosDeTrabalho:selMunicipio_input');
            if (sel) {
                sel.value = target;
                sel.dispatchEvent(new Event('change', {bubbles: true}));
            }
        }""", municipio_nome)
    except Exception as e:
        logger.warning(f"  select municipio falhou (segue sem filtro): {e}")

    await page.wait_for_timeout(1500)

    # Pesquisar
    await page.click('button[id="frmListaPlanosDeTrabalho:cmdBtnPesquisarListaPlanosDeTrabalho"]')
    await page.wait_for_timeout(15000)

    # Download CSV
    async with page.expect_download(timeout=120000) as dl_info:
        await page.locator('button:has-text("CSV")').first.click()
    dl = await dl_info.value
    tmp_path = f"/tmp/sigcon_{_norm(municipio_nome).lower().replace(' ', '_')}.csv"
    if os.name == "nt":
        tmp_path = os.path.join(os.environ.get("TEMP", "C:/Windows/Temp"), os.path.basename(tmp_path))
    await dl.save_as(tmp_path)

    # Parse CSV (latin-1)
    import csv
    with open(tmp_path, encoding="latin-1") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Normaliza chaves (header em latin-1 com caracteres especiais)
    out = []
    for r in rows:
        # mapeia cols latin-1 (ex: 'N\xb0 do SIAFI') -> nomes limpos
        clean = {}
        for k, v in r.items():
            kk = (k or "").strip()
            kk_norm = _norm(kk)
            if "SIAFI" in kk_norm:
                clean["nr_siafi"] = (v or "").strip()
            elif "TIPO DE INSTRUMENTO" in kk_norm:
                clean["tipo"] = (v or "").strip()
            elif "CONCEDENTE" in kk_norm:
                clean["orgao"] = (v or "").strip()
            elif "CONVENENTE" in kk_norm or "OSC" in kk_norm:
                clean["convenente"] = (v or "").strip()
            elif "MUNIC" in kk_norm:
                clean["municipio"] = (v or "").strip()
            elif "VALOR" in kk_norm and "REPASSE" in kk_norm:
                clean["valor_repasse"] = _parse_money(v or "")
            elif "TITULO" in kk_norm or "T\xcdTULO" in kk_norm or "T?TULO" in kk_norm:
                clean["objeto"] = (v or "").strip()
            elif "STATUS" in kk_norm:
                clean["status"] = (v or "").strip()
            elif "CONTA" in kk_norm:
                clean["conta_bancaria"] = (v or "").strip()
            elif "REMESSA" in kk_norm:
                clean["remessa"] = (v or "").strip()
        if clean.get("convenente") or clean.get("nr_siafi") or clean.get("objeto"):
            out.append(clean)
    logger.info(f"  CSV parsed: {len(out)} convenios para {municipio_nome}")
    return out


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
    inserted = updated = 0
    for mun_id, rec in all_records:
        # nr_sigcon: usar SIAFI se existir, senao chave sintetica
        nr_sigcon = rec.get("nr_siafi") or f"SIGCON-PORTAL-{mun_id}-{abs(hash(rec.get('objeto') or '')) % 10**8}"
        sit_norm = _norm(rec.get("status") or "")
        sit_label = STATUS_MAP.get(sit_norm, rec.get("status"))
        try:
            cur.execute("""
                INSERT INTO convenios_estadual (
                    nr_sigcon, nr_siafi, municipio_id, orgao_concedente,
                    convenente_nome, objeto, situacao, valor_repassado,
                    raw_data, tp_instrumento
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                ON CONFLICT (nr_sigcon) DO UPDATE SET
                    situacao = EXCLUDED.situacao,
                    valor_repassado = COALESCE(EXCLUDED.valor_repassado, convenios_estadual.valor_repassado),
                    convenente_nome = COALESCE(EXCLUDED.convenente_nome, convenios_estadual.convenente_nome),
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
                rec.get("valor_repasse"),
                json.dumps({**rec, "_source": "sigcon_scraper"}, ensure_ascii=False, default=str),
                rec.get("tipo"),
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
