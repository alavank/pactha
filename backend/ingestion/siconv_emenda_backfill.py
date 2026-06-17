"""Backfill do PARLAMENTAR (autor da emenda) dos instrumentos FEDERAIS.

Fonte: open data SICONV/TransfereGov (repositorio.dados.gov.br/seges/detru):
  - siconv_emenda.csv.zip   (~7.6 MB)  ID_PROPOSTA -> NOME_PARLAMENTAR
  - siconv_proposta.csv.zip (~199 MB)  NR_PROPOSTA  -> ID_PROPOSTA

A tela de detalhe (guest) do SICONV NAO expõe o autor da emenda, então o
scraper nunca conseguia preencher transferegov_propostas.parlamentar. Este
backfill resolve casando nossas propostas com o open data nacional.

Estratégia em 2 passos (o pesado se auto-desliga):
  1) backfill_ids():       só baixa o arquivo de 199 MB se houver propostas SEM
                           id_proposta_siconv. Depois que o scraper passa a
                           guardar o idProposta (vem da URL ?idProposta=NNN),
                           não há mais pendentes e este passo é pulado.
  2) backfill_parlamentar(): baixa só o arquivo de 7.6 MB (barato, roda sempre)
                           e atualiza parlamentar a partir do id_proposta_siconv.

Entry points: main() / backfill_ids() / backfill_parlamentar().
Wired no run do cron transferegov (transferegov_voluntarias) após a listagem.
"""
from __future__ import annotations
import csv
import io
import logging
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("siconv_emenda_backfill")

URL_EMENDA = "https://repositorio.dados.gov.br/seges/detru/siconv_emenda.csv.zip"
URL_PROPOSTA = "https://repositorio.dados.gov.br/seges/detru/siconv_proposta.csv.zip"

# Cache local (evita rebaixar em execuções repetidas no mesmo host/dia).
_CACHE_DIR = os.getenv("SICONV_CACHE_DIR") or os.path.join(
    os.getenv("TEMP") or os.getenv("TMPDIR") or "/tmp", "siconv_opendata"
)


def _db():
    import psycopg2
    url = os.getenv("DATABASE_URL_SYNC", "")
    url = url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    return psycopg2.connect(url)


def _norm_nr(s: str) -> str:
    """Normaliza NR_PROPOSTA p/ casamento tolerante (remove espaços e zeros à esq.)."""
    return (s or "").replace(" ", "").lstrip("0")


def _download(url: str, use_cache: bool = True) -> bytes:
    """Baixa (com cache local opcional)."""
    import httpx
    fname = url.rsplit("/", 1)[-1]
    path = os.path.join(_CACHE_DIR, fname)
    if use_cache and os.path.exists(path) and os.path.getsize(path) > 1000:
        logger.info(f"  cache: {path} ({os.path.getsize(path)} bytes)")
        return open(path, "rb").read()
    logger.info(f"  baixando {url} ...")
    r = httpx.get(url, timeout=900, verify=False, follow_redirects=True)
    r.raise_for_status()
    if use_cache:
        try:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            open(path, "wb").write(r.content)
        except OSError:
            pass
    logger.info(f"  baixado {len(r.content)} bytes")
    return r.content


def _open_csv(content: bytes):
    """Abre o único CSV de dentro do zip. Decodifica utf-8 (a base é utf-8;
    fallback latin-1 se algum byte escapar). Retorna (reader, header_list)."""
    z = zipfile.ZipFile(io.BytesIO(content))
    name = z.namelist()[0]
    f = z.open(name)
    # utf-8-sig remove o BOM (﻿) que prefixa a 1ª coluna do header.
    txt = io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace", newline="")
    rd = csv.reader(txt, delimiter=";")
    hdr = [h.strip().lstrip("﻿") for h in next(rd)]
    return rd, hdr


def _nossas_propostas(only_sem_id: bool = False) -> dict:
    """Retorna {numero_proposta: (municipio_id, id_proposta_siconv|None)}."""
    conn = _db(); cur = conn.cursor()
    sql = "SELECT numero_proposta, municipio_id, id_proposta_siconv FROM transferegov_propostas"
    if only_sem_id:
        sql += " WHERE id_proposta_siconv IS NULL"
    cur.execute(sql)
    out = {r[0].strip(): (r[1], r[2]) for r in cur.fetchall() if r[0]}
    cur.close(); conn.close()
    return out


