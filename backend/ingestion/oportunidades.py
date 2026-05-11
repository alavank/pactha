"""
Catalogo de Oportunidades - Programas Federais abertos.
Usa o endpoint do TransfereGov de programas em vigor.
Fonte: https://api.transferegov.gestao.gov.br/transferenciasespeciais/api/v1
       e tambem /programas via dadosabertos.
"""
import sys, os, time, json, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from datetime import datetime
from sqlalchemy import create_engine, text
from config import get_settings

logger = logging.getLogger("oportunidades")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))


def fetch_programas_transferegov():
    """API publica TransfereGov - programas abertos."""
    out = []
    # Endpoint v1 com paginacao
    url = "https://api.transferegov.gestao.gov.br/transferenciasespeciais/api/v1/programa"
    try:
        with httpx.Client(timeout=60, verify=False) as client:
            offset = 0
            while True:
                r = client.get(url, params={"limit": 100, "offset": offset,
                                              "filter[status_programa]": "Disponibilizado"},
                               headers={"Accept": "application/json"})
                if r.status_code != 200:
                    logger.warning(f"  HTTP {r.status_code}")
                    break
                data = r.json() or []
                if not data: break
                out.extend(data if isinstance(data, list) else data.get("data", []))
                if len(data) < 100: break
                offset += 100
                time.sleep(0.4)
                if offset > 5000: break
    except Exception as e:
        logger.error(f"  Erro: {e}")
    return out


def parse_dt(s):
    if not s: return None
    try: return datetime.fromisoformat(s.split("T")[0]).date()
    except: pass
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try: return datetime.strptime(s.strip(), fmt).date()
        except: continue
    return None


def parse_money(v):
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    s = str(v).strip().replace("R$", "").replace(" ", "")
    if "," in s and "." in s: s = s.replace(".", "").replace(",", ".")
    elif "," in s: s = s.replace(",", ".")
    try: return float(s)
    except: return None


def main():
    logger.info("=== Pipeline Oportunidades ===")
    progs = fetch_programas_transferegov()
    logger.info(f"  {len(progs)} programas encontrados")
    if not progs:
        logger.warning("  Nenhum dado")
        return

    with engine.begin() as conn:
        # Replace integral (refletir status atual)
        conn.execute(text("DELETE FROM programas_federais"))
        inserted = 0
        for p in progs:
            try:
                id_prog = p.get("id_programa") or p.get("idPrograma") or p.get("id")
                if not id_prog: continue
                nome = (p.get("nome_programa") or p.get("nomePrograma") or "")[:500]
                orgao = (p.get("orgao_executor") or p.get("orgaoExecutor") or p.get("orgao") or "")[:300]
                obj = p.get("descricao") or p.get("objetivo")
                situacao = (p.get("status_programa") or p.get("statusPrograma") or "Aberto")[:100]
                conn.execute(text("""
                  INSERT INTO programas_federais
                    (id_programa, nome_programa, orgao, objetivo, situacao,
                     dt_inicio_inscricao, dt_fim_inscricao,
                     valor_minimo, valor_maximo, raw_data)
                  VALUES (:i, :n, :o, :ob, :s, :dii, :dif, :vmi, :vma, CAST(:raw AS jsonb))
                  ON CONFLICT (id_programa) DO UPDATE SET
                    nome_programa = EXCLUDED.nome_programa,
                    orgao = EXCLUDED.orgao,
                    situacao = EXCLUDED.situacao,
                    raw_data = EXCLUDED.raw_data,
                    updated_at = NOW()
                """), {
                    "i": int(id_prog), "n": nome, "o": orgao, "ob": obj, "s": situacao,
                    "dii": parse_dt(p.get("data_inicio_recebimento_propostas") or p.get("dataInicioInscricoes")),
                    "dif": parse_dt(p.get("data_fim_recebimento_propostas") or p.get("dataFimInscricoes")),
                    "vmi": parse_money(p.get("valor_minimo") or p.get("valorMinimo")),
                    "vma": parse_money(p.get("valor_maximo") or p.get("valorMaximo")),
                    "raw": json.dumps(p, ensure_ascii=False, default=str)[:30000],
                })
                inserted += 1
            except Exception as e:
                continue
        conn.execute(text("""INSERT INTO ingestion_log (source, status, records_inserted, finished_at)
                              VALUES ('oportunidades', 'success', :n, NOW())"""), {"n": inserted})
    logger.info(f"=== Oportunidades concluido: {inserted} programas ===")


if __name__ == "__main__":
    try: main()
    except Exception as e:
        import traceback; traceback.print_exc()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO ingestion_log (source, status, error_message, finished_at)
                                 VALUES ('oportunidades', 'failed', :e, NOW())"""),
                          {"e": str(e)[:500]})
