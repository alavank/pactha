"""FUNDO A FUNDO da saude: o repasse do FNS ao Fundo Municipal, por bloco.

O que a plataforma ja tinha do FNS era a PROPOSTA (`convenios_estadual` com
fonte='FNS') — o extraordinario. Isto e o ORDINARIO: o dinheiro que sustenta a
rede todo mes, por BLOCO e por GRUPO de financiamento.

FONTE (PUBLICA, SEM LOGIN):
    GET https://consultafns.saude.gov.br/recursos/consulta-consolidada/repasse-bloco
        ?ano=2026&coMunicipioIbge=314340&coTipoRepasse=M&sgUf=MG&count=100&page=1

⚠️ COMO ESTE ENDERECO FOI ACHADO, porque a historia importa para o proximo que
mexer aqui. Uma primeira investigacao SONDOU os enderecos por adivinhacao
(`/recursos/consulta-detalhada/*`, `/recursos/consolidada`) e concluiu, com
`{}` e HTTP 400 na mao, que "nao ha caminho publico para o fundo a fundo". A
conclusao foi PUBLICADA e estava errada. O caminho apareceu ao ABRIR A TELA
(`consultafns.saude.gov.br/#/consolidada`) e ler as chamadas que ela mesma faz.
A licao, valida para qualquer portal de governo deste repo: **quando a API nao
responde, abra a tela antes de declarar que nao existe caminho.**

⚠️ O CAMINHO-PAI DA 404. `/recursos/consulta-consolidada` sozinho responde 404;
so o recurso-folha (`/repasse-bloco`) existe. Sondar o pai e concluir pela
ausencia foi exatamente o erro acima.

⚠️ A RESPOSTA E UMA ARVORE E A TABELA E PLANA. Cada bloco traz `repasses[]` com
os grupos. Bloco SEM grupo detalhado vira uma linha com `grupo_codigo = 0`, para
o total nao se perder — e nao ser confundido com um grupo real.

⚠️ O PORTAL E LENTO. Medido: o `entidades` estourou 120s no primeiro teste. Por
isso timeout generoso, uma pausa entre municipios e tratamento de falha POR
MUNICIPIO — um timeout nao pode derrubar a rodada inteira.

Rodar:  DATABASE_URL_SYNC=... python -u ingestion/fns_faf.py
        FNS_FAF_ANOS=3  -> coleta os 3 ultimos anos (padrao: 1, o corrente)
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date

import httpx
import psycopg2
from psycopg2.extras import Json

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fns_faf")

BASE = "https://consultafns.saude.gov.br/recursos"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Accept": "application/json, text/plain, */*"}
FONTE = "fns_faf"
TIMEOUT = float(os.getenv("FNS_FAF_TIMEOUT", "120") or "120")
PAUSA = float(os.getenv("FNS_FAF_PAUSA", "1.5") or "1.5")
ANOS = max(1, int(os.getenv("FNS_FAF_ANOS", "1") or "1"))


def _dsn() -> str:
    u = os.getenv("DATABASE_URL_SYNC", "") or os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
    return u.replace("&channel_binding=require", "").replace("?channel_binding=require", "")


_SQL = """
    INSERT INTO fns_repasse_faf
        (municipio_id, ano, tipo_repasse, bloco_codigo, bloco_nome,
         grupo_codigo, grupo_nome, vl_total, vl_desconto, vl_liquido,
         raw_data, updated_at)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,NOW())
    ON CONFLICT (municipio_id, ano, tipo_repasse, bloco_codigo, grupo_codigo)
    DO UPDATE SET
        bloco_nome=EXCLUDED.bloco_nome, grupo_nome=EXCLUDED.grupo_nome,
        -- ⚠️ SOBRESCRITA DIRETA, sem COALESCE: o valor do ano em curso CRESCE a
        -- cada competencia paga. Um COALESCE congelaria o numero da primeira
        -- coleta e a serie pararia no lugar, em silencio.
        vl_total=EXCLUDED.vl_total, vl_desconto=EXCLUDED.vl_desconto,
        vl_liquido=EXCLUDED.vl_liquido,
        raw_data=EXCLUDED.raw_data, updated_at=NOW()
