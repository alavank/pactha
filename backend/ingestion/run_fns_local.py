"""Rodada local AD-HOC do FNS scraper, sem service token.

Le cookies direto do Cofre (cofre_senhas WHERE automation_key='fns'),
chama API REST consultafns.saude.gov.br e UPSERT direto em
convenios_estadual (com fonte='FNS').

Uso:
    COFRE_KEY=... DATABASE_URL_SYNC=... python ingestion/run_fns_local.py
"""
import os
import sys
import json
import asyncio
import logging
from datetime import datetime
import httpx
import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import crypto

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fns_local")

BASE = "https://consultafns.saude.gov.br"

# Fallback: usado só se NENHUM municipio tiver fns_code configurado no banco.
FNS_CODE = {
    1: ("ARAUJOS", "310390"),
    2: ("NOVA SERRANA", "314520"),
    3: ("BOM DESPACHO", "310740"),
    4: ("SAO TIAGO", "316500"),
    5: ("TOLEDO", "316910"),
    6: ("PIRACEMA", "315060"),
}


def _load_fns_targets():
    """Municipios com codigo FNS configurado no banco (gerido pela Central).
    Fallback p/ o mapa hardcoded enquanto ninguem tiver configurado ainda."""
    try:
        conn = _db(); cur = conn.cursor()
        cur.execute("SELECT id, nome, fns_code FROM municipios "
                    "WHERE fns_code IS NOT NULL AND fns_code <> '' AND active = true ORDER BY nome")
        rows = cur.fetchall(); cur.close(); conn.close()
        if rows:
            return {r[0]: (r[1], r[2]) for r in rows}
    except Exception as e:
        log.warning(f"fns: nao li fns_code do banco ({e}); usando fallback hardcoded")
    return FNS_CODE

ANOS = list(range(2010, datetime.now().year + 1))


def _db():
    url = (os.getenv("DATABASE_URL_SYNC", "")
           .replace("&channel_binding=require", "")
           .replace("?channel_binding=require", ""))
    return psycopg2.connect(url)


def _load_fns_cookies():
    conn = _db(); cur = conn.cursor()
    cur.execute(
        "SELECT id, municipio_id, senha_hash FROM cofre_senhas "
        "WHERE automation_key='fns' AND length(senha_hash) > 1000 "
        "ORDER BY updated_at DESC LIMIT 1"
    )
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        return None
    dec = crypto.decrypt(row[2])
    if not dec or not dec.startswith("{"):
        return None
    data = json.loads(dec)
    cookies = data.get("cookies", [])
    return {c["name"]: c["value"] for c in cookies if c.get("name")}


def _upsert_items(items: list[dict]) -> int:
    if not items:
        return 0
    conn = _db(); cur = conn.cursor()
    sql = """
        INSERT INTO convenios_estadual
            (municipio_id, nr_sigcon, objeto, situacao, valor_total,
             valor_concedente, ano, fonte, orgao_concedente,
             nr_proposta, tipo_programa, raw_data, created_at, updated_at)
        VALUES (%(municipio_id)s, %(nr_proposta)s, %(objeto)s, %(situacao)s,
                %(valor)s, %(valor)s, %(ano)s, %(fonte)s, %(orgao_concedente)s,
                %(nr_proposta)s, %(tipo_programa)s, %(raw_data)s::jsonb,
                NOW(), NOW())
        ON CONFLICT (nr_sigcon) DO UPDATE SET
            situacao = EXCLUDED.situacao,
            valor_total = COALESCE(EXCLUDED.valor_total, convenios_estadual.valor_total),
            valor_concedente = COALESCE(EXCLUDED.valor_concedente, convenios_estadual.valor_concedente),
            objeto = COALESCE(EXCLUDED.objeto, convenios_estadual.objeto),
            raw_data = EXCLUDED.raw_data,
            updated_at = NOW()
    """
    n = 0
    for it in items:
        try:
            cur.execute(sql, {**it, "raw_data": json.dumps(it.get("raw_data", {}), ensure_ascii=False)})
            n += 1
        except Exception as e:
            log.warning(f"upsert falhou {it.get('nr_proposta')}: {e}")
            conn.rollback()
            continue
    conn.commit(); cur.close(); conn.close()
    return n


def _normalize(p: dict, ano: int, mun_id: int, cod_fns: str) -> dict:
    import hashlib
    tipo = (p.get("coTipoProposta") or "PROPOSTA").strip()
    recurso = (p.get("dsTipoRecurso") or "").strip()
    vl_prop = float(p.get("vlProposta") or 0)
    vl_pago = float(p.get("vlPago") or 0)
    vl_pagar = float(p.get("vlPagar") or 0)
    sit = ("Pago" if vl_pago > 0 and vl_pagar == 0
           else "Empenhado" if vl_pagar > 0
           else "Em analise" if vl_prop > 0
           else "Pendente")
    nu_proc = p.get("nuProcesso") or "NA"
    # ID estavel + UNICO usando hash do payload pra desambiguar mesmo tipo/recurso.
    # EXCLUI linhaPropostas (enriquecimento, nao identidade) p/ a chave nao mudar
    # quando as propostas individuais sao anexadas -> evita duplicar linhas.
    _hp = {k: v for k, v in p.items() if k != "linhaPropostas"}
    h = hashlib.md5(json.dumps(_hp, sort_keys=True, default=str).encode()).hexdigest()[:8]
    nr_proposta = f"FNS-{cod_fns}-{ano}-{tipo[:8]}-{recurso[:6]}-{nu_proc[:8]}-{h}".replace(" ", "_")[:60]
    return {
        "municipio_id": mun_id,
        "nr_proposta": nr_proposta,
        "objeto": (f"{tipo} - {recurso}".strip(" -") + (f" — Proc {nu_proc}" if nu_proc not in ("NA", "N/A") else ""))[:500],
        "tipo_programa": tipo[:100],
        "valor": vl_pago or vl_prop or 0,
        "situacao": sit,
        "ano": ano,
        "fonte": "FNS",
        "orgao_concedente": "MS - FNS",
        "raw_data": p,
    }


