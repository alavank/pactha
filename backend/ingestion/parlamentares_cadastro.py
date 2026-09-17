"""CADASTRO DE PARLAMENTARES: partido, UF, cargo e foto de quem assina emenda.

Nenhuma fonte de emenda traz isso. O `siconv_emenda.zip`, a CGU, o TransfereGov e o
SIGCON trazem so o NOME do autor (a excecao e o FNS, com `sgPartido` no raw). Este
coletor le o cadastro das casas legislativas, todas abertas e sem login:

    Camara   dadosabertos.camara.leg.br/api/v2/deputados?idLegislatura=N
             -> id, nome, siglaPartido, siglaUf, urlFoto (por legislatura)
    Senado   legis.senado.leg.br/dadosabertos/senador/lista/legislatura/N.json
             -> codigo, nome, UF do mandato. SEM partido e SEM foto na lista;
             o partido sai de /senador/lista/atual.json (so de quem esta em
             exercicio) e a foto tem URL fixa pelo codigo.
    ALMG     dadosabertos.almg.gov.br/api/v2/deputados/situacao/{1,2,3}
             -> id, nome, partido. SO a legislatura atual (em exercicio,
             afastados e licenciados): a API nao lista legislaturas passadas, e
             nao publica foto.

MEDIDO EM 17/09/2026: o autor das emendas federais INDIVIDUAIS do
`siconv_emenda.zip`, casado pelo nome contra Camara + Senado das legislaturas
52 a 57, cobre 98,5% das emendas (235.604 de 239.114; 1.518 de 1.585 autores). O
resto e grafia errada na fonte ("EDUARDO BRNADAO DE AZEREDO") ou nome civil longo
("MICHEL MIGUEL ELIAS TEMER LULIA"), resolvidos em `parlamentares_apelidos`.

⚠️ O PARTIDO E O DA ULTIMA LEGISLATURA LIDA, e nao o do dia da emenda. A Camara
publica o partido por legislatura; troca de partido no meio do mandato nao aparece.

⚠️ CASA QUE FALHA NAO APAGA NADA. O cadastro e historico (quem foi deputado em
2011 continua sendo o autor da emenda de 2011), entao este coletor nunca remove
linha: so insere e atualiza. Uma casa fora do ar deixa a rodada `partial`.

Rodar:  DATABASE_URL_SYNC=... python -u ingestion/parlamentares_cadastro.py
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.nome_parlamentar import chave_nome  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("parlamentares_cadastro")

FONTE = "parlamentares_cadastro"
MIN_INTERVAL_H = int(os.getenv("PARLAMENTARES_MIN_INTERVAL_H", "20") or "20")
# 52 = 2003-2007. Emenda no `siconv_emenda.zip` comeca em 2008.
LEGISLATURAS = range(int(os.getenv("PARLAMENTARES_LEG_INI", "52")), 58)
TIMEOUT = 60
UA = {"User-Agent": "PACTHA/1.0 (monitoramento de convenios)", "Accept": "application/json"}

CAMARA = "https://dadosabertos.camara.leg.br/api/v2/deputados"
SENADO = "https://legis.senado.leg.br/dadosabertos/senador"
ALMG = "https://dadosabertos.almg.gov.br/api/v2/deputados/situacao/{}"
FOTO_SENADO = "https://www.senado.leg.br/senadores/img/fotos-oficiais/senador{}.jpg"


# --------------------------------------------------------------------- puras ---

def de_camara(item: dict, legislatura: int) -> dict | None:
    """Um item de /deputados?idLegislatura=N -> registro. PURA."""
    ide, nome = item.get("id"), (item.get("nome") or "").strip()
    if not ide or not nome:
        return None
    return {"casa": "camara", "id_externo": str(ide), "nome": nome,
            "nomes_norm": {chave_nome(nome)}, "nome_civil": None,
            # A Camara marca partido extinto/fundido com asterisco ("PP**").
            "partido": (item.get("siglaPartido") or "").strip().rstrip("*") or None,
            "uf": (item.get("siglaUf") or "").strip().upper() or None,
            "cargo": "Deputado(a) Federal",
            "foto_url": (item.get("urlFoto") or "").strip() or None,
            "legislaturas": {legislatura}}


def de_senado(item: dict, legislatura: int) -> dict | None:
    """Um item de /senador/lista/legislatura/N.json -> registro. PURA.

    ⚠️ A UF MORA NO MANDATO, e nao na identificacao. O suplente que assumiu traz o
    mesmo formato; o nome e o dele.
    """
    ident = item.get("IdentificacaoParlamentar") or {}
    cod, nome = ident.get("CodigoParlamentar"), (ident.get("NomeParlamentar") or "").strip()
    if not cod or not nome:
        return None
    mandatos = (item.get("Mandatos") or {}).get("Mandato") or []
    if isinstance(mandatos, dict):
        mandatos = [mandatos]
    uf = next((m.get("UfParlamentar") for m in mandatos if m.get("UfParlamentar")), None)
    civil = (ident.get("NomeCompletoParlamentar") or "").strip() or None
    return {"casa": "senado", "id_externo": str(cod), "nome": nome,
            # O nome civil tambem vale como grafia: a fonte da emenda as vezes o usa.
            "nomes_norm": {chave_nome(nome)} | ({chave_nome(civil)} if civil else set()),
            "nome_civil": civil,
            "partido": (ident.get("SiglaPartidoParlamentar") or "").strip() or None,
            "uf": (uf or "").strip().upper() or None,
            "cargo": "Senador(a)",
            "foto_url": FOTO_SENADO.format(cod),
            "legislaturas": {legislatura}}


def de_almg(item: dict, legislatura_atual: int) -> dict | None:
    """Um item de /deputados/situacao/N (ALMG) -> registro. PURA."""
    ide, nome = item.get("id"), (item.get("nome") or "").strip()
    if not ide or not nome:
        return None
    return {"casa": "almg", "id_externo": str(ide), "nome": nome,
            "nomes_norm": {chave_nome(nome)}, "nome_civil": None,
            "partido": (item.get("partido") or "").strip() or None,
            "uf": "MG", "cargo": "Deputado(a) Estadual",
            "foto_url": None, "legislaturas": {legislatura_atual}}


def mescla(registros) -> dict[tuple[str, str], dict]:
    """Junta as legislaturas de um mesmo parlamentar (casa, id). PURA.

    O partido, a UF e a foto que valem sao os da legislatura MAIS RECENTE, e nao
    os da ultima linha lida: a ordem de chegada das paginas nao pode decidir o
    partido de ninguem.

    ⚠️ AS GRAFIAS DO NOME SE SOMAM, nunca se trocam. A Camara renomeia o mesmo
    deputado entre legislaturas ("Reinhold Stephanes Junior" -> "Stephanes
    Junior"), e a emenda antiga usa o nome antigo. Guardar so o mais recente
    deixava 1.400 emendas sem partido (medido em 17/09/2026).
    """
    out: dict[tuple[str, str], dict] = {}
    for r in registros:
        if not r:
            continue
        k = (r["casa"], r["id_externo"])
        atual = out.get(k)
        if atual is None:
            out[k] = {**r, "legislaturas": set(r["legislaturas"]),
                      "nomes_norm": set(r["nomes_norm"])}
            continue
        mais_nova = max(r["legislaturas"]) >= max(atual["legislaturas"])
        atual["legislaturas"] |= set(r["legislaturas"])
        atual["nomes_norm"] |= set(r["nomes_norm"])
        for campo in ("partido", "uf", "foto_url", "nome", "nome_civil"):
            if r.get(campo) and (mais_nova or not atual.get(campo)):
                atual[campo] = r[campo]
    return out


# ---------------------------------------------------------------------- rede ---

def _get_json(client: httpx.Client, url: str, params: dict | None = None):
    """GET com 3 tentativas. ⚠️ O Senado corta resposta grande no meio
    (`IncompleteRead` na legislatura 56, medido em 17/09/2026) e responde certo na
    segunda vez."""
    ultimo = None
    for tentativa in range(3):
        try:
            r = client.get(url, params=params, headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            ultimo = e
            time.sleep(2 * (tentativa + 1))
    raise RuntimeError(f"{url}: {ultimo}")


def ler_camara(client) -> list[dict]:
    regs = []
    for leg in LEGISLATURAS:
        pagina = 1
        while True:
            dados = _get_json(client, CAMARA, {"idLegislatura": leg, "itens": 100,
                                               "pagina": pagina})["dados"]
            if not dados:
                break
            regs += [de_camara(d, leg) for d in dados]
            pagina += 1
            if pagina > 50:  # 513 cadeiras + suplentes cabem em ~10 paginas
                raise RuntimeError(f"Camara leg {leg}: paginacao nao terminou")
    return [r for r in regs if r]


def ler_senado(client) -> list[dict]:
    regs = []
    for leg in LEGISLATURAS:
        d = _get_json(client, f"{SENADO}/lista/legislatura/{leg}.json")
        itens = d["ListaParlamentarLegislatura"]["Parlamentares"]["Parlamentar"]
        regs += [de_senado(i, leg) for i in itens]
    # O partido so existe na lista de quem esta em exercicio.
    atual = _get_json(client, f"{SENADO}/lista/atual.json")
    partidos = {}
    for i in atual["ListaParlamentarEmExercicio"]["Parlamentares"]["Parlamentar"]:
        ident = i.get("IdentificacaoParlamentar") or {}
        if ident.get("CodigoParlamentar") and ident.get("SiglaPartidoParlamentar"):
            partidos[str(ident["CodigoParlamentar"])] = ident["SiglaPartidoParlamentar"]
    regs = [r for r in regs if r]
    for r in regs:
        r["partido"] = r["partido"] or partidos.get(r["id_externo"])
    return regs


def ler_almg(client) -> list[dict]:
    regs = []
    for situacao in (1, 2, 3):  # em exercicio, afastado, licenciado
        d = _get_json(client, ALMG.format(situacao), {"formato": "json"})
        regs += [de_almg(i, max(LEGISLATURAS)) for i in d.get("list") or []]
    return [r for r in regs if r]


# ------------------------------------------------------------------- gravacao ---

_SQL = """
    INSERT INTO parlamentares_cadastro
        (casa, id_externo, nome, nomes_norm, nome_civil, partido, uf, cargo,
         foto_url, legislaturas, visto_em, updated_at)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())
    ON CONFLICT (casa, id_externo) DO UPDATE SET
        nome=EXCLUDED.nome,
        nomes_norm=(SELECT array_agg(DISTINCT x ORDER BY x) FROM unnest(
            parlamentares_cadastro.nomes_norm || EXCLUDED.nomes_norm) x),
        nome_civil=COALESCE(EXCLUDED.nome_civil, parlamentares_cadastro.nome_civil),
        -- ⚠️ PARTIDO NULO NAO APAGA O CONHECIDO: o Senado so publica partido de
        -- quem esta em exercicio, e o senador que saiu nao pode perder o dele.
        partido=COALESCE(EXCLUDED.partido, parlamentares_cadastro.partido),
        uf=COALESCE(EXCLUDED.uf, parlamentares_cadastro.uf),
        cargo=EXCLUDED.cargo,
        foto_url=COALESCE(EXCLUDED.foto_url, parlamentares_cadastro.foto_url),
        legislaturas=(SELECT array_agg(DISTINCT x ORDER BY x) FROM unnest(
            parlamentares_cadastro.legislaturas || EXCLUDED.legislaturas) x),
        visto_em=NOW(), updated_at=NOW()
