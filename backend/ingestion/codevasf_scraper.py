"""
Pipeline CODEVASF (Companhia de Desenvolvimento dos Vales do Sao Francisco e
do Parnaiba) - vinculada ao Min. Agricultura (orgao 22000).

A CODEVASF nao tem API publica propria. Estrategia:
1. Consultar Portal da Transparencia filtrando municipio + palavras-chave
   tipicas de doacoes CODEVASF (caminhao, retroescavadeira, pa carregadeira,
   patrulha mecanizada, trator).
2. Marcar fonte=CODEVASF e orgao=CODEVASF para diferenciar dos outros
   convenios MAPA.
3. Quando rodado depois do portal_transparencia.py principal, atualiza o
   campo `fonte` dos itens identificados.

Cobertura tipica: 4-8 itens por municipio (doacoes anuais).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging
from sqlalchemy import create_engine, text
from config import get_settings

logger = logging.getLogger("codevasf")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))


# Padroes tipicos de doacao CODEVASF (caso/insensitivo no objeto)
CODEVASF_KEYWORDS = [
    "CODEVASF", "CO.DE.VA.SF",
    # Doacoes mais comuns:
    "PATRULHA MECANIZADA",
    "RETROESCAVADEIRA",
    "PA CARREGADEIRA", "PA-CARREGADEIRA",
    "MOTONIVELADORA", "MOTO-NIVELADORA",
    "CAMINHAO BASCULANTE", "CAMINHAO BASCULA",
    "CAMINHAO CARROCERIA",
    "CAMINHAO SEMIPESADO",
    "TRATOR AGRICOLA",
    "TRATOR DE ESTEIRA",
    # Programas CODEVASF
    "VIVA O CAMPO",
    "AGUA PARA TODOS",
]


def is_codevasf_candidate(objeto: str, orgao: str = "") -> bool:
    """Heuristica: identifica convenios federais que sao tipicamente CODEVASF.

    Aceita se:
    - Objeto cita CODEVASF explicitamente
    - OU orgao e MAPA (22000) E objeto cita equipamento tipicamente doado
    """
    if not objeto:
        return False
    obj = objeto.upper()
    org = (orgao or "").upper()

    if "CODEVASF" in obj or "CODEVASF" in org:
        return True

    is_mapa = org in ("22000", "22202") or "AGRICULT" in org or "MAPA" in org
    if not is_mapa:
        return False

    return any(kw in obj for kw in CODEVASF_KEYWORDS[2:])


def main():
    """Marca convenios MAPA existentes como fonte CODEVASF quando objeto bate
    com o padrao tipico de doacao (patrulha mecanizada, retroescavadeira, etc).
    """
    logger.info("=== Identificando convenios CODEVASF ===")

    with engine.begin() as conn:
        # Buscar candidatos federais com objeto preenchido e orgao MAPA
        rows = conn.execute(text("""
            SELECT id, nr_convenio, municipio_id, orgao_concedente, objeto, fonte
            FROM convenios_federal
            WHERE objeto IS NOT NULL
              AND (
                upper(orgao_concedente) IN ('22000', '22202')
                OR upper(orgao_concedente) LIKE '%AGRICULT%'
                OR upper(orgao_concedente) LIKE '%MAPA%'
                OR upper(objeto) LIKE '%CODEVASF%'
              )
        """)).fetchall()

        marcados = 0
        for cid, nr, mun_id, orgao, obj, fonte in rows:
            if is_codevasf_candidate(obj, orgao):
                conn.execute(text("""
                    UPDATE convenios_federal
                    SET fonte = 'CODEVASF',
                        orgao_concedente = COALESCE(NULLIF(:orgao_novo, ''), orgao_concedente),
                        updated_at = NOW()
                    WHERE id = :id
                """), {"id": cid, "orgao_novo": "CODEVASF"})
                marcados += 1
                logger.info(f"  CODEVASF: convenio {nr} (mun {mun_id}) - {(obj or '')[:60]}")

        conn.execute(text("""
            INSERT INTO ingestion_log (source, status, records_inserted, finished_at)
            VALUES ('codevasf', 'success', :n, NOW())
        """), {"n": marcados})

    logger.info(f"\nTotal de convenios CODEVASF identificados: {marcados}")
    return marcados


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback; traceback.print_exc()
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO ingestion_log (source, status, error_message, finished_at)
                VALUES ('codevasf', 'failed', :e, NOW())
            """), {"e": str(e)[:500]})
        sys.exit(1)
