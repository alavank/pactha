"""
Catalogo de Oportunidades - Programas Federais abertos.
Usa o endpoint do TransfereGov de programas em vigor.
Fonte: https://api.transferegov.gestao.gov.br/transferenciasespeciais/api/v1
       e tambem /programas via dadosabertos.
"""
import sys, os, time, json, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from datetime import datetime
from sqlalchemy import create_engine, text
from config import get_settings

logger = logging.getLogger("oportunidades")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))


def fetch_programas_transferegov():
    """Bulk SICONV - siconv_programa.csv (atualizado diariamente).
    Fonte: http://repositorio.dados.gov.br/seges/detru/siconv_programa.csv.zip
    Contem TODOS programas (ativos + inativos). Filtra na ingestao por
    `situacao_programa = 'Disponibilizado'` para mostrar so abertos.
    """
    import zipfile, io
    from config import get_settings
    s = get_settings()
    url = (s.TRANSFEREGOV_BASE_URL or "http://repositorio.dados.gov.br/seges/detru/") + "siconv_programa.csv.zip"
    logger.info(f"  Baixando {url}")
    try:
        with httpx.Client(timeout=300, verify=False, follow_redirects=True) as client:
            r = client.get(url)
            if r.status_code != 200 or r.content[:2] != b"PK":
                logger.warning(f"  HTTP {r.status_code} ou nao-zip")
                return []
    except Exception as e:
        logger.error(f"  Erro download: {e}")
        return []

    import pandas as pd
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        csv_name = [n for n in zf.namelist() if n.endswith(".csv")][0]
        with zf.open(csv_name) as f:
            df = pd.read_csv(f, sep=";", encoding="latin-1", dtype=str,
                             on_bad_lines="skip", low_memory=False)
            df.columns = [c.strip().lstrip("﻿") for c in df.columns]
    logger.info(f"  Total programas bulk: {len(df)}")

    # Filtrar so disponibilizados E com prazo de inscricao aberto (dt_fim >= hoje)
    cols = {c.upper(): c for c in df.columns}
    sit_col = next((cols[c] for c in cols if "SIT" in c and "PROGRAMA" in c), None)
    if sit_col:
        before = len(df)
        df = df[df[sit_col].fillna("").str.upper().str.contains("DISPONIB")]
        logger.info(f"  Filtrado por situacao=Disponibilizado: {before} -> {len(df)}")

    # Filtrar prazo de inscricao em aberto
    fim_col = next((cols[c] for c in cols if "DT_FIM_RECEB_PROP" in c.upper() or "DT_FIM_REC" in c.upper()), None)
    if fim_col:
        from datetime import datetime
        hoje = datetime.now().date()
        def in_window(s):
            d = parse_dt(s)
            return d is not None and d >= hoje
        before = len(df)
        df = df[df[fim_col].apply(in_window)]
        logger.info(f"  Filtrado por prazo aberto: {before} -> {len(df)}")
    return df.to_dict("records")


def parse_dt(s):
    if not s: return None
    try: return datetime.fromisoformat(s.split("T")[0]).date()
    except: pass
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try: return datetime.strptime(s.strip(), fmt).date()
        except: continue
    return None


def parse_money(v):
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    s = str(v).strip().replace("R$", "").replace(" ", "")
    if "," in s and "." in s: s = s.replace(".", "").replace(",", ".")
    elif "," in s: s = s.replace(",", ".")
    try: return float(s)
    except: return None


def main():
    logger.info("=== Pipeline Oportunidades ===")
    progs = fetch_programas_transferegov()
    logger.info(f"  {len(progs)} programas encontrados")
    if not progs:
        logger.warning("  Nenhum dado")
        return

    with engine.begin() as conn:
        # Replace integral (refletir status atual)
        conn.execute(text("DELETE FROM programas_federais"))
        inserted = 0
        # Mapear colunas do CSV SICONV (caixa alta + variantes)
        def gp(p, *keys):
            for k in keys:
                for col in p.keys():
                    if k.upper() == str(col).upper().strip():
                        v = p[col]
                        if v is not None and str(v).strip().lower() not in ("nan","null","",""):
                            return str(v).strip()
            return None

        for p in progs:
            try:
                id_prog = gp(p, "ID_PROGRAMA", "id_programa", "idPrograma", "id")
                if not id_prog or not str(id_prog).strip().isdigit(): continue
                nome = (gp(p, "NM_PROGRAMA", "nome_programa", "nomePrograma") or "")[:500]
                orgao = (gp(p, "DESC_ORGAO", "NM_ORGAO_EXECUTOR", "orgao_executor", "orgaoExecutor", "orgao") or "")[:300]
                obj = gp(p, "OBJ_PROGRAMA", "DS_OBJETIVO", "descricao", "objetivo")
                situacao = (gp(p, "SIT_PROGRAMA", "status_programa", "statusPrograma") or "Aberto")[:100]
                modalidade = gp(p, "MODALIDADE_PROGRAMA", "modalidade")
                conn.execute(text("""
                  INSERT INTO programas_federais
                    (id_programa, nome_programa, orgao, objetivo, situacao, modalidade,
                     dt_inicio_inscricao, dt_fim_inscricao,
                     valor_minimo, valor_maximo, raw_data)
                  VALUES (:i, :n, :o, :ob, :s, :md, :dii, :dif, :vmi, :vma, CAST(:raw AS jsonb))
                  ON CONFLICT (id_programa) DO UPDATE SET
                    nome_programa = EXCLUDED.nome_programa,
                    orgao = EXCLUDED.orgao,
                    situacao = EXCLUDED.situacao,
                    modalidade = EXCLUDED.modalidade,
                    raw_data = EXCLUDED.raw_data,
                    updated_at = NOW()
                """), {
                    "i": int(id_prog), "n": nome, "o": orgao, "ob": obj, "s": situacao,
                    "md": (modalidade or "")[:200] or None,
                    "dii": parse_dt(gp(p, "DT_INIC_RECEB_PROP", "data_inicio_recebimento_propostas")),
                    "dif": parse_dt(gp(p, "DT_FIM_RECEB_PROP", "data_fim_recebimento_propostas")),
                    "vmi": parse_money(gp(p, "VL_GLOBAL_PROG_MIN", "valor_minimo")),
                    "vma": parse_money(gp(p, "VL_GLOBAL_PROG", "valor_maximo")),
                    "raw": json.dumps({k: (str(v)[:200] if v is not None else None) for k,v in p.items()},
                                       ensure_ascii=False, default=str)[:30000],
                })
                inserted += 1
            except Exception as e:
                continue
        conn.execute(text("""INSERT INTO ingestion_log (source, status, records_inserted, finished_at)
                              VALUES ('oportunidades', 'success', :n, NOW())"""), {"n": inserted})
    logger.info(f"=== Oportunidades concluido: {inserted} programas ===")


if __name__ == "__main__":
    try: main()
    except Exception as e:
        import traceback; traceback.print_exc()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO ingestion_log (source, status, error_message, finished_at)
                                 VALUES ('oportunidades', 'failed', :e, NOW())"""),
                          {"e": str(e)[:500]})
