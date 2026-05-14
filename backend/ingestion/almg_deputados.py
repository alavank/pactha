"""
Pipeline ALMG - Assembleia Legislativa de Minas Gerais.
API publica: dadosabertos.almg.gov.br/ws

Cobertura: 77 deputados estaduais MG em exercicio.
Estes sao os autores das emendas SIGCON estaduais que estamos rastreando.
"""
import sys, os, time, json, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from sqlalchemy import create_engine, text
from config import get_settings

logger = logging.getLogger("almg")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))

BASE = "https://dadosabertos.almg.gov.br/ws"


def main():
    logger.info("=== Pipeline ALMG - deputados estaduais MG ===")
    with httpx.Client(timeout=20, verify=False, follow_redirects=True) as client:
        r = client.get(f"{BASE}/deputados/em_exercicio",
                       headers={"Accept": "application/json", "User-Agent": "PACTA/1.0"})
        if r.status_code != 200:
            logger.error(f"HTTP {r.status_code}"); return

        data = r.json()
        items = data.get("list", [])
        if not items:
            items = data.get("deputados", []) or data.get("dados", [])
        logger.info(f"  {len(items)} deputados estaduais em exercicio")

        with engine.begin() as conn:
            atualizados = 0; criados = 0
            for d in items:
                nome = (d.get("nome") or "").strip().upper()
                if not nome: continue
                partido = (d.get("partido") or "").strip().upper() or None
                id_almg = d.get("id")

                # Lookup pelo MESMO unaccent do UNIQUE INDEX ix_parlamentares_nome_unaccent
                r = conn.execute(text("""
                  SELECT id FROM parlamentares
                  WHERE upper(translate(nome, 'áéíóúàâêôãõçÁÉÍÓÚÀÂÊÔÃÕÇ', 'AEIOUAAEOAOCAEIOUAAEOAOC'))
                      = upper(translate(:n, 'áéíóúàâêôãõçÁÉÍÓÚÀÂÊÔÃÕÇ', 'AEIOUAAEOAOCAEIOUAAEOAOC'))
                  LIMIT 1
                """), {"n": nome}).first()
                if r:
                    conn.execute(text("""
                      UPDATE parlamentares
                      SET partido = COALESCE(:p, partido),
                          external_id = COALESCE(NULLIF(external_id, ''), :ext),
                          uf = 'MG'
                      WHERE id = :id
                    """), {"p": partido, "ext": f"almg:{id_almg}", "id": r[0]})
                    atualizados += 1
                else:
                    conn.execute(text("""
                      INSERT INTO parlamentares (nome, partido, uf, esfera, legislatura, external_id)
                      VALUES (:n, :p, 'MG', 'estadual', '2023-2027', :ext)
                      ON CONFLICT DO NOTHING
                    """), {"n": nome[:300], "p": partido, "ext": f"almg:{id_almg}"})
                    criados += 1
            conn.execute(text("""
              INSERT INTO ingestion_log (source, status, records_inserted, finished_at)
              VALUES ('almg', 'success', :n, NOW())
            """), {"n": criados + atualizados})
        logger.info(f"=== ALMG concluido: {criados} criados, {atualizados} atualizados ===")


if __name__ == "__main__":
    try: main()
    except Exception as e:
        import traceback; traceback.print_exc()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO ingestion_log (source, status, error_message, finished_at)
                                 VALUES ('almg', 'failed', :e, NOW())"""), {"e": str(e)[:500]})
