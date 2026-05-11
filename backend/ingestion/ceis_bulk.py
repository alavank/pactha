"""
Pipeline CEIS - via API publica do Portal da Transparencia.
Usa a chave PORTAL_TRANSPARENCIA_KEY (mesma do portal_transparencia.py).
Endpoint: /api-de-dados/ceis (paginado, 15 itens/pag).
"""
import sys, os, time, json, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from datetime import datetime
from sqlalchemy import create_engine, text
from config import get_settings

logger = logging.getLogger("ceis")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))

API_KEY = os.getenv("PORTAL_TRANSPARENCIA_KEY", "")
BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"


def parse_dt(s):
    if not s: return None
    s = str(s).strip()
    if s.lower().startswith("sem ") or s == "":
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try: return datetime.strptime(s, fmt).date()
        except: continue
    return None


def main():
    logger.info("=== Pipeline CEIS (API) ===")
    if not API_KEY:
        logger.error("PORTAL_TRANSPARENCIA_KEY nao configurada"); return

    headers = {"chave-api-dados": API_KEY, "Accept": "application/json", "User-Agent": "PACTA/1.0"}

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM sancoes_ceis"))

    inserted = 0
    pag = 1
    with httpx.Client(timeout=30, verify=False, headers=headers) as client:
        while pag <= 200:  # max 200 paginas (3000 itens) para limitar
            try:
                r = client.get(f"{BASE}/ceis", params={"pagina": pag})
            except Exception as e:
                logger.warning(f"  pag {pag}: {e}"); break
            if r.status_code != 200:
                logger.info(f"  pag {pag}: HTTP {r.status_code} (fim?)")
                break
            data = r.json() or []
            if not data: break

            erros_amostra = []
            with engine.begin() as conn:
                for s in data:
                    try:
                        ss = s.get("sancionado") or {}
                        pessoa = s.get("pessoa") or {}
                        org = s.get("orgaoSancionador") or {}
                        cnpj_cpf = (ss.get("codigoFormatado") or pessoa.get("cnpjFormatado")
                                    or pessoa.get("cpfFormatado") or "")
                        cnpj_clean = "".join(c for c in cnpj_cpf if c.isdigit())[:20]
                        if not cnpj_clean: continue

                        fund = s.get("fundamentacao")
                        if isinstance(fund, list):
                            fund = "; ".join(f.get("descricao", "") for f in fund if isinstance(f, dict))

                        conn.execute(text("""
                          INSERT INTO sancoes_ceis
                            (cpf_cnpj, razao_social, nome_fantasia, tipo_pessoa, tipo_sancao,
                             fundamentacao, dt_inicio_sancao, dt_fim_sancao, dt_publicacao,
                             orgao_sancionador, uf_sancionador, raw_data)
                          VALUES (:c, :r, :nf, :tp, :ts, :f, :di, :df, :dp, :o, :u, CAST(:raw AS jsonb))
                        """), {
                            "c": cnpj_clean,
                            "r": (ss.get("nome") or pessoa.get("nome") or "")[:500],
                            "nf": (pessoa.get("nomeFantasiaReceita") or "")[:500] or None,
                            "tp": (pessoa.get("tipo") or "")[:20] or None,
                            "ts": (s.get("tipoSancao") or {}).get("descricaoResumida", "")[:200],
                            "f": fund,
                            "di": parse_dt(s.get("dataInicioSancao")),
                            "df": parse_dt(s.get("dataFimSancao")),
                            "dp": parse_dt(s.get("dataPublicacaoSancao")),
                            "o": (org.get("nome") or "")[:300] or None,
                            "u": (org.get("siglaUf") or "")[:2] or None,
                            "raw": json.dumps(s, ensure_ascii=False, default=str)[:10000],
                        })
                        inserted += 1
                    except Exception as e:
                        if len(erros_amostra) < 3:
                            erros_amostra.append(str(e)[:200])
                        continue
            if erros_amostra and pag == 1:
                logger.warning(f"  Erros amostra: {erros_amostra}")

            if len(data) < 15: break
            pag += 1
            time.sleep(0.4)

    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO ingestion_log (source, status, records_inserted, finished_at)
                              VALUES ('ceis_api', 'success', :n, NOW())"""), {"n": inserted})
    logger.info(f"=== CEIS concluido: {inserted} sancoes ({pag-1} paginas) ===")


if __name__ == "__main__":
    try: main()
    except Exception as e:
        import traceback; traceback.print_exc()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO ingestion_log (source, status, error_message, finished_at)
                                 VALUES ('ceis_api', 'failed', :e, NOW())"""),
                          {"e": str(e)[:500]})
