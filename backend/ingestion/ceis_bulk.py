"""
Pipeline CEIS (Cadastro de Empresas Inidoneas e Suspensas) - Portal Transparencia.
Bulk CSV mensal. Fornece sancoes administrativas para checagem de fornecedores.
"""
import sys, os, time, json, logging, zipfile, io, csv
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from datetime import datetime
from sqlalchemy import create_engine, text
from config import get_settings

logger = logging.getLogger("ceis")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))

# Portal Transparencia disponibiliza CSV mensal:
# https://portaldatransparencia.gov.br/sancoes/ceis
# Download direto: dados-abertos/sancoes/YYYYMM_CEIS.zip
URL_BASE = "https://portaldatransparencia.gov.br/download-de-dados/ceis"


def parse_dt(s):
    if not s: return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try: return datetime.strptime(s.strip(), fmt).date()
        except: continue
    return None


def fetch_latest_csv():
    """Tenta baixar CSV do mes atual ou anterior."""
    today = datetime.now()
    for ym_delta in range(0, 3):
        ano = today.year if today.month > ym_delta else today.year - 1
        mes = today.month - ym_delta if today.month - ym_delta > 0 else 12 + today.month - ym_delta
        url = f"https://portaldatransparencia.gov.br/download-de-dados/ceis/{ano}{mes:02d}"
        logger.info(f"  Tentando: {url}")
        try:
            r = httpx.get(url, timeout=120, verify=False, follow_redirects=True)
            if r.status_code == 200 and len(r.content) > 1000:
                # Tem que ser ZIP
                if r.content[:2] == b"PK":
                    return r.content
        except Exception as e:
            logger.warning(f"    {e}")
    return None


def main():
    logger.info("=== Pipeline CEIS ===")
    data = fetch_latest_csv()
    if not data:
        logger.error("Falha ao baixar CSV CEIS")
        return

    csv_name = None
    csv_bytes = None
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for n in zf.namelist():
            if n.endswith(".csv"):
                csv_name = n
                csv_bytes = zf.read(n)
                break
    if not csv_bytes:
        logger.error("Sem CSV no zip")
        return

    # CSV pode estar em latin-1 ou utf-8
    txt = None
    for enc in ("latin-1", "utf-8-sig", "utf-8"):
        try:
            txt = csv_bytes.decode(enc)
            break
        except: continue
    if not txt:
        logger.error("Falha decode CSV")
        return

    reader = csv.DictReader(io.StringIO(txt), delimiter=";")
    rows = list(reader)
    logger.info(f"  {len(rows)} linhas")
    if rows:
        logger.info(f"  Cols: {list(rows[0].keys())[:10]}")

    # Map cols comuns CEIS
    def get(row, *keys):
        for k in keys:
            for col in row.keys():
                if k.upper() in col.upper():
                    v = row[col]
                    if v and v.strip() and v.strip() not in ("-", "null"):
                        return v.strip()
        return None

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM sancoes_ceis"))
        inserted = 0
        for r in rows:
            try:
                cnpj = get(r, "CPF / CNPJ", "CPF_CNPJ", "CNPJ", "CPFCNPJ")
                if not cnpj: continue
                cnpj = cnpj.replace(".", "").replace("/", "").replace("-", "")[:20]
                razao = (get(r, "NOME INFORMADO", "RAZAO SOCIAL", "NOME") or "")[:500]
                tipo_pess = (get(r, "TIPO DE PESSOA", "TIPO") or "")[:20]
                tipo_sanc = (get(r, "CATEGORIA DA SANCAO", "TIPO DA SANCAO", "TIPO SANCAO") or "")[:200]
                fund = get(r, "FUNDAMENTACAO", "FUNDAMENTO")
                dt_ini = parse_dt(get(r, "DATA DE INICIO", "DT INICIO"))
                dt_fim = parse_dt(get(r, "DATA DE FIM", "DT FIM", "DATA FINAL"))
                dt_pub = parse_dt(get(r, "DATA DE PUBLICACAO", "DT PUBLICACAO"))
                orgao = (get(r, "NOME DO ORGAO SANCIONADOR", "ORGAO SANCIONADOR", "ORGAO") or "")[:300]
                uf = (get(r, "UF DO ORGAO SANCIONADOR", "UF SANCIONADOR", "UF") or "")[:2]

                conn.execute(text("""
                  INSERT INTO sancoes_ceis
                    (cpf_cnpj, razao_social, tipo_pessoa, tipo_sancao, fundamentacao,
                     dt_inicio_sancao, dt_fim_sancao, dt_publicacao, orgao_sancionador,
                     uf_sancionador, raw_data)
                  VALUES (:c, :r, :tp, :ts, :f, :di, :df, :dp, :o, :u, CAST(:raw AS jsonb))
                """), {"c": cnpj, "r": razao, "tp": tipo_pess, "ts": tipo_sanc, "f": fund,
                        "di": dt_ini, "df": dt_fim, "dp": dt_pub, "o": orgao, "u": uf,
                        "raw": json.dumps({k: (v or "")[:200] for k, v in r.items()},
                                         ensure_ascii=False, default=str)})
                inserted += 1
            except Exception as e:
                continue
        conn.execute(text("""INSERT INTO ingestion_log (source, status, records_inserted, finished_at)
                              VALUES ('ceis_bulk', 'success', :n, NOW())"""), {"n": inserted})
    logger.info(f"=== CEIS concluido: {inserted} sancoes ===")


if __name__ == "__main__":
    try: main()
    except Exception as e:
        import traceback; traceback.print_exc()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO ingestion_log (source, status, error_message, finished_at)
                                 VALUES ('ceis_bulk', 'failed', :e, NOW())"""),
                          {"e": str(e)[:500]})
