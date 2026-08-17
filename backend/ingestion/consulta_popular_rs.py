"""
Consulta Popular / COREDEs (RS) — o mecanismo de participação que não existe em MG.

Desde 1998 a população vota, por regiao (28 COREDEs), quais projetos entram na
LOA estadual; os mais votados viram convenio com municipio. A SPGG publica o
resultado em PLANILHA POR COREDE, e e isso que este coletor le.

⭐ O QUE ELE ENTREGA, com o exemplo real que motivou. Na edicao 2026/2027 o
COREDE Central elegeu duas demandas (R$ 2,23 milhoes). Santa Maria votou 153 e
141 vezes — e ficou **DESCLASSIFICADA NAS DUAS**, por nao atingir o minimo de
mobilizacao. A cidade ficou de fora de um recurso da propria regiao, e isso nao
aparece em nenhum sistema financeiro dela. E informacao que muda comportamento
no ano seguinte.

COMO A FONTE E ORGANIZADA (medido em 17/08/2026):

    https://consultapopular.rs.gov.br/resultado-da-consulta-popular-<edicao>
        -> 86 arquivos, ~3 por COREDE, em admin.consultapopular.rs.gov.br:
           <corede>-resultado-consulta-municipios-x-demandas-eleitas.xlsx  <- este
           <corede>-resultado-consulta-programa-valor.xlsx
           <corede>-resultados-eleitores-x-municipios.xlsx

⚠️ SAO XLSX, NAO PDF. A pagina tambem publica um `.pdf` de relatorio avulso, e
confundir os dois levaria a escrever parse de PDF sem necessidade — o dado
estruturado esta na planilha.

⚠️ O LAYOUT TEM DOIS BLOCOS na MESMA aba, e e isso que exige cuidado:
      linhas 2-4   as demandas ELEITAS do COREDE (texto, orgao, votos, valor)
      linha  5     cabecalho do bloco municipal
      linhas 6+    um municipio por linha, com COLUNAS PAREADAS por demanda:
                   (municipio, votos, status) para a 1a; idem para a 2a...
   Ler a planilha como tabela unica produz lixo silencioso: as colunas da 2a
   demanda entrariam como campos extras da 1a.

⚠️ A infraestrutura web do RS tem janelas de instabilidade (reset no handshake,
volta sozinha) — dai o retry. Ver `services/diario_rs.py` para o que foi medido.

Rodavel por Scheduled Task ou a mao:
    python -u ingestion/consulta_popular_rs.py            # coleta
    python -u ingestion/consulta_popular_rs.py --dry      # so mostra
"""
import io
import json
import logging
import os
import re
import sys
import time
import unicodedata

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("consulta_popular_rs")

BASE = "https://consultapopular.rs.gov.br"
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0 consulta publica Consulta Popular RS)"}
UF = "RS"
# A edicao vigente. ⚠️ Uma constante e nao "o ano corrente": a consulta e bienal
# e o rotulo ("2026/2027") e o que o gestor procura — derivar do calendario
# erraria em metade dos anos.
EDICAO = "2026/2027"
PAGINA = f"{BASE}/resultado-da-consulta-popular-{EDICAO.replace('/', '-')}"
ARQUIVO_ALVO = "municipios-x-demandas-eleitas"


def _sem_acento(s) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "").lower())
                   if unicodedata.category(c) != "Mn").strip()


def _get(url: str, tentativas: int = 4, **kw) -> httpx.Response:
    """GET com repeticao — a infra do RS tem janelas de reset (ver cabecalho)."""
    ultimo = None
    for i in range(1, tentativas + 1):
        try:
            with httpx.Client(timeout=60, follow_redirects=True) as c:
                r = c.get(url, headers=UA, **kw)
                r.raise_for_status()
                return r
        except Exception as e:
            ultimo = e
            if i < tentativas:
                log.info("  tentativa %d/%d falhou (%s) — repetindo",
                         i, tentativas, type(e).__name__)
                time.sleep(2.0 * i)
    raise ultimo


def url_da_planilha(corede: str) -> str | None:
    """A planilha 'municipios x demandas eleitas' do COREDE.

    ⚠️ O casamento e por NOME DO COREDE dentro da URL, sem acento — os arquivos
    sao nomeados assim ('...30223043-central-resultado-...'). Nao ha indice
    legivel por maquina; e o que a fonte oferece."""
    alvo = _sem_acento(corede).replace(" ", "-")
    if not alvo:
        return None
    html = _get(PAGINA).text
    candidatos = [u for u in re.findall(r'href="([^"]+\.xlsx)"', html, re.I)
                  if ARQUIVO_ALVO in u.lower() and f"-{alvo}-" in _sem_acento(u)]
    if not candidatos:
        return None
    # Mais de um = republicacao; o Estado prefixa o nome com data+hora, entao o
    # maior nome de arquivo em ordem lexical e o mais recente.
    return sorted(candidatos)[-1]


