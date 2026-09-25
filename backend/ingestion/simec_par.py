"""Scraper SIMEC PAR (Plano de Acoes Articuladas) - consulta publica MEC.

Fonte: https://simec.mec.gov.br/cte/relatoriopublico/impressao.php?estuf=MG&muncod={IBGE}
Sem login; Cloudflare na frente (daí o curl_cffi). Retorna HTML rico (~190KB) com:
  - Sintese por Dimensao (tabela 4): 4 dimensoes x contagem de indicadores
  - Liberacoes de Recursos (tabelas 19+): pagamentos federais por programa
    (PNAE, PNATE, QUOTA Salario-Educacao, etc.)

Roda diariamente via cron no Coolify. Sem dependencia de browser/credenciais.

⚠️ DESDE 24/09/2026 AS LIBERAÇÕES SÃO PLANO B. A fonte principal é a consulta do
FNDE (`ingestion/fnde_liberacoes.py`, pls/simad): o relatório daqui só lê o CNPJ
da PREFEITURA e só o ano corrente — Monte Sião recebe o salário-educação na
SECRETARIA desde 03/2026 e aqui aparecia só jan+fev; o PDDE das caixas escolares
não aparece nunca. As DIMENSÕES do PAR continuam sendo só daqui.
As liberações lidas aqui ainda são gravadas (`grava_liberacoes_reserva`), mas
NUNCA por cima do que o simad gravou: é a rede para a noite em que o simad cair.
"""
import json
import logging
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# curl_cffi impersona TLS/HTTP do Chrome -> vence Cloudflare do SIMEC
# (httpx puro recebe 403 mesmo com headers de browser).
from curl_cffi import requests as cffi
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("simec_par")

URL = "https://simec.mec.gov.br/cte/relatoriopublico/impressao.php"

# Map mes pt-BR (3 letras maiusculas) -> numero
MESES = {
    "JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12,
}


def _municipios_pacta() -> list[dict]:
    import psycopg2
    url = os.getenv("DATABASE_URL_SYNC", "")
    url = url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    conn = psycopg2.connect(url)
    cur = conn.cursor()
    cur.execute("SELECT id, nome, uf, ibge_code, cnpj FROM municipios WHERE active = true ORDER BY nome")
    out = [{"id": r[0], "nome": r[1], "uf": r[2], "ibge": r[3], "cnpj": r[4]} for r in cur.fetchall()]
    cur.close(); conn.close()
    return out


def _parse_money(s: str) -> float | None:
    if not s:
        return None
    s = re.sub(r"[^\d,.-]", "", s)
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _parse_data(s: str) -> date | None:
    """Aceita '26/FEV/2026' ou '26/02/2026'."""
    if not s:
        return None
    s = s.strip().upper()
    m = re.match(r"(\d{1,2})/([A-Z]{3}|\d{1,2})/(\d{4})", s)
    if not m:
        return None
    d, mes, ano = m.groups()
    if mes in MESES:
        mes_n = MESES[mes]
    else:
        try:
            mes_n = int(mes)
        except ValueError:
            return None
    try:
        return date(int(ano), mes_n, int(d))
    except (ValueError, TypeError):
        return None


