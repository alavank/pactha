"""
Ingestao de dados eleitorais TSE 2022.
Fonte: https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/

Baixa o CSV oficial de votacao por candidato e municipio para MG,
filtra para os municipios piloto, e popula:
  - parlamentares (deputados federais e estaduais)
  - dados_eleitorais (votos reais por municipio)
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import zipfile
import io
import pandas as pd
from sqlalchemy import create_engine, text
from config import get_settings
from ingestion.base import clean_string

settings = get_settings()
db_url = settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", "")
engine = create_engine(db_url)

TSE_URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_2022.zip"

# Codigos IBGE -> TSE municipio code mapping for our pilots
# TSE uses its own 5-digit code, not IBGE
PILOTOS_NOMES = ["ARAUJOS", "NOVA SERRANA", "BOM DESPACHO", "SAO TIAGO", "TOLEDO"]


def download_tse():
    """Download the TSE 2022 candidate votes CSV (filtered to MG)."""
    print(f"  Baixando {TSE_URL}...")
    with httpx.Client(timeout=httpx.Timeout(900.0, connect=30.0)) as client:
        r = client.get(TSE_URL, follow_redirects=True)
        r.raise_for_status()
    print(f"  Tamanho: {len(r.content)/1024/1024:.1f} MB")

    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        # Find the MG file
        mg_files = [n for n in zf.namelist() if "_MG" in n.upper() and n.endswith(".csv")]
        if not mg_files:
            mg_files = [n for n in zf.namelist() if n.endswith(".csv")][:1]
        print(f"  Arquivo MG: {mg_files[0]}")

        with zf.open(mg_files[0]) as f:
            df = pd.read_csv(
                f, sep=";", encoding="latin-1", dtype=str,
                on_bad_lines="skip", low_memory=False,
            )
            print(f"  Lido: {len(df)} linhas, {len(df.columns)} colunas")
            return df


def ingest_tse():
    print("\n=== Ingestao TSE 2022 ===")
    df = download_tse()
    print(f"  Colunas: {list(df.columns)[:20]}")

    # Detect column names (TSE varies by year)
    col_map = {}
    for col in df.columns:
        cu = col.upper()
        if "NM_MUNICIPIO" in cu or cu == "NM_MUN":
            col_map["municipio"] = col
        elif "DS_CARGO" in cu or cu == "DS_CARGO_PERGUNTA":
            col_map["cargo"] = col
        elif "NM_CANDIDATO" in cu and "URNA" not in cu and "SOCIAL" not in cu:
            col_map["nome"] = col
        elif "NM_URNA_CANDIDATO" in cu:
            col_map["nome_urna"] = col
        elif "SG_PARTIDO" in cu:
            col_map["partido"] = col
        elif "QT_VOTOS_NOMINAIS" in cu and "VALIDOS" not in cu:
            col_map["votos"] = col
        elif "DS_SIT_TOT_TURNO" in cu:
            col_map["situacao"] = col

    print(f"  Mapeamento: {col_map}")

    if not col_map.get("municipio") or not col_map.get("votos"):
        print("  ERRO: colunas essenciais nao encontradas")
        return 0

    # Filter to relevant cargos
    cargos_alvo = ["DEPUTADO FEDERAL", "DEPUTADO ESTADUAL"]
    df_filt = df[df[col_map["cargo"]].astype(str).str.upper().isin(cargos_alvo)]
    print(f"  Dep. federais/estaduais: {len(df_filt)}")

    # Filter to pilot municipalities
    df_filt = df_filt[df_filt[col_map["municipio"]].astype(str).str.upper().isin(PILOTOS_NOMES)]
    print(f"  Em municipios piloto: {len(df_filt)}")

    if len(df_filt) == 0:
        return 0

    # Parse votes
    df_filt["votos_int"] = pd.to_numeric(df_filt[col_map["votos"]], errors="coerce").fillna(0).astype(int)

    # Aggregate (a candidate has multiple zonas in same municipio - sum)
    name_col = col_map.get("nome_urna") or col_map["nome"]
    grouped = df_filt.groupby(
        [col_map["municipio"], name_col, col_map["partido"], col_map["cargo"]]
    ).agg({
        "votos_int": "sum",
        col_map["situacao"]: "first" if col_map.get("situacao") else lambda x: "",
    }).reset_index()

    print(f"  Candidatos unicos por municipio: {len(grouped)}")

    inserted_parl = 0
    inserted_eleicoes = 0

    with engine.connect() as conn:
        # Get municipios
        mun_result = conn.execute(text("SELECT id, UPPER(nome) FROM municipios"))
        mun_map = {row[1]: row[0] for row in mun_result.fetchall()}

        # Clear existing electoral data for 2022
        conn.execute(text("DELETE FROM dados_eleitorais WHERE ano_eleicao = 2022"))

        # Process each row
        for _, row in grouped.iterrows():
            mun_name = str(row[col_map["municipio"]]).upper().strip()
            mun_id = mun_map.get(mun_name)
            if not mun_id:
                continue

            nome = clean_string(row[name_col])
            partido = clean_string(row[col_map["partido"]])
            cargo = clean_string(row[col_map["cargo"]])
            votos = int(row["votos_int"])
            situacao = ""
            if col_map.get("situacao"):
                situacao = str(row[col_map["situacao"]] or "").upper()
            eleito = "ELEITO" in situacao

            esfera = "federal" if "FEDERAL" in cargo.upper() else "estadual"

            if not nome or votos == 0:
                continue

            # Upsert parlamentar
            result = conn.execute(text("""
                INSERT INTO parlamentares (nome, partido, esfera, uf, legislatura)
                VALUES (:n, :p, :e, 'MG', '2023-2027')
                ON CONFLICT (nome, partido, esfera) DO UPDATE SET
                    uf = EXCLUDED.uf
                RETURNING id
            """), {"n": nome, "p": partido, "e": esfera})
            parl_id = result.scalar()
            inserted_parl += 1

            # Insert electoral data
            conn.execute(text("""
                INSERT INTO dados_eleitorais (
                    parlamentar_id, municipio_id, ano_eleicao, votos, cargo, eleito
                ) VALUES (:p, :m, 2022, :v, :c, :e)
                ON CONFLICT (parlamentar_id, municipio_id, ano_eleicao, cargo)
                DO UPDATE SET votos = EXCLUDED.votos, eleito = EXCLUDED.eleito
            """), {"p": parl_id, "m": mun_id, "v": votos, "c": cargo, "e": eleito})
            inserted_eleicoes += 1

        # Log ingestion
        conn.execute(text("""
            INSERT INTO ingestion_log (source, status, records_processed, records_inserted, finished_at)
            VALUES ('tse', 'success', :n, :n, NOW())
        """), {"n": inserted_eleicoes})
        conn.commit()

    print(f"  Parlamentares: {inserted_parl}")
    print(f"  Resultados eleitorais: {inserted_eleicoes}")
    return inserted_eleicoes


if __name__ == "__main__":
    print("Iniciando ingestao TSE...")
    try:
        n = ingest_tse()
        print(f"\nConcluido: {n} resultados eleitorais reais inseridos")
    except Exception as e:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO ingestion_log (source, status, error_message, finished_at)
                VALUES ('tse', 'failed', :e, NOW())
            """), {"e": str(e)[:500]})
            conn.commit()
        print(f"\nErro: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