def parse_planilha(conteudo: bytes, municipio: str) -> list[dict]:
    """Extrai as demandas eleitas e o desempenho do municipio.

    Ver o cabecalho para o layout de DOIS BLOCOS — e por que ler como tabela
    unica produziria lixo."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    linhas = [[("" if v is None else str(v).strip()) for v in row]
              for row in wb[wb.sheetnames[0]].iter_rows(values_only=True)]

    # --- bloco 1: as demandas eleitas do COREDE ---------------------------
    demandas: list[dict] = []
    for r in linhas:
        if not r or not r[0] or _sem_acento(r[0]) in ("corede", "ambito municipal"):
            continue
        if _sem_acento(r[0]) == "ambito municipal":
            break
        # A linha da demanda tem o COREDE na 1a coluna e um texto numerado
        # ("1 - Fomento ao setor...") na 2a.
        texto = r[1] if len(r) > 1 else ""
        m = re.match(r"^\s*(\d+)\s*[-–]\s*(.+)$", texto)
        if not m:
            continue
        nums = [c for c in r[2:] if re.fullmatch(r"-?\d+(\.\d+)?", c or "")]
        demandas.append({
            "ordem": m.group(1),
            "demanda": m.group(2).strip(),
            "orgao": next((c for c in r[2:] if c and not re.fullmatch(r"-?\d+(\.\d+)?", c)), None),
            "votos_corede": int(float(nums[0])) if nums else None,
            "valor": float(nums[-1]) if len(nums) > 1 else None,
            "classificada": True,   # este arquivo lista só as ELEITAS
        })
    if not demandas:
        return []

    # --- bloco 2: os municipios, em colunas pareadas ----------------------
    # Descobre onde comeca: a linha cujo 1o campo e "Âmbito Municipal".
    i_cab = next((i for i, r in enumerate(linhas)
                  if r and _sem_acento(r[0]) == "ambito municipal"), None)
    if i_cab is None:
        return demandas
    alvo = _sem_acento(municipio)
    for r in linhas[i_cab + 1:]:
        # Cada demanda ocupa 3 colunas: (municipio, votos, status).
        for k, d in enumerate(demandas):
            base = k * 3
            if len(r) <= base + 2:
                continue
            if _sem_acento(r[base]) != alvo:
                continue
            votos = r[base + 1]
            d["votos_municipio"] = int(float(votos)) if re.fullmatch(r"\d+(\.\d+)?", votos or "") else None
            d["status_municipio"] = r[base + 2] or None
    return demandas


_SQL = """
INSERT INTO consulta_popular_rs (
    municipio_id, corede, edicao, demanda_ordem, demanda, orgao, votos_corede,
    classificada, valor, votos_municipio, status_municipio, raw_data, atualizado_em)
VALUES (%(mid)s, %(corede)s, %(edicao)s, %(ordem)s, %(demanda)s, %(orgao)s,
        %(votos_corede)s, %(classificada)s, %(valor)s, %(votos_mun)s,
        %(status_mun)s, %(raw)s::jsonb, NOW())
ON CONFLICT (municipio_id, edicao, demanda_ordem) DO UPDATE SET
    corede = EXCLUDED.corede, demanda = EXCLUDED.demanda, orgao = EXCLUDED.orgao,
    votos_corede = EXCLUDED.votos_corede, classificada = EXCLUDED.classificada,
    valor = EXCLUDED.valor, votos_municipio = EXCLUDED.votos_municipio,
    status_municipio = EXCLUDED.status_municipio, raw_data = EXCLUDED.raw_data,
    atualizado_em = NOW()
"""


def _log_ingest(cur, conn, status: str, n: int, erro: str | None = None):
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES ('consulta_popular_rs', %s, %s, %s, NOW())",
            (status, n, erro))
        conn.commit()
    except Exception as e:
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def ingest(dry: bool = False) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT id, nome, corede FROM municipios
                 WHERE active AND upper(coalesce(uf,'')) = %s
                 ORDER BY nome
            """, (UF,))
            municipios = cur.fetchall()
            if not municipios:
                log.info("nenhum municipio do RS neste tenant — Consulta Popular nao se aplica")
                if not dry:
                    _log_ingest(cur, conn, "success", 0)
                return 0

            gravados = 0
            for mid, nome, corede in municipios:
                if not corede:
                    # ⚠️ Sem COREDE nao ha como saber QUAL planilha ler — e
                    # adivinhar pela geografia seria pior que nao coletar. O
                    # campo e preenchido no provisionamento
                    # (/api/control/municipios).
                    log.warning("  %s: sem COREDE cadastrado — pulei "
                                "(preencha em /api/control/municipios)", nome)
                    continue
                url = url_da_planilha(corede)
                if not url:
                    log.warning("  %s (COREDE %s): planilha nao encontrada na "
                                "edicao %s", nome, corede, EDICAO)
                    continue
                demandas = parse_planilha(_get(url).content, nome)
                if not demandas:
                    log.warning("  %s: planilha lida mas sem demanda reconhecida "
                                "— o layout pode ter mudado", nome)
                    continue
                votou = [d for d in demandas if d.get("votos_municipio") is not None]
                log.info("  %s (COREDE %s): %d demanda(s) eleita(s), participacao "
                         "do municipio em %d", nome, corede, len(demandas), len(votou))
                for d in demandas:
                    if d.get("status_municipio"):
                        log.info("      %s… %s votos -> %s", d["demanda"][:44],
                                 d.get("votos_municipio"), d["status_municipio"])
                if dry:
                    continue
                for d in demandas:
                    cur.execute(_SQL, {
                        "mid": mid, "corede": corede, "edicao": EDICAO,
                        "ordem": d["ordem"], "demanda": d["demanda"],
                        "orgao": d.get("orgao"), "votos_corede": d.get("votos_corede"),
                        "classificada": d.get("classificada"), "valor": d.get("valor"),
                        "votos_mun": d.get("votos_municipio"),
                        "status_mun": d.get("status_municipio"),
                        "raw": json.dumps(d, ensure_ascii=False),
                    })
                    gravados += 1
            if dry:
                return 0
            conn.commit()
            log.info("=== Consulta Popular %s: %d linha(s) ===", EDICAO, gravados)
            _log_ingest(cur, conn, "success", gravados)
            return gravados
        except Exception as e:
            conn.rollback()
            log.error("Consulta Popular falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ingest(dry="--dry" in sys.argv)
