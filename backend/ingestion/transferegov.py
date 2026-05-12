"""
Pipeline de ingestao de dados do TransfereGov (federal).
Fonte: http://repositorio.dados.gov.br/seges/detru/
Estrutura: convenio.csv JOIN proposta.csv (via ID_PROPOSTA) para obter municipio.
           emenda.csv JOIN proposta.csv (via ID_PROPOSTA) para vincular.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import zipfile
import io
import json
import pandas as pd
from sqlalchemy import create_engine, text
from config import get_settings
from ingestion.base import parse_date_br, parse_decimal_br, clean_string

settings = get_settings()
db_url = settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", "")
engine = create_engine(db_url)

BASE_URL = settings.TRANSFEREGOV_BASE_URL

# Municipality names to match (uppercase, without accents for matching)
MUNICIPIO_NAMES = {
    "ARAUJOS": "3104502",
    "NOVA SERRANA": "3145208",
    "BOM DESPACHO": "3107406",
    "SAO TIAGO": "3164704",
    "TOLEDO": "3169406",
}


def download_csv(filename: str) -> pd.DataFrame:
    """Download a zip file from TransfereGov and extract the CSV."""
    url = BASE_URL + filename
    print(f"  Baixando {url}...")
    with httpx.stream("GET", url, timeout=600, follow_redirects=True) as r:
        data = b""
        for chunk in r.iter_bytes():
            data += chunk
    print(f"  Tamanho: {len(data)/1024/1024:.1f} MB")

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        csv_name = [n for n in zf.namelist() if n.endswith(".csv")][0]
        with zf.open(csv_name) as f:
            content = f.read()
            df = pd.read_csv(
                io.BytesIO(content),
                sep=";", encoding="latin-1", dtype=str,
                on_bad_lines="skip", low_memory=False,
            )
            # Clean BOM from first column name
            if df.columns[0].startswith("\ufeff"):
                df.columns = [c.lstrip("\ufeff") for c in df.columns]
            print(f"  Lido: {len(df)} linhas, {len(df.columns)} colunas")
            return df


def get_municipio_map():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT id, ibge_code FROM municipios"))
        return {row[1]: row[0] for row in result.fetchall()}


def ingest_convenios():
    """Ingest convenios: download proposta + convenio, join, filter by municipality."""
    print("\n=== Ingestao de Convenios Federais ===")
    mun_map = get_municipio_map()

    # 1. Download proposta (has municipality info)
    df_proposta = download_csv("siconv_proposta.csv.zip")
    print(f"  Colunas proposta: {list(df_proposta.columns)[:20]}...")

    # Find municipality column in proposta
    mun_col = None
    uf_col = None
    for col in df_proposta.columns:
        cl = col.upper().strip()
        if "MUNIC_PROPONENTE" in cl or "NM_MUNICIPIO" in cl:
            mun_col = col
        elif "UF_PROPONENTE" in cl or cl == "UF":
            uf_col = col

    if not mun_col:
        # Fallback: check all columns for municipality-like names
        for col in df_proposta.columns:
            if "munic" in col.lower():
                mun_col = col
                break

    print(f"  Coluna municipio: {mun_col}, UF: {uf_col}")

    # Filter propostas by MG municipalities
    if uf_col:
        df_mg = df_proposta[df_proposta[uf_col].astype(str).str.strip() == "MG"]
    else:
        df_mg = df_proposta

    # Match by municipality name
    matched_propostas = pd.DataFrame()
    if mun_col:
        df_mg[mun_col + "_upper"] = df_mg[mun_col].astype(str).str.upper().str.strip()
        for name in MUNICIPIO_NAMES.keys():
            matches = df_mg[df_mg[mun_col + "_upper"].str.contains(name, na=False)]
            matched_propostas = pd.concat([matched_propostas, matches])
        print(f"  Propostas de municipios-alvo: {len(matched_propostas)}")
    else:
        print("  AVISO: Coluna de municipio nao encontrada nas propostas")
        return 0

    if len(matched_propostas) == 0:
        print("  Nenhuma proposta encontrada para os municipios-alvo")
        return 0

    # Get ID_PROPOSTA set for these municipalities
    target_ids = set(matched_propostas["ID_PROPOSTA"].astype(str).str.strip())
    print(f"  IDs de proposta: {len(target_ids)}")

    # 2. Download convenios and filter by proposta IDs
    df_conv = download_csv("siconv_convenio.csv.zip")

    # Clean column names
    df_conv.columns = [c.strip() for c in df_conv.columns]
    if df_conv.columns[0].startswith("\ufeff"):
        df_conv.columns = [c.lstrip("\ufeff") for c in df_conv.columns]

    filtered = df_conv[df_conv["ID_PROPOSTA"].astype(str).str.strip().isin(target_ids)]
    print(f"  Convenios filtrados: {len(filtered)}")

    if len(filtered) == 0:
        return 0

    # Create proposta -> municipality mapping
    prop_to_mun = {}
    if mun_col:
        for _, row in matched_propostas.iterrows():
            prop_id = str(row["ID_PROPOSTA"]).strip()
            mun_name = str(row[mun_col]).upper().strip()
            for name, ibge in MUNICIPIO_NAMES.items():
                if name in mun_name:
                    prop_to_mun[prop_id] = mun_map.get(ibge)
                    break

    inserted = 0
    with engine.connect() as conn:
        for _, row in filtered.iterrows():
            nr = clean_string(row.get("NR_CONVENIO", None))
            if not nr:
                continue

            prop_id = str(row.get("ID_PROPOSTA", "")).strip()
            mun_id = prop_to_mun.get(prop_id)
            if not mun_id:
                continue

            # Get proposta data for this convenio
            prop_data = matched_propostas[matched_propostas["ID_PROPOSTA"].astype(str).str.strip() == prop_id]
            objeto = None
            orgao = None
            programa = None
            if len(prop_data) > 0:
                prow = prop_data.iloc[0]
                for col in prop_data.columns:
                    cl = col.upper().strip()
                    if "OBJETO" in cl and not objeto:
                        objeto = clean_string(prow.get(col))
                    elif "ORGAO" in cl and not orgao:
                        orgao = clean_string(prow.get(col))
                    elif "PROGRAMA" in cl and not programa:
                        programa = clean_string(prow.get(col))

            dt_inicio = parse_date_br(row.get("DIA_INIC_VIGENC_CONV"))
            dt_fim = parse_date_br(row.get("DIA_FIM_VIGENC_CONV"))
            sit = clean_string(row.get("SIT_CONVENIO"))

            raw = {}
            for k, v in row.to_dict().items():
                val = clean_string(v)
                if val:
                    raw[k.strip()] = val

            try:
                conn.execute(text("""
                    INSERT INTO convenios_federal (
                        nr_convenio, municipio_id, proponente_nome, orgao_concedente,
                        objeto, situacao, valor_global, valor_repasse, valor_contrapartida,
                        valor_empenhado, valor_desembolsado, dt_inicio, dt_fim_vigencia,
                        ano, programa, raw_data
                    ) VALUES (
                        :nr, :mun, :prop, :orgao, :obj, :sit,
                        :vg, :vr, :vc, :ve, :vd, :di, :df,
                        :ano, :prog, :raw
                    )
                    ON CONFLICT (nr_convenio) DO UPDATE SET
                        situacao = EXCLUDED.situacao,
                        valor_global = EXCLUDED.valor_global,
                        valor_repasse = EXCLUDED.valor_repasse,
                        valor_contrapartida = EXCLUDED.valor_contrapartida,
                        valor_empenhado = EXCLUDED.valor_empenhado,
                        valor_desembolsado = EXCLUDED.valor_desembolsado,
                        dt_fim_vigencia = EXCLUDED.dt_fim_vigencia,
                        raw_data = EXCLUDED.raw_data,
                        updated_at = NOW()
                """), {
                    "nr": nr,
                    "mun": mun_id,
                    "prop": clean_string(row.get("NM_PROPONENTE", None)) or orgao,
                    "orgao": orgao,
                    "obj": objeto,
                    "sit": sit,
                    "vg": parse_decimal_br(row.get("VL_GLOBAL_CONV")),
                    "vr": parse_decimal_br(row.get("VL_REPASSE_CONV")),
                    "vc": parse_decimal_br(row.get("VL_CONTRAPARTIDA_CONV")),
                    "ve": parse_decimal_br(row.get("VL_EMPENHADO_CONV")),
                    "vd": parse_decimal_br(row.get("VL_DESEMBOLSADO_CONV")),
                    "di": dt_inicio,
                    "df": dt_fim,
                    "ano": dt_inicio.year if dt_inicio else None,
                    "prog": programa,
                    "raw": json.dumps(raw, ensure_ascii=False, default=str),
                })
                inserted += 1
            except Exception as e:
                if "duplicate" not in str(e).lower():
                    print(f"  Erro: {e}")
                continue

        conn.commit()
    print(f"  Convenios inseridos/atualizados: {inserted}")
    return inserted


def ingest_emendas():
    """Ingest emendas linked to existing convenios via ID_PROPOSTA."""
    print("\n=== Ingestao de Emendas Federais ===")

    # Get existing convenios
    with engine.connect() as conn:
        result = conn.execute(text("SELECT nr_convenio, id, municipio_id FROM convenios_federal"))
        conv_map = {row[0]: (row[1], row[2]) for row in result.fetchall()}

    if not conv_map:
        print("  Nenhum convenio federal para vincular emendas")
        return 0

    # Download emendas
    df_emenda = download_csv("siconv_emenda.csv.zip")
    df_emenda.columns = [c.strip().lstrip("\ufeff") for c in df_emenda.columns]
    print(f"  Colunas emenda: {list(df_emenda.columns)}")

    # Download proposta to get nr_convenio mapping
    # Emendas link via ID_PROPOSTA, convenios also have ID_PROPOSTA
    # We need to map: emenda.ID_PROPOSTA -> proposta -> convenio.NR_CONVENIO

    # Download convenio CSV again to get ID_PROPOSTA -> NR_CONVENIO mapping
    df_conv = download_csv("siconv_convenio.csv.zip")
    df_conv.columns = [c.strip().lstrip("\ufeff") for c in df_conv.columns]

    # Build mapping: ID_PROPOSTA -> NR_CONVENIO
    prop_to_nr = {}
    for _, row in df_conv.iterrows():
        nr = str(row.get("NR_CONVENIO", "")).strip()
        pid = str(row.get("ID_PROPOSTA", "")).strip()
        if nr in conv_map:
            prop_to_nr[pid] = nr

    # Filter emendas by matched propostas
    target_props = set(prop_to_nr.keys())
    filtered = df_emenda[df_emenda["ID_PROPOSTA"].astype(str).str.strip().isin(target_props)]
    print(f"  Emendas vinculadas: {len(filtered)}")

    if len(filtered) == 0:
        return 0

    inserted = 0
    with engine.connect() as conn:
        for _, row in filtered.iterrows():
            pid = str(row["ID_PROPOSTA"]).strip()
            nr_conv = prop_to_nr.get(pid)
            if not nr_conv or nr_conv not in conv_map:
                continue
            conv_id, mun_id = conv_map[nr_conv]

            parl_nome = clean_string(row.get("NOME_PARLAMENTAR"))
            parl_id = None
            if parl_nome:
                result = conn.execute(text("""
                    INSERT INTO parlamentares (nome, esfera)
                    VALUES (:nome, 'federal')
                    ON CONFLICT (nome, partido, esfera) DO UPDATE SET nome = EXCLUDED.nome
                    RETURNING id
                """), {"nome": parl_nome})
                parl_id = result.scalar()

            nr_emenda = clean_string(row.get("NR_EMENDA"))
            valor = parse_decimal_br(row.get("VALOR_REPASSE_EMENDA"))
            tipo = clean_string(row.get("TIPO_PARLAMENTAR"))

            try:
                conn.execute(text("""
                    INSERT INTO emendas (nr_emenda, parlamentar_id, municipio_id, convenio_federal_id, valor, tipo, esfera)
                    VALUES (:nr, :parl, :mun, :conv, :val, :tipo, 'federal')
                """), {
                    "nr": nr_emenda, "parl": parl_id, "mun": mun_id,
                    "conv": conv_id, "val": valor, "tipo": tipo,
                })
                inserted += 1
            except Exception as e:
                continue

        conn.commit()
    print(f"  Emendas inseridas: {inserted}")
    return inserted


def log_ingestion(source, status, records, error=None):
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO ingestion_log (source, status, records_processed, records_inserted, error_message, finished_at)
            VALUES (:source, :status, :records, :records, :error, NOW())
        """), {"source": source, "status": status, "records": records, "error": error})
        conn.commit()


