"""
Pipeline Portal da Transparencia (CGU) - convenios federais por municipio.

Fonte oficial: https://api.portaldatransparencia.gov.br
Autenticacao: header chave-api-dados (gratuita, 3M req/dia)
Cadastro: https://api.portaldatransparencia.gov.br/api-de-dados/cadastrar-email

Captura convenios + emendas dos orgaos federais que NAO estavam cobertos
pelo TransfereGov bulk (FNS, FNDE, MAPA, MTUR, ESPORTE, etc).
"""
import os
import sys
import time
import logging
import re
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from sqlalchemy import create_engine, text
from config import get_settings

logger = logging.getLogger("portal_transp")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

API_KEY = os.getenv("PORTAL_TRANSPARENCIA_KEY", "")
BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"
PAGE_SIZE = 500


def _client():
    if not API_KEY:
        raise RuntimeError(
            "PORTAL_TRANSPARENCIA_KEY nao configurada. Cadastre em "
            "https://api.portaldatransparencia.gov.br/api-de-dados/cadastrar-email"
        )
    return httpx.Client(
        verify=False,
        timeout=30,
        headers={"chave-api-dados": API_KEY, "Accept": "application/json", "User-Agent": "PACTA/1.0"},
    )


def parse_dec(s):
    if s is None:
        return None
    if isinstance(s, (int, float, Decimal)):
        return float(s)
    s = str(s).strip()
    if not s:
        return None
    # "1.234,56" -> 1234.56
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def parse_date(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


def fetch_convenios(client, ibge: str, ano_inicial=2015, ano_final=2026):
    """Pagina TODOS os convenios federais para o municipio.
    A API retorna 15 itens/pagina (PAGE_SIZE real e 15, nao 500).
    Continua paginando ate retornar vazio.
    """
    out = []
    for pag in range(1, 100):  # max 100 paginas = 1500 convenios
        try:
            r = client.get(
                f"{BASE}/convenios",
                params={
                    "dataInicial": f"01/01/{ano_inicial}",
                    "dataFinal": f"31/12/{ano_final}",
                    "codigoIBGE": ibge,
                    "pagina": pag,
                },
            )
        except Exception as e:
            logger.error(f"  Erro pag {pag}: {e}")
            break
        if r.status_code != 200:
            logger.warning(f"  HTTP {r.status_code} pag {pag}: {r.text[:200]}")
            break
        data = r.json()
        if not data:
            break  # so para quando vier vazio
        out.extend(data)
        time.sleep(0.4)  # rate limit
    return out


def upsert_convenio(conn, mun_id: int, c: dict):
    """Insere ou atualiza convenio_federal."""
    dim = c.get("dimConvenio") or {}
    nr = (dim.get("numero") or dim.get("codigo") or f"PT-{c.get('id')}")[:50]
    objeto = (dim.get("objeto") or "")[:1000]
    situacao = (c.get("situacao") or "")[:200]

    orgao_obj = c.get("orgao") or {}
    orgao_max = orgao_obj.get("orgaoMaximo") or {}
    orgao_concedente = (orgao_obj.get("sigla") or orgao_obj.get("nome") or "?")[:200]
    orgao_superior_nome = orgao_max.get("nome") or ""

    dt_inicio = parse_date(c.get("dataInicioVigencia"))
    dt_fim = parse_date(c.get("dataFinalVigencia"))

    valor_total = parse_dec(c.get("valorTotal") or dim.get("valor"))
    valor_repasse = parse_dec(c.get("valorRepasse") or c.get("valorLiberado"))

    # Tentar extrair ano da dt_inicio
    ano = dt_inicio.year if dt_inicio else None

    raw = {
        "fonte": "PortalTransparencia",
        "id_pt": c.get("id"),
        "convenente": (c.get("convenente") or {}).get("nome"),
        "orgao_superior": orgao_superior_nome,
        "valorContrapartida": c.get("valorContrapartida"),
        "valorRepasse": c.get("valorRepasse"),
    }
    import json as jsonlib

    conn.execute(text("""
        INSERT INTO convenios_federal (
            nr_convenio, municipio_id, orgao_concedente, objeto,
            situacao, valor_global, valor_repasse,
            dt_inicio, dt_fim, dt_fim_vigencia, ano,
            programa, fonte, raw_data, updated_at
        ) VALUES (
            :nr, :mun, :orgao, :obj, :sit, :vg, :vr,
            :di, :df, :df, :ano, :prog, :fonte, CAST(:raw AS jsonb), NOW()
        )
        ON CONFLICT (nr_convenio) DO UPDATE SET
            orgao_concedente = EXCLUDED.orgao_concedente,
            situacao = EXCLUDED.situacao,
            valor_global = COALESCE(EXCLUDED.valor_global, convenios_federal.valor_global),
            valor_repasse = COALESCE(EXCLUDED.valor_repasse, convenios_federal.valor_repasse),
            dt_inicio = COALESCE(EXCLUDED.dt_inicio, convenios_federal.dt_inicio),
            dt_fim = COALESCE(EXCLUDED.dt_fim, convenios_federal.dt_fim),
            dt_fim_vigencia = COALESCE(EXCLUDED.dt_fim_vigencia, convenios_federal.dt_fim_vigencia),
            raw_data = EXCLUDED.raw_data,
            updated_at = NOW()
    """), {
        "nr": nr, "mun": mun_id, "orgao": orgao_concedente, "obj": objeto,
        "sit": situacao, "vg": valor_total, "vr": valor_repasse,
        "di": dt_inicio, "df": dt_fim, "ano": ano,
        "prog": orgao_superior_nome[:200], "fonte": "PortalTransparencia",
        "raw": jsonlib.dumps(raw, ensure_ascii=False, default=str),
    })


def main():
    settings = get_settings()
    engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))

    with engine.connect() as conn:
        muns = conn.execute(text(
            "SELECT id, nome, ibge_code FROM municipios WHERE active=true AND ibge_code IS NOT NULL ORDER BY nome"
        )).fetchall()

    logger.info(f"=== Portal da Transparencia - {len(muns)} municipios ===")
    total_inseridos = 0

    with _client() as cli:
        for mid, nome, ibge in muns:
            logger.info(f"\n>>> {nome} (IBGE {ibge})")
            try:
                convs = fetch_convenios(cli, ibge, ano_inicial=2020, ano_final=2026)
                logger.info(f"  {len(convs)} convenios encontrados")
                if not convs:
                    continue

                # Resumo orgaos
                orgaos = {}
                for c in convs:
                    o = (c.get("orgao") or {}).get("sigla", "?")
                    orgaos[o] = orgaos.get(o, 0) + 1
                logger.info(f"  Orgaos: {orgaos}")

                # Filtrar SO os que realmente sao do municipio (API as vezes ignora filtro)
                convs_validos = [
                    c for c in convs
                    if (c.get("municipioConvenente") or {}).get("codigoIBGE") == ibge
                ]
                if len(convs_validos) != len(convs):
                    logger.info(f"  {len(convs) - len(convs_validos)} convenios descartados (IBGE diferente)")

                with engine.begin() as conn:
                    for c in convs_validos:
                        try:
                            upsert_convenio(conn, mid, c)
                            total_inseridos += 1
                        except Exception as e:
                            logger.error(f"  Falha upsert {c.get('id')}: {e}")
            except Exception as e:
                logger.error(f"  ERRO {nome}: {e}")
            time.sleep(1)

    # Log final
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO ingestion_log (source, status, records_inserted, finished_at)
            VALUES ('portal_transparencia', 'success', :n, NOW())
        """), {"n": total_inseridos})

    logger.info(f"\n=== Total inseridos/atualizados: {total_inseridos} ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback; traceback.print_exc()
        sys.exit(1)
