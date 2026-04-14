"""
Ingestao de emendas parlamentares federais.
Fonte: Portal da Transparencia - CSV mensal de Execucao de Emendas
  https://portaldatransparencia.gov.br/download-de-dados/emendas

Vincula emendas reais aos convenios federais e parlamentares TSE existentes.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx, zipfile, io, pandas as pd, unicodedata
from sqlalchemy import create_engine, text
from datetime import datetime
from config import get_settings
from ingestion.base import parse_decimal_br, clean_string

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))

# Portal Transparencia publica CSVs mensais - usa o ano atual
ANO_ATUAL = datetime.now().year


def norm(s):
    if s is None:
        return ""
    s = str(s).strip().upper()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def download_emendas():
    """Download Portal Transparencia emendas CSV for current year."""
    urls = [
        f"https://portaldatransparencia.gov.br/download-de-dados/emendas/{ANO_ATUAL}",
        f"https://portaldatransparencia.gov.br/download-de-dados/emendas/{ANO_ATUAL - 1}",
    ]
    for url in urls:
        try:
            print(f"  Tentando {url}...")
            with httpx.Client(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
                r = client.get(url, follow_redirects=True)
                r.raise_for_status()
                content = r.content
            if content[:4] == b"PK\x03\x04":
                print(f"  Tamanho: {len(content)/1024/1024:.1f} MB")
                return content
        except Exception as e:
            print(f"  Falhou: {e}")
    return None


def parse_emendas_zip(data):
    """Extract CSV from emendas zip."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        csv_files = [n for n in zf.namelist() if n.endswith(".csv")]
        print(f"  Arquivos: {csv_files}")
        dfs = []
        for csv_name in csv_files:
            with zf.open(csv_name) as f:
                content = f.read()
                for encoding in ["latin-1", "utf-8", "cp1252"]:
                    try:
                        df = pd.read_csv(
                            io.BytesIO(content), sep=";", encoding=encoding,
                            dtype=str, on_bad_lines="skip", low_memory=False,
                        )
                        df.columns = [c.strip().lstrip("\ufeff").lstrip("\u00ef\u00bb\u00bf") for c in df.columns]
                        print(f"  {csv_name}: {len(df)} linhas, cols: {list(df.columns)[:10]}")
                        dfs.append((csv_name, df))
                        break
                    except Exception:
                        continue
        return dfs


def find_col(df, keywords):
    for col in df.columns:
        cu = col.upper()
        for kw in keywords:
            if kw in cu:
                return col
    return None


