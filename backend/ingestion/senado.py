"""
Pipeline da API publica do Senado Federal (dadosabertos.senado.leg.br).
Sem autenticacao. Cobertura: senadores em exercicio + identificacao basica.
Emendas senatoriais aparecem em outro endpoint, complementa Camara.
"""
import sys, os, time, json, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from sqlalchemy import create_engine, text
from config import get_settings

logger = logging.getLogger("senado")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))

BASE = "https://legis.senado.leg.br/dadosabertos"


def main():
    logger.info("=== Pipeline Senado ===")
    with httpx.Client(timeout=30, verify=False) as client:
        r = client.get(f"{BASE}/senador/lista/atual",
                       headers={"Accept": "application/json", "User-Agent": "PACTA/1.0"})
        if r.status_code != 200:
            logger.error(f"Falha: HTTP {r.status_code}")
            return
        data = r.json()
        parlamentares = data.get("ListaParlamentarEmExercicio", {}).get("Parlamentares", {}).get("Parlamentar", [])
        if not isinstance(parlamentares, list):
            parlamentares = [parlamentares] if parlamentares else []
        logger.info(f"  Senadores em exercicio: {len(parlamentares)}")

        # Filtrar MG
        senadores_mg = []
        for p in parlamentares:
            ident = p.get("IdentificacaoParlamentar", {})
            uf = ident.get("UfParlamentar")
            if uf == "MG":
                senadores_mg.append(p)
        logger.info(f"  Senadores MG: {len(senadores_mg)}")

        with engine.begin() as conn:
            for p in senadores_mg:
                ident = p.get("IdentificacaoParlamentar", {})
                nome = (ident.get("NomeParlamentar") or "").strip().upper()
                partido = (ident.get("SiglaPartidoParlamentar") or "").strip().upper()
                id_senado = ident.get("CodigoParlamentar")
                if not nome:
                    continue
                # Upsert
                r = conn.execute(text("""
                  SELECT id FROM parlamentares
                  WHERE upper(nome) = :n AND esfera = 'federal' LIMIT 1
                """), {"n": nome}).first()
                if r:
                    conn.execute(text("""
                      UPDATE parlamentares SET partido = COALESCE(:p, partido),
                                                external_id = COALESCE(NULLIF(external_id, ''), :ext)
                      WHERE id = :id
                    """), {"p": partido or None, "ext": f"senado:{id_senado}", "id": r[0]})
                else:
                    conn.execute(text("""
                      INSERT INTO parlamentares (nome, partido, uf, esfera, legislatura, external_id)
                      VALUES (:n, :p, 'MG', 'federal', '2023-2031', :ext)
                    """), {"n": nome[:300], "p": partido or None, "ext": f"senado:{id_senado}"})
                logger.info(f"    {nome} ({partido})")

            conn.execute(text("""
              INSERT INTO ingestion_log (source, status, records_inserted, finished_at)
              VALUES ('senado', 'success', :n, NOW())
            """), {"n": len(senadores_mg)})
    logger.info("=== Senado concluido ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback; traceback.print_exc()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO ingestion_log (source, status, error_message, finished_at)
                                 VALUES ('senado', 'failed', :e, NOW())"""),
                          {"e": str(e)[:500]})
        sys.exit(1)
