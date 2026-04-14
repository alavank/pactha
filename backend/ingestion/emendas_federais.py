"""
Ingestao de emendas parlamentares federais via SICONV.
Fonte: http://repositorio.dados.gov.br/seges/detru/siconv_emenda.csv.zip

O arquivo contem NOME_PARLAMENTAR, NR_EMENDA, VALOR_REPASSE_EMENDA, TIPO_PARLAMENTAR.
Linkamos via ID_PROPOSTA ao convenio federal ja ingerido.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx, zipfile, io, pandas as pd, time, unicodedata
from sqlalchemy import create_engine, text
from config import get_settings
from ingestion.base import parse_decimal_br, clean_string


def norm_name(s):
    if s is None:
        return ""
    s = str(s).strip().upper()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


OBJETO_TO_FUNCAO = {
    "saude": ("Saude", "Atencao Basica"),
    "ubs": ("Saude", "Atencao Basica"),
    "hospital": ("Saude", "Assistencia Hospitalar"),
    "ambulanc": ("Saude", "Atencao Basica"),
    "onibus": ("Transporte Escolar", "Transporte Escolar"),
    "transporte escolar": ("Transporte Escolar", "Transporte Escolar"),
    "escola": ("Educacao", "Ensino Fundamental"),
    "educa": ("Educacao", "Ensino Fundamental"),
    "creche": ("Educacao", "Educacao Infantil"),
    "biblioteca": ("Cultura", "Difusao Cultural"),
    "cultura": ("Cultura", "Difusao Cultural"),
    "esporte": ("Esporte", "Desporto Comunitario"),
    "quadra": ("Esporte", "Desporto Comunitario"),
    "ginasio": ("Esporte", "Desporto Comunitario"),
    "futebol": ("Esporte", "Desporto Comunitario"),
    "academia": ("Esporte", "Desporto Comunitario"),
    "pavimenta": ("Obras/Infraestrutura", "Infra-estrutura Urbana"),
    "asfalto": ("Obras/Infraestrutura", "Infra-estrutura Urbana"),
    "recapeamento": ("Obras/Infraestrutura", "Infra-estrutura Urbana"),
    "calcament": ("Obras/Infraestrutura", "Infra-estrutura Urbana"),
    "drenagem": ("Saneamento", "Saneamento Basico"),
    "agua": ("Saneamento", "Saneamento Basico"),
    "esgoto": ("Saneamento", "Saneamento Basico"),
    "habita": ("Habitacao", "Habitacao Urbana"),
    "social": ("Assistencia Social", "Assistencia Comunitaria"),
    "agric": ("Agricultura", "Extensao Rural"),
    "trator": ("Agricultura", "Extensao Rural"),
    "rural": ("Agricultura", "Extensao Rural"),
    "implementos": ("Agricultura", "Extensao Rural"),
    "veiculo": ("Equipamentos", "Aquisicao"),
    "equipamento": ("Equipamentos", "Aquisicao"),
    "material permanente": ("Equipamentos", "Aquisicao"),
    "praca": ("Urbanismo", "Servicos Urbanos"),
    "obra": ("Obras/Infraestrutura", "Infra-estrutura Urbana"),
}


def classify_funcao(objeto):
    if not objeto:
        return None, None
    obj = objeto.lower()
    for kw, (f, sf) in OBJETO_TO_FUNCAO.items():
        if kw in obj:
            return f, sf
    return "Outros", None

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
            df = pd.read_csv(io.BytesIO(f.read()), sep=";", encoding="utf-8-sig", dtype=str, low_memory=False)
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

    # Pre-build normalized parlamentar lookup from TSE data (for matching)
    tse_parl_lookup = {}  # normalized name -> (id, partido)
    with engine.connect() as conn:
        r = conn.execute(text("SELECT id, nome, partido FROM parlamentares WHERE partido IS NOT NULL"))
        for row in r.fetchall():
            tse_parl_lookup[norm_name(row[1])] = (row[0], row[2])
    print(f"  TSE parlamentares no DB: {len(tse_parl_lookup)}")

    # Load objetos and years from DB (already ingested by run_federal.py)
    conv_obj_by_id = {}
    conv_ano_by_id = {}
    with engine.connect() as conn:
        r = conn.execute(text("SELECT id, objeto, ano FROM convenios_federal"))
        for row in r.fetchall():
            if row[1]:
                conv_obj_by_id[row[0]] = row[1]
            if row[2]:
                conv_ano_by_id[row[0]] = int(row[2])
    print(f"  Convenios com objeto: {len(conv_obj_by_id)}")
    print(f"  Convenios com ano: {len(conv_ano_by_id)}")

    inserted = 0
    matched_tse = 0
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

            # Try to match existing TSE parlamentar by normalized name
            norm = norm_name(parl_nome)
            parl_id = None
            partido = None
            if norm in tse_parl_lookup:
                parl_id, partido = tse_parl_lookup[norm]
                matched_tse += 1
            else:
                # Check partial match (first and last name)
                for tse_norm, (tid, tpart) in tse_parl_lookup.items():
                    # Match if all words of parl_nome appear in tse_norm
                    parl_words = set(norm.split())
                    tse_words = set(tse_norm.split())
                    if parl_words and parl_words.issubset(tse_words):
                        parl_id, partido = tid, tpart
                        matched_tse += 1
                        break

            if not parl_id:
                # Insert new parlamentar (not in TSE) - no constraint now
                parl_result = conn.execute(text("""
                    INSERT INTO parlamentares (nome, esfera, uf)
                    VALUES (:n, 'federal', 'MG')
                    RETURNING id
                """), {"n": parl_nome.upper()})
                parl_id = parl_result.scalar()
                # Add to lookup to prevent duplicates in same run
                tse_parl_lookup[norm] = (parl_id, None)

            # Classify funcao from convenio objeto (already in DB)
            objeto = conv_obj_by_id.get(conv_id)
            funcao, subfuncao = classify_funcao(objeto)

            # Get ano from convenio
            conv_ano = conv_ano_by_id.get(conv_id)

            conn.execute(text("""
                INSERT INTO emendas (
                    nr_emenda, parlamentar_id, municipio_id, convenio_federal_id,
                    valor, tipo, esfera, funcao, subfuncao, ano
                ) VALUES (:ne, :p, :m, :cf, :v, :tipo, 'federal', :f, :sf, :ano)
            """), {
                "ne": nr_emenda, "p": parl_id, "m": mun_id,
                "cf": conv_id, "v": valor, "tipo": tipo,
                "f": funcao, "sf": subfuncao, "ano": conv_ano,
            })
            inserted += 1

        conn.execute(text("""
            INSERT INTO ingestion_log (source, status, records_inserted, finished_at)
            VALUES ('emendas_federais', 'success', :n, NOW())
        """), {"n": inserted})
        conn.commit()

    print(f"\nEmendas inseridas: {inserted} (matched TSE: {matched_tse})")
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