def ingest_emendas_federais():
    print("\n=== Ingestao Emendas Parlamentares Federais ===")

    data = download_emendas()
    if not data:
        print("  ERRO: nao foi possivel baixar")
        return 0

    dfs = parse_emendas_zip(data)
    if not dfs:
        print("  ERRO: sem CSV valido")
        return 0

    # Get all DB convenios and municipios
    with engine.connect() as conn:
        mun_result = conn.execute(text("SELECT id, nome FROM municipios"))
        mun_map = {norm(row[1]): row[0] for row in mun_result.fetchall()}
        print(f"  Municipios DB: {list(mun_map.keys())}")

        # Get existing federal convenios
        conv_result = conn.execute(text("SELECT id, nr_convenio, municipio_id FROM convenios_federal"))
        conv_map = {row[1]: (row[0], row[2]) for row in conv_result.fetchall()}

    total_inserted = 0

    for csv_name, df in dfs:
        print(f"\n  Processando {csv_name}...")

        # Find key columns (Portal Transparencia varies)
        col_parlamentar = find_col(df, ["AUTOR_EMENDA", "NOME AUTOR", "NM_AUTOR", "AUTOR"])
        col_partido = find_col(df, ["PARTIDO"])
        col_valor = find_col(df, ["VALOR EMPENHADO", "VALOR_EMPENHADO", "VALOR", "VR_"])
        col_municipio = find_col(df, ["MUNICIPIO FAVORECIDO", "NM_MUNICIPIO", "MUNICIPIO", "MUNIC"])
        col_uf = find_col(df, ["UF FAVORECIDO", "UF"])
        col_nr_emenda = find_col(df, ["NUMERO EMENDA", "CODIGO_EMENDA", "NR_EMENDA", "NUMERO"])
        col_funcao = find_col(df, ["FUNCAO"])
        col_nr_convenio = find_col(df, ["NR_CONVENIO", "NUMERO CONVENIO", "CONVENIO"])

        print(f"  Colunas: parlamentar={col_parlamentar}, valor={col_valor}, municipio={col_municipio}, uf={col_uf}")

        if not col_parlamentar or not col_valor:
            print(f"  Pulando (colunas essenciais ausentes)")
            continue

        # Filter to MG
        if col_uf:
            df_mg = df[df[col_uf].astype(str).str.strip() == "MG"]
            print(f"  MG: {len(df_mg)}")
        else:
            df_mg = df

        # Filter to our municipalities (normalized)
        if col_municipio:
            df_mg["_mun_norm"] = df_mg[col_municipio].apply(norm)
            df_filt = df_mg[df_mg["_mun_norm"].isin(mun_map.keys())]
            print(f"  Municipios alvo: {len(df_filt)}")
        else:
            df_filt = df_mg
            print(f"  Sem coluna municipio, processando todas")

        if len(df_filt) == 0:
            continue

        with engine.connect() as conn:
            for _, row in df_filt.iterrows():
                parl_nome = clean_string(row.get(col_parlamentar))
                if not parl_nome:
                    continue

                partido = clean_string(row.get(col_partido)) if col_partido else None
                valor = parse_decimal_br(row.get(col_valor))
                if not valor or float(valor) == 0:
                    continue

                mun_nome = norm(row.get(col_municipio)) if col_municipio else None
                mun_id = mun_map.get(mun_nome) if mun_nome else None
                if not mun_id:
                    continue

                # Upsert parlamentar (match existing TSE data)
                parl_result = conn.execute(text("""
                    INSERT INTO parlamentares (nome, partido, esfera, uf)
                    VALUES (:n, :p, 'federal', 'MG')
                    ON CONFLICT (nome, partido, esfera) DO UPDATE SET uf = 'MG'
                    RETURNING id
                """), {"n": parl_nome, "p": partido})
                parl_id = parl_result.scalar()

                # Match convenio if number given
                conv_fed_id = None
                if col_nr_convenio:
                    nr = clean_string(row.get(col_nr_convenio))
                    if nr and nr in conv_map:
                        conv_fed_id, _ = conv_map[nr]

                funcao = clean_string(row.get(col_funcao)) if col_funcao else None
                nr_emenda = clean_string(row.get(col_nr_emenda)) if col_nr_emenda else None

                conn.execute(text("""
                    INSERT INTO emendas (
                        nr_emenda, parlamentar_id, municipio_id, convenio_federal_id,
                        valor, tipo, esfera, funcao
                    ) VALUES (:ne, :p, :m, :cf, :v, 'Parlamentar', 'federal', :f)
                """), {
                    "ne": nr_emenda, "p": parl_id, "m": mun_id,
                    "cf": conv_fed_id, "v": valor, "f": funcao,
                })
                total_inserted += 1

            conn.commit()

    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO ingestion_log (source, status, records_inserted, finished_at)
            VALUES ('emendas_federais', 'success', :n, NOW())
        """), {"n": total_inserted})
        conn.commit()

    print(f"\n  Total emendas inseridas: {total_inserted}")
    return total_inserted


if __name__ == "__main__":
    try:
        n = ingest_emendas_federais()
        print(f"\nConcluido: {n} emendas reais inseridas")
    except Exception as e:
        import traceback; traceback.print_exc()
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO ingestion_log (source, status, error_message, finished_at)
                VALUES ('emendas_federais', 'failed', :e, NOW())
            """), {"e": str(e)[:500]})
            conn.commit()
        sys.exit(1)