"""


def _recente_demais(cur) -> bool:
    if os.getenv("PARLAMENTARES_FORCE") == "1":
        return False
    cur.execute("SELECT max(finished_at) FROM ingestion_log "
                "WHERE source = %s AND status = 'success'", (FONTE,))
    ultimo = (cur.fetchone() or [None])[0]
    if not ultimo:
        return False
    horas = (datetime.now(ultimo.tzinfo) - ultimo).total_seconds() / 3600
    if horas < MIN_INTERVAL_H:
        log.info("ultima coleta ha %.1fh (< %dh) — pulando. PARLAMENTARES_FORCE=1 forca.",
                 horas, MIN_INTERVAL_H)
        return True
    return False


def ingest() -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        if _recente_demais(cur):
            return 0

        falhas, regs = [], []
        with httpx.Client(follow_redirects=True) as client:
            for nome, ler in (("Camara", ler_camara), ("Senado", ler_senado), ("ALMG", ler_almg)):
                try:
                    lidos = ler(client)
                    if not lidos:
                        raise RuntimeError("zero parlamentares")
                    log.info("%s: %d registros", nome, len(lidos))
                    regs += lidos
                except Exception as e:  # uma casa fora do ar nao derruba as outras
                    log.error("%s falhou: %s", nome, str(e)[:200])
                    falhas.append(f"{nome}: {str(e)[:120]}")

        porpessoa = mescla(regs)
        for r in porpessoa.values():
            cur.execute(_SQL, (r["casa"], r["id_externo"], r["nome"], sorted(r["nomes_norm"]),
                               r["nome_civil"], r["partido"], r["uf"], r["cargo"],
                               r["foto_url"], sorted(r["legislaturas"])))
        conn.commit()

        status = "error" if len(falhas) == 3 else "partial" if falhas else "success"
        try:
            cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, "
                        "error_message, finished_at) VALUES (%s,%s,%s,%s,NOW())",
                        (FONTE, status, len(porpessoa), "; ".join(falhas) or None))
            conn.commit()
        except Exception as e:
            log.warning("ingestion_log falhou: %s", str(e)[:120])
        log.info("cadastro: %d parlamentares gravados (%s)", len(porpessoa), status)
        return len(porpessoa)


if __name__ == "__main__":
    ingest()