def ingest_propostas_pendentes():
    """Ingere propostas SICONV que ainda nao viraram convenio formalizado.

    Motivacao: PDF Freitas mostra que muitas indicacoes 2025/2026 estao em fase
    de proposta (Festa do Ruralista R$398k, Pavimentacao Dr. Frederico R$398k,
    etc) - ainda em analise pelo concedente, sem nr_convenio formalizado. O
    ingest_convenios() so pega convenios formalizados e perde tudo isso.

    Esta funcao pega propostas 2025+ que NAO tem convenio correspondente, e
    insere como stub com situacao='Proposta em analise' usando ID_PROPOSTA
    como nr_convenio (prefixo 'PROP-' para nao conflitar).
    """
    print("\n=== Ingestao de Propostas Pendentes (sem convenio) ===")
    mun_map = get_municipio_map()

    df_proposta = download_csv("siconv_proposta.csv.zip")
    df_proposta.columns = [c.strip().lstrip("﻿") for c in df_proposta.columns]

    mun_col = next((c for c in df_proposta.columns if "MUNIC_PROPONENTE" in c.upper() or "NM_MUNICIPIO" in c.upper()), None)
    uf_col = next((c for c in df_proposta.columns if "UF_PROPONENTE" in c.upper() or c.upper().strip() == "UF"), None)
    if not mun_col:
        print("  AVISO: coluna municipio nao encontrada")
        return 0

    if uf_col:
        df_proposta = df_proposta[df_proposta[uf_col].astype(str).str.strip() == "MG"]

    df_proposta[mun_col + "_upper"] = df_proposta[mun_col].astype(str).str.upper().str.strip()
    matched = pd.DataFrame()
    for name in MUNICIPIO_NAMES.keys():
        matched = pd.concat([matched, df_proposta[df_proposta[mun_col + "_upper"].str.contains(name, na=False)]])

    if len(matched) == 0:
        return 0

    # Filtrar so propostas 2025+ (cobrem o gap atual; antigas ja viraram convenio)
    ano_col = next((c for c in matched.columns if c.upper().strip() == "ANO_PROP"), None)
    if ano_col:
        matched = matched[matched[ano_col].astype(str).str.strip().isin(["2025", "2026"])]
    print(f"  Propostas 2025/2026 nos municipios-alvo: {len(matched)}")

    # Identificar propostas SEM convenio formalizado
    df_conv = download_csv("siconv_convenio.csv.zip")
    df_conv.columns = [c.strip().lstrip("﻿") for c in df_conv.columns]
    convenios_props = set(df_conv["ID_PROPOSTA"].astype(str).str.strip())

    matched_pending = matched[~matched["ID_PROPOSTA"].astype(str).str.strip().isin(convenios_props)]
    print(f"  Propostas SEM convenio formalizado: {len(matched_pending)}")

    if len(matched_pending) == 0:
        return 0

    inserted = 0
    with engine.connect() as conn:
        for _, row in matched_pending.iterrows():
            prop_id = str(row["ID_PROPOSTA"]).strip()
            mun_name = str(row[mun_col]).upper().strip()
            mun_id = None
            for name, ibge in MUNICIPIO_NAMES.items():
                if name in mun_name:
                    mun_id = mun_map.get(ibge)
                    break
            if not mun_id:
                continue

            nr = f"PROP-{prop_id}"
            objeto = next((clean_string(row.get(c)) for c in row.index if "OBJETO" in c.upper()), None)
            orgao = next((clean_string(row.get(c)) for c in row.index if "ORGAO" in c.upper()), None)
            programa = next((clean_string(row.get(c)) for c in row.index if "PROGRAMA" in c.upper() and "DESC" in c.upper()), None)
            sit = next((clean_string(row.get(c)) for c in row.index if "SIT_PROPOSTA" in c.upper()), "Proposta em analise")
            ano = None
            if ano_col:
                try: ano = int(str(row.get(ano_col, "")).strip())
                except: pass

            raw = {k: clean_string(v) for k, v in row.to_dict().items() if clean_string(v)}
            try:
                conn.execute(text("""
                    INSERT INTO convenios_federal (
                        nr_convenio, municipio_id, proponente_nome, orgao_concedente,
                        objeto, situacao, valor_global, valor_repasse, ano, programa, fonte, raw_data
                    ) VALUES (
                        :nr, :mun, :prop, :orgao, :obj, :sit, :vg, :vr, :ano, :prog, 'TransfereGov-Proposta', :raw
                    )
                    ON CONFLICT (nr_convenio) DO UPDATE SET
                        situacao = EXCLUDED.situacao,
                        valor_global = EXCLUDED.valor_global,
                        valor_repasse = EXCLUDED.valor_repasse,
                        raw_data = EXCLUDED.raw_data,
                        updated_at = NOW()
                """), {
                    "nr": nr,
                    "mun": mun_id,
                    "prop": clean_string(row.get("NM_PROPONENTE")) or orgao,
                    "orgao": orgao,
                    "obj": objeto,
                    "sit": sit,
                    "vg": parse_decimal_br(row.get("VL_GLOBAL_PROP") or row.get("VL_GLOBAL")),
                    "vr": parse_decimal_br(row.get("VL_REPASSE_PROP") or row.get("VL_REPASSE")),
                    "ano": ano,
                    "prog": programa,
                    "raw": json.dumps(raw, ensure_ascii=False, default=str),
                })
                inserted += 1
            except Exception as e:
                if "duplicate" not in str(e).lower():
                    print(f"  Erro inserindo proposta {nr}: {e}")
                continue
        conn.commit()

    print(f"  Propostas pendentes inseridas: {inserted}")
    return inserted


if __name__ == "__main__":
    print("Iniciando ingestao TransfereGov...")
    try:
        total = ingest_convenios()
        total += ingest_emendas()
        total += ingest_propostas_pendentes()
        log_ingestion("transferegov", "success", total)
        print(f"\nIngestao concluida: {total} registros total")
    except Exception as e:
        log_ingestion("transferegov", "failed", 0, str(e))
        print(f"\nErro na ingestao: {e}")
        import traceback
        traceback.print_exc()
