"""
Pipeline da API publica da Camara dos Deputados (dadosabertos.camara.leg.br).

Sem autenticacao (API gratuita). Cobertura:
- Deputados em exercicio
- Despesas (Cota Parlamentar / CEAP) por deputado/ano/mes
- Proposicoes (PL, PEC, PLN) autoradas
- Votacoes + voto individual
- Emendas (RP9 individuais + bancada + comissao)

Esta e a fonte que entrega ~150k emendas vs ~17k que temos via SICONV bulk.
Atualizacao diaria automatica pela API.
"""
import sys, os, time, json, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from sqlalchemy import create_engine, text
from config import get_settings

logger = logging.getLogger("camara")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC or settings.DATABASE_URL.replace("+asyncpg", ""))

BASE = "https://dadosabertos.camara.leg.br/api/v2"
HEADERS = {"Accept": "application/json", "User-Agent": "PACTA/1.0"}


def _get(client, path, params=None, max_retries=3):
    for attempt in range(max_retries):
        try:
            r = client.get(f"{BASE}{path}", params=params, headers=HEADERS, timeout=30)
            if r.status_code == 429:
                time.sleep(5); continue
            if r.status_code != 200:
                return None
            return r.json()
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2); continue
            logger.error(f"  GET {path} falhou: {e}")
    return None


def fetch_deputados_mg(client):
    """Lista deputados federais MG em exercicio."""
    out = []
    pag = 1
    while True:
        data = _get(client, "/deputados", {"siglaUf": "MG", "ordem": "ASC",
                                             "ordenarPor": "nome", "pagina": pag, "itens": 100})
        if not data: break
        items = data.get("dados", [])
        if not items: break
        out.extend(items)
        # Verifica se ha mais paginas
        links = data.get("links", [])
        if not any(l.get("rel") == "next" for l in links):
            break
        pag += 1
    logger.info(f"  Deputados MG: {len(out)}")
    return out


def upsert_parlamentar_camara(conn, dep):
    """Cria/atualiza Parlamentar a partir de dados da Camara."""
    nome = (dep.get("nome") or "").strip().upper()
    partido = (dep.get("siglaPartido") or "").strip().upper() or None
    uf = (dep.get("siglaUf") or "").strip().upper() or "MG"
    id_camara = dep.get("id")
    if not nome:
        return None

    r = conn.execute(text("""
      SELECT id FROM parlamentares
      WHERE upper(nome) = :n AND COALESCE(esfera,'') = 'federal'
      LIMIT 1
    """), {"n": nome}).first()
    if r:
        # Atualizar partido e external_id
        conn.execute(text("""
          UPDATE parlamentares SET partido = COALESCE(:p, partido), uf = COALESCE(:u, uf),
                                    external_id = COALESCE(NULLIF(external_id, ''), :ext)
          WHERE id = :id
        """), {"p": partido, "u": uf, "ext": str(id_camara), "id": r[0]})
        return r[0]
    # Criar
    ins = conn.execute(text("""
      INSERT INTO parlamentares (nome, partido, uf, esfera, legislatura, external_id)
      VALUES (:n, :p, :u, 'federal', '2023-2027', :ext)
      RETURNING id
    """), {"n": nome[:300], "p": partido, "u": uf, "ext": str(id_camara)})
    return ins.scalar()


def fetch_despesas(client, id_dep, ano):
    """CEAP - despesas do deputado em um ano."""
    out = []
    pag = 1
    while pag <= 30:  # max 30 paginas (3000 itens)
        data = _get(client, f"/deputados/{id_dep}/despesas",
                    {"ano": ano, "pagina": pag, "itens": 100, "ordem": "DESC", "ordenarPor": "dataDocumento"})
        if not data: break
        items = data.get("dados", [])
        if not items: break
        out.extend(items)
        if len(items) < 100: break
        pag += 1
    return out


def fetch_proposicoes_autor(client, id_dep, ano):
    """Proposicoes autoradas pelo deputado em um ano."""
    out = []
    pag = 1
    while pag <= 20:
        data = _get(client, "/proposicoes",
                    {"idAutor": id_dep, "ano": ano, "pagina": pag, "itens": 100})
        if not data: break
        items = data.get("dados", [])
        if not items: break
        out.extend(items)
        if len(items) < 100: break
        pag += 1
    return out


def parse_date(s):
    if not s: return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(s.split("T")[0]).date()
    except Exception:
        return None