def parse_relatorio(html: str) -> dict:
    """Parseia o HTML do relatorio. Retorna {'dimensoes': [...], 'liberacoes': [...]}."""
    # ⚠️ lxml, NUNCA html.parser (25/09/2026): o relatório tem HTML malformado e o
    # html.parser desmonta a tabela da ALIMENTAÇÃO ESCOLAR (PNAE) — sobrava 1 linha
    # sem OB, que o upsert descarta. Monte Sião: 6 liberações contra 45, e o PNAE
    # (40 parcelas) sumia de todos os tenants sem erro nenhum.
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    dimensoes = []
    liberacoes = []

    # === Sintese por Dimensao (tabela com header "Dimensao | Pontuacao") ===
    for t in tables:
        rows = t.find_all("tr")
        if len(rows) < 3:
            continue
        h0 = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
        if len(h0) >= 2 and "dimens" in h0[0].lower() and "pontua" in h0[1].lower():
            # rows[1] = '4 3 2 1 n/a'; rows[2..] = dimensao + 5 numeros; ultima 'Total:'
            for r in rows[2:]:
                cells = [c.get_text(" ", strip=True) for c in r.find_all(["th", "td"])]
                if len(cells) < 6 or cells[0].lower().startswith(("total", "*")):
                    continue
                try:
                    dimensoes.append({
                        "dimensao": cells[0],
                        "score_4": int(cells[1] or 0),
                        "score_3": int(cells[2] or 0),
                        "score_2": int(cells[3] or 0),
                        "score_1": int(cells[4] or 0),
                        "score_na": int(cells[5] or 0),
                    })
                except (ValueError, IndexError):
                    pass
            break

    # === Liberacoes por programa (tabelas onde 2a linha eh "Data Pgto OB Valor ...") ===
    for t in tables:
        rows = t.find_all("tr")
        if len(rows) < 2:
            continue
        hdr = [c.get_text(" ", strip=True).lower() for c in rows[1].find_all(["th", "td"])]
        if not hdr or "data pgto" not in (hdr[0] if hdr else ""):
            continue
        # Nome do programa na primeira linha
        prog_full = rows[0].get_text(" ", strip=True)
        prog_sigla = prog_full.split("-", 1)[0].strip() or prog_full[:40]
        # Mapa colunas -> indice (algumas tabelas tem 'Parcela', outras nao)
        col = {h: i for i, h in enumerate(hdr)}
        for r in rows[2:]:
            cells = [c.get_text(" ", strip=True) for c in r.find_all(["th", "td"])]
            if not cells or cells[0].lower().startswith("total"):
                continue

            def g(k):
                i = col.get(k)
                return cells[i] if i is not None and i < len(cells) else None

            dt = _parse_data(g("data pgto") or "")
            valor = _parse_money(g("valor") or "")
            if not dt and not valor:
                continue
            liberacoes.append({
                "programa": prog_sigla[:50],
                "programa_full": prog_full[:200],
                "dt_pgto": dt,
                "ob": (g("ob") or "")[:30] or None,
                "valor": valor,
                "parcela": (g("parcela") or "")[:30] or None,
                "descricao": (g("programa") or "")[:200] or None,
                "banco": (g("banco") or "")[:50] or None,
                "agencia": (g("agência") or g("agencia") or "")[:30] or None,
                "conta": (g("c/c") or "")[:50] or None,
                "ano": dt.year if dt else None,
            })
    return {"dimensoes": dimensoes, "liberacoes": liberacoes}


def scrape_municipio(mun: dict) -> dict | None:
    """Baixa e parseia o relatorio de um municipio. Retorna {dimensoes, liberacoes}."""
    # inuid=3040 -> ativa secao "SINTESE DO PAR" no relatorio (sem isso vem
    # so as Liberacoes de Recursos, ~123KB ao inves de ~188KB).
    params = {
        "inuid": "3040", "itrid": "", "est": "", "mun": "",
        "municod": "", "estuf": mun["uf"], "muncod": mun["ibge"],
    }
    try:
        r = cffi.get(URL, params=params, impersonate="chrome", verify=False, timeout=60)
        if r.status_code != 200:
            logger.warning(f"  {mun['nome']}: HTTP {r.status_code}")
            return None
    except Exception as e:
        logger.warning(f"  {mun['nome']}: {str(e)[:120]}")
        return None
    try:
        html = r.content.decode("cp1252", errors="replace")
    except Exception:
        html = r.text
    return parse_relatorio(html)


# PLANO B das liberações (ver o cabeçalho). O relatório só mostra a PREFEITURA,
# então a linha nasce com o CNPJ dela (`municipios.cnpj`, '' se o tenant não
# cadastrou) e `tipo_favorecido = 'prefeitura'`, `fonte = 'simec'`.
#
# ⚠️ NUNCA POR CIMA DO SIMAD, nas duas formas em que isso poderia acontecer:
#   - mesma chave (CNPJ, programa, data, OB) já gravada pelo simad: o ON CONFLICT
#     só atualiza linha que seja do próprio SIMEC (`WHERE ... fonte = 'simec'`);
#   - a mesma liberação da prefeitura gravada sob OUTRO CNPJ (o cadastro do tenant
#     diverge do FNDE, ou está vazio): o NOT EXISTS não deixa inserir a gêmea.
# E nada é apagado: plano B só acrescenta.
_SQL_LIB_RESERVA = """
    INSERT INTO simec_par_liberacoes
        (municipio_id, programa, programa_full, dt_pgto, ob, valor, parcela,
         descricao, banco, agencia, conta, ano, raw, cnpj_favorecido,
         tipo_favorecido, fonte, updated_at)
    SELECT %(mid)s, %(programa)s, %(programa_full)s, %(dt_pgto)s, %(ob)s, %(valor)s,
           %(parcela)s, %(descricao)s, %(banco)s, %(agencia)s, %(conta)s, %(ano)s,
           %(raw)s::jsonb, %(cnpj)s, 'prefeitura', 'simec', NOW()
    WHERE NOT EXISTS (
        SELECT 1 FROM simec_par_liberacoes x
        WHERE x.municipio_id = %(mid)s AND x.programa = %(programa)s
          AND x.dt_pgto = %(dt_pgto)s AND x.ob = %(ob)s
          AND x.tipo_favorecido = 'prefeitura' AND x.cnpj_favorecido <> %(cnpj)s)
    ON CONFLICT (municipio_id, cnpj_favorecido, programa, dt_pgto, ob) DO UPDATE SET
        programa_full=EXCLUDED.programa_full, valor=EXCLUDED.valor,
        parcela=EXCLUDED.parcela, descricao=EXCLUDED.descricao,
        banco=EXCLUDED.banco, agencia=EXCLUDED.agencia, conta=EXCLUDED.conta,
        ano=EXCLUDED.ano, raw=EXCLUDED.raw, updated_at=NOW()
    WHERE simec_par_liberacoes.fonte = 'simec'
"""


