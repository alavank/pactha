"""
Pipeline DOU (Diario Oficial da Uniao) via INLABS.
Fonte: https://inlabs.in.gov.br/index.php (requer cadastro gratuito)
       Login + XML/JSON diario por secao (1, 2, 3, 1e, 2e, 3e).

Funcionamento:
1. Login via POST em https://inlabs.in.gov.br/login
2. Download do ZIP do dia em /index.php?p=YYYY-MM-DD&secao=do1
3. Parse XML + filtro por keywords + municipios alvo
"""
import sys, os, time, json, logging, zipfile, io, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta
from sqlalchemy import create_engine, text
from config import get_settings

logger = logging.getLogger("dou_inlabs")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))

# Credenciais INLABS via env (gratuito - cadastrar em inlabs.in.gov.br)
INLABS_USER = os.getenv("INLABS_USER")
INLABS_PASS = os.getenv("INLABS_PASS")

# Palavras-chave de interesse Freitas (orgaos + programas)
KEYWORDS = [
    "Piracema", "Bom Despacho", "Nova Serrana", "Araujos", "Sao Tiago", "Toledo",
    "FNDE", "Ministerio da Saude", "FNS", "PAP", "MAC", "Custeio",
    "CODEVASF", "TransfereGov", "Transferencia Especial",
    "emenda parlamentar", "indicacao parlamentar",
]


def autenticar():
    """Login INLABS retorna cookies de sessao."""
    if not INLABS_USER or not INLABS_PASS:
        raise RuntimeError("INLABS_USER e INLABS_PASS nao configurados no env")
    s = httpx.Client(timeout=60, verify=False, follow_redirects=True)
    r = s.post("https://inlabs.in.gov.br/logar.php",
               data={"email": INLABS_USER, "password": INLABS_PASS})
    if "Sair" not in r.text and "logout" not in r.text.lower():
        raise RuntimeError("Login INLABS falhou")
    return s


def baixar_dia(client, dt: date, secao: str = "do1"):
    """Baixa zip do dia/secao. Retorna lista de articles parseados."""
    url = f"https://inlabs.in.gov.br/index.php?p={dt.isoformat()}&dl={dt.isoformat()}-{secao}.zip"
    r = client.get(url)
    if r.status_code != 200 or r.content[:2] != b"PK":
        return []

    articles = []
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        for name in zf.namelist():
            if not name.endswith(".xml"): continue
            try:
                xml = zf.read(name).decode("utf-8", errors="replace")
                root = ET.fromstring(xml)
                for art in root.findall(".//article"):
                    body = " ".join(t.text or "" for t in art.iter() if t.text)
                    if not body.strip(): continue
                    articles.append({
                        "id_oficio": art.get("id") or art.get("idMateria"),
                        "secao": secao,
                        "dt": dt,
                        "orgao": (art.get("artType") or art.get("artCategory") or "")[:300],
                        "titulo": (art.get("name") or art.findtext(".//Title") or "")[:1000],
                        "texto": body[:50000],
                        "edicao": art.get("editionNumber"),
                        "pagina": art.get("pageNumber"),
                        "url_pdf": art.get("pdfPage"),
                        "xml": xml[:50000],
                    })
            except Exception:
                continue
    return articles


def matches_keywords(texto: str) -> list[str]:
    if not texto: return []
    t = texto.lower()
    return [kw for kw in KEYWORDS if kw.lower() in t]


def municipio_match(texto: str) -> str | None:
    if not texto: return None
    for mun in ["Piracema", "Bom Despacho", "Nova Serrana", "Araujos", "Araújos", "Sao Tiago", "São Tiago", "Toledo"]:
        if mun in texto: return mun
    return None


def main():
    logger.info("=== Pipeline DOU INLABS ===")
    try:
        client = autenticar()
    except Exception as e:
        logger.error(f"Sem credencial INLABS: {e}")
        logger.info("Cadastre-se em https://inlabs.in.gov.br e configure INLABS_USER/INLABS_PASS")
        return

    # Processar ultimos 3 dias uteis
    hoje = date.today()
    total = 0
    with engine.begin() as conn:
        for delta in range(0, 7):
            dt = hoje - timedelta(days=delta)
            if dt.weekday() >= 5:  # sab/dom
                continue
            for secao in ("do1", "do2", "do3"):
                articles = baixar_dia(client, dt, secao)
                logger.info(f"  {dt} {secao}: {len(articles)} artigos")
                for a in articles:
                    kws = matches_keywords(a["texto"] + " " + a["titulo"])
                    mun = municipio_match(a["texto"] + " " + a["titulo"])
                    if not kws and not mun: continue  # so guardar relevantes
                    try:
                        conn.execute(text("""
                          INSERT INTO dou_publicacoes
                            (id_oficio, secao, dt_publicacao, orgao, titulo, texto,
                             edicao, pagina, url_pdf, raw_xml, keywords_match, municipio_match)
                          VALUES (:i, :s, :d, :o, :t, :tx, :e, :p, :u, :raw, CAST(:kw AS jsonb), :m)
                          ON CONFLICT (id_oficio) DO NOTHING
                        """), {
                            "i": a["id_oficio"], "s": a["secao"], "d": a["dt"],
                            "o": a["orgao"], "t": a["titulo"], "tx": a["texto"],
                            "e": a["edicao"], "p": a["pagina"], "u": a["url_pdf"],
                            "raw": a["xml"], "kw": json.dumps(kws), "m": mun,
                        })
                        total += 1
                    except Exception:
                        continue
                time.sleep(1)
        conn.execute(text("""INSERT INTO ingestion_log (source, status, records_inserted, finished_at)
                              VALUES ('dou_inlabs', 'success', :n, NOW())"""), {"n": total})
    logger.info(f"=== DOU concluido: {total} relevantes ===")


if __name__ == "__main__":
    try: main()
    except Exception as e:
        import traceback; traceback.print_exc()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO ingestion_log (source, status, error_message, finished_at)
                                 VALUES ('dou_inlabs', 'failed', :e, NOW())"""),
                          {"e": str(e)[:500]})
