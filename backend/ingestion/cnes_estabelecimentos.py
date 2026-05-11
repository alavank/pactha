"""
Pipeline CNES - Cadastro Nacional de Estabelecimentos de Saude.
API publica: apidadosabertos.saude.gov.br/cnes/estabelecimentos

Ingere todos os estabelecimentos dos municipios atendidos.
Util para enriquecer convenios de saude e analise de cobertura.
"""
import sys, os, time, json, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from sqlalchemy import create_engine, text
from config import get_settings

logger = logging.getLogger("cnes")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))

BASE = "https://apidadosabertos.saude.gov.br"
HEADERS = {"Accept": "application/json", "User-Agent": "PACTA/1.0"}


def fetch_estabelecimentos(client, codigo_municipio):
    """Pagina todos os estabelecimentos de um municipio.
    IMPORTANTE: API CNES usa `codMun` (6 digitos sem digito verificador)."""
    cod6 = str(codigo_municipio)[:6]  # remove ultimo digito (IBGE 7d -> CNES 6d)
    out = []
    offset = 0
    while offset < 5000:
        try:
            r = client.get(f"{BASE}/cnes/estabelecimentos",
                            params={"codMun": cod6, "limit": 100, "offset": offset},
                            headers=HEADERS)
        except Exception as e:
            logger.warning(f"  Erro offset {offset}: {e}"); break
        if r.status_code != 200:
            break
        data = r.json() or {}
        items = data.get("estabelecimentos") or []
        if not items: break
        out.extend(items)
        if len(items) < 100: break
        offset += 100
        time.sleep(0.3)
    return out


def main():
    logger.info("=== Pipeline CNES - estabelecimentos saude ===")
    with engine.connect() as conn:
        muns = conn.execute(text(
            "SELECT id, nome, ibge_code FROM municipios WHERE active=true AND ibge_code IS NOT NULL"
        )).fetchall()

    total = 0
    with httpx.Client(timeout=20, verify=False, follow_redirects=True) as client:
        for mid, nome, ibge in muns:
            logger.info(f"  {nome} (IBGE {ibge})")
            ests = fetch_estabelecimentos(client, ibge)
            logger.info(f"    {len(ests)} estabelecimentos")
            with engine.begin() as conn:
                for e in ests:
                    try:
                        conn.execute(text("""
                          INSERT INTO estabelecimentos_cnes
                            (cnes, cnpj, nome_fantasia, razao_social, municipio_id, codigo_ibge,
                             natureza_juridica, tipo_estabelecimento, subtipo,
                             endereco, bairro, cep, telefone, email, raw_data)
                          VALUES (:cn, :cj, :nf, :rs, :mid, :ib, :nj, :te, :sb,
                                   :en, :bs, :ce, :tl, :em, CAST(:raw AS jsonb))
                          ON CONFLICT (cnes) DO UPDATE SET
                            nome_fantasia = EXCLUDED.nome_fantasia,
                            razao_social = EXCLUDED.razao_social,
                            municipio_id = EXCLUDED.municipio_id,
                            raw_data = EXCLUDED.raw_data,
                            updated_at = NOW()
                        """), {
                            "cn": str(e.get("codigo_cnes") or "")[:15],
                            "cj": str(e.get("numero_cnpj_entidade") or e.get("cnpj") or "")[:20] or None,
                            "nf": (e.get("nome_fantasia") or "")[:500],
                            "rs": (e.get("nome_razao_social") or e.get("razao_social") or "")[:500] or None,
                            "mid": mid, "ib": ibge,
                            "nj": (e.get("natureza_organizacao_entidade") or "")[:200] or None,
                            "te": (e.get("descricao_tipo_unidade") or e.get("tipo_unidade") or "")[:200] or None,
                            "sb": (e.get("descricao_esfera_administrativa") or e.get("subtipo") or "")[:200] or None,
                            "en": (e.get("endereco_estabelecimento") or e.get("logradouro") or "")[:500] or None,
                            "bs": (e.get("bairro_estabelecimento") or e.get("bairro") or "")[:200] or None,
                            "ce": (e.get("codigo_cep_estabelecimento") or e.get("cep") or "")[:10] or None,
                            "tl": (e.get("numero_telefone_estabelecimento") or e.get("telefone") or "")[:50] or None,
                            "em": (e.get("endereco_email_estabelecimento") or e.get("email") or "")[:200] or None,
                            "raw": json.dumps(e, ensure_ascii=False, default=str)[:10000],
                        })
                        total += 1
                    except Exception:
                        continue
            time.sleep(0.5)

    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO ingestion_log (source, status, records_inserted, finished_at)
                              VALUES ('cnes', 'success', :n, NOW())"""), {"n": total})
    logger.info(f"=== CNES concluido: {total} estabelecimentos ===")


if __name__ == "__main__":
    try: main()
    except Exception as e:
        import traceback; traceback.print_exc()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO ingestion_log (source, status, error_message, finished_at)
                                 VALUES ('cnes', 'failed', :e, NOW())"""), {"e": str(e)[:500]})
