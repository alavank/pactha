"""
Extrai emendas parlamentares estaduais dos convenios SIGCON.
O objeto dos convenios estaduais frequentemente contem:
  "TRANSFERENCIA ESPECIAL: NOME DO DEPUTADO - INDICACAO: XXXXX"

Esta funcao extrai o nome e cria um registro em emendas vinculado ao convenio
e ao parlamentar (criado ou existente).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import re
import unicodedata
from sqlalchemy import create_engine, text
from config import get_settings

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))


def norm_name(s):
    if not s:
        return ""
    s = str(s).strip().upper()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


# Regex para extrair nome do parlamentar/bloco/comissao do objeto
# Exemplos reais SIGCON:
#   "TRANSFERENCIA ESPECIAL: FABIO AVELAR DE OLIVEIRA - INDICACAO: 78139"
#   "TRANSFERENCIA ESPECIAL: BLOCO LIBERDADE E PROGRESSO - INDICACAO: 62571"
#   "TRANSFERENCIA ESPECIAL: PARTIDO LIBERAL - INDICACAO: 115305"
#   "TRANSFERENCIA ESPECIAL: COMISSAO DE SAUDE - INDICACAO: 99999"
#   "TRANSFERENCIA ESPECIAL: FRED COSTA / REGINALDO LOPES - INDICACAO: ..."  (compartilhada)
#   "TRANSFERENCIA ESPECIAL: VILSON / FETAEMG - INDICACAO: ..."

# Programas estaduais MG conhecidos (rotulos institucionais sem deputado)
# Quando aparecem no objeto, classificam como autor da indicacao.
PROGRAMAS_ESTADUAIS = [
    "PROMAQ",         # Programa Mineiro de Aquisicao de Equipamentos
    "FETAEMG",        # Federacao Trabalhadores Agricultura MG
    "VIVAVALE",       # Programa estadual
    "MINAS COMUNICA", # Programa SEAPA
    "AGUA PARA TODOS",
    "TRAVESSIA",
    "AGENTES DO BEM",
    # Resolucoes SES costumam vir com numero
    # Bancada / Bloco / Comissao identificados por keywords no PATTERNS
]

# Regex para indicacao compartilhada: "X / Y" ou "X E Y"
RE_COMPARTILHADA = re.compile(
    r"TRANSFERENC[IÍ]A\s+ESPECIAL\s*[:\-]?\s*"
    r"([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ][A-ZÁÉÍÓÚÀÂÊÔÃÕÇ\s\.]+?)\s*[\/]\s*"
    r"([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ][A-ZÁÉÍÓÚÀÂÊÔÃÕÇ\s\.]+?)"
    r"(?:\s*[-–]\s*INDICA[CÇ][AÃ]O|\s*$)",
    re.IGNORECASE,
)


def extract_shared(objeto):
    """Detecta indicacao compartilhada 'NomeA / NomeB'.
    Retorna lista de nomes [A, B] ou None."""
    if not objeto: return None
    m = RE_COMPARTILHADA.search(objeto)
    if not m: return None
    nomes = [m.group(1).strip().upper(), m.group(2).strip().upper()]
    # Filtrar ruido
    return [n for n in nomes if 3 <= len(n) <= 60]


def extract_programa_estadual(objeto):
    """Detecta programa estadual conhecido no objeto.
    Retorna nome do programa ou None."""
    if not objeto: return None
    obj_u = objeto.upper()
    for prog in PROGRAMAS_ESTADUAIS:
        if prog in obj_u:
            return prog
    return None


def is_institucional_keyword(name):
    """Detecta se o nome extraido contem keyword institucional.
    Usado para padronizar capitalizacao quando insere parlamentar novo."""
    if not name: return False
    nu = name.upper()
    return any(k in nu for k in [
        "BANCADA", "COMISS", "BLOCO", "RELATOR", "PROGRAMA",
        "DOACAO", "RESOLUC", "FETAEMG", "FAEMG",
    ])


PATTERNS = [
    # Pattern principal: tudo entre "TRANSFERENCIA ESPECIAL:" e "- INDICACAO:" (ou final)
    re.compile(
        r"TRANSFERENC[IÍ]A\s+ESPECIAL\s*[:\-]?\s*([^-\n]+?)(?:\s*[-–]\s*INDICA[CÇ][AÃ]O|\s*$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"INDICA[CÇ][AÃ]O\s+(?:DE\s+|DO\s+|DA\s+)?([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ][A-ZÁÉÍÓÚÀÂÊÔÃÕÇ\s]+?)(?:\s*[-–]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"EMENDA\s+PARLAMENTAR\s*[:\-]?\s*([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ][A-ZÁÉÍÓÚÀÂÊÔÃÕÇ\s]+?)(?:\s*[-–]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"DEPUTAD[OA]\s+(?:ESTADUAL\s+|FEDERAL\s+)?([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ][A-ZÁÉÍÓÚÀÂÊÔÃÕÇ\s]+?)(?:\s*[-–]|$)",
        re.IGNORECASE,
    ),
    # SES-MG e SEGOV-MG: padroes de "RESOLUCAO" + numero podem indicar grupo
    re.compile(
        r"RESOLU[CÇ][AÃ]O\s+(\d{4,5}\s*/?\s*SES)",
        re.IGNORECASE,
    ),
]

# Stopwords no inicio do nome (devem ser removidas)
LEAD_NOISE = re.compile(r"^(SR\.?|SR[AO]\.?|DEPUTAD[OA]|DEP\.?)\s+", re.IGNORECASE)


def extract_name(objeto):
    if not objeto:
        return None
    obj = objeto.strip()
    for pat in PATTERNS:
        m = pat.search(obj)
        if m:
            name = m.group(1).strip()
            # Limpa ruido inicial e final
            name = LEAD_NOISE.sub("", name)
            name = re.sub(r"\s+(DE|DA|DO|DOS|DAS|E|EM|PARA)\s*$", "", name, flags=re.IGNORECASE)
            name = re.sub(r"\s+", " ", name).strip()
            # Remove pontuacao no final
            name = name.rstrip(".,;:")
            if 3 <= len(name) <= 80:
                return name.upper()
    return None


def main():
    print("=== Extraindo parlamentares de convenios estaduais SIGCON ===")

    with engine.connect() as conn:
        # Get all convenios estaduais with valor > 0 and objeto
        rows = conn.execute(text("""
            SELECT id, municipio_id, objeto,
                   COALESCE(NULLIF(valor_emenda_parlamentar, 0), valor_total, 0) as valor,
                   ano
            FROM convenios_estadual
            WHERE objeto IS NOT NULL
        """)).fetchall()
        print(f"  Convenios a analisar: {len(rows)}")

        # Preload existing TSE parlamentares for fuzzy matching
        tse_rows = conn.execute(text("""
            SELECT id, nome, partido FROM parlamentares WHERE partido IS NOT NULL
        """)).fetchall()
        tse_by_norm = {}
        for pid, pnome, ppart in tse_rows:
            tse_by_norm[norm_name(pnome)] = (pid, ppart)
        print(f"  Parlamentares TSE disponiveis: {len(tse_by_norm)}")

        # Clear existing estaduais first
        conn.execute(text("DELETE FROM emendas WHERE esfera = 'estadual'"))

        extracted = 0
        matched_tse = 0
        shared_count = 0
        programa_count = 0
        for cid, mun_id, objeto, valor, ano in rows:
            valor_f = float(valor or 0)

            # === 1. INDICACAO COMPARTILHADA (X / Y) ===
            shared = extract_shared(objeto)
            if shared:
                # Cria 2 emendas, uma para cada parlamentar, dividindo o valor
                valor_share = valor_f / 2
                shared_pids = []
                for nome_s in shared:
                    norm_s = norm_name(nome_s)
                    pid_s = tse_by_norm.get(norm_s, (None, None))[0]
                    if not pid_s:
                        res = conn.execute(text("""
                            INSERT INTO parlamentares (nome, esfera, uf)
                            VALUES (:n, 'estadual', 'MG') RETURNING id
                        """), {"n": nome_s[:300]})
                        pid_s = res.scalar()
                        tse_by_norm[norm_s] = (pid_s, None)
                    shared_pids.append(pid_s)
                for pid_s in shared_pids:
                    conn.execute(text("""
                        INSERT INTO emendas (parlamentar_id, municipio_id, convenio_estadual_id,
                                              valor, tipo, esfera, ano)
                        VALUES (:p, :m, :c, :v, 'Transferencia Especial Compartilhada', 'estadual', :a)
                    """), {"p": pid_s, "m": mun_id, "c": cid, "v": valor_share,
                            "a": int(ano) if ano else None})
                shared_count += 1
                extracted += 2
                continue

            # === 2. PROGRAMA ESTADUAL conhecido (PROMAQ, FETAEMG, etc) ===
            prog = extract_programa_estadual(objeto)
            if prog:
                norm_p = norm_name(prog)
                pid_p = tse_by_norm.get(norm_p, (None, None))[0]
                if not pid_p:
                    res = conn.execute(text("""
                        INSERT INTO parlamentares (nome, esfera, uf)
                        VALUES (:n, 'estadual', 'MG') RETURNING id
                    """), {"n": prog})
                    pid_p = res.scalar()
                    tse_by_norm[norm_p] = (pid_p, None)
                conn.execute(text("""
                    INSERT INTO emendas (parlamentar_id, municipio_id, convenio_estadual_id,
                                          valor, tipo, esfera, ano)
                    VALUES (:p, :m, :c, :v, 'Programa Estadual', 'estadual', :a)
                """), {"p": pid_p, "m": mun_id, "c": cid, "v": valor_f,
                        "a": int(ano) if ano else None})
                programa_count += 1
                extracted += 1
                continue

            # === 3. PARLAMENTAR INDIVIDUAL (regex padrao) ===
            name = extract_name(objeto)
            if not name:
                continue
            # Aceitar valor 0 desde que seja indicacao real (PDF mostra varios pendentes/em analise)

            # Try to match with TSE (exact or fuzzy)
            norm = norm_name(name)
            parl_id = None
            parl_partido = None

            if norm in tse_by_norm:
                parl_id, parl_partido = tse_by_norm[norm]
                matched_tse += 1
            else:
                # Fuzzy mais rigoroso: ignorar conectivos e exigir match de nome+sobrenome
                # ou um sobrenome distintivo (4+ chars, nao em STOP).
                # 2 palavras compartilhadas sao insuficientes (ex.: "DE OLIVEIRA" causava
                # falsos positivos: "FABIO AVELAR DE OLIVEIRA" -> "MAERCIO DE OLIVEIRA").
                STOP = {
                    "DE", "DA", "DO", "DOS", "DAS", "E", "EM",
                    "BLOCO", "PARTIDO", "DEPUTADO", "DEPUTADA", "SR", "SRA",
                    "JUNIOR", "FILHO", "NETO",
                }
                name_core = [w for w in norm.split() if w not in STOP and len(w) >= 3]
                if len(name_core) >= 2:
                    for tse_norm, (tid, tpart) in tse_by_norm.items():
                        tse_core = [w for w in tse_norm.split() if w not in STOP and len(w) >= 3]
                        if len(tse_core) < 2:
                            continue
                        common = set(name_core) & set(tse_core)
                        # exige: 2+ tokens comuns E ratio >= 0.6 dos tokens distintivos
                        # do nome do banco (evita "MINAS" sozinho casar bloco generico)
                        if len(common) >= 2 and len(common) / max(len(tse_core), 1) >= 0.6:
                            parl_id = tid
                            parl_partido = tpart
                            matched_tse += 1
                            break

            if not parl_id:
                # Create new parlamentar
                res = conn.execute(text("""
                    INSERT INTO parlamentares (nome, esfera, uf)
                    VALUES (:n, 'estadual', 'MG')
                    RETURNING id
                """), {"n": name})
                parl_id = res.scalar()
                tse_by_norm[norm] = (parl_id, None)

            # Insert emenda
            conn.execute(text("""
                INSERT INTO emendas (
                    parlamentar_id, municipio_id, convenio_estadual_id,
                    valor, tipo, esfera, ano
                ) VALUES (:p, :m, :c, :v, 'Transferencia Especial', 'estadual', :a)
            """), {
                "p": parl_id, "m": mun_id, "c": cid,
                "v": valor_f, "a": int(ano) if ano else None,
            })
            extracted += 1

        conn.execute(text("""
            INSERT INTO ingestion_log (source, status, records_inserted, finished_at)
            VALUES ('emendas_estaduais', 'success', :n, NOW())
        """), {"n": extracted})
        conn.commit()

    print(f"\n  Emendas estaduais extraidas: {extracted}")
    print(f"  Matchadas com TSE: {matched_tse}")
    print(f"  Compartilhadas (X / Y): {shared_count}")
    print(f"  Programas estaduais (PROMAQ/FETAEMG/etc): {programa_count}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback; traceback.print_exc()
        sys.exit(1)