def grava_liberacoes_reserva(cur, mun_id: int, cnpj_prefeitura: str | None,
                             liberacoes: list[dict]) -> int:
    """Grava as liberações do relatório do SIMEC como PLANO B. Devolve quantas
    linhas de fato entraram ou mudaram (`rowcount`): 0 quando o simad já tem
    todas — o log não pode dizer "45 liberações" de uma rodada que não escreveu
    nada."""
    cnpj = re.sub(r"\D", "", cnpj_prefeitura or "")
    cnpj = cnpj if len(cnpj) == 14 else ""
    n = 0
    for li in liberacoes:
        if not (li.get("dt_pgto") and li.get("ob")):
            continue  # chave UNIQUE precisa de dt_pgto + ob
        cur.execute(_SQL_LIB_RESERVA, {
            "mid": mun_id, "programa": li["programa"], "programa_full": li["programa_full"],
            "dt_pgto": li["dt_pgto"], "ob": li["ob"], "valor": li["valor"],
            "parcela": li["parcela"], "descricao": li["descricao"], "banco": li["banco"],
            "agencia": li["agencia"], "conta": li["conta"], "ano": li["ano"],
            "raw": json.dumps(li, default=str), "cnpj": cnpj,
        })
        n += max(cur.rowcount or 0, 0)
    return n


def upsert(mun_id: int, data: dict, cnpj_prefeitura: str | None = None) -> tuple[int, int]:
    """UPSERT dimensoes + liberacoes (estas como plano B). Retorna (n_dimensoes, n_liberacoes)."""
    import psycopg2
    url = os.getenv("DATABASE_URL_SYNC", "")
    url = url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    conn = psycopg2.connect(url); cur = conn.cursor()
    nd = 0
    for d in data.get("dimensoes", []):
        cur.execute("""
            INSERT INTO simec_par_dimensoes
                (municipio_id, dimensao, score_4, score_3, score_2, score_1, score_na, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
            ON CONFLICT (municipio_id, dimensao) DO UPDATE SET
                score_4=EXCLUDED.score_4, score_3=EXCLUDED.score_3, score_2=EXCLUDED.score_2,
                score_1=EXCLUDED.score_1, score_na=EXCLUDED.score_na, updated_at=NOW()
        """, (mun_id, d["dimensao"][:200], d["score_4"], d["score_3"],
              d["score_2"], d["score_1"], d["score_na"]))
        nd += 1
    nl = grava_liberacoes_reserva(cur, mun_id, cnpj_prefeitura, data.get("liberacoes", []))
    conn.commit(); cur.close(); conn.close()
    return nd, nl


try:
    from ingestion import status_coleta as _st
except ImportError:  # rodando como script (python ingestion/simec_par.py)
    import status_coleta as _st


def run():
    municipios = _municipios_pacta()
    logger.info(f"=== SIMEC PAR: {len(municipios)} municipios ===")
    total_d = total_l = 0
    falhas = 0
    for mun in municipios:
        data = scrape_municipio(mun)
        if data is None:
            falhas += 1
            continue
        nd, nl = upsert(mun["id"], data, mun.get("cnpj"))
        logger.info(f"  {mun['nome']}: {nd} dimensoes + {nl} liberacoes novas/atualizadas "
                    f"(plano B: o que o simad ja tem nao e tocado)")
        total_d += nd; total_l += nl
    logger.info(f"=== Finalizado: {total_d} dimensoes + {total_l} liberacoes "
                f"({falhas} municipio(s) sem resposta) ===")
    # ⚠️ A-1 (auditoria 11/09): status HONESTO, nao 'success' cravado. O SIMEC ja
    # gravou success com 0 registros 3x quando o curl_cffi/layout quebrou.
    # A decisao e por FALHA DE FETCH, nao por contagem: um tenant de 1 municipio
    # pode legitimamente ter 0 liberacoes (municipio sem PAR), entao 0 registros
    # SEM falha de fetch e success de verdade. Todos falharam => error (fonte fora
    # do ar/Cloudflare); alguns => partial; nenhum => success.
    status, erro = _st.simec_par(len(municipios), falhas)
    try:
        import psycopg2
        url = os.getenv("DATABASE_URL_SYNC", "").replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        conn = psycopg2.connect(url); cur = conn.cursor()
        cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, error_message, finished_at) "
                    "VALUES ('simec_par',%s,%s,%s,NOW())", (status, total_d + total_l, erro))
        conn.commit(); cur.close(); conn.close()
    except Exception:
        pass


if __name__ == "__main__":
    run()
