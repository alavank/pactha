"""Cofinanciamento estadual da saúde — SES-GO, dados abertos de Goiás.

Duas bases no CKAN `dadosabertos.go.gov.br`, com esquemas DIFERENTES:

- **Atenção Primária** (48343911-…): por quadrimestre, traz o TETO
  (`valor_quadrimestral`), o indicador de desempenho (`isf`), o percentual e o
  VALOR A RECEBER. A diferença entre teto e a receber é dinheiro que o município
  perde por indicador — é o alerta que justifica o produto.
- **Vigilância em Saúde** (a9db21fb-…): por programa e parcela, com
  `pagamento_liberado` SIM/NÃO. Parcela não liberada é dinheiro parado.

⚠️ NÃO SÃO O MESMO PARSER, e o comentário existe porque a tentação é essa: a
Vigilância não tem ano nem quadrimestre; a Primária não tem programa nem parcela.

⚠️ ARMADILHAS MEDIDAS NA FONTE (05/08/2026):

1. **O SEPARADOR DECIMAL VARIA DENTRO DA MESMA BASE.** Na Atenção Primária:
   `valor_quadrimestral` = "51180" (sem separador), `valor_receber` = "44526,6"
   (VÍRGULA), `isf` = "67.5" (PONTO). Na Vigilância, `valor` = "1807.43"
   (ponto). Um parser que assuma vírgula erraria o valor da Vigilância por 100×
   — e valor errado de dinheiro público na tela é o pior defeito possível aqui.
   `_num` decide pelo separador que ENCONTRA, e trata o caso dos dois juntos.
2. **`data_referencia_*` vem como a STRING literal "None"**, não como nulo.
   `_data` trata; sem isso, viraria data inválida ou explodiria o parse.
3. **`codigo_ibge` tem 6 DÍGITOS** (sem o verificador). Os nossos têm 7 — o
   casamento trunca o nosso, nunca completa o deles.
4. O parâmetro `q=` de busca textual do datastore **não funciona** nestas bases
   (devolveu total 0). Usar `filters=` com o código IBGE.
"""
import json
import logging
import os
import re
import sys
from datetime import date, datetime

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

log = logging.getLogger("cofin-ses-go")

CKAN = "https://dadosabertos.go.gov.br/api/3/action/datastore_search"
FONTE = "SES-GO"
UF = "GO"
RES_PRIMARIA = "48343911-cf38-4a99-938f-7ec8cec56dc1"
RES_VIGILANCIA = "a9db21fb-ba20-413c-aac1-fade8121c1fc"
PAGINA = 1000


def _num(s) -> float | None:
    """Número que aceita os TRÊS formatos da fonte (ver armadilha 1).

    "51180" -> 51180.0 · "44526,6" -> 44526.6 · "1807.43" -> 1807.43
    Com os dois separadores, o ÚLTIMO é o decimal ("1.234,56" e "1,234.56")."""
    t = str(s or "").strip()
    if not t or t.lower() in ("none", "null", "-"):
        return None
    t = re.sub(r"[^\d,.\-]", "", t)
    if not t:
        return None
    v, p = t.rfind(","), t.rfind(".")
    if v >= 0 and p >= 0:
        # o separador decimal é o que aparece por ÚLTIMO; o outro é milhar
        if v > p:
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif v >= 0:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _data(s) -> date | None:
    """⚠️ A fonte manda a string "None" quando não há data (armadilha 2)."""
    t = str(s or "").strip()
    if not t or t.lower() in ("none", "null"):
        return None
    for f in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, f).date()
        except ValueError:
            pass
    return None


def _sim(s) -> bool | None:
    t = str(s or "").strip().upper()
    if t in ("SIM", "S", "TRUE", "1"):
        return True
    if t in ("NAO", "NÃO", "N", "FALSE", "0"):
        return False
    return None


def _int(s) -> int | None:
    v = _num(s)
    return int(v) if v is not None else None


def _mapa_ibge6(cur) -> dict:
    """IBGE de 6 dígitos -> municipio_id (a fonte não traz o verificador)."""
    cur.execute("SELECT id, ibge_code FROM municipios "
                "WHERE active AND upper(coalesce(uf, '')) = %s "
                "AND ibge_code IS NOT NULL", (UF,))
    return {str(ib)[:6]: mid for mid, ib in cur.fetchall() if ib}


def _buscar(cli: httpx.Client, resource: str, ibge6: str) -> list[dict]:
    """Todas as linhas de um município. Usa `filters` — o `q=` não funciona
    nestas bases (armadilha 4)."""
    saida, offset = [], 0
    while True:
        r = cli.get(CKAN, params={
            "resource_id": resource,
            "filters": json.dumps({"codigo_ibge": ibge6}),
            "limit": PAGINA, "offset": offset,
        })
        r.raise_for_status()
        d = r.json()
        if not d.get("success"):
            raise RuntimeError(f"CKAN recusou: {str(d)[:160]}")
        regs = d["result"].get("records") or []
        saida.extend(regs)
        if len(regs) < PAGINA:
            return saida
        offset += PAGINA