def backfill_ids(use_cache: bool = True) -> int:
    """Preenche id_proposta_siconv casando NR_PROPOSTA no siconv_proposta (199 MB).
    Só baixa o arquivo se houver propostas SEM id (auto-desliga depois)."""
    pendentes = _nossas_propostas(only_sem_id=True)
    if not pendentes:
        logger.info("backfill_ids: nenhuma proposta sem id_proposta_siconv — pulando download de 199 MB")
        return 0
    logger.info(f"backfill_ids: {len(pendentes)} proposta(s) sem id — baixando siconv_proposta")
    nr_exato = {nr: nr for nr in pendentes}
    nr_norm = {_norm_nr(nr): nr for nr in pendentes}

    content = _download(URL_PROPOSTA, use_cache=use_cache)
    rd, hdr = _open_csv(content)
    iid, inr = hdr.index("ID_PROPOSTA"), hdr.index("NR_PROPOSTA")
    achados: dict[str, str] = {}  # numero_proposta -> id_proposta
    for row in rd:
        if len(row) <= max(iid, inr):
            continue
        nr = row[inr].strip()
        key = nr_exato.get(nr) or nr_norm.get(_norm_nr(nr))
        if key and key not in achados:
            achados[key] = row[iid].strip()
    logger.info(f"backfill_ids: casados {len(achados)}/{len(pendentes)}")

    if not achados:
        return 0
    conn = _db(); cur = conn.cursor()
    n = 0
    for nr, idp in achados.items():
        cur.execute(
            "UPDATE transferegov_propostas SET id_proposta_siconv=%s "
            "WHERE numero_proposta=%s AND id_proposta_siconv IS NULL",
            (idp, nr),
        )
        n += cur.rowcount
    conn.commit(); cur.close(); conn.close()
    logger.info(f"backfill_ids: {n} linha(s) atualizadas com id_proposta_siconv")
    return n


def backfill_parlamentar(use_cache: bool = True) -> int:
    """Atualiza parlamentar a partir de siconv_emenda (7.6 MB) via id_proposta_siconv."""
    nossas = _nossas_propostas()
    ids_nossos = {v[1] for v in nossas.values() if v[1]}
    if not ids_nossos:
        logger.info("backfill_parlamentar: nenhuma proposta com id_proposta_siconv ainda")
        return 0
    logger.info(f"backfill_parlamentar: {len(ids_nossos)} proposta(s) com id — baixando siconv_emenda")
    content = _download(URL_EMENDA, use_cache=use_cache)
    rd, hdr = _open_csv(content)
    ip, npn = hdr.index("ID_PROPOSTA"), hdr.index("NOME_PARLAMENTAR")
    id2nomes: dict[str, list] = {}
    for row in rd:
        if len(row) <= max(ip, npn):
            continue
        idp = row[ip].strip()
        if idp not in ids_nossos:
            continue
        nome = " ".join((row[npn] or "").split()).strip().upper()
        if not nome:
            continue
        lst = id2nomes.setdefault(idp, [])
        if nome not in lst:
            lst.append(nome)
    logger.info(f"backfill_parlamentar: {len(id2nomes)} id_proposta com parlamentar no open data")

    if not id2nomes:
        return 0
    # id_proposta -> [numero_proposta...]  (pode haver >1 município com mesmo id? não; id é único)
    id_to_nr = {v[1]: nr for nr, v in nossas.items() if v[1]}
    conn = _db(); cur = conn.cursor()
    n = 0
    for idp, nomes in id2nomes.items():
        nr = id_to_nr.get(idp)
        if not nr:
            continue
        valor = ", ".join(sorted(nomes))[:200]
        cur.execute(
            "UPDATE transferegov_propostas SET parlamentar=%s WHERE numero_proposta=%s",
            (valor, nr),
        )
        n += cur.rowcount
    conn.commit(); cur.close(); conn.close()
    logger.info(f"backfill_parlamentar: {n} linha(s) atualizadas com parlamentar")
    return n


def main(use_cache: bool = True):
    logger.info("=== SICONV emenda backfill (parlamentar federal) ===")
    try:
        backfill_ids(use_cache=use_cache)
    except Exception as e:
        logger.error(f"backfill_ids falhou: {str(e)[:200]}")
    try:
        n = backfill_parlamentar(use_cache=use_cache)
    except Exception as e:
        logger.error(f"backfill_parlamentar falhou: {str(e)[:200]}")
        n = 0
    # log de ingestao
    try:
        conn = _db(); cur = conn.cursor()
        cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, finished_at) "
                    "VALUES ('siconv_emenda_backfill','success',%s,NOW())", (n,))
        conn.commit(); cur.close(); conn.close()
    except Exception:
        pass
    logger.info("=== fim ===")


if __name__ == "__main__":
    # Em produção (Railway) sem cache de disco persistente: --no-cache força download fresco.
    main(use_cache="--no-cache" not in sys.argv)