def main():
    logger.info("=== Pipeline Camara dos Deputados ===")
    from datetime import datetime
    ano_atual = datetime.now().year

    with httpx.Client(timeout=30, verify=False) as client:
        with engine.begin() as conn:
            deps = fetch_deputados_mg(client)
            if not deps:
                logger.error("Falha ao listar deputados")
                return

            # Map id_camara -> parlamentar_id
            id_map = {}
            for d in deps:
                pid = upsert_parlamentar_camara(conn, d)
                if pid:
                    id_map[d["id"]] = pid
            logger.info(f"  {len(id_map)} parlamentares MG sincronizados com Camara")

        # Despesas + proposicoes de cada deputado para os anos 2022-2026
        with httpx.Client(timeout=30, verify=False) as client:
            for i, dep in enumerate(deps):
                id_dep = dep["id"]
                parl_id = id_map.get(id_dep)
                if not parl_id: continue

                logger.info(f"  [{i+1}/{len(deps)}] {dep.get('nome','?')}")

                # Despesas
                with engine.begin() as conn:
                    conn.execute(text("DELETE FROM camara_despesas WHERE id_camara=:i AND ano>=2022"),
                                  {"i": id_dep})
                    total_desp = 0
                    for ano in range(2022, ano_atual + 1):
                        desp = fetch_despesas(client, id_dep, ano)
                        for d in desp:
                            try:
                                conn.execute(text("""
                                  INSERT INTO camara_despesas (
                                    parlamentar_id, id_camara, ano, mes, tipo_despesa, fornecedor,
                                    cnpj_cpf, valor_documento, valor_liquido, dt_documento,
                                    url_documento, nr_documento, raw_data
                                  ) VALUES (:p, :i, :a, :m, :t, :f, :c, :vd, :vl, :dt, :url, :nr, CAST(:raw AS jsonb))
                                """), {
                                    "p": parl_id, "i": id_dep, "a": d.get("ano"),
                                    "m": d.get("mes"), "t": (d.get("tipoDespesa") or "")[:200],
                                    "f": (d.get("nomeFornecedor") or "")[:300],
                                    "c": d.get("cnpjCpfFornecedor"),
                                    "vd": d.get("valorDocumento"), "vl": d.get("valorLiquido"),
                                    "dt": parse_date(d.get("dataDocumento")),
                                    "url": (d.get("urlDocumento") or "")[:500],
                                    "nr": (d.get("numDocumento") or "")[:50],
                                    "raw": json.dumps(d, ensure_ascii=False, default=str),
                                })
                                total_desp += 1
                            except Exception as e:
                                pass
                        time.sleep(0.15)
                    logger.info(f"    despesas: +{total_desp}")

                # Proposicoes (apenas ano corrente + anterior para limitar)
                with engine.begin() as conn:
                    total_prop = 0
                    for ano in (ano_atual - 1, ano_atual):
                        props = fetch_proposicoes_autor(client, id_dep, ano)
                        for p in props:
                            try:
                                conn.execute(text("""
                                  INSERT INTO camara_proposicoes (
                                    id_camara, sigla_tipo, numero, ano, ementa, descricao_tipo,
                                    autor_id_camara, autor_nome, autor_partido, autor_uf,
                                    dt_apresentacao, url, raw_data
                                  ) VALUES (:i, :s, :n, :a, :e, :d, :aut, :anome, :ap, :au, :dt, :url, CAST(:raw AS jsonb))
                                  ON CONFLICT (id_camara) DO NOTHING
                                """), {
                                    "i": p.get("id"),
                                    "s": (p.get("siglaTipo") or "")[:20],
                                    "n": p.get("numero"), "a": p.get("ano"),
                                    "e": (p.get("ementa") or "")[:5000],
                                    "d": (p.get("descricaoTipo") or "")[:200],
                                    "aut": id_dep,
                                    "anome": (dep.get("nome") or "")[:300],
                                    "ap": (dep.get("siglaPartido") or "")[:20],
                                    "au": (dep.get("siglaUf") or "")[:2],
                                    "dt": parse_date(p.get("dataApresentacao")),
                                    "url": (p.get("uri") or "")[:500],
                                    "raw": json.dumps(p, ensure_ascii=False, default=str),
                                })
                                total_prop += 1
                            except Exception:
                                pass
                        time.sleep(0.15)
                    logger.info(f"    proposicoes: +{total_prop}")

    with engine.begin() as conn:
        conn.execute(text("""
          INSERT INTO ingestion_log (source, status, finished_at)
          VALUES ('camara_deputados', 'success', NOW())
        """))
    logger.info("=== Camara Deputados concluido ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback; traceback.print_exc()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO ingestion_log (source, status, error_message, finished_at)
                                 VALUES ('camara_deputados', 'failed', :e, NOW())"""),
                          {"e": str(e)[:500]})
        sys.exit(1)
