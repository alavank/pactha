"""
Ingestao SIGCON-MG completa via CKAN resources + join das dimensoes.
Popula convenios_estadual para todos os 5 municipios piloto.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx, gzip, io, pandas as pd, json, unicodedata
from sqlalchemy import create_engine, text
from config import get_settings
from ingestion.base import parse_date_br, parse_decimal_br, clean_string

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))

BASE_DL = "https://dados.mg.gov.br/dataset/52fcf7e5-d9a6-4b17-a491-12a5a978aecd/resource"
RESOURCES = {
    "convenio": ("23de2c3f-cbf6-494a-8b32-4c9c151fb999", "dm_convenio.csv.gz"),
    "municipio": ("9cd4ddc8-7efd-45dc-b572-9ea6840c9815", "dm_municipio.csv.gz"),
    "conv_saida": ("d8b48c2b-c2ec-451a-99f0-0421987ceeba", "dm_conv_saida.csv.gz"),
    "orgao": ("cf96b7cc-b534-4c4b-8338-dce4c9ed5517", "dm_orgao_concedente.csv.gz"),
    "situacao": ("1ddced7a-dfcf-4ca2-8c3c-23439b944bb2", "dm_situacao_convenio.csv.gz"),
    "convenente": ("3b9d9df2-1a50-451d-bc7e-3a0b82fcf821", "dm_convenente.csv.gz"),
}

TARGET_NAMES = ["ARAUJOS", "NOVA SERRANA", "BOM DESPACHO", "SAO TIAGO", "TOLEDO"]


def norm(s):
    if s is None:
        return ""
    s = str(s).strip().upper()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def dl(key):
    rid, name = RESOURCES[key]
    url = f"{BASE_DL}/{rid}/download/{name}"
    print(f"  Downloading {name}...")
    with httpx.Client(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
        r = client.get(url, follow_redirects=True)
        r.raise_for_status()
    return pd.read_csv(io.BytesIO(gzip.decompress(r.content)), sep=";", encoding="utf-8", dtype=str, low_memory=False)


def main():
    print("=== Ingestao SIGCON-MG (full pipeline) ===")

    df_conv = dl("convenio")
    df_mun = dl("municipio")
    df_fact = dl("conv_saida")
    df_orgao = dl("orgao")
    df_sit = dl("situacao")

    print(f"  Convenios: {len(df_conv)}, Municipios: {len(df_mun)}, Facts: {len(df_fact)}")

    # Find target municipalities (match by normalized name)
    df_mun["_norm"] = df_mun["nome"].apply(norm)
    target_muns = df_mun[df_mun["_norm"].isin(TARGET_NAMES)]
    print(f"  Target municipios in SIGCON: {len(target_muns)}")

    if len(target_muns) == 0:
        print("  ERRO: nenhum municipio encontrado")
        return

    # Map SIGCON id_municipio -> our DB municipio_id
    mun_db_map = {}
    with engine.connect() as conn:
        for _, row in target_muns.iterrows():
            nome_norm = row["_norm"]
            result = conn.execute(text("""
                SELECT id FROM municipios
                WHERE UPPER(nome) = :n OR :n = ANY(ARRAY[UPPER(nome)])
            """), {"n": nome_norm})
            # Fallback: normalize DB name
            db_rows = conn.execute(text("SELECT id, nome FROM municipios")).fetchall()
            for dbr in db_rows:
                if norm(dbr[1]) == nome_norm:
                    mun_db_map[str(row["id_municipio"])] = dbr[0]
                    break

    print(f"  Mapeamento DB: {mun_db_map}")

    # Filter fact table by target municipalities
    target_mun_ids = set(mun_db_map.keys())
    filt_facts = df_fact[df_fact["id_municipio"].astype(str).isin(target_mun_ids)]
    print(f"  Fact records: {len(filt_facts)}")

    # Get convenio details
    target_conv_ids = set(filt_facts["id_convenio"].astype(str).tolist())
    filt_convs = df_conv[df_conv["id_convenio"].astype(str).isin(target_conv_ids)]

    inserted = 0
    with engine.connect() as conn:
        # Clear dependent data first (FK constraints)
        conn.execute(text("DELETE FROM prestacao_documentos"))
        conn.execute(text("DELETE FROM prestacao_contas WHERE convenio_estadual_id IS NOT NULL"))
        conn.execute(text("DELETE FROM emendas WHERE convenio_estadual_id IS NOT NULL"))
        conn.execute(text("DELETE FROM convenios_estadual"))

        for _, fact in filt_facts.iterrows():
            conv_id = str(fact["id_convenio"])
            mun_sigcon_id = str(fact["id_municipio"])
            mun_db_id = mun_db_map.get(mun_sigcon_id)
            if not mun_db_id:
                continue

            conv_data = filt_convs[filt_convs["id_convenio"].astype(str) == conv_id]
            if len(conv_data) == 0:
                continue
            crow = conv_data.iloc[0]

            nr_sigcon = clean_string(crow.get("nr_sigcon")) or f"SIGCON-{conv_id}"

            orgao_name = None
            orgao_id = str(fact.get("id_orgao", ""))
            if orgao_id:
                om = df_orgao[df_orgao["id_orgao"].astype(str) == orgao_id]
                if len(om) > 0:
                    orgao_name = clean_string(om.iloc[0].get("nome"))

            dt_pub = parse_date_br(crow.get("dt_publicacao"))
            dt_ini = parse_date_br(crow.get("dt_vigencia_inicial"))
            dt_fim = parse_date_br(crow.get("dt_vigencia_final"))
            dt_atual = parse_date_br(crow.get("dt_vigencia_atual"))

            try:
                conn.execute(text("""
                    INSERT INTO convenios_estadual (
                        nr_sigcon, nr_siafi, municipio_id, orgao_concedente,
                        objeto, objetivo, tp_instrumento,
                        valor_concedente, valor_emenda_parlamentar, valor_contrapartida, valor_total, valor_repassado,
                        dt_publicacao, dt_vigencia_inicial, dt_vigencia_final, dt_vigencia_atual,
                        ano, situacao, raw_data
                    ) VALUES (
                        :nr, :siafi, :mun, :orgao, :obj, :objetivo, :tp,
                        :vc, :ve, :vcp, :vt, :vrep,
                        :dp, :di, :df, :da,
                        :ano, :sit, :raw
                    )
                """), {
                    "nr": nr_sigcon,
                    "siafi": clean_string(crow.get("nr_siafi")),
                    "mun": mun_db_id,
                    "orgao": orgao_name,
                    "obj": clean_string(crow.get("nome")),
                    "objetivo": clean_string(crow.get("objetivo")),
                    "tp": clean_string(crow.get("tp_instrumento")),
                    "vc": parse_decimal_br(fact.get("vr_concede_atual")),
                    "ve": parse_decimal_br(fact.get("vr_emen_parl_atual")),
                    "vcp": parse_decimal_br(fact.get("vr_contra_atual")),
                    "vt": parse_decimal_br(fact.get("vr_total_atual")),
                    "vrep": parse_decimal_br(fact.get("vr_rep_concede_atual")),
                    "dp": dt_pub, "di": dt_ini, "df": dt_fim, "da": dt_atual,
                    "ano": (dt_ini.year if dt_ini else (dt_pub.year if dt_pub else None)),
                    "sit": "Em vigor" if dt_atual else None,
                    "raw": json.dumps(
                        {k: clean_string(v) for k, v in {**crow.to_dict(), **fact.to_dict()}.items() if clean_string(v)},
                        ensure_ascii=False, default=str,
                    ),
                })
                inserted += 1
            except Exception as e:
                if "duplicate" not in str(e).lower():
                    print(f"  Error: {e}")
                continue

        conn.execute(text("""
            INSERT INTO ingestion_log (source, status, records_processed, records_inserted, finished_at)
            VALUES ('sigcon_full', 'success', :n, :n, NOW())
        """), {"n": inserted})
        conn.commit()

    print(f"\n  Total inseridos: {inserted}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO ingestion_log (source, status, error_message, finished_at)
                VALUES ('sigcon_full', 'failed', :e, NOW())
            """), {"e": str(e)[:500]})
            conn.commit()
        print(f"ERROR: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