async def _fetch_individuais(client: httpx.AsyncClient, cod_fns: str, ano: int,
                             tipo: str, recurso: str) -> list[dict]:
    """Propostas INDIVIDUAIS (Nº SIPA) de um grupo tipo/recurso. O portal usa
    tpProposta/tpRecurso (em vez de co.../ds...) p/ destravar o agrupamento e
    retornar 1 item por proposta, cada um com nuProposta."""
    if not tipo:
        return []
    try:
        r = await client.get(
            f"{BASE}/recursos/proposta/consultar",
            params={"ano": ano, "coEsfera": "", "coMunicipioIbge": cod_fns,
                    "count": 200, "page": 1, "sgUf": "MG",
                    "tpProposta": tipo, "tpRecurso": recurso},
            timeout=30,
        )
        if r.status_code != 200:
            return []
        its = r.json().get("resultado", {}).get("itensPagina", []) or []
        out = []
        for it in its:
            nup = it.get("nuProposta")
            if not nup:
                continue
            # Situacao REAL do portal (ex.: "EM ANALISE PELA AREA FINALISTICA") NAO
            # vem na listagem — so no detalhe (obter-proposta). 1 chamada por proposta.
            sit_desc = None
            try:
                rd = await client.get(
                    f"{BASE}/recursos/proposta/obter-proposta",
                    params={"nuProposta": nup}, timeout=20,
                )
                if rd.status_code == 200:
                    dd = rd.json().get("resultado", {}) or {}
                    sit_desc = (dd.get("situacao") or {}).get("descricaoSituacaoproposta")
            except Exception:
                pass
            out.append({
                "nuProposta": nup,
                "entidade": it.get("noEntidade") or "FUNDO MUNICIPAL DE SAUDE",
                "nuProcesso": it.get("nuProcesso"),
                "vlProposta": float(it.get("vlProposta") or 0),
                "vlPago": float(it.get("vlPago") or 0),
                "vlPagar": float(it.get("vlPagar") or 0),
                "parlamentares": it.get("parlamentares") or [],
                "situacao_desc": sit_desc,
            })
        return out
    except Exception as ex:
        log.warning(f"  individuais {tipo}/{recurso} {ano}: {str(ex)[:80]}")
        return []


async def collect_for_municipio(client: httpx.AsyncClient, mun_id: int, cod_fns: str, nome: str) -> list[dict]:
    items: list[dict] = []
    for ano in ANOS:
        pagina = 1
        while pagina < 30:
            try:
                r = await client.get(
                    f"{BASE}/recursos/proposta/consultar",
                    params={
                        "ano": ano,
                        "coMunicipioIbge": cod_fns,
                        "sgUf": "MG",
                        "count": 200,
                        "page": pagina,
                    },
                    timeout=30,
                )
                if r.status_code == 401:
                    log.warning(f"  {nome} ano={ano}: SESSAO EXPIRADA — re-capture")
                    return items
                if r.status_code != 200:
                    log.warning(f"  {nome} ano={ano} pag={pagina}: HTTP {r.status_code}")
                    break
                j = r.json().get("resultado", {})
                propostas = j.get("itensPagina", []) or []
                if not propostas:
                    break
                for p in propostas:
                    # Enriquece o agregado com as propostas INDIVIDUAIS (Nº SIPA)
                    # p/ o RM mostrar o numero real de cada proposta.
                    p["linhaPropostas"] = await _fetch_individuais(
                        client, cod_fns, ano,
                        (p.get("coTipoProposta") or "").strip(),
                        (p.get("dsTipoRecurso") or "").strip(),
                    )
                    items.append(_normalize(p, ano, mun_id, cod_fns))
                if len(propostas) < 200:
                    break
                pagina += 1
            except Exception as e:
                log.error(f"  {nome} ano={ano} pag={pagina}: {e}")
                break
        await asyncio.sleep(0.3)  # gentil
    return items


async def main():
    cookies = _load_fns_cookies()
    if not cookies:
        log.error("Nenhuma sessao FNS no Cofre. Capture via bookmarklet em consultafns.saude.gov.br.")
        return
    log.info(f"Sessao FNS: {len(cookies)} cookies")
    total = 0
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/131",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://consultafns.saude.gov.br/",
    }
    async with httpx.AsyncClient(cookies=cookies, headers=headers, verify=False) as client:
        for mun_id, (nome, cod_fns) in _load_fns_targets().items():
            log.info(f"=== {nome} (mun={mun_id} fns={cod_fns}) ===")
            items = await collect_for_municipio(client, mun_id, cod_fns, nome)
            log.info(f"  coletadas {len(items)} propostas")
            n = _upsert_items(items)
            log.info(f"  inseridas/atualizadas {n} no banco")
            total += n
    log.info(f"=== TOTAL: {total} propostas FNS no banco ===")


if __name__ == "__main__":
    asyncio.run(main())
