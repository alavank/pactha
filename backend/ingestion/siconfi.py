"""
SICONFI / Tesouro Nacional — entregas de contas e CAPAG, para QUALQUER estado.

Fonte NACIONAL, sem login e sem token: a API do datalake do Tesouro
(`apidatalake.tesouro.gov.br/ords/siconfi`) responde JSON puro, e a CAPAG sai do
CKAN do Tesouro Transparente. Duas coisas que o produto nao tinha e que decidem
convenio:

  * **o extrato de entregas** — o que o municipio mandou ao Tesouro, em que
    periodo e em que dia. O CAUC ja diz REGULAR/IRREGULAR nas obrigacoes 3.1.2,
    3.2.2 e 3.3; ele nao diz O QUE faltou. Este coletor diz.
  * **a CAPAG** — a nota de A+ a D que define se o ente pode contrair operacao
    de credito com garantia da Uniao. Nova Palma e **A+** (posicao 06/2026).

Os tres endpoints usados, todos GET e todos publicos:

    /tt/entes
        -> os 5.598 entes numa resposta so (`hasMore: false`), com CNPJ,
           populacao e UF. E de onde sai o CNPJ oficial do municipio.
    /tt/extrato_entregas?an_referencia=<ano>&id_ente=<ibge7>
        -> uma linha por entregavel x periodo, com data_status e forma_envio.
    (CKAN) /ckan/api/3/action/package_show?id=capag-municipios
        -> os XLSX por ano; o mais recente traz a nota e os 3 indicadores.

AS ARMADILHAS, todas medidas contra a fonte em 02/09/2026:

1. ⚠️⚠️ **O PORTE DO MUNICIPIO MUDA O NOME DO DEMONSTRATIVO, E O ERRO E MUDO.**
   Nova Palma (5.676 hab.) publica `RREO Simplificado` e `RGF Simplificado`;
   Santa Maria publica `RREO` e `RGF`. Pedir `co_tipo_demonstrativo=RREO` para
   Nova Palma devolve **HTTP 200 com `count: 0`** — em 2023, 2024, 2025 e 2026,
   todos os periodos. Um coletor que lesse isso como ausencia afirmaria que a
   prefeitura nunca prestou contas ao Tesouro desde 2023, que e justamente um
   item que o CAUC e o CHE cobram: alarme falso de irregularidade grave, sem
   erro nenhum em log. Por isso este coletor NAO consulta `/tt/rreo` para saber
   se houve entrega — quem responde isso e o `extrato_entregas`, que lista o
   entregavel com o nome que aquele ente de fato usa.

2. ⚠️ **A PREFEITURA E A CAMARA VEM MISTURADAS**, com o mesmo `cod_ibge`, e a
   Camara vem PRIMEIRO na resposta (medido: 15 linhas da Camara e 22 da
   Prefeitura em 2025, nessa ordem). O que separa e o texto de `instituicao`.
   Ler a primeira linha, ou nao filtrar, poe a MSC da Camara na conta da
   prefeitura. Mesma armadilha do TCE-RS (PM 53100 x CM 53101) e do CHE.

3. ⚠️ **`status_relatorio` NAO E UNIFORME, e filtrar por ele perde metade.**
   Medido em Nova Palma/2025: RREO, RGF e DCA vem com `status='HO'`
   (homologado), enquanto as MSC — que sao 12 das 22 entregas do ano — vem com
   `status: null` e a data preenchida. Um coletor que exigisse `status == 'HO'`
   descartaria toda a matriz contabil e afirmaria que o municipio nao entregou
   MSC nenhuma no ano. Quem prova a entrega e a DATA; o status entra como
   informacao adicional, nunca como criterio.

4. ⚠️ **A `populacao` do SICONFI muda dentro do mesmo ano** (5.328 no extrato
   de 2025, 5.676 no cadastro de entes de 2026) — sao estimativas do IBGE de
   momentos diferentes. Serve de contexto, nunca de chave nem de conferencia.

5. ⚠️ **O NOME DO RECURSO DA CAPAG NAO E ESTAVEL.** Sao 16 recursos no dataset,
   com varias revisoes do mesmo ano ("CAPAG Municipios 2024 - 14/05/2024",
   "... - 15/10/2024"), grafia oscilando entre "CAPAG" e "Capag" e um deles
   comecando com espaco (" Capag Municipios 2026 - 01/06/2026"). Escolher por
   nome quebra na proxima publicacao: a escolha e por `last_modified`.

6. ⚠️ **O CABECALHO DA PLANILHA NAO ESTA NA PRIMEIRA LINHA** — na aba "Previa da
   CAPAG" ele esta na terceira, depois de duas linhas de sumario, e nas abas de
   ano-base esta na quarta. Este parser PROCURA a linha do cabecalho pelos
   rotulos; assumir indice fixo faz o coletor ler numero de sumario como se
   fosse municipio.

7. ⚠️ **Os numeros da planilha vem como TEXTO** ('0.044333864612702376', com
   ponto decimal), nao como numero — `parse_decimal_br` estragaria o valor ao
   tratar o ponto como separador de milhar.

8. O XLSX nacional tem **24 MB**. Ele so e baixado quando a posicao publicada e
   mais nova que a ja gravada; nas demais rodadas o coletor le so o JSON do
   CKAN (alguns KB). A CAPAG muda 2 a 4 vezes por ano.

Rodavel por Scheduled Task em qualquer worker, ou a mao:
    python -u ingestion/siconfi.py            # coleta de verdade
    python -u ingestion/siconfi.py --dry      # consulta e mostra, sem gravar
"""
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("siconfi")

