"""Notas de Empenho do DADO ABERTO federal (siconv_empenho.zip) — fallback.

⚠️ O REQUISITO QUE DEFINE ESTE COLETOR: "nao podemos perder informacao, nem nas
consultas automaticas". Por isso ele grava numa coluna SEPARADA
(`notas_empenho_aberto`) e NUNCA toca `notas_empenho`, que e a listagem rica do
scraper autenticado. O RM le a rica quando existe e cai para esta so quando a
rica e nula. Assim a fonte logada — que tem detalhe que a API nao tem — nunca e
degradada, independentemente da ordem em que as rotinas automaticas rodam.

POR QUE EXISTE. Medido em 04/09/2026 (freitas): a listagem do scraper e nula em
2.742 de 3.200 propostas, porque a sessao gov.br fica fria (298 de 720 horas
mortas num mes). O `siconv_empenho.zip` e publico, diario, sem login e fora do
bloqueio de IP — e cobre a NE de 598 dos 665 convenios celebrados hoje sem
listagem. O VALOR ja vinha do agregado `valor_empenhado`; o que faltava e a
LISTAGEM nota a nota: numero, situacao e data.

⚠️ SO NE REAL. O dump mistura, medido no arquivo de 04/09:
  - 105.962 linhas com valor <= R$1  -> MINUTA (nao e dinheiro)
  - dezenas de milhares com valor NEGATIVO ou tipo "Anulacao"/"...CANC..." de RP
Jogar isso cru no RM contaria minuta como empenho e somaria estorno como
recurso. O filtro `_e_ne_real` descarta os dois na origem, entao tudo que grava
nasce com `minuta_apenas=False`.

⚠️ CASA POR NR_CONVENIO = `codigo_instrumento`, so para os convenios que ja
existem no NOSSO banco (o dump federal tem 437 mil linhas; a esmagadora maioria
e de outros municipios). Carrega em memoria so o que casa.

Rodar:  DATABASE_URL_SYNC=... python -u ingestion/siconv_empenho_aberto.py
"""
import io
import json
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2  # noqa: E402
from ingestion.transferegov_opendata import _linhas  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("siconv_empenho_aberto")

FONTE = "siconv_empenho_aberto"


def _dsn() -> str:
    u = os.getenv("DATABASE_URL_SYNC", "") or os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
    return u.replace("&channel_binding=require", "").replace("?channel_binding=require", "")


def _num(x) -> float | None:
    try:
        return float((x or "0").replace(".", "").replace(",", ".")) if "," in (x or "") \
            else float(x or 0)
    except (TypeError, ValueError):
        return None


def _e_ne_real(linha: dict) -> bool:
    """True so para NOTA DE EMPENHO que é dinheiro de verdade.

    ⚠️ Espelha o que o RM (`_tem_ne_real`/`minuta_apenas`) considera empenho: nao
    minuta (valor <= R$1), nao anulacao/cancelamento (tipo ou valor negativo).
    Sem isto, o dado aberto DEGRADARIA o relatorio — que e exatamente o que o
    requisito 'nao perder informacao' proibe."""
    v = _num(linha.get("VALOR_EMPENHO"))
    if v is None or v <= 1:
        return False
    tipo = (linha.get("DESC_TIPO_NOTA") or "").upper()
    if "ANULA" in tipo or "CANC" in tipo:
        return False
    return True


def _registro(linha: dict) -> dict:
    """Uma linha do dump vira uma NE no MESMO formato de `notas_empenho`.

    O RM le as duas colunas com as mesmas funcoes; o formato tem de bater:
    [{numero, valor, situacao, dt_emissao, minuta_apenas}]."""
    return {
        "numero": (linha.get("NR_EMPENHO") or "").strip() or None,
        "valor": _num(linha.get("VALOR_EMPENHO")),
        "situacao": (linha.get("DESC_SITUACAO_EMPENHO") or "").strip() or None,
        "dt_emissao": (linha.get("DATA_EMISSAO") or "").strip() or None,
        # ⚠️ SEMPRE False: `_e_ne_real` ja descartou minuta e anulacao na origem.
        "minuta_apenas": False,
    }