def _grava_primaria(cur, mid: int, r: dict) -> None:
    ano, quad = _int(r.get("ano")), _int(r.get("quadrimestre"))
    chave = f"AP|{r.get('codigo_ibge')}|{ano}|{quad}"
    cur.execute("""
        INSERT INTO cofinanciamento_saude (
            municipio_id, fonte, tipo, chave, competencia, valor_teto, valor,
            perc_receber, indicador, fechado, ano, raw_data
        ) VALUES (%s,%s,'atencao_primaria',%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
        ON CONFLICT (fonte, chave) DO UPDATE SET
            valor_teto = EXCLUDED.valor_teto, valor = EXCLUDED.valor,
            perc_receber = EXCLUDED.perc_receber, indicador = EXCLUDED.indicador,
            fechado = EXCLUDED.fechado, raw_data = EXCLUDED.raw_data,
            updated_at = NOW()
    """, (mid, FONTE, chave,
          f"{ano}/Q{quad}" if ano and quad else None,
          _num(r.get("valor_quadrimestral")), _num(r.get("valor_receber")),
          _num(r.get("perc_receber")), _num(r.get("isf")),
          _sim(r.get("quadrimestre_fechado")), ano,
          json.dumps(r, ensure_ascii=False)))


def _grava_vigilancia(cur, mid: int, r: dict) -> None:
    prog, parc = _int(r.get("numero_programa")), _int(r.get("numero_parcela"))
    chave = f"VG|{r.get('codigo_ibge')}|{prog}|{parc}|{r.get('data_fechamento') or ''}"
    dt = _data(r.get("data_fechamento"))
    cur.execute("""
        INSERT INTO cofinanciamento_saude (
            municipio_id, fonte, tipo, chave, competencia, programa, valor,
            liberado, data_ref, ano, raw_data
        ) VALUES (%s,%s,'vigilancia',%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
        ON CONFLICT (fonte, chave) DO UPDATE SET
            valor = EXCLUDED.valor, liberado = EXCLUDED.liberado,
            programa = EXCLUDED.programa, raw_data = EXCLUDED.raw_data,
            updated_at = NOW()
    """, (mid, FONTE, chave,
          f"programa {prog} · parcela {parc}" if prog else None,
          str(r.get("descricao_programa") or "")[:300],
          _num(r.get("valor")), _sim(r.get("pagamento_liberado")),
          dt, dt.year if dt else None,
          json.dumps(r, ensure_ascii=False)))


def _log_ingest(cur, status: str, n: int, erro: str | None = None):
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES (%s,%s,%s,%s,NOW())",
            ("cofin_ses_go", status, n, erro))
    except Exception:
        pass


try:
    from ingestion import status_coleta as _st
except ImportError:
    import status_coleta as _st


def ingest() -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            mapa = _mapa_ibge6(cur)
            if not mapa:
                log.info("nenhum municipio de GO neste tenant — SES-GO nao se aplica")
                _log_ingest(cur, "success", 0)
                conn.commit()
                return 0
            log.info("SES-GO: %d municipio(s) de GO", len(mapa))

            total = 0
            falhas = 0  # ⚠️ M-3/M-4: municipio de GO que falhou
            with httpx.Client(timeout=90, follow_redirects=True,
                              headers={"User-Agent": "Mozilla/5.0"}) as cli:
                for ibge6, mid in sorted(mapa.items()):
                    # ⚠️ M-4 (auditoria 11/09): SAVEPOINT por municipio. Antes, uma
                    # falha de _buscar/_grava propagava e derrubava o run inteiro
                    # para 'error'. Agora o municipio ruim e isolado e o resto grava.
                    try:
                        cur.execute("SAVEPOINT cofin_mun")
                        ap = _buscar(cli, RES_PRIMARIA, ibge6)
                        for r in ap:
                            _grava_primaria(cur, mid, r)
                        vg = _buscar(cli, RES_VIGILANCIA, ibge6)
                        for r in vg:
                            _grava_vigilancia(cur, mid, r)
                        cur.execute("RELEASE SAVEPOINT cofin_mun")
                        total += len(ap) + len(vg)
                        log.info("  ibge %s: %d atencao primaria + %d vigilancia",
                                 ibge6, len(ap), len(vg))
                    except Exception as e:
                        cur.execute("ROLLBACK TO SAVEPOINT cofin_mun")
                        falhas += 1
                        log.warning("  ibge %s: falhou (%s)", ibge6, str(e)[:120])
            conn.commit()
            log.info("SES-GO: %d registro(s) gravados, %d municipio(s) com falha", total, falhas)
            # ⚠️ M-3: 'partial' quando parte dos municipios de GO falhou — nao 'success' cravado.
            status, erro = _st.por_falhas(total, falhas, "municipio de GO")
            _log_ingest(cur, status, total, erro)
            conn.commit()
            return total
        except Exception as e:
            conn.rollback()
            log.error("SES-GO falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, "error", 0, str(e)[:400])
            conn.commit()
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ingest()
