"""Ingest TransfereGov federal data with retries."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx, zipfile, io, pandas as pd, json, time, unicodedata
from sqlalchemy import create_engine, text
from ingestion.base import parse_date_br, parse_decimal_br, clean_string
from config import get_settings

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))
BASE_URL = settings.TRANSFEREGOV_BASE_URL

def normalize_name(s):
    """Remove accents and uppercase."""
    if s is None:
        return ""
    s = str(s).strip().upper()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _load_municipios():
    """Carrega municipios ativos do DB. {NOME_NORM: id}."""
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, nome FROM municipios WHERE active=true AND uf='MG'"
        )).fetchall()
    return {normalize_name(nome): mid for mid, nome in rows}


MUNICIPIO_NAMES = _load_municipios()


def download_with_retry(filename, retries=3):
    for attempt in range(retries):
        try:
            url = BASE_URL + filename
            print(f"  Attempt {attempt+1}: Downloading {filename}...")
            with httpx.Client(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
                r = client.get(url, follow_redirects=True)
                r.raise_for_status()
                return r.content
        except Exception as e:
            print(f"  Failed: {e}")
            if attempt < retries - 1:
                time.sleep(5)
    return None


def read_zip_csv(data):
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        csv_name = [n for n in zf.namelist() if n.endswith(".csv")][0]
        with zf.open(csv_name) as f:
            df = pd.read_csv(io.BytesIO(f.read()), sep=";", encoding="utf-8-sig", dtype=str, low_memory=False)
            df.columns = [c.strip().lstrip("\ufeff").lstrip("\u00ef\u00bb\u00bf") for c in df.columns]
            return df


def main():
    # Download convenio
    data = download_with_retry("siconv_convenio.csv.zip")
    if not data:
        print("Failed to download convenios")
        return
    df_conv = read_zip_csv(data)
    print(f"Convenios: {len(df_conv)} rows")

    # Download proposta
    data2 = download_with_retry("siconv_proposta.csv.zip")
    if not data2:
        print("Failed to download propostas")
        return
    df_prop = read_zip_csv(data2)
    print(f"Propostas: {len(df_prop)} rows")
    print(f"Proposta columns: {list(df_prop.columns)[:20]}")

    # Find municipality column
    mun_col = None
    for col in df_prop.columns:
        if "MUNIC" in col.upper():
            mun_col = col
            break
    uf_col = None
    for col in df_prop.columns:
        if "UF_PROPON" in col.upper():
            uf_col = col
            break
    print(f"Mun column: {mun_col}, UF column: {uf_col}")

    # Filter MG
    df_mg = df_prop[df_prop[uf_col].astype(str).str.strip() == "MG"] if uf_col else df_prop
    print(f"MG propostas: {len(df_mg)}")

    # Search for our municipalities
    matched = pd.DataFrame()
    search_col = mun_col
    if not search_col:
        for col in df_prop.columns:
            if "NM" in col.upper() and "PROPON" in col.upper():
                search_col = col
                break

    if search_col:
        for name in MUNICIPIO_NAMES.keys():
            m = df_mg[df_mg[search_col].astype(str).apply(normalize_name).str.contains(name, na=False)]
            matched = pd.concat([matched, m])
            print(f"  {name}: {len(m)} propostas")

    print(f"Total matched propostas: {len(matched)}")
    if len(matched) == 0:
        print("No matching propostas found")
        return

    # Map proposta IDs to convenios
    target_ids = set(matched["ID_PROPOSTA"].astype(str).str.strip())
    filtered = df_conv[df_conv["ID_PROPOSTA"].astype(str).str.strip().isin(target_ids)]
    print(f"Convenios matched: {len(filtered)}")

    # Build proposta -> mun_id mapping
    prop_to_mun = {}
    for _, row in matched.iterrows():
        pid = str(row["ID_PROPOSTA"]).strip()
        mname = normalize_name(row[search_col])
        for name, db_id in MUNICIPIO_NAMES.items():
            if name in mname:
                prop_to_mun[pid] = db_id
                break

    # Insert
    inserted = 0
    with engine.connect() as conn:
        for _, row in filtered.iterrows():
            nr = clean_string(row.get("NR_CONVENIO"))
            if not nr:
                continue
            pid = str(row.get("ID_PROPOSTA", "")).strip()
            mun_id = prop_to_mun.get(pid)
            if not mun_id:
                continue

            pdata = matched[matched["ID_PROPOSTA"].astype(str).str.strip() == pid]
            objeto = orgao = None
            if len(pdata) > 0:
                pr = pdata.iloc[0]
                for c in pdata.columns:
                    cu = c.upper()
                    if "OBJETO" in cu and not objeto:
                        objeto = clean_string(pr.get(c))
                    elif "ORGAO" in cu and not orgao:
                        orgao = clean_string(pr.get(c))

            dt_inicio = parse_date_br(row.get("DIA_INIC_VIGENC_CONV"))
            dt_fim = parse_date_br(row.get("DIA_FIM_VIGENC_CONV"))

            try:
                conn.execute(text("""
                    INSERT INTO convenios_federal (
                        nr_convenio, municipio_id, orgao_concedente, objeto, situacao,
                        valor_global, valor_repasse, valor_contrapartida, valor_empenhado, valor_desembolsado,
                        dt_inicio, dt_fim_vigencia, ano, raw_data
                    ) VALUES (
                        :nr, :mun, :orgao, :obj, :sit,
                        :vg, :vr, :vc, :ve, :vd,
                        :di, :df, :ano, :raw
                    ) ON CONFLICT (nr_convenio) DO UPDATE SET
                        orgao_concedente = EXCLUDED.orgao_concedente,
                        objeto = EXCLUDED.objeto,
                        situacao = EXCLUDED.situacao,
                        valor_global = EXCLUDED.valor_global,
                        valor_repasse = EXCLUDED.valor_repasse,
                        valor_contrapartida = EXCLUDED.valor_contrapartida,
                        valor_empenhado = EXCLUDED.valor_empenhado,
                        valor_desembolsado = EXCLUDED.valor_desembolsado,
                        dt_inicio = EXCLUDED.dt_inicio,
                        dt_fim_vigencia = EXCLUDED.dt_fim_vigencia,
                        ano = EXCLUDED.ano,
                        raw_data = EXCLUDED.raw_data,
                        updated_at = NOW()
                """), {
                    "nr": nr, "mun": mun_id, "orgao": orgao, "obj": objeto,
                    "sit": clean_string(row.get("SIT_CONVENIO")),
                    "vg": parse_decimal_br(row.get("VL_GLOBAL_CONV")),
                    "vr": parse_decimal_br(row.get("VL_REPASSE_CONV")),
                    "vc": parse_decimal_br(row.get("VL_CONTRAPARTIDA_CONV")),
                    "ve": parse_decimal_br(row.get("VL_EMPENHADO_CONV")),
                    "vd": parse_decimal_br(row.get("VL_DESEMBOLSADO_CONV")),
                    "di": dt_inicio, "df": dt_fim,
                    "ano": dt_inicio.year if dt_inicio else None,
                    "raw": json.dumps(
                        {k: clean_string(v) for k, v in row.to_dict().items() if clean_string(v)},
                        ensure_ascii=False, default=str,
                    ),
                })
                inserted += 1
            except Exception as e:
                if "duplicate" not in str(e).lower():
                    print(f"Error: {e}")

        conn.commit()

    print(f"\nFederal convenios inserted: {inserted}")

    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO ingestion_log (source, status, records_processed, records_inserted, finished_at)
            VALUES ('transferegov', 'success', :n, :n, NOW())
        """), {"n": inserted})
        conn.commit()


if __name__ == "__main__":
    print("Starting TransfereGov ingestion...")
    main()