"""


def _num(x):
    """None continua None; numero vira float. '' e ausencia, nao zero."""
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def achata(resultado) -> list[dict]:
    """A arvore bloco->grupo vira lista de linhas. Funcao PURA (testavel).

    ⚠️ Bloco sem grupo detalhado NAO e descartado: vira uma linha com
    `grupo_codigo = 0` e o nome do proprio bloco. Descartar perderia o total; e
    usar o codigo de um grupo real inventaria detalhamento que o portal nao deu.
    """
    linhas = []
    for bloco in (resultado or []):
        if not isinstance(bloco, dict):
            continue
        bcod = bloco.get("codigo")
        bnome = (bloco.get("nome") or "").strip() or None
        if bcod is None:
            continue
        grupos = [g for g in (bloco.get("repasses") or []) if isinstance(g, dict)]
        if not grupos:
            linhas.append({"bloco_codigo": int(bcod), "bloco_nome": bnome,
                           "grupo_codigo": 0, "grupo_nome": bnome,
                           "vl_total": _num(bloco.get("vlTotal")),
                           "vl_desconto": _num(bloco.get("vlDesconto")),
                           "vl_liquido": _num(bloco.get("vlLiquido")),
                           "raw": bloco})
            continue
        for g in grupos:
            gcod = g.get("codigo")
            if gcod is None:
                continue
            linhas.append({"bloco_codigo": int(bcod), "bloco_nome": bnome,
                           "grupo_codigo": int(gcod),
                           "grupo_nome": (g.get("nome") or "").strip() or None,
                           "vl_total": _num(g.get("vlTotal")),
                           "vl_desconto": _num(g.get("vlDesconto")),
                           "vl_liquido": _num(g.get("vlLiquido")),
                           "raw": g})
    return linhas


def busca(cli: httpx.Client, ano: int, ibge6: str, uf: str) -> list | None:
    """None = a consulta FALHOU (nao confundir com lista vazia = sem repasse)."""
    try:
        r = cli.get(f"{BASE}/consulta-consolidada/repasse-bloco",
                    params={"ano": ano, "coMunicipioIbge": ibge6, "coTipoRepasse": "M",
                            "sgUf": uf, "count": 100, "page": 1})
    except Exception as e:
        log.warning(f"  {ibge6}/{ano}: {type(e).__name__}")
        return None
    if r.status_code != 200:
        log.warning(f"  {ibge6}/{ano}: HTTP {r.status_code}")
        return None
    if "json" not in r.headers.get("content-type", "").lower():
        # 200 com HTML e a assinatura de muro/erro, nao de "sem dado"
        log.warning(f"  {ibge6}/{ano}: resposta nao-JSON ({len(r.content)}B)")
        return None
    try:
        return r.json().get("resultado") or []
    except Exception:
        log.warning(f"  {ibge6}/{ano}: JSON ilegivel")
        return None


def run() -> int:
    cn = psycopg2.connect(_dsn())
    cur = cn.cursor()
    cur.execute("SELECT id, nome, ibge_code, uf FROM municipios "
                "WHERE coalesce(active, true) AND ibge_code IS NOT NULL "
                "AND btrim(ibge_code) <> '' ORDER BY nome")
    muns = cur.fetchall()
    anos = [date.today().year - i for i in range(ANOS)]
    log.info(f"FNS fundo a fundo: {len(muns)} municipio(s) x {len(anos)} ano(s) {anos}")

    total = 0
    falhas = []
    with httpx.Client(headers=UA, timeout=TIMEOUT, follow_redirects=True) as cli:
        for mid, nome, ibge, uf in muns:
            ibge6 = str(ibge).strip()[:6]
            for ano in anos:
                res = busca(cli, ano, ibge6, str(uf).strip().upper())
                if res is None:
                    falhas.append(f"{nome}/{ano}")
                    continue
                linhas = achata(res)
                for l in linhas:
                    cur.execute(_SQL, (mid, ano, "M", l["bloco_codigo"], l["bloco_nome"],
                                       l["grupo_codigo"], l["grupo_nome"], l["vl_total"],
                                       l["vl_desconto"], l["vl_liquido"],
                                       json.dumps(l["raw"], ensure_ascii=False)))
                total += len(linhas)
                if linhas:
                    soma = sum(x["vl_total"] or 0 for x in linhas)
                    log.info(f"  {nome}/{ano}: {len(linhas)} linha(s), R$ {soma:,.2f}")
                time.sleep(PAUSA)
            cn.commit()

    # ⚠️ ZERO E ERRO, NAO SUCESSO VAZIO. Tres dos quatro coletores auditados em
    # 31/08 gravavam 'success' cravado e pintavam verde sobre rodada vazia; a
    # tela de Status dos Dados mentia junto. Aqui o status sai do que saiu.
    if total == 0:
        status = "error"
    elif falhas:
        status = "partial"
    else:
        status = "success"
    msg = (f"{len(falhas)} municipio(s)-ano sem resposta: " + ", ".join(falhas[:8])) if falhas else None
    try:
        cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, "
                    "error_message, finished_at) VALUES (%s,%s,%s,%s,NOW())",
                    (FONTE, status, total, msg))
        cn.commit()
    except Exception:
        cn.rollback()
    cur.close()
    cn.close()
    log.info(f"FNS fundo a fundo: FIM — {total} linha(s), {len(falhas)} falha(s), status={status}")
    return total


if __name__ == "__main__":
    run()