API = "https://apidatalake.tesouro.gov.br/ords/siconfi"
CKAN = "https://www.tesourotransparente.gov.br/ckan/api/3/action"
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0 dados abertos SICONFI/Tesouro)",
      "Accept": "application/json"}
TIMEOUT = 60

# Pausa entre chamadas ao datalake. O ORDS nao devolveu 429 em nenhuma das
# medicoes, mas uma carteira de 44 municipios sao 44 requisicoes seguidas contra
# um orgao publico — o custo de ser educado aqui e de segundos.
PAUSA_S = float(os.getenv("SICONFI_PAUSA_S", "0.6") or "0.6")

# Auto-limite, no mesmo desenho do SISMOB e do SIMEC-Termos: as entregas mudam
# no maximo uma vez por mes (a MSC e mensal), entao rodar 4x/dia so gasta CPU.
MIN_INTERVAL_H = int(os.getenv("SICONFI_MIN_INTERVAL_H", "20") or "20")

# Só a Prefeitura. A Câmara compartilha o `cod_ibge` e não é o cliente.
_RE_PREFEITURA = re.compile(r"prefeitura|munic[ií]pio\s+de", re.IGNORECASE)
_RE_CAMARA = re.compile(r"c[âa]mara", re.IGNORECASE)

# "Capag Municípios 2026 - 01/06/2026" -> (2026, date(2026, 6, 1))
_RE_POSICAO = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s*$")
_RE_ANO = re.compile(r"\b(20\d{2})\b")


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _get_json(client: httpx.Client, url: str, params: dict | None = None) -> dict:
    r = client.get(url, params=params, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def entes(client: httpx.Client) -> dict[str, dict]:
    """{ibge7: {cnpj, populacao, ente, uf}} para os 5.598 entes.

    Uma requisicao so: `hasMore` volta false e `count` = 5598. Nao paginar aqui
    e deliberado — se um dia a resposta passar a paginar, o `hasMore` abaixo
    avisa em log em vez de truncar em silencio."""
    d = _get_json(client, f"{API}/tt/entes")
    if d.get("hasMore"):
        log.warning("tt/entes voltou paginado (count=%s) — o cadastro cresceu e "
                    "este coletor esta lendo so a primeira pagina", d.get("count"))
    out: dict[str, dict] = {}
    for x in d.get("items") or []:
        ibge = str(x.get("cod_ibge") or "").strip()
        if len(ibge) != 7:
            continue
        out[ibge] = {
            "cnpj": re.sub(r"\D", "", str(x.get("cnpj") or "")),
            "populacao": x.get("populacao"),
            "ente": (x.get("ente") or "").strip(),
            "uf": (x.get("uf") or "").strip().upper(),
        }
    return out


def extrato_entregas(client: httpx.Client, ibge: str, ano: int) -> list[dict]:
    """As entregas DA PREFEITURA naquele exercicio (armadilha 2)."""
    d = _get_json(client, f"{API}/tt/extrato_entregas",
                  {"an_referencia": ano, "id_ente": ibge})
    linhas = []
    for x in d.get("items") or []:
        inst = (x.get("instituicao") or "").strip()
        if _RE_CAMARA.search(inst) or not _RE_PREFEITURA.search(inst):
            continue
        linhas.append(x)
    return linhas


# ---------------------------------------------------------------------------
# CAPAG
# ---------------------------------------------------------------------------
def capag_recurso(client: httpx.Client) -> dict | None:
    """O XLSX mais recente do dataset `capag-municipios` (armadilha 5).

    Devolve {url, nome, exercicio, posicao, last_modified} ou None."""
    d = _get_json(client, f"{CKAN}/package_show", {"id": "capag-municipios"})
    if not d.get("success"):
        return None
    xlsx = [r for r in (d.get("result") or {}).get("resources", [])
            if (r.get("format") or "").upper() == "XLSX"]
    if not xlsx:
        return None
    xlsx.sort(key=lambda r: r.get("last_modified") or r.get("created") or "")
    r = xlsx[-1]
    nome = (r.get("name") or "").strip()
    posicao = None
    m = _RE_POSICAO.search(nome)
    if m:
        try:
            posicao = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            posicao = None
    anos = _RE_ANO.findall(nome)
    return {
        "url": r.get("url"),
        "nome": nome,
        # O ano do TITULO, nao o da data de posicao: a revisao de 15/10/2024 e
        # do ano-base 2024, e as duas coisas coincidirem e coincidencia.
        "exercicio": int(anos[0]) if anos else (posicao.year if posicao else None),
        "posicao": posicao,
        "last_modified": r.get("last_modified") or r.get("created"),
    }


def capag_por_ibge(caminho: str, ibges: set[str]) -> dict[str, dict]:
    """Le a aba de nota consolidada e devolve {ibge: linha} para os que importam.

    A aba certa e a que tem a coluna `CAPAG` (a nota final, 'A+'/'B'/'C'/'D')
    ao lado dos tres indicadores — nas abas de ano-base ha o memorial de
    calculo, com dezenas de colunas e sem a nota consolidada."""
    import openpyxl

    wb = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    try:
        for aba in wb.sheetnames:
            ws = wb[aba]
            cab: list[str] | None = None
            idx: dict[str, int] = {}
            achados: dict[str, dict] = {}
            for row in ws.iter_rows(values_only=True):
                vals = ["" if c is None else str(c).strip() for c in row]
                if cab is None:
                    # Armadilha 6: procurar o cabecalho, nunca assumir a linha.
                    norm = [_sem_acento(v).lower() for v in vals]
                    if any("codigo municipio" in v for v in norm) and "capag" in norm:
                        cab = vals
                        idx = {_sem_acento(v).lower(): i for i, v in enumerate(vals) if v}
                    continue
                if not vals or not vals[0]:
                    continue
                ibge = re.sub(r"\D", "", vals[0])
                if ibge in ibges:
                    achados[ibge] = {k: (vals[i] if i < len(vals) else None)
                                     for k, i in idx.items()}
                    if len(achados) == len(ibges):
                        return achados
            if achados:
                return achados
        return {}
    finally:
        wb.close()


def _sem_acento(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def _num(v) -> float | None:
    """Armadilha 7: os numeros vem como texto com PONTO decimal."""
    if v is None or str(v).strip() in ("", "-", "nan", "None"):
        return None
    try:
        return float(str(v).strip().replace(",", "."))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
def _alvos(cur) -> list[dict]:
    """Todo municipio ATIVO com IBGE de 7 digitos — a fonte e nacional."""
    cur.execute("""
        SELECT id, nome, uf, ibge_code,
               regexp_replace(coalesce(cnpj,''), '\\D', '', 'g')
          FROM municipios
         WHERE active AND length(coalesce(ibge_code,'')) = 7
         ORDER BY nome
    """)
    return [{"id": r[0], "nome": r[1], "uf": r[2], "ibge": r[3], "cnpj": r[4]}
            for r in cur.fetchall()]


def _preencher_cnpj(cur, alvos: list[dict], cadastro: dict[str, dict]) -> int:
    """Preenche `municipios.cnpj` onde ele esta vazio, com o CNPJ do Tesouro.

    ⭐ E O GANHO TRANSVERSAL DESTE COLETOR. O CHE so consulta municipio que tem
    CNPJ em `municipios`; a Transferencia Especial casa por CNPJ; o CAGEC infere
    o dele de dado ja coletado. Ate hoje esse campo dependia de alguem digitar
    pelo control-plane, e onde ninguem digitou a fonte simplesmente nao rodava —
    em silencio, porque "sem CNPJ" nao e erro.

    ⚠️ SO PREENCHE O QUE ESTA VAZIO. Um CNPJ ja cadastrado foi posto por gente e
    pode ser o de um fundo especifico; sobrescrever seria trocar uma decisao
    humana por um palpite nosso."""
    n = 0
    for a in alvos:
        if len(a["cnpj"] or "") == 14:
            continue
        cnpj = (cadastro.get(a["ibge"]) or {}).get("cnpj") or ""
        if len(cnpj) != 14:
            continue
        cur.execute("UPDATE municipios SET cnpj = %s WHERE id = %s AND "
                    "coalesce(regexp_replace(cnpj, '\\D', '', 'g'), '') <> %s",
                    (cnpj, a["id"], cnpj))
        if cur.rowcount:
            log.info("  %s/%s: CNPJ preenchido do Tesouro -> %s",
                     a["nome"], a["uf"], cnpj)
            a["cnpj"] = cnpj
            n += 1
    return n


_SQL_ENTREGA = """
INSERT INTO siconfi_entregas (municipio_id, exercicio, entregavel, periodo,
                              periodicidade, status_relatorio, data_status,
                              forma_envio, instituicao, raw_data, atualizado_em)
VALUES (%(mid)s, %(exercicio)s, %(entregavel)s, %(periodo)s, %(periodicidade)s,
        %(status)s, %(data_status)s, %(forma)s, %(instituicao)s,
        %(raw)s::jsonb, NOW())
ON CONFLICT (municipio_id, exercicio, entregavel, periodo) DO UPDATE SET
    periodicidade = EXCLUDED.periodicidade,
    status_relatorio = EXCLUDED.status_relatorio,
    data_status = EXCLUDED.data_status,
    forma_envio = EXCLUDED.forma_envio,
    instituicao = EXCLUDED.instituicao,
    raw_data = EXCLUDED.raw_data,
    atualizado_em = NOW()
"""

_SQL_CAPAG = """
INSERT INTO siconfi_capag (municipio_id, exercicio, posicao, nota,
                           ind_endividamento, nota_endividamento,
                           ind_poupanca, nota_poupanca,
                           ind_liquidez, nota_liquidez, icf, observacao,
                           raw_data, atualizado_em)
VALUES (%(mid)s, %(exercicio)s, %(posicao)s, %(nota)s,
        %(i1)s, %(n1)s, %(i2)s, %(n2)s, %(i3)s, %(n3)s, %(icf)s, %(obs)s,
        %(raw)s::jsonb, NOW())
ON CONFLICT (municipio_id, exercicio) DO UPDATE SET
    posicao = EXCLUDED.posicao, nota = EXCLUDED.nota,
    ind_endividamento = EXCLUDED.ind_endividamento,
    nota_endividamento = EXCLUDED.nota_endividamento,
    ind_poupanca = EXCLUDED.ind_poupanca,
    nota_poupanca = EXCLUDED.nota_poupanca,
    ind_liquidez = EXCLUDED.ind_liquidez,
    nota_liquidez = EXCLUDED.nota_liquidez,
    icf = EXCLUDED.icf, observacao = EXCLUDED.observacao,
    raw_data = EXCLUDED.raw_data, atualizado_em = NOW()
"""


def _data(v) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def _log_ingest(cur, conn, status: str, n: int, erro: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES ('siconfi', %s, %s, %s, NOW())",
            (status, n, erro))
        conn.commit()
    except Exception as e:  # a contabilidade nunca derruba a coleta
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def _recente_demais(cur) -> bool:
    """Auto-limite por `ingestion_log`, como sismob e simec_termos."""
    if os.getenv("SICONFI_FORCE") == "1":
        return False
    cur.execute("SELECT max(finished_at) FROM ingestion_log "
                "WHERE source = 'siconfi' AND status IN ('success','ok')")
    ultimo = (cur.fetchone() or [None])[0]
    if not ultimo:
        return False
    horas = (datetime.now(ultimo.tzinfo) - ultimo).total_seconds() / 3600
    if horas < MIN_INTERVAL_H:
        log.info("ultima coleta ha %.1fh (< %dh) — pulando. SICONFI_FORCE=1 forca.",
                 horas, MIN_INTERVAL_H)
        return True
    return False


def _capag_ja_gravada(cur, exercicio: int, posicao: date | None,
                      ids: list[int]) -> bool:
    """Evita baixar 24 MB para reescrever o que ja esta la (armadilha 8)."""
    if os.getenv("SICONFI_CAPAG_FORCE") == "1" or not ids:
        return False
    cur.execute("SELECT count(*) FROM siconfi_capag WHERE exercicio = %s "
                "AND posicao IS NOT DISTINCT FROM %s AND municipio_id = ANY(%s)",
                (exercicio, posicao, ids))
    return (cur.fetchone() or [0])[0] >= len(ids)


# ---------------------------------------------------------------------------
def ingest(dry: bool = False) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    ano_atual = date.today().year
    anos = [ano_atual, ano_atual - 1]

    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            if not dry and _recente_demais(cur):
                return 0

            alvos = _alvos(cur)
            if not alvos:
                log.info("nenhum municipio ativo com IBGE — nada a coletar")
                if not dry:
                    _log_ingest(cur, conn, "success", 0)
                return 0

            gravados = falhas = 0
            with httpx.Client(follow_redirects=True) as client:
                # --- 1. cadastro de entes: CNPJ oficial ------------------
                try:
                    cadastro = entes(client)
                    log.info("tt/entes: %d entes no cadastro do Tesouro", len(cadastro))
                    if not dry:
                        _preencher_cnpj(cur, alvos, cadastro)
                except Exception as e:
                    cadastro = {}
                    falhas += 1
                    log.warning("tt/entes falhou: %s: %s", type(e).__name__, str(e)[:140])

                # --- 2. extrato de entregas por municipio ----------------
                for a in alvos:
                    for ano in anos:
                        try:
                            linhas = extrato_entregas(client, a["ibge"], ano)
                        except Exception as e:
                            falhas += 1
                            log.warning("  %s/%s %d: %s: %s", a["nome"], a["uf"],
                                        ano, type(e).__name__, str(e)[:120])
                            continue
                        if not linhas:
                            # ⚠️ Fato sobre o ente, nao falha nossa: exercicio
                            # sem entrega registrada (tipico do ano corrente no
                            # comeco do ano). Gravar linha vazia diria que ele
                            # entregou algo em branco.
                            log.info("  %s/%s %d: sem entrega registrada",
                                     a["nome"], a["uf"], ano)
                            continue
                        log.info("  %s/%s %d: %d entrega(s) da prefeitura",
                                 a["nome"], a["uf"], ano, len(linhas))
                        if dry:
                            for x in linhas[:3]:
                                log.info("      %s P%s %s -> %s",
                                         x.get("entregavel"), x.get("periodo"),
                                         x.get("periodicidade"), x.get("data_status"))
                            continue
                        for x in linhas:
                            cur.execute(_SQL_ENTREGA, {
                                "mid": a["id"],
                                "exercicio": x.get("exercicio") or ano,
                                "entregavel": (x.get("entregavel") or "").strip(),
                                "periodo": x.get("periodo") or 0,
                                "periodicidade": (x.get("periodicidade") or "")[:2] or None,
                                "status": x.get("status_relatorio"),
                                "data_status": _data(x.get("data_status")),
                                "forma": (x.get("forma_envio") or "")[:30] or None,
                                "instituicao": (x.get("instituicao") or "").strip() or None,
                                "raw": json.dumps(x, ensure_ascii=False),
                            })
                            gravados += 1
                        time.sleep(PAUSA_S)

                # --- 3. CAPAG -------------------------------------------
                try:
                    gravados += _coletar_capag(cur, client, alvos, dry)
                except Exception as e:
                    falhas += 1
                    log.warning("CAPAG falhou: %s: %s", type(e).__name__, str(e)[:140])

            if dry:
                return 0
            conn.commit()
            log.info("=== SICONFI: %d linha(s) gravada(s), %d falha(s) ===",
                     gravados, falhas)
            _log_ingest(cur, conn, "success" if not falhas else "partial", gravados)
            return gravados
        except Exception as e:
            conn.rollback()
            log.error("SICONFI falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


def _coletar_capag(cur, client: httpx.Client, alvos: list[dict], dry: bool) -> int:
    import tempfile

    rec = capag_recurso(client)
    if not rec or not rec.get("url") or not rec.get("exercicio"):
        log.warning("CAPAG: nenhum XLSX utilizavel no dataset")
        return 0
    log.info("CAPAG: recurso %r (posicao %s, publicado %s)",
             rec["nome"], rec["posicao"], (rec.get("last_modified") or "?")[:10])

    ids = [a["id"] for a in alvos]
    if not dry and _capag_ja_gravada(cur, rec["exercicio"], rec["posicao"], ids):
        log.info("CAPAG: posicao ja gravada para todos os municipios — "
                 "pulando o download de 24 MB. SICONFI_CAPAG_FORCE=1 forca.")
        return 0

    por_ibge = {a["ibge"]: a for a in alvos}
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        caminho = tmp.name
    try:
        with client.stream("GET", rec["url"], headers=UA, timeout=180) as r:
            r.raise_for_status()
            with open(caminho, "wb") as f:
                for bloco in r.iter_bytes(1 << 16):
                    f.write(bloco)
        achados = capag_por_ibge(caminho, set(por_ibge))
    finally:
        try:
            os.unlink(caminho)
        except OSError:
            pass

    n = 0
    for ibge, linha in achados.items():
        a = por_ibge[ibge]
        nota = (linha.get("capag") or "").strip() or None
        log.info("  %s/%s: CAPAG %s (endividamento %s, poupanca %s, liquidez %s)",
                 a["nome"], a["uf"], nota, linha.get("nota 1"),
                 linha.get("nota 2"), linha.get("nota 3"))
        if dry:
            continue
        cur.execute(_SQL_CAPAG, {
            "mid": a["id"], "exercicio": rec["exercicio"], "posicao": rec["posicao"],
            "nota": nota,
            "i1": _num(linha.get("indicador 1")), "n1": (linha.get("nota 1") or None),
            "i2": _num(linha.get("indicador 2")), "n2": (linha.get("nota 2") or None),
            "i3": _num(linha.get("indicador 3")), "n3": (linha.get("nota 3") or None),
            "icf": (linha.get("icf") or None),
            "obs": (linha.get("observacao") or None),
            "raw": json.dumps(linha, ensure_ascii=False),
        })
        n += 1
    faltando = set(por_ibge) - set(achados)
    if faltando:
        # Municipio fora da planilha da CAPAG e fato do Tesouro (ente sem DCA
        # entregue nao entra no calculo) — nao e falha de coleta.
        log.info("CAPAG: %d municipio(s) sem nota na planilha: %s",
                 len(faltando), ", ".join(sorted(faltando)[:8]))
    return n


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ingest(dry="--dry" in sys.argv)
