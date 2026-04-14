"""
Ingestao de emendas parlamentares federais via SICONV.
Fonte: http://repositorio.dados.gov.br/seges/detru/siconv_emenda.csv.zip

O arquivo contem NOME_PARLAMENTAR, NR_EMENDA, VALOR_REPASSE_EMENDA, TIPO_PARLAMENTAR.
Linkamos via ID_PROPOSTA ao convenio federal ja ingerido.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx, zipfile, io, pandas as pd, time
from sqlalchemy import create_engine, text
from config import get_settings
from ingestion.base import parse_decimal_br, clean_string

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))

BASE_URL = settings.TRANSFEREGOV_BASE_URL


def download_with_retry(filename, retries=3):
    for attempt in range(retries):
        try:
            url = BASE_URL + filename
            print(f"  Attempt {attempt+1}: {filename}")
            with httpx.Client(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
                r = client.get(url, follow_redirects=True)
                r.raise_for_status()
                return r.content
        except Exception as e:
            print(f"  Falhou: {e}")
            if attempt < retries - 1:
                time.sleep(5)
    return None


def read_zip_csv(data):
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        csv_name = [n for n in zf.namelist() if n.endswith(".csv")][0]
        with zf.open(csv_name) as f:
            df = pd.read_csv(io.BytesIO(f.read()), sep=";", encoding="latin-1", dtype=str, low_memory=False)
            df.columns = [c.strip().lstrip("\ufeff").lstrip("\u00ef\u00bb\u00bf") for c in df.columns]
            return df


def main():
    print("=== Ingestao Emendas Parlamentares Federais (SICONV) ===")

    # Need propostas+convenios to join, and emendas file
    print("\nDownload emendas...")
    data_e = download_with_retry("siconv_emenda.csv.zip")
    if not data_e:
        print("ERRO emendas")
        return 0
    df_em = read_zip_csv(data_e)
    print(f"  Emendas: {len(df_em)} linhas, cols: {list(df_em.columns)}")

    print("\nDownload convenios...")
    data_c = download_with_retry("siconv_convenio.csv.zip")
    if not data_c:
        print("ERRO convenios")
        return 0
    df_conv = read_zip_csv(data_c)
    print(f"  Convenios: {len(df_conv)} linhas")

    # Get DB convenios federal
    with engine.connect() as conn:
        r = conn.execute(text("SELECT id, nr_convenio, municipio_id FROM convenios_federal"))
        db_convs = {row[1]: (row[0], row[2]) for row in r.fetchall()}
    print(f"  DB convenios federais: {len(db_convs)}")

    if not db_convs:
        print("  Nenhum convenio federal no DB - pipeline emendas depende do federal rodar antes")
        return 0

    # Map ID_PROPOSTA -> nr_convenio -> (db_id, municipio_id)
    prop_to_db = {}
    for _, row in df_conv.iterrows():
        nr = str(row.get("NR_CONVENIO", "")).strip()
        pid = str(row.get("ID_PROPOSTA", "")).strip()
        if nr in db_convs:
            prop_to_db[pid] = db_convs[nr]
    print(f"  Mapping prop->db: {len(prop_to_db)}")

    # Filter emendas by target propostas
    target_props = set(prop_to_db.keys())
    filt = df_em[df_em["ID_PROPOSTA"].astype(str).str.strip().isin(target_props)]
    print(f"  Emendas vinculadas: {len(filt)}")

    if len(filt) == 0:
        return 0

    inserted = 0
    with engine.connect() as conn:
        # Clear existing federal emendas
        conn.execute(text("DELETE FROM emendas WHERE esfera = 'federal'"))
        conn.commit()

        for _, row in filt.iterrows():
            pid = str(row.get("ID_PROPOSTA", "")).strip()
            if pid not in prop_to_db:
                continue
            conv_id, mun_id = prop_to_db[pid]

            parl_nome = clean_string(row.get("NOME_PARLAMENTAR"))
            if not parl_nome:
                continue

            tipo = clean_string(row.get("TIPO_PARLAMENTAR"))
            nr_emenda = clean_string(row.get("NR_EMENDA"))
            valor = parse_decimal_br(row.get("VALOR_REPASSE_EMENDA")) or parse_decimal_br(row.get("VALOR_REPASSE_PROPOSTA_EMENDA"))

            # Upsert parlamentar (match TSE if exists)
            parl_result = conn.execute(text("""
                INSERT INTO parlamentares (nome, esfera, uf)
                VALUES (:n, 'federal', 'MG')
                ON CONFLICT (nome, partido, esfera) DO UPDATE SET uf = EXCLUDED.uf
                RETURNING id
            """), {"n": parl_nome})
            parl_id = parl_result.scalar()

            conn.execute(text("""
                INSERT INTO emendas (
                    nr_emenda, parlamentar_id, municipio_id, convenio_federal_id,
                    valor, tipo, esfera
                ) VALUES (:ne, :p, :m, :cf, :v, :tipo, 'federal')
            """), {
                "ne": nr_emenda, "p": parl_id, "m": mun_id,
                "cf": conv_id, "v": valor, "tipo": tipo,
            })
            inserted += 1

        conn.execute(text("""
            INSERT INTO ingestion_log (source, status, records_inserted, finished_at)
            VALUES ('emendas_federais', 'success', :n, NOW())
        """), {"n": inserted})
        conn.commit()

    print(f"\nEmendas inseridas: {inserted}")
    return inserted


if __name__ == "__main__":
    try:
        n = main()
        print(f"\nConcluido: {n}")
    except Exception as e:
        import traceback; traceback.print_exc()
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO ingestion_log (source, status, error_message, finished_at)
                VALUES ('emendas_federais', 'failed', :e, NOW())
            """), {"e": str(e)[:500]})
            conn.commit()
        sys.exit(1)