def coletar() -> dict:
    res = {"fonte": FONTE, "status": "erro", "convenios": 0, "notas": 0}
    conn = None
    try:
        conn = psycopg2.connect(_dsn(), connect_timeout=15)
        cur = conn.cursor()

        # Os NR_CONVENIO que existem NESTE tenant. So estes interessam.
        cur.execute("SELECT id, codigo_instrumento FROM transferegov_propostas "
                    "WHERE codigo_instrumento IS NOT NULL AND codigo_instrumento <> ''")
        por_conv: dict[str, list[int]] = {}
        for pid, nc in cur.fetchall():
            por_conv.setdefault(nc.strip(), []).append(pid)
        log.info(f"{len(por_conv)} convenio(s) com codigo_instrumento neste tenant")
        if not por_conv:
            res["status"] = "success"
            return res

        # Varre o dump uma vez, acumulando SO o que casa e SO NE real.
        acc: dict[str, list[dict]] = {}
        vistos = descartados = 0
        for linha in _linhas("siconv_empenho.zip"):
            nc = (linha.get("NR_CONVENIO") or "").strip()
            if nc not in por_conv:
                continue
            vistos += 1
            if not _e_ne_real(linha):
                descartados += 1
                continue
            acc.setdefault(nc, []).append(_registro(linha))
        log.info(f"linhas do dump que casaram: {vistos} "
                 f"({descartados} descartadas por minuta/anulacao); "
                 f"{len(acc)} convenio(s) com NE real")

        # Grava — SEMPRE em `notas_empenho_aberto`, NUNCA em `notas_empenho`.
        agora = datetime.now(timezone.utc)
        for nc, notas in acc.items():
            payload = json.dumps(notas, ensure_ascii=False)
            for pid in por_conv[nc]:
                cur.execute(
                    "UPDATE transferegov_propostas "
                    "SET notas_empenho_aberto = %s::jsonb, "
                    "    notas_empenho_aberto_atualizado_em = %s "
                    "WHERE id = %s",
                    (payload, agora, pid))
                res["convenios"] += 1
                res["notas"] += len(notas)
        conn.commit()
        res["status"] = "success"
        log.info(f"gravados {res['convenios']} proposta(s), {res['notas']} NE(s) "
                 f"em notas_empenho_aberto")
        return res
    except Exception as e:
        if conn:
            conn.rollback()
        res["erro"] = str(e)[:200]
        log.error(f"ERRO: {e}")
        return res
    finally:
        # ⚠️ A LINHA DO ingestion_log SAI SEMPRE — sucesso, vazio ou erro. Fonte
        # sem linha nunca e cobrada pelo watchdog (foi assim que coletas morreram
        # em silencio). Rollback proprio para nao arrastar erro anterior.
        if conn:
            try:
                c2 = conn.cursor()
                c2.execute(
                    "INSERT INTO ingestion_log (source, status, records_inserted, finished_at) "
                    "VALUES (%s, %s, %s, %s)",
                    (FONTE, res["status"], res.get("notas", 0),
                     datetime.now(timezone.utc)))
                conn.commit()
            except Exception as e2:
                log.error(f"nao consegui gravar o ingestion_log: {e2}")
            conn.close()


# Alias no padrao dos outros coletores de dado aberto.
def ingest() -> dict:
    return coletar()


if __name__ == "__main__":
    r = coletar()
    print(f"siconv_empenho_aberto: FIM — status={r['status']} "
          f"{r.get('convenios',0)} proposta(s), {r.get('notas',0)} NE(s)"
          + (f" | ERRO: {r['erro']}" if r.get("erro") else ""))
    sys.exit(0 if r["status"] == "success" else 1)
